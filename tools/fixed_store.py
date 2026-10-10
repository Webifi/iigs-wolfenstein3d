"""Shared art source and per-floor programs for the loader-built art.

shared(): palette-independent data stored once on disk.
floor_program(): the compact per-floor program (addresses only).
regenerate(): host reference of the native generator. It must rebuild the
exact RAM bytes of fixed_art.pack_floor from shared + program + light tables.
"""
import memmap
import functools
import struct

import fixed_art
from registered_art import (FRAME_BYTES, FRAME_LEFT, FRAME_GAP, FRAME_CLIP, FRAME_COMMAND_BANK,
                            FRAME_LIGHT_BANKS, WALL_POINTERS)


@functools.lru_cache(maxsize=None)
def sources():
    """The source columns/groups; a floor program does not need templates."""
    from wolfdata import vswap
    pages, base, _ = vswap()
    wall_pages = [p for p in range(base) if len(pages[p]) == 4096]
    columns = sorted({bytes(pages[p][x * 64:(x + 1) * 64]) for p in wall_pages for x in range(64)})
    ids = {raw: n for n, raw in enumerate(columns)}
    page_ids = {p: [ids[bytes(pages[p][x * 64:(x + 1) * 64])] for x in range(64)] for p in wall_pages}
    group_list = fixed_art.groups()
    return dict(columns=columns, page_ids=page_ids, groups=group_list)


@functools.lru_cache(maxsize=None)
def shared():
    import pool_cover
    from wolfdata import vswap, sprite
    data = sources()
    group_list = data['groups']
    pages, base, _ = vswap()
    templates = {}
    pools = pool_cover.pages()
    for g, (members, blob) in enumerate(group_list):
        for shape in members:
            art = sprite(pages[base + shape])
            original = [[] for _ in range(64)]
            for x, column in enumerate(art['columns'], art['left']):
                original[x] = [(a, b, bytes(raw)) for a, b, raw in column]
            body = [list(c) for c in original]
            if shape in pools:
                for x in range(64):
                    body[x], _ = pool_cover.split_runs(body[x], pools[shape][:2])
            runs = [[(a, b, blob.find(raw)) for a, b, raw in sorted(col, reverse=True)] for col in body]
            assert all(o >= 0 for col in runs for _, _, o in col)
            opaque = {t for column in original for a, b, _ in column for t in range(a, b)}
            if 32 in opaque:
                gap = (255, 0)
            else:
                lo, hi = 32, 33
                while lo > 0 and lo - 1 not in opaque:
                    lo -= 1
                while hi < 64 and hi not in opaque:
                    hi += 1
                gap = (lo, hi)
            clip = bytearray()
            for cut in range(32):
                used = [x for x, col in enumerate(original) if any(b > cut and a < 64 - cut for a, b, _ in col)]
                clip += bytes((min(used), max(used))) if used else bytes((64, 0))
            fixed = bytes((art['left'], art['right'], gap[0], gap[1] | (128 if shape in pools else 0))) + bytes(clip)
            templates[shape] = dict(group=g, runs=runs, fixed=fixed)
    return dict(data, templates=templates)


def floor_program(floor, program, wall_count):
    """Compress the wall placements to fill ranges plus aliases."""
    walls = program['walls']
    first = {}
    aliases, fresh = [], []
    for k, address in enumerate(walls):
        if address in first:
            aliases.append((k, first[address]))
        else:
            first[address] = k
            fresh.append(address)
    ranges = []
    for address in fresh:
        if ranges and ranges[-1][0] + 128 * ranges[-1][1] == address and ranges[-1][0] >> 16 == address >> 16:
            ranges[-1][1] += 1
        else:
            ranges.append([address, 1])
    if program.get('wall_mode') == 'pointers':
        # Packed walls: the pointer table is loaded; the generator takes each address from it.
        ranges, aliases = None, []
    return dict(groups=program['groups'], areas=program['areas'], strip_at=program['strip_at'], strips=program['strips'],
                commands=program['commands'], wall_ranges=ranges, wall_aliases=aliases,
                wall_count=wall_count, sight=program['sight'], walls=walls)


def mapped(raw, table):
    return b''.join(bytes(table[c]) for c in raw)


def regenerate(floor, prog, receipt, wall_pages, shapes_in_order, weapon_shapes, header_bytes):
    """Return {address: bytes} exactly as the native generator must write it."""
    from wolfdata import vswap, sprite
    pages, base, _ = vswap()
    data = shared()
    mapped = fixed_art.FloorColors(receipt)
    out = []
    # 1. Walls: ranks in id order; fresh slots come from the fill ranges.
    used = sorted({i for p in wall_pages for i in data['page_ids'][p]})
    assert len(used) == prog['wall_count']
    addresses = []
    if prog['wall_ranges'] is None:
        for rank, gid in enumerate(used):
            for light in range(4):
                address = prog['walls'][rank * 4 + light]
                addresses.append(address)
                out.append((address, mapped(data['columns'][gid], receipt['wall_lights'][light])))
    else:
        slots = [a + 128 * n for a, count in prog['wall_ranges'] for n in range(count)]
        alias = dict(prog['wall_aliases'])
        fresh = iter(slots)
        for rank, gid in enumerate(used):
            for light in range(4):
                k = rank * 4 + light
                if k in alias:
                    addresses.append(addresses[alias[k]])
                else:
                    address = next(fresh)
                    addresses.append(address)
                    out.append((address, mapped(data['columns'][gid], receipt['wall_lights'][light])))
    pointers = b''.join(struct.pack('<HH', a & 0xFFFF, (a >> 8) & 0xff00) for a in addresses)
    rank_of = {gid: rank for rank, gid in enumerate(used)}
    cache = bytearray(memmap.WALL_COLUMNS_SIZE)
    for page in wall_pages:
        for x in range(64):
            struct.pack_into('<HH', cache, page * 256 + x * 4, rank_of[data['page_ids'][page][x]] * 16, page << 8)
    # 2. Group areas: mapped blob, then the floor's strip blob.
    lights = receipt['sprite_lights']
    local = {gid: n for n, gid in enumerate(prog['groups'])}
    for g, gid in enumerate(prog['groups']):
        blob = data['groups'][gid][1]
        strip_blob, _ = prog['strips'][g]
        for light in range(4):
            out.append((prog['areas'][g, light], mapped(blob, lights[light])))
            if light == 0 or prog['strip_at'][g, light] != prog['strip_at'][g, light - 1]:
                out.append((prog['strip_at'][g, light], mapped(strip_blob, lights[light])))
    # 3. Commands from the shape templates; distinct columns in first-use order.
    import pool_cover
    ends = pool_cover.page_endpoints()
    command_ptrs = {}
    for shape in shapes_in_order:
        t = data['templates'][shape]
        g = local[t['group']]
        blob = data['groups'][t['group']][1]
        strip_blob, strip_runs = prog['strips'][g]
        strips = {(x, a): pos for s, x, a, pos in strip_runs if s == shape}
        keys = []
        for x, runs in enumerate(t['runs']):
            command = bytearray()
            strip = [(a, pos) for (sx, a), pos in strips.items() if sx == x]
            for a, pos in sorted(strip, reverse=True):
                command += struct.pack('<H', a | (ends[shape][1] << 8))
                for light in range(4):
                    command += struct.pack('<H', (prog['strip_at'][g, light] & 0xFFFF) + 2 * pos)
            for a, b, offset in runs:
                command += struct.pack('<H', a | (b << 8))
                for light in range(4):
                    command += struct.pack('<H', (prog['areas'][g, light] & 0xFFFF) + 2 * offset - 2 * a)
            command += b'\0\0'
            keys.append(bytes(command))
        canon = fixed_art.column_classes([[(a, b) + (o,) for a, b, o in runs] for runs in t['runs']],
                                         [sorted((a, pos) for (sx, a), pos in strips.items() if sx == x) for x in range(64)])
        at = prog['commands'][shape]
        out.append((at, b''.join(keys[x] for x in range(64) if canon[x] == x)))
        ptr = {}
        for x in range(64):
            if canon[x] == x:
                ptr[x] = at & 0xFFFF
                at += len(keys[x])
        command_ptrs[shape] = [ptr[canon[x]] for x in range(64)]
    # 4. Frame headers.
    headers = bytearray(header_bytes)
    for number, shape in enumerate(shapes_in_order):
        frame = number * FRAME_BYTES
        t = data['templates'][shape]
        g = local[t['group']]
        struct.pack_into('<64H', headers, frame, *command_ptrs[shape])
        headers[frame + FRAME_LEFT:frame + FRAME_COMMAND_BANK] = t['fixed']
        struct.pack_into('<H', headers, frame + FRAME_COMMAND_BANK, prog['commands'][shape] >> 16)
        headers[frame + FRAME_LIGHT_BANKS:frame + FRAME_LIGHT_BANKS + 4] = bytes(prog['areas'][g, l] >> 16 for l in range(4))
    for n, shape in enumerate(weapon_shapes):
        art = sprite(pages[base + shape])
        frame = len(shapes_in_order) * FRAME_BYTES + n * (FRAME_BYTES - FRAME_LEFT) - FRAME_LEFT
        headers[frame + FRAME_LEFT:frame + FRAME_LEFT + 2] = bytes((art['left'], art['right']))
        headers[frame + FRAME_GAP:frame + FRAME_GAP + 2] = bytes((255, 0))
        for cut in range(32):
            used_x = [x for x, col in enumerate(art['columns'], art['left']) if any(b > cut and a < 64 - cut for a, b, _ in col)]
            headers[frame + FRAME_CLIP + cut * 2:frame + FRAME_CLIP + cut * 2 + 2] = bytes((min(used_x), max(used_x))) if used_x else bytes((64, 0))
    out += [(memmap.SPRITE_CMDS, bytes(headers)), (WALL_POINTERS, pointers), (memmap.WALL_COLUMNS, bytes(cache))]
    return out
