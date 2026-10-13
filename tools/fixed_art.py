"""Deterministic floor art layout that a native loader can repeat.

Same RAM formats as registered_art.pack_floor: lit A/B words, frame headers,
sprite commands, wall light pointers and the column cache. Only the
placement rule changes:

- Sprite shapes that occur on exactly the same set of floors form a group.
  A group's index runs are overlap-packed once, in index space, so the
  packing does not depend on a floor palette. Each light of a group is one
  contiguous area: the mapped blob, then that floor's pool strips.
- Each shape's sprite commands are one contiguous block of its distinct
  column commands.
- Wall columns are 128 bytes per light. An A/B string that already exists
  on the floor is reused (the build ships these aliases per floor).
- Allocation is first fit in ascending address order, largest unit first.
"""
import memmap
from collections import defaultdict
import functools
import json
from pathlib import Path
import struct

from probe_art_overlap import overlap_strings
from registered_art import (EXTRA_RANGES, FRAME_BYTES, FRAME_LEFT, FRAME_GAP, FRAME_CLIP,
                            FRAME_COMMAND_BANK, FRAME_LIGHT_BANKS, WALL_POINTERS, ROOT_SOUND,
                            floor_parts)

BANK_BIAS = 128
LAST_PROGRAM = None
# Art RAM that play can still overwrite (registered_loads.restore_ranges): bank $1D, the
# stage of every view, weapon and compressed read, and the in-game pause's $3C frame. Only
# wall columns go here, filled last, so a resume regenerates the highest wall ranks only.
CLOBBER = ((memmap.BOOT_STAGE, memmap.BOOT_STAGE_END), (memmap.MENU_FRAME, memmap.FADE_BUFFER))


def split(ranges, cuts):
    """(outside, inside) pieces of ranges against the cut ranges."""
    outside, inside = [], []
    for a, b in ranges:
        points = sorted({a, b} | {x for c, d in cuts for x in (c, d) if a < x < b})
        for lo, hi in zip(points, points[1:]):
            (inside if any(c <= lo and hi <= d for c, d in cuts) else outside).append((lo, hi))
    return outside, inside
GROUP_LIMIT = memmap.GEN_USED - memmap.SFX_BASE


class Space:
    """Free fragments, each inside one bank; first fit in the given order."""
    def __init__(self, ranges, ordered=False):
        fragments = []
        for a, b in ranges:
            while a < b:
                end = min(b, (a & ~65535) + 65536)
                fragments.append([a, end])
                a = end
        self.free = fragments if ordered else sorted(fragments)
        self.records = []
        self.kinds = []
        self.last_request = None
        self.last_fragment = 0

    def place(self, raw, kind, size=None, bias=0, bank=None):
        size = len(raw) if size is None else size
        request = size, bias, bank
        first = self.last_fragment if request == self.last_request else 0
        # Allocations only shrink free fragments. Earlier failures still fail
        # when the next request has exactly the same size and restrictions.
        for n in range(first, len(self.free)):
            a, b = self.free[n]
            start = max(a, (a & ~0xFFFF) + bias)
            start += start & 1
            if bank is not None and start >> 16 != bank:
                continue
            if start + size <= b and start >> 16 == (start + size - 1) >> 16:
                self.free[n:n + 1] = ([[a, start]] if a < start else []) + (
                    [[start + size, b]] if start + size < b else [])
                self.last_request, self.last_fragment = request, n
                if raw is not None:
                    self.records.append((start, bytes(raw)))
                    self.kinds.append(kind)
                return start
        raise ValueError(f'no {size} byte {kind} window; {sum(b - a for a, b in self.free)} free bytes')


@functools.lru_cache(maxsize=None)
def shape_runs(shape):
    """Palette-independent index runs (a < 200) of one world frame."""
    import pool_cover
    from wolfdata import vswap, sprite
    pages, base, _ = vswap()
    original = sprite(pages[base + shape])
    fast = fast_frame(shape)
    arts = (original, fast[0]) if fast else (original,)
    pools = pool_cover.pages()
    runs = set()
    for art in arts:
        for column in art['columns']:
            if shape in pools:
                column, _ = pool_cover.split_runs(column, pools[shape][:2])
            runs.update(bytes(raw) for a, b, raw in column)
    return runs


@functools.lru_cache(maxsize=None)
def floor_strip_runs(floor):
    from wolfdata import ROOT
    _, _, frames, _ = floor_parts(floor, ROOT / 'build/palettes', include_mapped=False)
    return {shape: {raw for column in columns for a, b, raw in column if a >= 200}
            for shape, _, columns, _ in frames}


@functools.lru_cache(maxsize=None)
def groups():
    """Shared source groups whose doubled bodies and floor strips fit the input buffer."""
    import pool_cover
    from floor_art import shapes
    from wolfdata import maps, PROFILE
    where = defaultdict(set)
    levels = maps()
    for floor in range(PROFILE.floors):
        actors, objects, _ = shapes(levels[floor])
        for shape in actors | objects:
            where[shape].add(floor)
    by_floors = defaultdict(list)
    for shape, floors in where.items():
        by_floors[frozenset(floors)].append(shape)
    result = []
    for floors, members in sorted(by_floors.items(), key=lambda g: sorted(g[1])):
        current = []
        runs, current_blob = set(), None
        for shape in sorted(members):
            trial = current + [shape]
            trial_runs = runs | shape_runs(shape)
            blob = None
            # Even an unshared concatenation fits: no overlap search is needed
            # to decide this boundary. Pack only the eventual emitted group.
            if current and 2 * sum(map(len, trial_runs)) > GROUP_LIMIT:
                blob, _ = overlap_strings(trial_runs, alignment=1)
                if 2 * len(blob) > GROUP_LIMIT:
                    if current_blob is None:
                        current_blob, _ = overlap_strings(runs, alignment=1)
                    result.append((tuple(current), bytes(current_blob)))
                    current, runs, current_blob = [shape], shape_runs(shape), None
                    continue
            current, runs, current_blob = trial, trial_runs, blob
        if current_blob is None:
            current_blob, _ = overlap_strings(runs, alignment=1)
        result.append((tuple(current), bytes(current_blob)))
    pools = pool_cover.pages()

    def fits(members, blob):
        # A raw strip load writes whole sectors from its unaligned destination.
        room = (GROUP_LIMIT - 2 * len(blob)) // 512 * 512
        if room < 0:
            return False
        marked = set(members) & pools.keys()
        if not marked:
            return True
        for floor in where[members[0]]:
            runs = set().union(*(floor_strip_runs(floor)[shape] for shape in marked))
            if sum(map(len, runs)) <= room:
                continue
            strips, _ = overlap_strings(runs, alignment=1)
            if len(strips) > room:
                return False
        return True

    safe = []
    for members, blob in result:
        if fits(members, blob):
            safe.append((members, blob))
            continue
        current, runs, current_blob = [], set(), b''
        for shape in members:
            trial_runs = runs | shape_runs(shape)
            trial_blob, _ = overlap_strings(trial_runs, alignment=1)
            if current and not fits(current + [shape], trial_blob):
                safe.append((tuple(current), bytes(current_blob)))
                current, runs = [shape], shape_runs(shape)
                current_blob, _ = overlap_strings(runs, alignment=1)
            else:
                current, runs, current_blob = current + [shape], trial_runs, trial_blob
            if not fits(current, current_blob):
                raise ValueError(f'sprite {shape}: generator input exceeds {GROUP_LIMIT} bytes')
        safe.append((tuple(current), bytes(current_blob)))
    return tuple(safe)


def column_classes(bodies, strips):
    """Column x reuses the first column with equal body runs when its strips are equal too."""
    first, canon = {}, []
    for x, body in enumerate(bodies):
        y = first.setdefault(tuple(body), x)
        canon.append(y if strips[y] == strips[x] else x)
    return canon


def mapped(raw, table):
    if len(raw) >= 256:
        data = bytearray(2 * len(raw))
        data[::2] = raw.translate(bytes(pair[0] for pair in table))
        data[1::2] = raw.translate(bytes(pair[1] for pair in table))
        return bytes(data)
    return b''.join(bytes(table[c]) for c in raw)


class FloorColors:
    """Map each source string once during this floor's placement search."""
    def __init__(self, receipt):
        self.tables = receipt['sprite_lights'] + receipt['wall_lights']
        self.translations = {id(t): (bytes(p[0] for p in t), bytes(p[1] for p in t))
                             for t in self.tables}
        self.results = {}

    def __call__(self, raw, table):
        key = raw, id(table)
        if key not in self.results:
            low, high = self.translations[id(table)]
            data = bytearray(2 * len(raw))
            data[::2] = raw.translate(low)
            data[1::2] = raw.translate(high)
            self.results[key] = bytes(data)
        return self.results[key]


@functools.lru_cache(maxsize=32768)
def blob_offset(blob, raw):
    """A source run has the same offset at every light and trial placement."""
    return blob.find(raw)


def group_strips(members, by_shape):
    """Pool strips follow the doubled source blob in the generator's input buffer."""
    strips = [(shape, x, a, raw) for shape in members
              for x, column in enumerate(by_shape[shape][1])
              for a, b, raw in column if a >= 200]
    blob, _ = overlap_strings({raw for _, _, _, raw in strips}, alignment=1) if strips else (b'', None)
    return strips, bytes(blob)


def pack_floor(floor, palette_dir, compact=False, protected_cache=None, required_sight=None):
    """Same return values as registered_art.pack_floor. The first layout that fits, in this
    order: 700, 500, 350, 250 sight rooms, then none; for each, walls in fill ranges before
    packed walls (a loaded pointer table). A layout with art in the in-game pause's $3C frame
    (every resume from the pause must read that art again) is taken only when no later
    layout fits without it. The play cache (memmap PLAY_CACHE: the blocks of the loads during
    play stay there from the boot) stays free of art when the floor keeps its sight rooms that
    way, also with packed walls or with art in bank $1D. Else the art takes the top of it, as
    few 512-byte slots as keep the layout of the whole RAM (sight rooms, no art in the pause
    frame, walls not packed, no more art in bank $1D); the floor's load clears those slots of
    the play cache and keeps the ones below (tools/build_registered_episode.py play_cache)."""
    global LAST_PROGRAM
    _, walls, frames, receipt = floor_parts(floor, palette_dir, include_mapped=False)
    by_shape = {shape: (art, columns) for shape, art, columns, _ in frames}
    for members, blob in groups():
        if not set(members) & by_shape.keys():
            continue
        _, strips = group_strips(members, by_shape)
        size = 2 * len(blob) + (len(strips) + 511) // 512 * 512
        if size > GROUP_LIMIT:
            raise ValueError(f'floor {floor + 1}: sprite group input needs {size} bytes; buffer holds {GROUP_LIMIT}')
    from wolf_source import sprite_ids
    ids = sprite_ids()
    weapon_shapes = range(ids['SPR_KNIFEREADY'], ids['SPR_CHAINREADY'] + 5)
    header_bytes = len(frames) * FRAME_BYTES + len(weapon_shapes) * (FRAME_BYTES - FRAME_LEFT)
    from sprite_simplify import mirror_shape
    if mirror_shape() in by_shape:
        header_bytes += FRAME_BYTES
    pages, raw_walls, ranges = wall_space(floor, header_bytes)
    if compact:
        from dense_art import extra_ranges
        ranges += extra_ranges(floor)
        ranges = split(ranges, [(memmap.DRAW_BUFFER, memmap.DRAW_BUFFER_END),
                                (memmap.WALL_PAINT, memmap.WALL_PAINT_END)])[0]
    if protected_cache is not None:
        ranges = split(ranges, [(memmap.PLAY_CACHE, protected_cache)])[0]
    args = (floor, frames, receipt, walls, raw_walls, pages, header_bytes, weapon_shapes, FloorColors(receipt), compact)
    sight_cache = {}
    cached = ranges
    for c, d in PLAY_CACHE:
        cached = [(lo, hi) for a, b in cached for lo, hi in ((a, min(b, c)), (max(a, d), b)) if lo < hi]
    chosen = search(*args, cached, sight_cache)
    if chosen is None or chosen[0] > 0 or in_frame(chosen[1][0]):
        whole = search(*args, ranges, sight_cache)
        if whole is None:
            if not compact:
                return pack_floor(floor, palette_dir, compact=True)
            raise ValueError(f'floor {floor + 1}: art does not fit')
        if chosen is None or (chosen[0], in_frame(chosen[1][0])) > (whole[0], in_frame(whole[1][0])):
            # The fewest top slots that keep the whole layout's quality (a bisection: more
            # slots never fit worse here; none failed above, all is the whole RAM).
            slots = (memmap.PLAY_CACHE_END - memmap.PLAY_CACHE) // 512
            low, high, chosen = 0, slots, whole
            while high - low > 1:
                middle = (low + high) // 2
                top = cached + [(memmap.PLAY_CACHE_END - middle * 512, memmap.PLAY_CACHE_END)]
                trial = search(*args, top, sight_cache)
                if trial is not None and all(a <= b for a, b in zip(quality(trial), quality(whole))):
                    high, chosen = middle, trial
                else:
                    low = middle
            print(f'floor {floor + 1}: its art takes the top {high} of the {slots} play cache slots', flush=True)
    baseline = chosen
    baseline_records = baseline[1][0]
    buffer_start, buffer_end = memmap.DRAW_BUFFER, memmap.DRAW_BUFFER_END
    overlaps = any(a < buffer_end and buffer_start < a + len(raw)
                   for a, raw in baseline_records)
    # Preserve every play-cache byte the original layout could retain. A full
    # draw buffer may change art placement, but cannot evict more cache slots.
    cache_start = min((max(a, memmap.PLAY_CACHE) for a, raw in baseline_records
                       if a < memmap.PLAY_CACHE_END and memmap.PLAY_CACHE < a + len(raw)),
                      default=memmap.PLAY_CACHE_END)
    if overlaps:
        reserved = [(buffer_start, buffer_end), (memmap.PLAY_CACHE, cache_start)]
        usable = split(ranges, reserved)[0]
        chosen = search(*args, usable, sight_cache)
        if chosen is None:
            if not compact:
                return pack_floor(floor, palette_dir, compact=True, protected_cache=cache_start,
                                  required_sight=quality(baseline)[0])
            raise ValueError(f'floor {floor + 1}: full draw buffer does not fit without evicting play cache')
    index, result, LAST_PROGRAM = chosen
    report = result[-1]
    report['draw_buffer'] = dict(address=buffer_start, bytes=buffer_end-buffer_start,
                                repacked=overlaps, baseline_free_bytes=baseline[1][-1]['free_bytes'],
                                baseline_quality=quality(baseline), quality=quality(chosen),
                                protected_play_end=cache_start)
    if not overlaps and not compact:
        report['free_bytes'] -= buffer_end-buffer_start
    assert all(not (a < buffer_end and buffer_start < a + len(raw)) for a, raw in result[0])
    assert all(not (a < cache_start and memmap.PLAY_CACHE < a + len(raw)) for a, raw in result[0])
    # Reserve wall metadata after measuring the existing draw-buffer layout,
    # so the new reservation cannot consume its retained play-cache slots.
    original = chosen
    lo, hi = memmap.WALL_PAINT, memmap.WALL_PAINT_END
    wall_overlap = any(a < hi and lo < a + len(raw) for a,raw in result[0])
    old_cache = min((max(a,memmap.PLAY_CACHE) for a,raw in result[0]
                     if a < memmap.PLAY_CACHE_END and memmap.PLAY_CACHE < a+len(raw)),
                    default=memmap.PLAY_CACHE_END)
    if wall_overlap:
        usable = split(ranges, [(buffer_start,buffer_end), (lo,hi), (memmap.PLAY_CACHE,old_cache)])[0]
        chosen = search(*args, usable, sight_cache)
        if chosen is None or quality(chosen)[0] > quality(original)[0]:
            if not compact:
                return pack_floor(floor, palette_dir, compact=True, protected_cache=old_cache,
                                  required_sight=quality(original)[0])
            raise ValueError(f'floor {floor + 1}: wall painter does not fit beside draw buffer and sight tables')
        index, result, LAST_PROGRAM = chosen
        report = result[-1]
        report['draw_buffer'] = original[1][-1]['draw_buffer']
    elif not compact:
        report['free_bytes'] -= hi-lo
    assert quality(chosen)[0] <= quality(original)[0], 'wall painter would weaken sight tables'
    report['wall_paint'] = dict(address=lo, bytes=hi-lo, repacked=wall_overlap,
                               baseline_quality=quality(original),quality=quality(chosen),
                               protected_play_end=old_cache)
    assert all(not (a < buffer_end and buffer_start < a + len(raw)) for a, raw in result[0])
    assert all(not (a < old_cache and memmap.PLAY_CACHE < a + len(raw)) for a, raw in result[0])
    assert all(not (a < memmap.WALL_PAINT_END and memmap.WALL_PAINT < a + len(raw))
               for a, raw in result[0]), 'floor art overlaps the reserved wall painter'
    if required_sight is not None:
        assert index <= required_sight, 'compact art would weaken sight tables'
    report['compact_art'] = compact
    if SIGHT_ROOMS[index]:
        sight_needs(floor, SIGHT_ROOMS[index], sight_cache)  # later tries rewrote its files
    return result


def in_frame(records):
    """True when art lies in the in-game pause's $3C frame."""
    return any(a < memmap.FADE_BUFFER and memmap.MENU_FRAME < a + len(raw) for a, raw in records)


def quality(found):
    """(sight rooms index, art in the pause frame, walls packed, art bytes in bank $1D) of a
    search result: lower is better in each."""
    index, result, program = found
    stage = sum(max(0, min(a + len(raw), memmap.BOOT_STAGE_END) - max(a, memmap.BOOT_STAGE)) for a, raw in result[0])
    return index, in_frame(result[0]), program.get('wall_mode') == 'pointers', stage


def search(floor, frames, receipt, walls, raw_walls, pages, header_bytes, weapon_shapes, colors, compact, ranges, sight_cache):
    """(index in SIGHT_ROOMS, result, program) of the first layout that fits the ranges, a
    layout with art in the pause frame only when no later one fits without it; None."""
    framed = None
    for index, rooms in enumerate(SIGHT_ROOMS[:1] if compact else SIGHT_ROOMS):
        sight = sight_needs(floor, rooms, sight_cache) if rooms else None
        usable = ranges
        if sight:
            usable = [(lo, hi) for a, b in ranges
                      for lo, hi in ((a, min(b, memmap.BLOCK_DIR)), (max(a, memmap.BLOCK_MASKS_END), b)) if lo < hi]
        for packed in (False, True):
            try:
                result = place_all(floor, frames, receipt, walls, raw_walls, pages, header_bytes, weapon_shapes,
                                   usable, sight, packed, mapped=colors, compact=compact)
            except ValueError:
                print(f'floor {floor + 1}: art does not fit with {rooms} sight rooms, packed walls {packed}', flush=True)
                continue
            if not in_frame(result[0]):
                return index, result, LAST_PROGRAM
            print(f'floor {floor + 1}: {rooms} sight rooms, packed walls {packed} put art in the pause frame', flush=True)
            framed = framed or (index, result, LAST_PROGRAM)
    return framed


def wall_space(floor, header_bytes):
    """(wall pages, distinct wall columns, art ranges) of the floor."""
    from wolfdata import vswap
    pages = vswap()[0]
    chosen = wall_pages(floor)
    raw_walls = sorted({bytes(pages[p][x * 64:(x + 1) * 64]) for p in chosen for x in range(64)})
    if len(raw_walls) * 16 > 0xfc00:
        raise ValueError('wall light pointers exceed their bank')
    ranges = [(b * 65536, (b + 1) * 65536) for b in range(0x10, 0x30)]
    ranges += [(memmap.SPRITE_CMDS + header_bytes, memmap.BLOCK_DIR), (memmap.BLOCK_DIR, memmap.VIS_STAMPS),
               (WALL_POINTERS + len(raw_walls) * 16, memmap.PIC_KEEP)]
    ranges += EXTRA_RANGES
    if memmap.WALL_COLUMNS != memmap.SHR_SHADOW:
        # The Spear directory is live throughout play, outside allocatable art.
        a, b = memmap.WALL_COLUMNS, memmap.WALL_COLUMNS_END
        ranges = [(lo, hi) for x, y in ranges
                  for lo, hi in ((x, min(y, a)), (max(x, b), y)) if lo < hi]
    import os
    effect_manifest = Path(os.environ.get('WOLF_FLOOR_EFFECTS', ROOT_SOUND)) / f'effects-floor-{floor:02}-loads.json'
    if effect_manifest.exists():
        for row in json.loads(effect_manifest.read_text()):
            a, b = row['address'], row['address'] + row['bytes']
            ranges = [(lo, hi) for x, y in ranges for lo, hi in ((x, min(y, a)), (max(x, b), y)) if lo < hi]
    return chosen, raw_walls, ranges


def wall_pages(floor, all_doors=False):
    """The floor's 4096-byte wall pages that the renderer can draw: both pages of each wall
    material on the map (an elevator switch 21 also turns into 22) and the two door pages.
    The renderer draws a wall, a door-side wall and a push wall from page
    2*(material-1)+side (src/iigs/wolf.s wallHit, level.s PWallHit; lglue.s renderMap drops
    the door-side bit) and every door from DOORWALL or DOORWALL+1 (wolf.s doorHit); it never
    draws the other six door pages (door sides, elevator and locked doors). all_doors=True
    adds them: the per-floor packer (registered_art.pack_floor) still loads all eight."""
    from wolfdata import maps, vswap
    from native_map_format import wall_material
    pages, base, _ = vswap()
    tiles = {m for t in maps()[floor]['planes'][0] if (m := wall_material(t)) is not None}
    if 21 in tiles:
        tiles.add(22)
    doors = range(base - 8, base if all_doors else base - 6)
    chosen = sorted({p for t in tiles for p in (2 * (t - 1), 2 * (t - 1) + 1)} | set(doors))
    return [p for p in chosen if len(pages[p]) == 4096]


SIGHT_ROOMS = (700, 500, 350, 250, None)
# The play cache: the store blocks of the loads during play stay in this RAM from the boot
# (src/iigs/leveldirectory.s playLookup, ui_overlays.s PlayCacheFill).
PLAY_CACHE = ((memmap.PLAY_CACHE, memmap.PLAY_CACHE_END),)


def sight_needs(floor, rooms, cache):
    """Room-pair sight data of the floor (sight_rooms.py), or None when it has no proofs."""
    from wolfdata import ROOT
    import sight_rooms
    folder = ROOT / f'build/levels/{floor}'
    if not (folder / 'source-planes.bin').exists():
        return None
    if rooms in cache:
        report, files = cache[rooms]
        for name, data in files:
            (folder / name).write_bytes(data)
        return report if report['enabled'] else None
    # Geometry proofs are shared by all room limits in this one floor search.
    report = sight_rooms.prepare(ROOT, floor, rooms, proofs=cache.setdefault('proofs', {}))
    # The search revisits caps while bisecting available RAM. Keep each proof
    # once for this floor, including the files the next placement reads.
    names = ('sight-rooms.bin', 'sight-matrix.bin', 'sight-lower.bin', 'sight.json')
    cache[rooms] = report, [(name, (folder / name).read_bytes())
                          for name in names if (folder / name).is_file()]
    return report if report['enabled'] else None


@functools.lru_cache(maxsize=1)
def wall_packing(sprites, strings, alignment=2):
    """Wall matches and overlap paths depend on sprite bytes, not their addresses.
    Keep them while the floor search tries different free RAM ranges."""
    from probe_art_overlap import overlap_strings
    placed, unmatched = {}, set(strings)
    for index, raw in enumerate(sprites):
        for size in sorted({len(piece) for piece in unmatched}):
            for at in range(0, len(raw)-size+1, alignment):
                piece = raw[at:at+size]
                if piece in unmatched:
                    placed[piece] = index, at
                    unmatched.remove(piece)
    blob, _ = overlap_strings(unmatched, alignment=alignment)
    from probe_art_overlap import aligned_offsets
    where = aligned_offsets(blob, unmatched, alignment)
    return placed, bytes(blob), where


def packed_walls(space, sprite_records, sprite_kinds, strings, alignment=2):
    """Reuse sprite substrings, then place whole wall strings in free fragments."""
    sprites = [row for row, kind in zip(sprite_records, sprite_kinds) if kind == 'sprite art']
    matches, blob, where = wall_packing(tuple(raw for _, raw in sprites), frozenset(strings), alignment)
    placed = {piece: sprites[index][0] + at for piece, (index, at) in matches.items()}
    for start, end in cut_paths(blob, sorted(set((at, at + len(raw)) for raw, at in where.items())), space):
        address = space.place(blob[start:end], 'wall art')
        for raw, at in where.items():
            if start <= at and at + len(raw) <= end and raw not in placed:
                placed[raw] = address + at - start
    assert len(placed) >= len(where)
    return placed


def cut_paths(blob, spans, space):
    """Pieces (start, end) of blob for the free fragments in order, one at a time (the
    caller places each before the next is cut): each piece holds whole strings only
    (spans: sorted (start, end) of every string), begins at the first string the
    earlier pieces did not hold and ends at its last whole string, so the generator
    writes every byte of every piece."""
    done = 0
    while done < len(spans):
        start = spans[done][0]
        fragment = next(((a, b) for a, b in space.free if (b - (a + (a & 1))) >= spans[done][1] - start), None)
        if fragment is None:
            raise ValueError(f'packed walls: {len(spans) - done} strings left')
        a, b = fragment
        limit = start + ((b - (a + (a & 1))) & ~1)
        end = start
        while done < len(spans) and spans[done][1] <= limit:
            end = max(end, spans[done][1])
            done += 1
        yield start, end


@functools.lru_cache(maxsize=None)
def fast_frame(shape):
    from sprite_simplify import world_sprite
    from wolfdata import vswap, sprite
    import pool_cover
    pages, base, _ = vswap()
    art = world_sprite(pages[base + shape])
    if art == sprite(pages[base + shape]):
        return None
    if shape in pool_cover.pages():
        from sprite_simplify import source_pixels
        from viewgeometry import HEIGHTS
        original = sprite(pages[base + shape])
        source, pixels = source_pixels(original), source_pixels(art)
        start, end = pool_cover.pages()[shape][:2]
        # The pool scaler retargets these rows to filtered source slots.
        # Keep its feature and any rows sharing those slots unchanged.
        protected = set(range(start, end))
        for h in HEIGHTS:
            if h >= 64:
                break
            patched = {row for height, row in pool_cover.plan().slot if height == h}
            for tex in range(64):
                if patched.intersection(range(pool_cover._e(h, tex), pool_cover._e(h, tex + 1))):
                    protected.add(tex)
        for x in range(64):
            for y in protected:
                pixels[x][y] = source[x][y]
        columns = []
        for column in pixels:
            runs, y = [], 0
            while y < 64:
                if column[y] is None:
                    y += 1
                    continue
                top = y
                while y < 64 and column[y] is not None:
                    y += 1
                runs.append((top, y, bytes(column[top:y])))
            columns.append(runs)
        used = [x for x, col in enumerate(columns) if col]
        art = dict(art, left=min(used), right=max(used), columns=columns[min(used):max(used)+1])
    columns = [[] for _ in range(64)]
    for x, column in enumerate(art['columns'], art['left']):
        columns[x] = [(a, b, bytes(raw)) for a, b, raw in column]
    return art, columns


def fast_columns_for(shape, columns, original):
    """Reuse the original floor's filtered strips in the simplified body."""
    import pool_cover
    if shape not in pool_cover.pages():
        return columns
    feature = pool_cover.pages()[shape][:2]
    return [pool_cover.split_runs(col, feature)[0] +
            [(a, b, bytes(raw)) for a, b, raw in original[x] if a >= 200]
            for x, col in enumerate(columns)]


def compact_sources(space, frames, receipt, colors):
    """Pack exact mapped runs when shared index groups cannot fit the floor.

    These floor-local bytes load directly. Source banks and command formats
    are unchanged, so drawing needs no decompression or additional lookup.
    """
    from dense_art import frame_banks
    if not hasattr(colors, 'compact_banks'):
        runs = {}
        for shape, art, columns, original in frames:
            pieces = {raw for col in columns for a, b, raw in col}
            fast = fast_frame(shape)
            if fast:
                pieces.update(raw for col in fast_columns_for(shape, fast[1], columns)
                              for a, b, raw in col)
            runs[shape] = pieces
        groups = {(shape, light): {colors(raw, table) for raw in pieces}
                  for shape, pieces in runs.items()
                  for light, table in enumerate(receipt['sprite_lights'])}
        colors.compact_banks = frame_banks(groups)
        colors.compact_runs = runs
    banks, offsets = {}, {}
    for bank in sorted(colors.compact_banks, key=lambda b: -len(b.blob)):
        address = space.place(bank.blob, 'sprite art', bias=BANK_BIAS)
        for shape, light in bank.groups:
            banks[shape, light] = address >> 16
            positions = {}
            for raw in colors.compact_runs[shape]:
                piece = colors(raw, receipt['sprite_lights'][light])
                at = bank.blob.find(piece)
                assert at >= 0
                positions[raw] = (address & 65535) + at
            offsets[shape, light] = positions
    return banks, offsets


def frame_header(shape, art, columns, pointers, bank, lights):
    import pool_cover
    header = bytearray(FRAME_BYTES)
    struct.pack_into('<64H', header, 0, *pointers)
    header[FRAME_LEFT:FRAME_LEFT + 2] = bytes((art['left'], art['right']))
    opaque = {t for column in columns for a, b, _ in column for t in range(a, b)}
    if 32 in opaque:
        gap = (255, 0)
    else:
        lo, hi = 32, 33
        while lo > 0 and lo - 1 not in opaque:
            lo -= 1
        while hi < 64 and hi not in opaque:
            hi += 1
        gap = (lo, hi)
    header[FRAME_GAP:FRAME_GAP + 2] = bytes((gap[0], gap[1] | (128 if shape in pool_cover.pages() else 0)))
    for cut in range(32):
        used = [x for x, col in enumerate(columns) if any(b > cut and a < 64 - cut for a, b, _ in col)]
        header[FRAME_CLIP + cut * 2:FRAME_CLIP + cut * 2 + 2] = bytes((min(used), max(used))) if used else bytes((64, 0))
    struct.pack_into('<H', header, FRAME_COMMAND_BANK, bank)
    header[FRAME_LIGHT_BANKS:FRAME_LIGHT_BANKS + 4] = lights
    return bytes(header)


def place_all(floor, frames, receipt, walls, raw_walls, wall_pages, header_bytes, weapon_shapes, ranges, sight, packed=False, mapped=mapped, compact=False):
    from wolfdata import vswap, sprite
    import pool_cover
    pages, base, _ = vswap()
    open_ranges, clobbered = split(ranges, CLOBBER)
    space = Space(open_ranges)
    sight_rows = None
    if sight:
        from wolfdata import ROOT
        matrix = (ROOT / f'build/levels/{floor}/sight-matrix.bin').read_bytes()
        sight_rows = space.place(matrix, 'sight matrix')
    lights = receipt['sprite_lights']
    shape_set = {shape for shape, _, _, _ in frames}
    floor_groups = [(members, blob) for members, blob in groups() if shape_set & set(members)]
    assert {s for members, _ in floor_groups for s in members} == shape_set
    by_shape = {shape: (art, columns) for shape, art, columns, _ in frames}
    # A group's strips use only pool marker colours, which are equal in every light
    # table. When all four light blobs and one strip copy fit one bank, they form one
    # unit: [light 0][light 1][light 2][light 3][strips]. Otherwise each light area is
    # its blob followed by its own strip copy.
    units = []
    for g, (members, blob) in enumerate(floor_groups):
        strips, strip_blob = group_strips(members, by_shape)
        if strip_blob:
            assert len({mapped(strip_blob, lights[l]) for l in range(4)}) == 1
        joined = 8 * len(blob) + 2 * len(strip_blob)
        if strip_blob and joined <= 65536 - BANK_BIAS:
            units.append((joined, g, None, strips, strip_blob))
        else:
            size = 2 * len(blob) + 2 * len(strip_blob)
            if size > 65536 - BANK_BIAS:
                raise ValueError(f'floor {floor + 1}: sprite group {members} needs {size} bytes')
            for light in range(4):
                units.append((size, g, light, strips, strip_blob))
    art_banks, run_offsets = {}, {}
    global_ids = {members: n for n, (members, _) in enumerate(groups())}
    program = dict(groups=[global_ids[m] for m, _ in floor_groups], areas={}, strip_at={}, strips={},
                   commands={}, walls=[], sight=(sight_rows, sight['stride'], sight['rooms']) if sight else None)
    if compact:
        program['groups'] = []
        art_banks, run_offsets = compact_sources(space, frames, receipt, mapped)
    else:
        for size, g, light, runs, strip_blob in sorted(units, key=lambda r: (-r[0], r[1], -1 if r[2] is None else r[2])):
            members, blob = floor_groups[g]
            span = 2 * len(blob)
            if light is None:
                data = b''.join(mapped(blob, lights[l]) for l in range(4)) + mapped(strip_blob, lights[0])
                address = space.place(data, 'sprite art', bias=BANK_BIAS)
                placed = [(l, address + span * l, address + 4 * span) for l in range(4)]
            else:
                data = mapped(blob, lights[light]) + mapped(strip_blob, lights[light])
                address = space.place(data, 'sprite art', bias=BANK_BIAS)
                placed = [(light, address, address + span)]
            program['strips'][g] = (strip_blob, [(shape, x, a, blob_offset(strip_blob, raw)) for shape, x, a, raw in runs])
            for l, area, strip_at in placed:
                program['areas'][g, l] = area
                program['strip_at'][g, l] = strip_at
                positions = {(shape, x, a): (strip_at - area) + 2 * blob_offset(strip_blob, raw) for shape, x, a, raw in runs}
                for shape in members:
                    art_banks[shape, l] = area >> 16
                    run_offsets[shape, l] = (area & 0xFFFF, blob, positions)
    def command_keys(shape, columns):
        keys = []
        for x, column in enumerate(columns):
            command = bytearray()
            for a, b, raw in sorted(column, reverse=True):
                offsets = []
                for light in range(4):
                    if compact:
                        offset = run_offsets[shape, light][raw] - (a * 2 if a < 200 else 0)
                    else:
                        start, blob, positions = run_offsets[shape, light]
                        within = positions[shape, x, a] if a >= 200 else 2 * blob_offset(blob, raw)
                        assert within >= 0
                        offset = start + within - (a * 2 if a < 200 else 0)
                    assert 0 <= offset < 65536
                    offsets.append(offset)
                command += struct.pack('<5H', a | (b << 8), *offsets)
            command += b'\0\0'
            keys.append(bytes(command))
        return keys

    command_ptrs, command_banks = {}, {}
    blocks = []
    for shape in sorted(shape_set):
        columns = by_shape[shape][1]
        canon = column_classes([[r for r in c if r[0] < 200] for c in columns],
                               [[r for r in c if r[0] >= 200] for c in columns])
        keys = command_keys(shape, columns)
        unique = [keys[x] for x in range(64) if canon[x] == x]
        blocks.append((sum(map(len, unique)), shape, canon, keys))
    if compact:
        contents = {a >> 16: {} for a, b in space.free}
        for size, shape, canon, keys in sorted(blocks, key=lambda r: (-r[0], r[1])):
            pieces = set(keys)
            choices = []
            for bank, have in contents.items():
                extra = pieces - have.keys()
                ranges = [(a, b) for a, b in space.free if a >> 16 == bank]
                room, cost = sum(b-a for a, b in ranges), sum(map(len, extra))
                if cost > room:
                    continue
                trial = Space(ranges)
                try:
                    for raw in sorted(extra, key=lambda raw: (-len(raw), raw)):
                        trial.place(raw, 'sprite commands')
                except ValueError:
                    continue
                choices.append((cost, room-cost, bank))
            if not choices:
                raise ValueError(f'no command bank for sprite {shape}')
            bank = min(choices)[2]
            for raw in sorted(pieces-contents[bank].keys(), key=lambda raw: (-len(raw), raw)):
                address = space.place(raw, 'sprite commands', bank=bank)
                contents[bank][raw] = address & 65535
            command_banks[shape] = bank
            for x, key in enumerate(keys):
                command_ptrs[shape, x] = contents[bank][key]
    else:
        for size, shape, canon, keys in sorted(blocks, key=lambda r: (-r[0], r[1])):
            address = space.place(b''.join(keys[x] for x in range(64) if canon[x] == x), 'sprite commands')
            program['commands'][shape] = address
            command_banks[shape] = address >> 16
            at = address & 0xFFFF
            for x in range(64):
                if canon[x] == x:
                    command_ptrs[shape, x] = at
                    at += len(keys[x])
            for x in range(64):
                command_ptrs[shape, x] = command_ptrs[shape, canon[x]]

    # Both modes share the lit source groups. Only changed shapes need another
    # command stream. A bank-local XOR program swaps their resident headers;
    # applying it twice restores every original pointer and clipping bound.
    from sprite_simplify import mirror_shape
    from wolf_source import sprite_ids
    mirrored = mirror_shape()
    mirror_header = None
    quality_records = []
    deltas = bytearray()
    for number, (shape, art, columns, original) in enumerate(frames):
        fast = fast_frame(shape)
        if fast is None:
            continue
        fast_art, fast_columns = fast
        drawable = fast_columns_for(shape, fast_columns, columns)
        keys = command_keys(shape, drawable)
        unique = list(dict.fromkeys(keys))
        address = space.place(b''.join(unique), 'fast sprite commands')
        quality_records.append(space.records[-1])
        pointers = {}
        at = address & 65535
        for key in unique:
            pointers[key] = at
            at += len(key)
        banks = bytes(art_banks[shape, l] for l in range(4))
        before = frame_header(shape, art, original,
                              [command_ptrs[shape, x] for x in range(64)], command_banks[shape], banks)
        after = frame_header(shape, fast_art, fast_columns,
                             [pointers[key] for key in keys], address >> 16, banks)
        deltas += struct.pack('<H', number * FRAME_BYTES)
        deltas += bytes(a ^ b for a, b in zip(before, after))
        if shape == mirrored:
            mirror_header = before
            mirror_art = dict(fast_art, left=63 - fast_art['right'], right=63 - fast_art['left'])
            reflected = frame_header(shape, mirror_art, fast_columns[::-1],
                                     [pointers[key] for key in keys[::-1]], address >> 16, banks)
            deltas += struct.pack('<H', header_bytes - FRAME_BYTES)
            deltas += bytes(a ^ b for a, b in zip(before, reflected))
    delta_count = len(deltas) // (FRAME_BYTES + 2)
    address = space.place(struct.pack('<H', delta_count) + deltas, 'sprite header deltas')
    quality_records.append(space.records[-1])
    state = struct.pack('<4H', address & 65535, address >> 16, 0, 0)
    quality_records.append((memmap.SPRITE_QUALITY_STATE, state))
    program['quality_records'] = quality_records
    program['quality_shapes'] = delta_count
    walls_space = Space(sorted(map(tuple, space.free)) + sorted(clobbered), ordered=True)
    sprite_records, sprite_kinds = space.records, space.kinds
    space = walls_space
    wall_addresses, placed = {}, {}
    if packed:
        placed = packed_walls(space, sprite_records, sprite_kinds,
                              {mapped(raw, mapping) for raw in raw_walls for mapping in receipt['wall_lights']},
                              alignment=1 if compact else 2)
        program['wall_mode'] = 'pointers'
    for raw in raw_walls:
        for mapping in receipt['wall_lights']:
            ab = mapped(raw, mapping)
            if ab not in placed:
                placed[ab] = space.place(ab, 'wall art')
            wall_addresses[raw, id(mapping)] = placed[ab]
            program['walls'].append(placed[ab])
    wall_pointers = bytearray()
    wall_ids = {raw: i * 16 for i, raw in enumerate(raw_walls)}
    for raw in raw_walls:
        for mapping in receipt['wall_lights']:
            address = wall_addresses[raw, id(mapping)]
            wall_pointers += struct.pack('<HH', address & 65535, (address >> 8) & 0xff00)
    cache = bytearray(memmap.WALL_COLUMNS_SIZE)
    for page in wall_pages:
        for x in range(64):
            token = wall_ids[bytes(pages[page][x * 64:(x + 1) * 64])]
            struct.pack_into('<HH', cache, page * 256 + x * 4, token, page << 8)
    headers = bytearray(header_bytes)
    frame_offsets = {}
    pools = pool_cover.pages()
    for number, (shape, art, columns, original) in enumerate(frames):
        frame = number * FRAME_BYTES
        frame_offsets[shape] = frame
        headers[frame:frame + FRAME_BYTES] = frame_header(
            shape, art, original, [command_ptrs[shape, x] for x in range(64)],
            command_banks[shape], bytes(art_banks[shape, l] for l in range(4)))
    for n, shape in enumerate(weapon_shapes):
        art = sprite(pages[base + shape])
        frame = len(frames) * FRAME_BYTES + n * (FRAME_BYTES - FRAME_LEFT) - FRAME_LEFT
        frame_offsets[shape] = frame
        headers[frame + FRAME_LEFT:frame + FRAME_LEFT + 2] = bytes((art['left'], art['right']))
        headers[frame + FRAME_GAP:frame + FRAME_GAP + 2] = bytes((255, 0))
        for cut in range(32):
            used = [x for x, col in enumerate(art['columns'], art['left']) if any(b > cut and a < 64 - cut for a, b, _ in col)]
            headers[frame + FRAME_CLIP + cut * 2:frame + FRAME_CLIP + cut * 2 + 2] = bytes((min(used), max(used))) if used else bytes((64, 0))
    if mirror_header is not None:
        # The companion is loaded with the weapon metadata, after generated
        # world headers. Off mode uses the original, unreflected commands.
        frame_offsets[len(sprite_ids())] = header_bytes - FRAME_BYTES
        headers[-FRAME_BYTES:] = mirror_header
    if compact:
        program['baked_records'] = [(a, raw) for (a, raw), kind in zip(sprite_records, sprite_kinds)
                                    if kind in ('sprite art', 'sprite commands')]
        program['baked_records'].append((memmap.SPRITE_CMDS, bytes(headers)))
    global LAST_PROGRAM
    LAST_PROGRAM = program
    space.records = sprite_records + space.records
    space.kinds = sprite_kinds + space.kinds
    if sight:
        import sight_rooms
        from wolfdata import ROOT
        ids = (ROOT / f'build/levels/{floor}/sight-rooms.bin').read_bytes()
        space.records.append((memmap.BLOCK_DIR, sight_rooms.meta(ids, sight_rows, sight['stride'])))
        space.kinds.append('sight tables')
    records = space.records + [(memmap.SPRITE_QUALITY_STATE, state), (memmap.SPRITE_CMDS, bytes(headers)), (WALL_POINTERS, bytes(wall_pointers)), (memmap.WALL_COLUMNS, bytes(cache))]
    ordered = sorted(records)
    for (a, raw), (b, _) in zip(ordered, ordered[1:]):
        assert a + len(raw) <= b, (hex(a), hex(b))
    peak = max(a + len(raw) for a, raw in records)
    assert peak <= memmap.FAST_RAM_END
    report = dict(floor=floor, frames=len(frames), wall_columns=len(raw_walls),
                  bytes_by_kind={k: sum(len(raw) for (_, raw), kind in zip(space.records, space.kinds) if kind == k)
                                 for k in set(space.kinds)},
                  mirrored_shape=mirrored if mirror_header is not None else None,
                  mirror_bytes=FRAME_BYTES * 2 + 4 if mirror_header is not None else 0,
                  quality_shapes=delta_count, quality_bytes=sum(len(raw) for _, raw in quality_records),
                  headers_bytes=len(headers), wall_pointer_bytes=len(wall_pointers),
                  free_bytes=sum(b - a for a, b in space.free), highest_address=peak - 1,
                  layout='fixed', sight_rows=sight_rows, wall_aliases=len(raw_walls) * 4 - len(placed), sprite_groups=len(floor_groups),
                  wall_pages=list(wall_pages))
    return records, frame_offsets, frames, receipt, report
