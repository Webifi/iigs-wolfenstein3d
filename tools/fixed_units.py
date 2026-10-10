"""Binary units for the loader-built art, and a byte-level model of the generator.

Load-time scratch is in sound-effect RAM, overwritten by the final effect loads.
The selected memmap supplies its addresses and bounds:
  SFX_BASE     column chunk, group blob or group templates, below GEN_USED
               (chunks and blobs hold doubled indexes: u16 c*2)
  GEN_USED     bitmap and shape workspace; GEN_BITMAP_BYTES bounds the bitmap
  FIXED_GEN    generator code, loaded as a raw shared unit
  FLOOR_STAGE  bank-aligned decode stage; decoders use offsets within its bank
  GEN_PAGES    page table, dead after the program step; overlaps FLOOR_STAGE
  GEN_PROG     floor program

Floor unit order (the episode-disk part of a floor load,
loader then calls the generator after every unit until it reports done:
  GEN loaded -> program step; per group: BLOB g -> art step, TMPL g -> command
  step; per chunk: COLS k -> column step. Then the effects. The floor-disk part
  (WEAPONHDR, the sight units, the rest) loads before or after it.
Groups come first: they never use pause-menu RAM, walls fill it last.

Program (little endian):
  +0  'FP'          +2  wall section offset   +4 group section offset
  +6  frame count   +8  header bytes          +10 global column count
  +12 sight parameters offset (0: the floor has no sight proofs)
  +16 wall light tables 4 x 512, then sprite light tables 4 x 512 (A, B per index)
  wall section: page bitmap 16 bytes, u16 column count,
                u16 ranges, ranges x (addr24, u16 slots),
                u16 aliases, aliases x (u16 entry, u16 target entry)  (entry = rank*4+light);
                ranges $FFFF (packed walls): no ranges, no aliases; the wall
                pointer table ($0A:0000) is loaded before the program and gives
                the address of every entry
  group section: u16 groups, then per group (load order):
                u8 id, u16 blob texels, 4 x addr24 areas,
                4 x addr24 strip copies (a repeat means shared),
                u16 strip texels (the strip bytes are a shared unit, STRIP, loaded
                at SRC + 2 x blob texels right after the blob),
                per member (template order): u16 frame, addr24 commands,
                u16 strip count, strips x (u8 x, u16 strip position)
  sight parameters: addr24 matrix rows, u16 row stride, u16 rooms.
  The generator does not read them. With sight, the floor-disk part loads the
  matrix with only bits j <= i of row i (at its rows), the parameters with ROOMS
  (u16 room per cell, at SIGHT_PARAMS and SIGHT_ROOMS) and the sight unit
  (src/iigs/sight_gen.s), which writes the 32 KB tables at $32:0000 and copies
  each bit (i, j) to (j, i) (op_sight, op_matrix below).
Template unit: u16 members, then per member: u16 shape, 68 header
  bytes (+128..+195), u8 pool low, u8 pool high, 64 x u8 first equal column,
  then 64 columns: u8 runs, runs x (u8 a, u8 b, u16 blob offset).
"""
import struct

import fixed_art
import fixed_store
import memmap
from registered_art import FRAME_BYTES, FRAME_LEFT, WALL_POINTERS

SRC, USED, GEN, PROG, PAGES = memmap.SFX_BASE, memmap.GEN_USED, memmap.FIXED_GEN, memmap.GEN_PROG, memmap.GEN_PAGES
ROOMS = memmap.SIGHT_ROOMS
assert ROOMS >> 16 == memmap.SIGHT_GEN >> 16, 'sight_gen.s reads the rooms in its own bank'
CHUNK = 384
LIMITS = dict(SRC=49152, USED=memmap.GEN_BITMAP_BYTES, GEN=memmap.FIXED_GEN_SIZE, PROG=26624, PAGES=memmap.GEN_PAGES_SIZE, STAGE=28672)


def a24(value):
    return struct.pack('<HB', value & 0xFFFF, value >> 16)


def shared_units():
    """Palette-independent units: page table, column chunks, group units."""
    d = fixed_store.shared()
    pages = bytearray(memmap.WALL_PAGE_COUNT * 128)
    for p in range(memmap.WALL_PAGE_COUNT):
        ids = d['page_ids'].get(p)
        for x in range(64):
            struct.pack_into('<H', pages, p * 128 + x * 2, ids[x] if ids else 0xFFFF)
    doubled = lambda raw: b''.join(struct.pack('<H', 2 * c) for c in raw)
    cols = [doubled(b''.join(d['columns'][k:k + CHUNK])) for k in range(0, len(d['columns']), CHUNK)]
    import pool_cover
    ends = pool_cover.page_endpoints()
    blobs, tmpls = [], []
    for g, (members, blob) in enumerate(d['groups']):
        t = bytearray(struct.pack('<H', len(members)))
        for shape in members:
            tp = d['templates'][shape]
            first = {}
            fe = [first.setdefault(tuple(runs), x) for x, runs in enumerate(tp['runs'])]
            low, high = (ends[shape][0], ends[shape][1]) if shape in ends else (0, 0)
            t += struct.pack('<H', shape) + tp['fixed'] + bytes((low, high)) + bytes(fe)
            for runs in tp['runs']:
                t.append(len(runs))
                for a, b, offset in runs:
                    t += struct.pack('<BBH', a, b, offset)
        # The store makes no record for an empty file; the generator expects one unit per blob.
        blobs.append(doubled(blob) or b'\0\0')
        tmpls.append(bytes(t))
    assert len(pages) <= LIMITS['PAGES']
    assert max(map(len, cols + blobs + tmpls)) <= LIMITS['SRC'], max(map(len, cols + blobs + tmpls))
    assert (len(d['columns']) + 7) // 8 <= LIMITS['USED']
    return dict(pages=bytes(pages), cols=cols, blobs=blobs, tmpls=tmpls, columns=len(d['columns']))


def program_unit(prog, receipt, wall_pages, shapes_in_order, header_bytes):
    d = fixed_store.sources()
    out = bytearray(16)
    for table in receipt['wall_lights'] + receipt['sprite_lights']:
        out += b''.join(bytes(table[c]) for c in range(256))
    wall_at = len(out)
    bitmap = bytearray(memmap.WALL_BITMAP_BYTES)
    for p in wall_pages:
        bitmap[p >> 3] |= 1 << (p & 7)
    if prog['wall_ranges'] is None:
        out += bitmap + struct.pack('<HH', prog['wall_count'], 0xFFFF)
    else:
        out += bitmap + struct.pack('<HH', prog['wall_count'], len(prog['wall_ranges']))
        for address, count in prog['wall_ranges']:
            out += a24(address) + struct.pack('<H', count)
    out += struct.pack('<H', len(prog['wall_aliases']))
    for k, target in prog['wall_aliases']:
        out += struct.pack('<HH', k, target)
    group_at = len(out)
    out += struct.pack('<H', len(prog['groups']))
    frame_of = {s: n for n, s in enumerate(shapes_in_order)}
    for g, gid in enumerate(prog['groups']):
        members, blob = d['groups'][gid]
        strip_blob, strip_runs = prog['strips'][g]
        assert 2 * len(blob) + len(strip_blob) <= LIMITS['SRC'], ('group source overlaps generator scratch', gid, len(blob), len(strip_blob))
        out += struct.pack('<BH', gid, len(blob))
        for light in range(4):
            out += a24(prog['areas'][g, light])
        for light in range(4):
            out += a24(prog['strip_at'][g, light])
        out += struct.pack('<H', len(strip_blob))
        for shape in members:
            runs = sorted((x, pos) for s, x, a, pos in strip_runs if s == shape)
            out += struct.pack('<H', frame_of[shape])
            out += a24(prog['commands'][shape]) + struct.pack('<H', len(runs))
            for x, pos in runs:
                out += struct.pack('<BH', x, pos)
    sight_at = 0
    if prog.get('sight'):
        sight_at = len(out)
        rows_at, stride, rooms = prog['sight']
        out += a24(rows_at) + struct.pack('<HH', stride, rooms)
    struct.pack_into('<2sHHHHHH', out, 0, b'FP', wall_at, group_at, len(shapes_in_order), header_bytes,
                     len(d['columns']), sight_at)
    assert len(out) <= LIMITS['PROG'], len(out)
    return bytes(out)


class Model:
    """Byte-level model of the native generator; RAM is a bytearray."""
    def __init__(self):
        self.ram = bytearray(memmap.FAST_RAM_END)
        self.written = bytearray(memmap.FAST_RAM_END)

    def put(self, address, data):
        self.ram[address:address + len(data)] = data
        self.written[address:address + len(data)] = b'\1' * len(data)

    def u8(self, a):
        return self.ram[a]

    def u16(self, a):
        return self.ram[a] | self.ram[a + 1] << 8

    def u24(self, a):
        return self.u16(a) | self.ram[a + 2] << 16

    def expand(self, src, count, table, dest):
        """count index bytes at src -> A/B words at dest through a 512-byte light table."""
        out = bytearray()
        for i in range(count):
            c = self.ram[src + i]
            out += self.ram[table + 2 * c:table + 2 * c + 2]
        self.put(dest, out)

    def expand4(self, src, count, tables, dests):
        """count doubled indexes (u16 2c) at src -> four A/B streams, one per light.
        A destination of None is an alias: its writes go nowhere."""
        for light in range(4):
            if dests[light] is None:
                continue
            out = bytearray()
            for i in range(count):
                c2 = self.u16(src + 2 * i)
                out += self.ram[tables + 512 * light + c2:tables + 512 * light + c2 + 2]
            self.put(dests[light], out)

    def load(self, address, data):
        self.ram[address:address + len(data)] = data

    def op_program(self):
        """After PROG and PAGES: used bitmap, column cache (via a temporary
        rank table in SRC), and the wall walk state."""
        wall = PROG + self.u16(PROG + 2)
        columns = self.u16(PROG + 10)
        self.ram[USED:USED + 1024] = bytes(1024)
        for p in range(memmap.WALL_PAGE_COUNT):
            if self.ram[wall + (p >> 3)] >> (p & 7) & 1:
                for x in range(64):
                    gid = self.u16(PAGES + p * 128 + x * 2)
                    self.ram[USED + (gid >> 3)] |= 1 << (gid & 7)
        rank = 0
        # The temporary rank table uses the load buffer; no unit is in it yet.
        for gid in range(columns):
            self.ram[SRC + 2 * gid:SRC + 2 * gid + 2] = struct.pack('<H', rank * 16)
            if self.ram[USED + (gid >> 3)] >> (gid & 7) & 1:
                rank += 1
        assert rank == self.u16(wall + memmap.WALL_BITMAP_BYTES)
        cache = bytearray(memmap.WALL_COLUMNS_SIZE)
        for p in range(memmap.WALL_PAGE_COUNT):
            if self.ram[wall + (p >> 3)] >> (p & 7) & 1:
                for x in range(64):
                    gid = self.u16(PAGES + p * 128 + x * 2)
                    struct.pack_into('<HH', cache, p * 256 + x * 4, self.u16(SRC + 2 * gid), p << 8)
        self.put(memmap.WALL_COLUMNS, cache)
        ranges = self.u16(wall + memmap.WALL_BITMAP_BYTES + 2)
        self.loaded_pointers = ranges == 0xFFFF
        if self.loaded_pointers:
            ranges = 0
        self.range_at, self.range_end = wall + memmap.WALL_BITMAP_BYTES + 4, wall + memmap.WALL_BITMAP_BYTES + 4 + 5 * ranges
        self.slots_left = 0
        self.alias_at = self.range_end + 2
        self.alias_end = self.alias_at + 4 * self.u16(self.range_end)
        self.entry = 0
        self.group_at = PROG + self.u16(PROG + 4) + 2

    def next_slot(self):
        if not self.slots_left:
            assert self.range_at < self.range_end
            self.slot, self.slots_left = self.u24(self.range_at), self.u16(self.range_at + 3)
            self.range_at += 5
        address = self.slot
        self.slot += 128
        self.slots_left -= 1
        return address

    def op_columns(self, chunk):
        """After COLS chunk in SRC."""
        columns = self.u16(PROG + 10)
        for i in range(min(CHUNK, columns - chunk * CHUNK)):
            gid = chunk * CHUNK + i
            if not self.ram[USED + (gid >> 3)] >> (gid & 7) & 1:
                continue
            dests = []
            for light in range(4):
                pointer = WALL_POINTERS + self.entry * 4
                if self.loaded_pointers:
                    dests.append(self.u16(pointer) | self.u16(pointer + 2) << 8)
                elif self.alias_at < self.alias_end and self.u16(self.alias_at) == self.entry:
                    target = WALL_POINTERS + self.u16(self.alias_at + 2) * 4
                    self.alias_at += 4
                    self.put(pointer, self.ram[target:target + 4])
                    dests.append(None)
                else:
                    address = self.next_slot()
                    self.put(pointer, struct.pack('<HH', address & 0xFFFF, (address >> 8) & 0xff00))
                    dests.append(address)
                self.entry += 1
            self.expand4(SRC + 128 * i, 64, PROG + 16, dests)

    def op_matrix(self):
        """After the lower matrix at its rows: bit (j, i) of every set bit (i, j), j < i."""
        at = PROG + self.u16(PROG + 12)
        rows_at, stride, n = self.u24(at), self.u16(at + 3), self.u16(at + 5)
        rows = [int.from_bytes(self.ram[rows_at + i * stride:rows_at + (i + 1) * stride], 'little') for i in range(n + 1)]
        full = list(rows)
        for i, v in enumerate(rows):
            for j in range(i):
                if v >> j & 1:
                    full[j] |= 1 << i
        for i, v in enumerate(full):
            self.put(rows_at + i * stride, v.to_bytes(stride, 'little'))

    def op_sight(self):
        """At the program step, from ROOMS: the engine's row, offset and mask tables."""
        at = PROG + self.u16(PROG + 12)
        rows_at, stride = self.u24(at), self.u16(at + 3)
        directory, offsets, masks = bytearray(16384), bytearray(8192), bytearray(8192)
        for cell in range(4096):
            k = self.u16(ROOMS + 2 * cell)
            address = rows_at + k * stride
            struct.pack_into('<HH', directory, 4 * cell, address & 0xFFFF, address >> 16)
            if k:
                struct.pack_into('<H', offsets, 2 * cell, k >> 3)
                struct.pack_into('<H', masks, 2 * cell, 1 << (k & 7))
        self.put(memmap.BLOCK_DIR, bytes(directory + offsets + masks))

    def op_group_art(self, gid):
        """After BLOB gid (doubled) in SRC."""
        at = self.group_at
        assert self.u8(at) == gid
        blob_len = self.u16(at + 1)
        areas = [self.u24(at + 3 + 3 * l) for l in range(4)]
        strip_at = [self.u24(at + 15 + 3 * l) for l in range(4)]
        strip_len = self.u16(at + 27)
        strip_src = SRC + 2 * blob_len
        at += 29
        self.expand4(SRC, blob_len, PROG + 16 + 2048, areas)
        for light in range(4):
            if light == 0 or strip_at[light] != strip_at[light - 1]:
                self.expand(strip_src, strip_len, PROG + 16 + 2048 + 512 * light, strip_at[light])
        self.group_state = (at, blob_len, areas, strip_at)

    def op_group_commands(self, gid):
        """After TMPL gid in SRC."""
        at, blob_len, areas, strip_at = self.group_state
        members = self.u16(SRC)
        t = SRC + 2
        for _ in range(members):
            frame = self.u16(at)
            commands = self.u24(at + 2)
            nstrips = self.u16(at + 5)
            strips = {self.u8(at + 7 + 3 * k): self.u16(at + 8 + 3 * k) for k in range(nstrips)}
            at += 7 + 3 * nstrips
            fixed = self.ram[t + 2:t + 70]
            low, high = self.u8(t + 70), self.u8(t + 71)
            fe = self.ram[t + 72:t + 136]
            t += 136
            cursor = commands
            pointers = []
            for x in range(64):
                y = fe[x]
                runs = self.u8(t)
                body = t + 1
                t += 1 + 4 * runs
                if y != x and strips.get(y) == strips.get(x):
                    pointers.append(pointers[y])
                    continue
                pointers.append(cursor & 0xFFFF)
                command = bytearray()
                if x in strips:
                    command += struct.pack('<H', low | high << 8)
                    for light in range(4):
                        command += struct.pack('<H', ((strip_at[light] & 0xFFFF) + 2 * strips[x]) & 0xFFFF)
                for r in range(runs):
                    a, b, offset = self.u8(body + 4 * r), self.u8(body + 4 * r + 1), self.u16(body + 4 * r + 2)
                    command += struct.pack('<H', a | b << 8)
                    for light in range(4):
                        command += struct.pack('<H', ((areas[light] & 0xFFFF) + 2 * offset - 2 * a) & 0xFFFF)
                command += b'\0\0'
                self.put(cursor, command)
                cursor += len(command)
            header = memmap.SPRITE_CMDS + frame * FRAME_BYTES
            self.put(header, struct.pack('<64H', *pointers) + fixed + struct.pack('<H', commands >> 16)
                     + bytes(a >> 16 for a in areas))
        self.group_at = at


def run_floor(units, prog_bytes, weapon_block, weapon_at, gids, rooms=None, matrix=None, strips=None):
    m = Model()
    if rooms is not None:
        rows_at, lower = matrix
        m.load(rows_at, lower)
        m.load(ROOMS, rooms)
    m.load(PROG, prog_bytes)
    m.load(PAGES, units['pages'])
    m.op_program()
    if rooms is not None:
        m.op_sight()
    for gid in gids:
        m.load(SRC, units['blobs'][gid])
        if strips and strips.get(gid):
            m.load(SRC + len(units['blobs'][gid]), strips[gid])
        m.op_group_art(gid)
        m.load(SRC, units['tmpls'][gid])
        m.op_group_commands(gid)
    for k, chunk in enumerate(units['cols']):
        m.load(SRC, chunk)
        m.op_columns(k)
    if rooms is not None:
        m.op_matrix()
    m.put(weapon_at, weapon_block)
    return m
