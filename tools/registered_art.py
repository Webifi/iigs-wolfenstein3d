"""Exact A/B storage shared by independently lit frames and wall columns.

Each world frame uses one source bank at each of the four distances. The
builder may share any identical byte window, including between light levels.
No color lookup or decompression is required while drawing.
"""
import memmap
from dataclasses import dataclass, field
import json
from pathlib import Path
import struct

from probe_art_overlap import overlap_strings

FRAME_BYTES = 202
FRAME_LEFT = 128
FRAME_GAP = 130
FRAME_CLIP = 132
FRAME_COMMAND_BANK = 196
FRAME_LIGHT_BANKS = 198
ENDPOINT_ORIGINALS = memmap.REG_ENDPOINT_ORIGINALS
WALL_POINTERS = memmap.WALL_LIGHT_POINTERS
ROOT_SOUND = str(Path(__file__).resolve().parents[1] / "build/sound")

# These ranges are unavailable to the corresponding paused UI or inactive
# view data. The floor loader and transition restore groups own their lifetime.
# Every hot arithmetic table keeps its original byte format and address.
EXTRA_RANGES = (
    (memmap.LOGIC_ART_HOLE, memmap.LOGIC_ART_HOLE_END),  # state table ends before B000
    (memmap.SPARE_3A, memmap.GRAY_BASE),  # after gray conversion code
    (memmap.TINTS_SPARE, memmap.LEVEL_IO),  # after the shared HUD tint load
    ((memmap.WALL_COLUMNS_END if memmap.WALL_COLUMNS == memmap.SHR_SHADOW else memmap.SHR_SHADOW), memmap.REMEMBERED),
    (memmap.HORIZONTAL_SPARE, memmap.SHORT_LIGHT_MAPS),
    (memmap.SHORT_LIGHT_SPARE, memmap.ENDPOINTS),  # FF00-FF7F holds sixteen short-light horizontal maps
    (memmap.UI_SPARE, memmap.VIEW_HEIGHT), (memmap.VIEW_HEIGHT_SPARE, memmap.SHADING),
    (memmap.SHADING_SPARE, memmap.DEMOS), (memmap.CLIPS_SPARE, memmap.ROWCODE),
    (memmap.ROWCODE_SPARE, memmap.MAP), (memmap.SHAREWARE_LINEIDS, memmap.LOGIC_LOW), (memmap.REGISTERED_LOGIC_SPARE, memmap.WALL_CAST),
    (memmap.THRUST_SPARE, memmap.RAY_PRODUCTS_DIRECTORY), (memmap.RAW_BOOT, memmap.WEIGHTS),
    (memmap.WEIGHTS_SPARE, memmap.UI_EXTRA), (memmap.MENU_CACHE_4, memmap.ART_BASE),
    (memmap.BOOT_SEEDS_ART, memmap.BOOT_SEEDS_ART_END),
    (memmap.SPARE_33, memmap.RAY_FOCAL), (memmap.SPARE_35, memmap.TANGENT),
    (memmap.RAY_WEIGHTS_HIGH, memmap.SFX_BASE),
    (memmap.GRAY_RECS, memmap.GRAY_FLOOR), (memmap.MENU_CACHE_8, memmap.SPR_RECORDS),
    ((memmap.MENU_FRAME+0x4a00), memmap.ATTRACT_RESERVE), (memmap.SPARE_3C, memmap.HEIGHT_TABLE),
    (memmap.SPARE_3D, memmap.SOUND_CODE), (memmap.SPARE_3F, memmap.DISPLAY_BACKUP),
    (memmap.MENU_CACHE_7, memmap.UI_BOXBUF), (memmap.TITLE_SONG, memmap.MENU_CACHE_1_END),
    (memmap.SNAP_PIX, memmap.SNAP_PIX_END), (memmap.MENU_CACHE_5, memmap.MENU_CACHE_3_END),
)


class Space:
    """Bank-local fragments; every allocation retains its exact payload."""
    def __init__(self, ranges):
        for start, end in ((memmap.DRAW_BUFFER, memmap.DRAW_BUFFER_END),
                           (memmap.WALL_PAINT, memmap.WALL_PAINT_END)):
            ranges = [(lo, hi) for a, b in ranges
                      for lo, hi in ((a, min(b, start)), (max(a, end), b)) if lo < hi]
        self.free = [list(r) for r in sorted(ranges)]
        self.records = []
        self.kinds = []
        for start, end in self.free:
            assert start < end and start >> 16 == (end - 1) >> 16

    def available(self, bank):
        return sum(b-a for a,b in self.free if a >> 16 == bank)

    def place(self, raw, kind, bank=None, largest=False, bias=0):
        choices = []
        for n, (a, b) in enumerate(self.free):
            a = max(a, (a & ~65535) + bias)
            if (bank is None or a >> 16 == bank) and a + len(raw) <= b:
                choices.append((-(b-a) if largest else b-a, a, n))
        if not choices:
            raise ValueError(f'no {len(raw)} byte {kind} window in bank {bank}; '
                             f'{sum(b-a for a,b in self.free)} free bytes')
        _, address, n = min(choices)
        start, end = self.free.pop(n)
        # A biased sprite source cannot use the beginning of a bank, but a
        # wall column or command can. Keep that prefix available.
        self.free[n:n] = ([ [start, address] ] if start < address else []) + (
            [ [address + len(raw), end] ] if address + len(raw) < end else [])
        self.records.append((address, bytes(raw)))
        self.kinds.append(kind)
        return address


def layout_include():
    from wolfdata import ROOT
    import pool_cover
    pool_count = len(pool_cover.feature_starts()) * 2
    stride = 65 + pool_count
    constants = dict(SPR_HEADER_BYTES=FRAME_BYTES, SPR_LEFT=FRAME_LEFT,
                     SPR_GAP=FRAME_GAP, SPR_CLIP=FRAME_CLIP,
                     SPR_COMMAND_BANK=FRAME_COMMAND_BANK, SPR_LIGHT_BANKS=FRAME_LIGHT_BANKS,
                     SPR_RUN_BYTES=10, SPR_EP_SOURCE=ENDPOINT_ORIGINALS,
                     SPR_EP_PLANS=ENDPOINT_ORIGINALS + 200 * stride,
                     SPR_EP_LIMIT=200 + pool_count, SPR_EP_STRIDE=stride,
                     WALL_LIGHT_POINTERS=WALL_POINTERS)
    (ROOT / 'build/gen/sprite_layout.inc').write_text(
        '\n'.join(f'{k} .equ 0x{v:x}' for k,v in constants.items()) + '\n')


def pack_floor(floor, palette_dir):
    """Return exact bank-safe art, frame commands, and four-light wall pointers."""
    groups, walls, frames, receipt = floor_parts(floor, palette_dir)
    from wolfdata import maps, vswap, sprite, PROFILE
    from wolf_source import sprite_ids
    from native_map_format import wall_material
    pages, base, _ = vswap()
    ids = sprite_ids()
    weapon_shapes = range(ids['SPR_KNIFEREADY'], ids['SPR_CHAINREADY'] + 5)
    # Weapon coverage still needs silhouette metadata, but its source runs
    # live only in the host oracle. Bias these short headers past the unused
    # column-pointer fields, retaining the renderer's ordinary field reads.
    header_bytes = len(frames)*FRAME_BYTES + len(weapon_shapes)*(FRAME_BYTES-FRAME_LEFT)
    tiles = {m for t in maps()[floor]['planes'][0] if (m:=wall_material(t)) is not None}
    if 21 in tiles:
        tiles.add(22)
    wall_pages = sorted({p for t in tiles for p in (2*(t-1),2*(t-1)+1)} | set(range(base-8,base)))
    wall_pages = [p for p in wall_pages if len(pages[p]) == 4096]
    if PROFILE.spear:
        from fixed_art import wall_pages as drawn_wall_pages
        wall_pages = drawn_wall_pages(floor)
    raw_walls = sorted({bytes(pages[p][x*64:(x+1)*64]) for p in wall_pages for x in range(64)})
    if len(raw_walls)*16 > 0xfc00:
        raise ValueError('wall light pointers exceed their bank')
    ranges = [(b*65536, (b+1)*65536) for b in range(0x10,0x30)]
    ranges += [(memmap.SPRITE_CMDS+header_bytes,memmap.BLOCK_DIR), (memmap.BLOCK_DIR,memmap.VIS_STAMPS),
               (WALL_POINTERS+len(raw_walls)*16,memmap.PIC_KEEP)]
    ranges += EXTRA_RANGES
    if memmap.WALL_COLUMNS != memmap.SHR_SHADOW:
        # The Spear directory is live throughout play, outside allocatable art.
        a, b = memmap.WALL_COLUMNS, memmap.WALL_COLUMNS_END
        ranges = [(lo, hi) for x, y in ranges
                  for lo, hi in ((x, min(y, a)), (max(x, b), y)) if lo < hi]
    from build_logic import state_table, LAYOUT
    assert LAYOUT['STATES'] + len(state_table()[0]) <= 0xb000
    effect_manifest = Path(__import__('os').environ.get('WOLF_FLOOR_EFFECTS',
                            ROOT_SOUND)) / f'effects-floor-{floor:02}-loads.json'
    if effect_manifest.exists():
        for row in json.loads(effect_manifest.read_text()):
            a,b = row['address'], row['address'] + row['bytes']
            ranges = [(lo,hi) for x,y in ranges
                      for lo,hi in ((x,min(y,a)),(max(x,b),y)) if lo<hi]
    space = Space(ranges)
    banks = frame_banks(groups)
    art_banks, art_offsets = {}, {}
    for b in sorted(banks, key=lambda b: -len(b.blob)):
        address = space.place(b.blob, 'sprite art', largest=True, bias=128)
        for key in b.groups:
            art_banks[key] = address >> 16
            for raw in groups[key]:
                at = b.blob.find(raw)
                while at & 1:
                    at = b.blob.find(raw, at+1)
                assert at >= 0
                art_offsets[key, raw] = (address & 65535) + at
    # A frame's command pointers all use the same bank. Commands contain a
    # shared pair of endpoints followed by one corrected offset per light.
    column_bytes, keys_by_frame = {}, {}
    for shape, _, columns, _ in frames:
        keys = []
        for column in columns:
            command = bytearray()
            for a,b,raw in sorted(column,reverse=True):
                offsets = []
                for light,mapping in enumerate(receipt['sprite_lights']):
                    ab = b''.join(bytes(mapping[c]) for c in raw)
                    offset = art_offsets[(shape,light),ab] - (a*2 if a<200 else 0)
                    assert offset >= 0
                    offsets.append(offset)
                command += struct.pack('<5H',a|(b<<8),*offsets)
            command += b'\0\0'
            keys.append(bytes(command))
        keys_by_frame[shape] = keys
        column_bytes[shape] = set(keys)
    command_ptrs, command_banks = {}, {}
    contents = {b:set() for b in {a>>16 for a,b in space.free}}
    for shape in sorted(column_bytes,key=lambda s:(-sum(map(len,column_bytes[s])),s)):
        pieces = column_bytes[shape]
        choices = []
        for bank, have in contents.items():
            extra = pieces-have
            cost = sum(map(len,extra))
            room = space.available(bank)
            if cost <= room and max(map(len,extra),default=0) <= max((b-a for a,b in space.free if a>>16==bank),default=0):
                trial = Space([r for r in space.free if r[0]>>16 == bank])
                try:
                    for raw in sorted(extra,key=lambda b:(-len(b),b)):
                        trial.place(raw,'commands')
                except ValueError:
                    continue
                choices.append((cost,room-cost,bank))
        if not choices:
            raise ValueError(f'no command bank for shape {shape}')
        _,_,bank = min(choices)
        for raw in sorted(pieces-contents[bank],key=lambda b:(-len(b),b)):
            address = space.place(raw,'sprite commands',bank=bank)
            command_ptrs[bank,raw] = address & 65535
        contents[bank].update(pieces)
        command_banks[shape] = bank
    # Long wall paths are split with a 126-byte overlap, retaining every
    # complete 128-byte source column across each physical bank boundary.
    wall_addresses = {}
    unmatched = set(walls)
    for (address,raw),kind in zip(space.records,space.kinds):
        if kind != 'sprite art':
            continue
        for piece in tuple(unmatched):
            at=raw.find(piece)
            while at>=0 and at&1:
                at=raw.find(piece,at+1)
            if at>=0:
                wall_addresses[piece]=address+at
                unmatched.remove(piece)
    # Each piece holds whole strings only, from the first string the earlier pieces
    # did not hold to its last whole string: the art generator writes every byte of
    # every piece (build_registered_sprites: walls of this layout are generated).
    wall_blob, wall_stats = overlap_strings(unmatched, alignment=2)
    where={}
    for raw in unmatched:
        at=wall_blob.find(raw)
        while at&1:at=wall_blob.find(raw,at+1)
        where[raw]=at
    spans=sorted(set((at,at+len(raw)) for raw,at in where.items()));done=0
    while done<len(spans):
        start=spans[done][0]
        room=max((b-a for a,b in space.free),default=0)&~1
        if room<spans[done][1]-start:
            raise ValueError(f'wall storage exhausted with {len(spans)-done} strings left')
        end=start
        while done<len(spans) and spans[done][1]<=start+room:
            end=max(end,spans[done][1]);done+=1
        address=space.place(wall_blob[start:end],'wall art',largest=True)
        for raw,at in where.items():
            if start<=at and at+len(raw)<=end and raw not in wall_addresses:
                wall_addresses[raw]=address+at-start
    wall_pointers=bytearray();wall_ids={raw:i*16 for i,raw in enumerate(raw_walls)}
    for raw in raw_walls:
        for mapping in receipt['wall_lights']:
            address=wall_addresses[b''.join(bytes(mapping[c]) for c in raw)]
            wall_pointers+=struct.pack('<HH',address&65535,(address>>8)&0xff00)
    cache=bytearray(memmap.WALL_COLUMNS_SIZE)
    for page in wall_pages:
        for x in range(64):
            token=wall_ids[bytes(pages[page][x*64:(x+1)*64])]
            struct.pack_into('<HH',cache,page*256+x*4,token,page<<8)
    headers=bytearray(header_bytes)
    frame_offsets={}
    import pool_cover
    pools=pool_cover.pages()
    for number,(shape,art,columns,original) in enumerate(frames):
        frame=number*FRAME_BYTES;frame_offsets[shape]=frame
        bank=command_banks[shape]
        struct.pack_into('<64H',headers,frame,*(command_ptrs[bank,c] for c in keys_by_frame[shape]))
        headers[frame+FRAME_LEFT:frame+FRAME_LEFT+2]=bytes((art['left'],art['right']))
        opaque={t for column in original for a,b,_ in column for t in range(a,b)}
        if 32 in opaque:gap=(255,0)
        else:
            lo,hi=32,33
            while lo>0 and lo-1 not in opaque:lo-=1
            while hi<64 and hi not in opaque:hi+=1
            gap=(lo,hi)
        headers[frame+FRAME_GAP:frame+FRAME_GAP+2]=bytes((gap[0],gap[1]|(128 if shape in pools else 0)))
        for cut in range(32):
            used=[x for x,col in enumerate(original) if any(b>cut and a<64-cut for a,b,_ in col)]
            headers[frame+FRAME_CLIP+cut*2:frame+FRAME_CLIP+cut*2+2]=bytes((min(used),max(used))) if used else bytes((64,0))
        struct.pack_into('<H',headers,frame+FRAME_COMMAND_BANK,bank)
        headers[frame+FRAME_LIGHT_BANKS:frame+FRAME_LIGHT_BANKS+4]=bytes(art_banks.get((shape,l),0) for l in range(4))
    for n,shape in enumerate(weapon_shapes):
        art=sprite(pages[base+shape])
        frame=len(frames)*FRAME_BYTES+n*(FRAME_BYTES-FRAME_LEFT)-FRAME_LEFT
        frame_offsets[shape]=frame
        headers[frame+FRAME_LEFT:frame+FRAME_LEFT+2]=bytes((art['left'],art['right']))
        headers[frame+FRAME_GAP:frame+FRAME_GAP+2]=bytes((255,0))
        for cut in range(32):
            used=[x for x,col in enumerate(art['columns'],art['left']) if any(b>cut and a<64-cut for a,b,_ in col)]
            headers[frame+FRAME_CLIP+cut*2:frame+FRAME_CLIP+cut*2+2]=bytes((min(used),max(used))) if used else bytes((64,0))
    records=space.records+[(memmap.SPRITE_CMDS,bytes(headers)),(WALL_POINTERS,bytes(wall_pointers)),(memmap.WALL_COLUMNS,bytes(cache))]
    # Verify every resident interval and every original mapped window.
    ordered=sorted(records)
    for (a,raw),(b,_) in zip(ordered,ordered[1:]):assert a+len(raw)<=b,(hex(a),hex(b))
    peak=max(a+len(raw) for a,raw in records);assert peak<=memmap.FAST_RAM_END
    report=dict(floor=floor,frames=len(frames),wall_columns=len(raw_walls),
                bytes_by_kind={k:sum(len(raw) for (_,raw),kind in zip(space.records,space.kinds) if kind==k)
                               for k in set(space.kinds)},headers_bytes=len(headers),wall_pointer_bytes=len(wall_pointers),
                free_bytes=sum(b-a for a,b in space.free),highest_address=peak-1,wall_overlap=wall_stats,
                wall_records=[a for (a,_),kind in zip(space.records,space.kinds) if kind=='wall art'])
    return records,frame_offsets,frames,receipt,report


@dataclass
class Bank:
    capacity: int = 65536 - 128
    pieces: set = field(default_factory=set)
    groups: list = field(default_factory=list)
    size: int = 0
    blob: bytes = b''

    def compact(self):
        self.blob, _ = overlap_strings(self.pieces, alignment=2)
        self.size = len(self.blob)


def frame_banks(groups):
    """Pack complete frame/light groups, preferring exact shared runs.

    Compression is a build-time operation. The final allocation is verified
    against byte windows and the bank boundary, independent of this heuristic.
    """
    banks = []
    for key, pieces in sorted(groups.items(), key=lambda p: (-sum(map(len, p[1])), p[0])):
        if not pieces:
            continue
        total = sum(map(len, pieces))
        costs = [(sum(map(len, pieces - b.pieces)), i) for i, b in enumerate(banks)]
        costs.sort(key=lambda pair: (pair[0], banks[pair[1]].capacity - banks[pair[1]].size))
        chosen = None
        for cost, i in costs:
            b = banks[i]
            if b.size + cost <= b.capacity:
                chosen = (b, cost)
                break
            # A fresh compaction can recover suffix/prefix and substring space.
            # Try only a strongly related bank; unrelated groups fill a new one.
            if cost < total * .65:
                trial, _ = overlap_strings(b.pieces | pieces, alignment=2)
                if len(trial) <= b.capacity:
                    b.blob = trial
                    chosen = (b, len(trial) - b.size)
                    break
        if chosen is None:
            b = Bank()
            banks.append(b)
            chosen = (b, total)
        b, cost = chosen
        b.pieces.update(pieces)
        b.groups.append(key)
        b.size += cost
        if b.size > b.capacity:
            b.compact()
            if b.size > b.capacity:
                raise ValueError(f'frame {key} needs {b.size} source bytes in one bank')
    for b in banks:
        b.compact()
    return banks


def floor_parts(floor, palette_dir, include_mapped=True):
    import pool_cover
    from floor_art import shapes, ceiling, floor_color
    from wolfdata import maps, vswap, sprite, PROFILE

    level = maps()[floor]
    receipt = json.loads((Path(palette_dir) / f'{floor}.json').read_text())
    pages, base, _ = vswap()
    pools = pool_cover.pages()
    ends = pool_cover.page_endpoints()
    colors = pool_cover.Colors(receipt['sprite_lights'], receipt['palette'],
                              receipt['wall_ab'][floor_color()][0] & 15)
    actors, objects, weapons = shapes(level)
    groups = {}
    frames = []
    for shape in sorted(actors | objects):
        art = sprite(pages[base + shape])
        columns = [[] for _ in range(64)]
        for x, column in enumerate(art['columns'], art['left']):
            columns[x] = [(a, b, bytes(raw)) for a, b, raw in column]
        original = [list(c) for c in columns]
        if shape in pools:
            feature = pools[shape]
            low, high, _ = ends[shape]
            strips = pool_cover.strips(columns, feature, colors)
            for x in range(64):
                columns[x], _ = pool_cover.split_runs(columns[x], feature[:2])
                if any(c != colors.gray for c in strips[x]):
                    columns[x].append((low, high, strips[x]))
        frames.append((shape, art, columns, original))
    for shape, _, columns, _ in (frames if include_mapped else ()):
        runs = {raw for col in columns for _, _, raw in col}
        for light, mapping in enumerate(receipt['sprite_lights']):
            groups[shape, light] = {b''.join(bytes(mapping[c]) for c in raw) for raw in runs}
    from native_map_format import wall_material
    tiles = {m for t in level['planes'][0] if (m:=wall_material(t)) is not None}
    if 21 in tiles:
        tiles.add(22)
    wall_pages = sorted({p for t in tiles for p in (2 * (t - 1), 2 * (t - 1) + 1)} |
                        set(range(base - 8, base)))
    if PROFILE.spear:
        from fixed_art import wall_pages as drawn_wall_pages
        wall_pages = drawn_wall_pages(floor)
    raw_walls = {bytes(pages[p][u:u + 64]) for p in wall_pages
                 if len(pages[p]) == 4096 for u in range(0, 4096, 64)}
    walls = {b''.join(bytes(mapping[c]) for c in raw) for raw in raw_walls
             for mapping in receipt['wall_lights']} if include_mapped else set()
    return groups, walls, frames, receipt


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--palettes', type=Path, required=True)
    ap.add_argument('--floors', type=int, nargs='+', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    report = []
    for floor in args.floors:
        groups, walls, frames, _ = floor_parts(floor, args.palettes)
        banks = frame_banks(groups)
        unmatched = set(walls)
        for bank in banks:
            unmatched = {raw for raw in unmatched if bank.blob.find(raw) < 0}
        wall_blob, wall_stats = overlap_strings(unmatched, alignment=2)
        row = dict(floor=floor, frames=len(frames), sprite_banks=len(banks),
                   sprite_bytes=sum(len(b.blob) for b in banks),
                   sprite_slack=sum(b.capacity - len(b.blob) for b in banks),
                   walls_unmatched=wall_stats,
                   combined_bytes=sum(len(b.blob) for b in banks) + len(wall_blob),
                   group_sizes=[dict(groups=len(b.groups), bytes=len(b.blob)) for b in banks])
        report.append(row)
        print(json.dumps(row), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
