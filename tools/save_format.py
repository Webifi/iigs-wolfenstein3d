"""Compact saved-world format (src/iigs/gamesave.s): reference encoder and decoder.

The file has a 178-byte header (226 for Spear), the 9,600-byte object list, a length word
and this world stream. The stream is a bit stream, least significant bit
first, in six sections. Each section describes bank $30 against the fresh
floor that StartFloor builds before a load.

  K  pushwall cells, in plane order: every cell a pushwall can reach (its
     start and up to three cells each way, stopped by a fixed wall). Per cell:
     TILEMAP 1 bit on an empty cell (same / byte) and 2 bits on a wall or
     door (same / zero / byte), MAP0 1 bit (same / byte), and at a pushwall
     start MAP1 2 bits (same / zero / byte).
  S  statics: 2 bits per slot below max(fresh, live) laststat: same / taken
     (shape $FFFF) / dropped item (cell 12, item 8, taken 1) / raw 64 bits.
  D  doors: 1 bit per door, then position, action and tics (48 bits).
  A  area tables: one bit per AREABYPLAYER area (37), then byte entries
     (index 11, value 8) over $6600-$6BFF, ended by index $7FF.
  R  ACTORAT, after the fresh actor marks are cleared and every pushwall
     cell is predicted from its TILEMAP byte: gap nibbles (15 = skip 15)
     and a value code (object 0-149, 255 zero, 254 raw word, 253 end).
  G  anything else: offset and word pairs, ended by offset $FFFF.

The reference works on whole bank images (bytes indexed by $30 offsets).
tools/check_save_stream.py checks that the native encoder writes exactly
these bytes and that the native decoder restores the world;
tools/check_save_bound.py bounds every section on the selected campaign's floors.
"""
import struct
from wolfdata import PROFILE

TILEMAP, ACTORAT, OBJLIST, STATICS = 0x0000, 0x1000, 0x3000, 0x5600
DOORPOS, DOORTILE, DOORVERT, DOORLOCK = 0x6300, 0x6380, 0x6400, 0x6480
DOORACT, DOORTICS, AREACONNECT, AREABYPLAYER = 0x6500, 0x6580, 0x6600, 0x6B80
VARS, MAP0, MAP1 = 0x6C00, 0x7000, 0x8000
OBJSIZE, MAXACTORS, MAXSTATS = 64, 150, 400
OBJEND = OBJLIST + OBJSIZE * MAXACTORS
STATEND = STATICS + 8 * MAXSTATS
PUSHABLE = 98
LASTSTAT = 10 + (112 if PROFILE.spear else 64)
HEADER, OBJBYTES = LASTSTAT + 72 + 32, 9600
WORLD = HEADER + OBJBYTES + 2          # stream offset in the file
DR_CLOSED = 1
CODE_END, CODE_RAW, CODE_ZERO = 253, 254, 255


class BitW:
    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, bits):
        for i in range(bits):
            if (value >> i) & 1:
                self.acc |= 1 << self.n
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                self.acc = 0
                self.n = 0

    def bits(self):
        return len(self.out) * 8 + self.n

    def done(self):
        if self.n:
            self.out.append(self.acc)
            self.acc = 0
            self.n = 0
        return bytes(self.out)


class BitR:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def get(self, bits):
        value = 0
        for i in range(bits):
            byte = self.data[self.pos >> 3]
            if (byte >> (self.pos & 7)) & 1:
                value |= 1 << i
            self.pos += 1
        return value


def w16(bank, offset):
    return bank[offset] | bank[offset + 1] << 8


def put16(bank, offset, value):
    bank[offset] = value & 255
    bank[offset + 1] = value >> 8 & 255


def plane_of(cell):
    return (cell & 63) * 64 + (cell >> 6)


def kplanes(raw):
    """Planes (y*64+x) a pushwall can ever write, in order, and the starts.

    A fixed wall (a wall tile that is not itself a pushwall start) stops the
    walk; doors, floor and other pushwall starts do not."""
    raw0, raw1 = raw[:4096], raw[4096:]

    def barrier(x, y):
        if not (0 <= x < 64 and 0 <= y < 64):
            return True
        p = y * 64 + x
        if raw1[p] == PUSHABLE:
            return False
        v = raw0[p]
        return v < 106 and not 90 <= v < 102

    planes, starts = set(), set()
    for p in range(4096):
        if raw1[p] != PUSHABLE:
            continue
        y, x = divmod(p, 64)
        planes.add(p)
        starts.add(p)
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            for j in (1, 2, 3):
                xx, yy = x + dx * j, y + dy * j
                if barrier(xx, yy):
                    break
                planes.add(yy * 64 + xx)
    return sorted(planes), starts


def kcells(raw):
    """The same cells as column-major cell indices (x*64+y)."""
    planes, starts = kplanes(raw)
    return sorted(plane_of(p) for p in planes), {plane_of(p) for p in starts}


def shape_of(logic, item, statinfo=0xE410):
    """The first STATINFO row with this item, as PlaceItemType searches it."""
    from wolf_source import statics
    for i in range(len(statics()) if PROFILE.spear else 49):
        shape, kind = struct.unpack_from('<2H', logic, statinfo + 4 * i)
        if kind == item:
            return shape
    return None


def value_code(v):
    if v == 0:
        return CODE_ZERO, None
    if OBJLIST <= v < OBJEND and (v - OBJLIST) % OBJSIZE == 0:
        return (v - OBJLIST) // OBJSIZE, None
    return CODE_RAW, v


def act_predict(bank_t, cell, fresh_act):
    """ACTORAT for a cell whose TILEMAP byte the K section changed."""
    t = bank_t
    if t == 0:
        return 0
    if t < 0x80:
        return t
    return fresh_act


def cleared(v):
    return 0 if OBJLIST <= v < OBJEND else v


def encode(fresh, live, raw, logic, laststat_live, doornum):
    """World stream for bank image live against bank image fresh."""
    bw = BitW()
    sizes = {}
    raw1 = raw[4096:]
    planes, starts = kplanes(raw)
    kset = set(planes)
    tchanged = set()
    # K
    mark = bw.bits()
    for p in planes:
        c = plane_of(p)
        tf, tl = fresh[TILEMAP + c], live[TILEMAP + c]
        if tf == 0:
            # an empty cell can only gain a wall: same, or a byte
            if tl == 0:
                bw.put(0, 1)
            else:
                bw.put(1, 1)
                bw.put(tl, 8)
                tchanged.add(c)
        elif tl == tf:
            bw.put(0, 2)
        elif tl == 0:
            bw.put(1, 2)
            tchanged.add(c)
        else:
            bw.put(2, 2)
            bw.put(tl, 8)
            tchanged.add(c)
        mf, ml = fresh[MAP0 + p], live[MAP0 + p]
        if ml == mf:
            bw.put(0, 1)
        else:
            bw.put(1, 1)
            bw.put(ml, 8)
        if raw1[p] == PUSHABLE:
            qf, ql = fresh[MAP1 + p], live[MAP1 + p]
            if ql == qf:
                bw.put(0, 2)
            elif ql == 0:
                bw.put(1, 2)
            else:
                bw.put(2, 2)
                bw.put(ql, 8)
    sizes['K'] = bw.bits() - mark
    # S
    mark = bw.bits()
    nfresh = (w16(fresh, VARS + 0x58) - STATICS) // 8
    nlive = (laststat_live - STATICS) // 8
    count = max(nfresh, nlive)
    for i in range(count):
        o = STATICS + 8 * i
        f = struct.unpack_from('<4H', fresh, o)
        lv = struct.unpack_from('<4H', live, o)
        if lv == f:
            bw.put(0, 2)
        elif f[1] != 0xFFFF and lv == (f[0], 0xFFFF, f[2], f[3]):
            bw.put(1, 2)
        elif (lv[2] == 2 and lv[0] < 4096 and lv[3] < 256 and shape_of(logic, lv[3]) is not None
              and lv[1] in (0xFFFF, shape_of(logic, lv[3]))):
            bw.put(2, 2)
            bw.put(lv[0], 12)
            bw.put(lv[3], 8)
            bw.put(1 if lv[1] == 0xFFFF else 0, 1)
        else:
            bw.put(3, 2)
            for word in lv:
                bw.put(word, 16)
    sizes['S'] = bw.bits() - mark
    # D
    mark = bw.bits()
    for i in range(doornum):
        f = (w16(fresh, DOORPOS + 2 * i), w16(fresh, DOORACT + 2 * i), w16(fresh, DOORTICS + 2 * i))
        lv = (w16(live, DOORPOS + 2 * i), w16(live, DOORACT + 2 * i), w16(live, DOORTICS + 2 * i))
        if lv == f:
            bw.put(0, 1)
        else:
            bw.put(1, 1)
            for word in lv:
                bw.put(word, 16)
    sizes['D'] = bw.bits() - mark
    # A
    mark = bw.bits()
    expect = bytearray(fresh[AREACONNECT:VARS])
    for i in range(37):
        bit = live[AREABYPLAYER + i] & 1
        bw.put(bit, 1)
        expect[AREABYPLAYER - AREACONNECT + i] = bit
    for i in range(VARS - AREACONNECT):
        if live[AREACONNECT + i] != expect[i]:
            bw.put(i, 11)
            bw.put(live[AREACONNECT + i], 8)
    bw.put(0x7FF, 11)
    sizes['A'] = bw.bits() - mark
    # R
    mark = bw.bits()
    prev = -1
    entries = 0
    for c in range(4096):
        fa = cleared(w16(fresh, ACTORAT + 2 * c))
        if c in tchanged:
            fa = act_predict(live[TILEMAP + c], c, fa)
        la = w16(live, ACTORAT + 2 * c)
        if la == fa:
            continue
        gap = c - prev - 1
        while gap >= 15:
            bw.put(15, 4)
            gap -= 15
        bw.put(gap, 4)
        code, extra = value_code(la)
        bw.put(code, 8)
        if extra is not None:
            bw.put(extra, 16)
        prev = c
        entries += 1
    bw.put(0, 4)
    bw.put(CODE_END, 8)
    sizes['R'] = bw.bits() - mark
    sizes['R_entries'] = entries
    # G, in the order the native walks emit it
    mark = bw.bits()
    generic = []
    last = None

    def word(o):
        nonlocal last
        o &= ~1
        if o != last:
            last = o
            generic.append(o)

    for c in range(4096):
        if fresh[TILEMAP + c] != live[TILEMAP + c] and plane_of(c) not in kset:
            word(TILEMAP + c)
    for p in range(4096):
        if fresh[MAP0 + p] != live[MAP0 + p] and p not in kset:
            word(MAP0 + p)
    for p in range(4096):
        if fresh[MAP1 + p] != live[MAP1 + p] and not (p in kset and raw1[p] == PUSHABLE):
            word(MAP1 + p)
    for o in range(STATICS + 8 * count, DOORPOS, 2):
        if fresh[o:o + 2] != live[o:o + 2]:
            generic.append(o)
    for i in range(64):
        tables = ((DOORPOS, DOORACT, DOORTICS) if i >= doornum else ()) + (DOORTILE, DOORVERT, DOORLOCK)
        for table in tables:
            o = table + 2 * i
            if fresh[o:o + 2] != live[o:o + 2]:
                generic.append(o)
    for o in generic:
        bw.put(o, 16)
        bw.put(w16(live, o), 16)
    bw.put(0xFFFF, 16)
    sizes['G'] = bw.bits() - mark
    sizes['G_entries'] = len(generic)
    return bw.done(), sizes


def decode(fresh, raw, data, logic, laststat_live, doornum):
    """Bank image after StartFloor's fresh floor and this stream."""
    bank = bytearray(fresh)
    br = BitR(data)
    raw1 = raw[4096:]
    planes, starts = kplanes(raw)
    tchanged = set()
    for p in planes:
        c = plane_of(p)
        if bank[TILEMAP + c] == 0:
            code = 2 if br.get(1) else 0
        else:
            code = br.get(2)
        if code == 1:
            bank[TILEMAP + c] = 0
            tchanged.add(c)
        elif code == 2:
            bank[TILEMAP + c] = br.get(8)
            tchanged.add(c)
        elif code == 3:
            raise ValueError('bad tile code')
        if br.get(1):
            bank[MAP0 + p] = br.get(8)
        if raw1[p] == PUSHABLE:
            code = br.get(2)
            if code == 1:
                bank[MAP1 + p] = 0
            elif code == 2:
                bank[MAP1 + p] = br.get(8)
            elif code == 3:
                raise ValueError('bad info code')
    nfresh = (w16(fresh, VARS + 0x58) - STATICS) // 8
    nlive = (laststat_live - STATICS) // 8
    for i in range(max(nfresh, nlive)):
        o = STATICS + 8 * i
        code = br.get(2)
        if code == 1:
            put16(bank, o + 2, 0xFFFF)
        elif code == 2:
            cell, item, taken = br.get(12), br.get(8), br.get(1)
            shape = 0xFFFF if taken else shape_of(logic, item)
            struct.pack_into('<4H', bank, o, cell, shape, 2, item)
        elif code == 3:
            struct.pack_into('<4H', bank, o, *(br.get(16) for _ in range(4)))
    for i in range(doornum):
        if br.get(1):
            put16(bank, DOORPOS + 2 * i, br.get(16))
            put16(bank, DOORACT + 2 * i, br.get(16))
            put16(bank, DOORTICS + 2 * i, br.get(16))
    for i in range(37):
        bank[AREABYPLAYER + i] = br.get(1)
    while True:
        index = br.get(11)
        if index == 0x7FF:
            break
        bank[AREACONNECT + index] = br.get(8)
    for c in range(4096):
        o = ACTORAT + 2 * c
        put16(bank, o, cleared(w16(bank, o)))
    for c in tchanged:
        o = ACTORAT + 2 * c
        put16(bank, o, act_predict(bank[TILEMAP + c], c, w16(bank, o)))
    c = 0
    while True:
        gap = br.get(4)
        c += gap
        if gap == 15:
            continue
        code = br.get(8)
        if code == CODE_END:
            break
        if code == CODE_ZERO:
            v = 0
        elif code == CODE_RAW:
            v = br.get(16)
        elif code < MAXACTORS:
            v = OBJLIST + OBJSIZE * code
        else:
            raise ValueError('bad actor code %d' % code)
        put16(bank, ACTORAT + 2 * c, v)
        c += 1
    while True:
        o = br.get(16)
        if o == 0xFFFF:
            break
        put16(bank, o, br.get(16))
    return bank, (br.pos + 7) // 8


def regions():
    """Bank $30 ranges the file restores, other than the header words."""
    return [(TILEMAP, OBJLIST), (STATICS, VARS), (MAP0, MAP1 + 4096)]
