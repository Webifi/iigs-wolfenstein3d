"""Worst-case saved-game size on every floor (tools/save_format.py, src/iigs/gamesave.s).

emu816 runs the real LogicNewGame, LogicSetupLevel and gsCapture of build/wolf.elf on
every floor at each difficulty. The tool checks the fresh floor against the encoder's
fresh models (static records from the info plane, closed doors, zero area tables, the
capture lists within their caps), then bounds each section of the world stream with
every pushwall moved, every static taken, every dropper killed and every door changed.
It fails when a file could pass GS_BLOCKS blocks.

The writers each bound rests on (src/iigs):
  TILEMAP  StoreLogicTile only (lact.s:64). PushWall claims one cell and marks its
           start (lact.s:696-714); MovePWalls vacates a cell and claims the next
           (lact.s:761-823); the elevator switch (lagent.s:813) ends the floor in the
           same tic. A changed nonzero byte is a resting pushwall (one per pushwall)
           or the moving one's second cell: at most P+1 bytes, all in K.
  MAP0     MovePWalls only (lact.s:779), once per block crossed and at most three
           crossings (it stops when pwallstate >= 257). A cell is vacated only after
           the wall claimed the next one.
  MAP1     PushWall only (lact.s:726), to zero: no byte.
  STATICS  a pickup sets shape $FFFF (lagent.s:1219); PlaceItemType writes (cell,
           STATINFO shape, 2, item) (lact.s:877-883), once per dropper's death
           (lact.s:2396-2431, lregistered.s:257).
  doors    position, action and tics only (lact.s:134-515).
  areas    setPair on the two side areas of a door (lact.s:575-600). A side cell
           changes area only when a pushwall vacates it, at most once per pushwall,
           so a door touches at most 1 + changes pairs. ConnectAreas writes 0 or 1
           to areas 0-36 (lact.s:608-655).
  ACTORAT  an object marks its O_CELL (lplay.s:312-395); KillActor moves O_CELL and
           leaves the old mark (lact.s:2381-2443): two marks per killable object,
           one per other object. Doors (lact.s:329-335, 452-459). A pushwall cell
           follows its tile but for the moving wall's second cell. Needles and
           rockets (flags 128, lprojectile.s:195-210) mark any open cell: on those
           floors every cell that is or can become open counts.

Usage (cwd = the build's root): python3 tools/check_save_bound.py [--difficulties 0 1 2 3]
"""
import argparse
import math
import struct
import sys
from pathlib import Path

import memmap
import save_format as F
from wolfdata import PROFILE
from check_sight_cast import image
from elf import read

ROOT = Path(__file__).resolve().parents[1]
LB = memmap.LOGIC_BASE
SENTINEL = memmap.REGISTERED_LOGIC_SPARE + 0xff0
GS_BLOCKS = memmap.SAVE_BLOCKS
NONMARK_THROWERS = {22, 25, 26} if PROFILE.spear else {8, 18, 19}
DROP_CLASSES_FIXED = {3, 5}            # guard and SS drop in KillActor itself
DOG = 6
MECHA = 10                             # A_HitlerMorph spawns Hitler (lboss.s:210)
FL_SHOOTABLE, FL_NEVERMARK = 1, 4


class Rig:
    def __init__(self):
        elf = ROOT / 'build/wolf.elf'
        self.e, self.s = image(elf)
        for segment in read(elf)[0]:
            self.e.load(segment['address'], segment['data'])
        self.e.wr8(self.s['Progress2'], 0x6b)
        self.e.wr8(self.s['Progress3'], 0x6b)

    def call(self, name):
        e = self.e
        e.d, e.db, e.mf, e.xf, e.s = 0x1100, LB >> 16, 0, 0, 0x1fff
        address = self.s[name]
        e.call(address >> 16, address & 0xffff, long_return=True, sentinel=SENTINEL, limit=40_000_000)

    def floor(self, floor, difficulty):
        folder = ROOT / 'build/levels' / str(floor)
        self.e.load(LB, (folder / 'logic.bin').read_bytes())
        if (folder / 'source-planes.bin').exists():         # registered: planes at $E1:A000
            self.e.load(memmap.RAW_PLANES, (folder / 'source-planes.bin').read_bytes())
        e = self.e
        e.d, e.db, e.mf, e.xf, e.s = 0x1100, LB >> 16, 0, 0, 0x1fff
        e.a, e.x = difficulty, floor
        address = self.s['LogicNewGame']
        e.call(address >> 16, address & 0xffff, long_return=True, sentinel=SENTINEL, limit=40_000_000)
        self.call('LogicSetupLevel')
        raw = self.s['RAW0_ADDRESS']                        # shareware: inside the logic image
        return bytearray(e.m[LB:LB + 0x10000]), bytes(e.m[raw:raw + 8192])


def paths(raw):
    """Per pushwall start: its four walks, cells S, S+1.. up to a fixed wall."""
    raw0, raw1 = raw[:4096], raw[4096:]

    def barrier(x, y):
        if not (0 <= x < 64 and 0 <= y < 64):
            return True
        p = y * 64 + x
        if raw1[p] == F.PUSHABLE:
            return False
        v = raw0[p]
        return v < 106 and not 90 <= v < 102

    out = []
    for p in range(4096):
        if raw1[p] != F.PUSHABLE:
            continue
        y, x = divmod(p, 64)
        walks = []
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            walk = [x * 64 + y]
            for j in (1, 2, 3):
                xx, yy = x + dx * j, y + dy * j
                if barrier(xx, yy):
                    break
                walk.append(xx * 64 + yy)
            walks.append(walk)
        out.append((x * 64 + y, walks))
    return out


def fresh_statics(raw, bank):
    """The records SpawnStatic makes, in info-plane order (gsNextStatic)."""
    from sprite_simplify import mirror_shape
    from wolf_source import sprite_ids
    mirrored, alias = mirror_shape(), len(sprite_ids())
    raw1 = raw[4096:]
    recs = []
    for p in range(4096):
        v = raw1[p]
        if 23 <= v < 75:
            shape, kind = struct.unpack_from('<2H', bank, 0xE410 + 4 * (v - 23))
            y, x = divmod(p, 64)
            if shape == mirrored and (x ^ y) & 1:
                shape = alias
            bonus = kind not in (0, 1)
            recs.append((x << 6 | y, shape, 2 if bonus else 0, kind if bonus else 0))
    return recs


def floor_bound(floor, bank, raw, rig):
    s = rig.s
    raw0 = raw[:4096]
    cells, starts = F.kcells(raw)
    kset = set(cells)
    P = len(starts)
    vacatable, vac = set(), {}
    for start, ws in paths(raw):
        for walk in ws:
            for j in range(len(walk) - 1):        # S+j needs S+j+1 claimed
                vacatable.add(walk[j])
                vac.setdefault(walk[j], set()).add(start)
    nfresh = (F.w16(bank, s['V_laststat']) - F.STATICS) // 8
    doornum = F.w16(bank, s['V_doornum'])
    # the encoder's fresh models equal the native fresh floor
    model = fresh_statics(raw, bank)
    assert len(model) == nfresh, (floor, len(model), nfresh)
    for i, rec in enumerate(model):
        assert struct.unpack_from('<4H', bank, F.STATICS + 8 * i) == rec, (floor, i)
    assert not any(bank[F.STATICS + 8 * nfresh:F.DOORPOS])
    for i in range(64):
        f = (F.w16(bank, F.DOORPOS + 2 * i), F.w16(bank, F.DOORACT + 2 * i), F.w16(bank, F.DOORTICS + 2 * i))
        assert f == ((0, F.DR_CLOSED, 0) if i < doornum else (0, 0, 0)), (floor, i, f)
    assert not any(bank[F.AREACONNECT:F.AREABYPLAYER])
    assert sum(1 for b in bank[F.AREABYPLAYER:F.VARS] if b) == 1
    assert max(bank[F.AREABYPLAYER:F.AREABYPLAYER + 37]) == 1
    assert rig.e.rd16(s['gsBaseOk']) == 1, (floor, 'capture lists overflow')
    # objects at spawn
    objs = []
    ob = F.w16(bank, F.OBJLIST + s['O_NEXT'])
    while ob:
        objs.append((F.w16(bank, ob + s['O_CLASS']), F.w16(bank, ob + s['O_FLAGS'])))
        ob = F.w16(bank, ob + s['O_NEXT'])
    classes = {c for c, _ in objs}
    droppers = marks = 0
    for cls, flags in objs:
        if 'CLASS_DATA' in s:               # registered: ClassKill drops C_DROP (lregistered.s)
            drop = struct.unpack_from('<h', bank, s['CLASS_DATA'] + 32 * cls + s['C_DROP'])[0]
        else:                               # shareware: every other class drops the key (lact.s killBoss)
            drop = 5
        killable = bool(flags & FL_SHOOTABLE)
        if killable and cls != DOG and (cls in DROP_CLASSES_FIXED or drop >= 0):
            droppers += 1
        if not flags & FL_NEVERMARK:
            marks += 2 if killable else 1
    runtime = 1 if MECHA in classes else 0
    marks = min(marks + 2 * runtime, 2 * (F.MAXACTORS - 1))
    projectile = bool(classes & NONMARK_THROWERS)
    # doors: cells, side cells and the area pairs they can touch
    doorcells = []
    for p in range(4096):
        if 90 <= raw0[p] < 102:
            y, x = divmod(p, 64)
            doorcells.append((x, y, raw0[p]))
    assert len(doorcells) == doornum
    doors_in_k = sum(1 for x, y, _ in doorcells if x * 64 + y in kset)
    area_entries = 0
    for x, y, v in doorcells:
        vertical = (v - 90) % 2 == 0
        sides = ((x + 1, y), (x - 1, y)) if vertical else ((x, y - 1), (x, y + 1))
        changes = 0
        areas = [bank[F.MAP0 + sy * 64 + sx] - 107 for sx, sy in sides]
        assert all(0 <= a < 37 for a in areas) or (PROFILE.spear and any(0 <= a < 37 for a in areas)), (floor, sides, areas)
        assert 0 <= bank[F.MAP0 + y * 64 + x] - 107 < 37, (floor, x, y, 'door area')
        for sx, sy in sides:
            changes += len(vac.get(sx * 64 + sy, ()))
        area_entries += 2 * (1 + changes)
    area_entries = min(area_entries, 37 * 37)
    # cells that are or can become open (projectiles); every spawn mark is one
    open_set = set(kset)
    for c in range(4096):
        x, y = c >> 6, c & 63
        if bank[F.TILEMAP + c] == 0 or 90 <= raw0[y * 64 + x] < 102:
            open_set.add(c)
    for c in range(4096):
        v = F.w16(bank, F.ACTORAT + 2 * c)
        if F.OBJLIST <= v < F.OBJEND:
            assert c in open_set, (floor, c)
    # the sections, in bits
    kzero = sum(1 for c in cells if bank[F.TILEMAP + c] == 0)
    k_bits = kzero + 2 * (len(cells) - kzero) + 8 * (P + 1) + len(cells) \
        + 8 * min(3 * P, len(vacatable)) + 2 * P
    count = min(F.MAXSTATS, nfresh + droppers)
    s_bits = 2 * count + 21 * min(droppers, count)
    d_bits = 49 * doornum
    a_bits = 37 + 19 * area_entries + 11
    entries = len(open_set) if projectile else min(marks + doornum + 1 + doors_in_k, len(open_set))
    raw_codes = 1 + doors_in_k
    escapes = (4096 - entries) // 15
    r_bits = 4 * (entries + escapes) + 8 * entries + 16 * raw_codes + 12
    g_bits = 16
    bits = dict(K=k_bits, S=s_bits, D=d_bits, A=a_bits, R=r_bits, G=g_bits)
    world = (sum(bits.values()) + 7) // 8
    total = F.WORLD + world
    return dict(floor=floor + 1, pushwalls=P, kcells=len(cells), statics=nfresh, droppers=droppers,
                doors=doornum, marks=marks, projectile=projectile, actor_entries=entries,
                bytes={k: (v + 7) // 8 for k, v in bits.items()}, world=world, file=total,
                blocks=math.ceil(total / 512))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--difficulties', type=int, nargs='+', default=[0, 1, 2, 3])
    ap.add_argument('--floors', type=int, nargs='*', default=list(range(PROFILE.floors)))
    args = ap.parse_args()
    rig = Rig()
    worst = None
    for difficulty in args.difficulties:
        for floor in args.floors:
            bank, raw = rig.floor(floor, difficulty)
            row = floor_bound(floor, bank, raw, rig)
            row['difficulty'] = difficulty
            b = row['bytes']
            print('d%d floor %2d P %3d K %4d statics %3d droppers %3d doors %2d marks %3d proj %d R %4d | '
                  'K %4d S %3d D %3d A %3d R %4d | world %4d file %5d blocks %2d' % (
                      difficulty, row['floor'], row['pushwalls'], row['kcells'], row['statics'],
                      row['droppers'], row['doors'], row['marks'], row['projectile'], row['actor_entries'],
                      b['K'], b['S'], b['D'], b['A'], b['R'], row['world'], row['file'], row['blocks']),
                  flush=True)
            if worst is None or row['file'] > worst['file']:
                worst = row
    print('largest: floor %d difficulty %d, world %d bytes, file %d bytes (%d blocks); slot %d blocks, '
          'margin %d bytes' % (worst['floor'], worst['difficulty'], worst['world'], worst['file'],
                               worst['blocks'], GS_BLOCKS, GS_BLOCKS * 512 - worst['file']))
    if worst['file'] > GS_BLOCKS * 512:
        sys.exit('a saved game can pass GS_BLOCKS')


if __name__ == '__main__':
    main()
