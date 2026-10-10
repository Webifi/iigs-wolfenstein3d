"""Execute registered actor routines, checking DOS maps and arithmetic.

This is a 65816 routine test, not an emulator gameplay or performance result.
The loading progress/snapshot callbacks are skipped while testing setup.
Run with WOLF_PROFILE=wolf3d and WOLF_DOS_DATA pointing at extracted WL6 files.
"""
import memmap
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import struct

from check_sight_cast import image
from elf import read
from map_semantics import MapSemantics
from native_map_format import native_plane_bytes
from wolfdata import ROOT, PROFILE, maps
from wolfsim import build_tables, fixed_by_frac

LB, DP = memmap.LOGIC_BASE, 0x1100
KINDS = {'guard': 3, 'officer': 4, 'ss': 5, 'dog': 6, 'hans': 7,
         'schabbs': 8, 'fake-hitler': 9, 'mecha-hitler': 10, 'mutant': 11,
         'ghost': 15, 'gretel': 17, 'giftmacher': 18, 'fatface': 19}
KINDS.update({name: 15 for name in ('blinky', 'clyde', 'pinky', 'inky')})


class Rig:
    def __init__(self, elf):
        self.e, self.s = image(elf)
        # The legacy sample's math load includes the space now used by new
        # cold code. Restore linked code after reading shared test data.
        for segment in read(elf)[0]:
            self.e.load(segment['address'], segment['data'])
        self.e.load(LB, (elf.parent / 'logic-tables.bin').read_bytes())

    def call(self, name, a=0, x=0, y=0, long=False):
        e, s = self.e, self.s
        e.d, e.db, e.mf, e.xf, e.s = DP, LB >> 16, 0, 0, 0x1fff
        e.a, e.x, e.y = a, x, y
        before = e.cycles
        address = s[name]
        e.call(address >> 16, address & 65535, long_return=long,
               sentinel=(memmap.REGISTERED_LOGIC_SPARE+0xff0), limit=4_000_000)
        return e.cycles - before

    def word(self, name, value=None, base=LB):
        address = base + self.s[name]
        if value is None:
            return self.e.rd16(address)
        self.e.wr16(address, value & 65535)

    def long(self, address, value=None):
        if value is None:
            return struct.unpack_from('<I', self.e.m, address)[0]
        struct.pack_into('<I', self.e.m, address, value & 0xffffffff)


def setup(rig, floors, difficulties):
    e, s = rig.e, rig.s
    semantics = MapSemantics(PROFILE.resource('map_semantics'))
    # UI progress and save-baseline capture are independently tested by the
    # disk/emulator checks. Neither affects actor construction.
    e.wr8(s['Progress2'], 0x6b)
    e.wr8(s['gsCapture'], 0x6b)
    cases = []
    for floor in floors:
        planes = maps()[floor]['planes']
        for difficulty in difficulties:
            for plane in (0, 1):
                e.load(s['RAW0_ADDRESS'] + plane * 4096,
                       native_plane_bytes(planes[plane], floor=floor, plane=plane, extended_info=True))
            rig.call('LogicNewGame', a=difficulty, x=floor, long=True)
            rig.call('LogicSetupLevel', long=True)
            expected = Counter()
            for code in planes[1]:
                row = semantics.lookup.get((1, code), {})
                if row.get('kind') == 'actor':
                    if difficulty >= row.get('parameters', {}).get('minimum_difficulty', 0):
                        expected[KINDS[row['behavior']]] += 1
                elif row.get('behavior') == 'dead_guard':
                    expected[2] += 1
            actual = Counter()
            ob = e.rd16(LB + s['OBJLIST'] + s['O_NEXT'])
            seen = set()
            while ob:
                assert ob not in seen and len(seen) < 150, (floor, difficulty, 'actor list')
                seen.add(ob)
                actual[e.rd16(LB + ob + s['O_CLASS'])] += 1
                ob = e.rd16(LB + ob + s['O_NEXT'])
            assert actual == expected, (floor, difficulty, actual, expected)
            assert rig.word('V_killtotal') == sum(n for k, n in expected.items() if k != 2)
            assert rig.word('V_doornum') == sum(90 <= v <= 101 for v in planes[0])
            cases.append(dict(floor=floor, difficulty=difficulty, actors=sum(actual.values()), classes=dict(actual)))
        print('setup floor', floor, 'passed', flush=True)
    return cases


def aim(rig, count):
    e, s = rig.e, rig.s
    rng = random.Random(4130)
    shooter = s['OBJLIST'] + s['OBJSIZE']
    player = s['OBJLIST']
    origin = 32 << 16
    rig.long(LB + shooter + s['O_X'], origin)
    rig.long(LB + shooter + s['O_Y'], origin)
    vectors = [(x, y) for x in (-65536, -1, 0, 1, 65536)
               for y in (-65536, -1, 0, 1, 65536)]
    # Test either side of every integer-degree threshold at map-scale radii.
    for degree in range(360):
        x = round(math.cos(math.radians(degree)) * 1_900_000)
        y = round(math.sin(math.radians(degree)) * 1_900_000)
        vectors.extend((x + dx, y + dy) for dx, dy in ((0, 0), (1, -1), (-1, 1)))
    vectors += [(rng.randrange(-2_000_000, 2_000_001), rng.randrange(-2_000_000, 2_000_001)) for _ in range(count)]
    cycles = []
    for x, y in vectors:
        rig.long(LB + player + s['O_X'], origin + x)
        rig.long(LB + player + s['O_Y'], origin - y)
        cycles.append(rig.call('ProjectileAim', x=shooter))
        radians = math.atan2(y, x)
        if radians < 0:
            radians += math.tau
        expected = int(radians * 360 / math.tau)
        # Exact cardinal/diagonal degrees avoid host libm's 224.999... error.
        if not x or not y or abs(x) == abs(y):
            expected = round(radians * 360 / math.tau) % 360
        assert e.a == expected, (x, y, e.a, expected)
    return dict(cases=len(vectors), nominal_cycles_max=max(cycles), nominal_cycles_mean=sum(cycles)/len(cycles))


def fraction(rig):
    e, s = rig.e, rig.s
    table = build_tables()[2]
    count = 0
    for magnitude in (0, 1, 0x1200, 0x2000, 0xffff, 0x10000, 0x24000, 0x80000):
        for angle in range(451):
            rig.long(DP + s['L_MOVE'], magnitude)
            rig.call('ProjectileFraction', y=s['SINTAB'] + angle * 4)
            got = rig.long(DP + s['L_PB'])
            expected = fixed_by_frac(magnitude, table[angle]) & 0xffffffff
            assert got == expected, (magnitude, angle, got, expected)
            count += 1
    return dict(cases=count)


def projectiles(rig):
    e, s = rig.e, rig.s
    table = build_tables()[2]
    ob = s['OBJLIST'] + s['OBJSIZE']
    origin = 16 * 65536 + 32768
    e.load(LB + s['ACTORAT'], bytes(8192))
    rig.long(LB + s['OBJLIST'] + s['O_X'], 50 << 16)
    rig.long(LB + s['OBJLIST'] + s['O_Y'], 50 << 16)
    rig.word('L_OB', ob, DP)
    checks = 0
    for speed in (0x1200, 0x2000):
        for tics in (1, 4, 8, 64):
            rig.word('V_tics', tics)
            for angle in range(360):
                rig.long(LB + ob + s['O_X'], origin)
                rig.long(LB + ob + s['O_Y'], origin)
                e.wr16(LB + ob + s['O_SPEED'], speed)
                e.wr16(LB + ob + s['O_ANGLE'], angle)
                e.wr16(LB + ob + s['O_CLASS'], 20)
                e.wr16(LB + ob + s['O_STATE'], s['s_rocket'])
                rig.call('T_Projectile')
                dx = min(65536, fixed_by_frac(speed*tics, table[angle+90]))
                dy = min(65536, -fixed_by_frac(speed*tics, table[angle]))
                expected = origin+dx, origin+dy
                got = rig.long(LB + ob + s['O_X']), rig.long(LB + ob + s['O_Y'])
                assert got == expected, (speed, tics, angle, got, expected)
                assert e.rd16(LB + ob + s['O_TILEX']) == expected[0] >> 16
                assert e.rd16(LB + ob + s['O_TILEY']) == expected[1] >> 16
                checks += 1
    # A wall catches the full bounding box; a reserved actor tile does not.
    rig.word('V_tics', 1)
    for kind in (12, 13, 20):
        for occupant in (1, 128, s['OBJLIST'], 0):
            rig.long(LB + ob + s['O_X'], origin)
            rig.long(LB + ob + s['O_Y'], origin)
            e.wr16(LB + ob + s['O_SPEED'], 0)
            e.wr16(LB + ob + s['O_ANGLE'], 0)
            e.wr16(LB + ob + s['O_CLASS'], kind)
            e.wr16(LB + ob + s['O_STATE'], s['s_rocket'])
            e.wr16(LB + ob + s['O_TICS'], 2)
            cell = LB + s['ACTORAT'] + (16*64+16)*2
            e.wr16(cell, occupant)
            rig.call('T_Projectile')
            expected = s['s_rocket'] if occupant in (0, s['OBJLIST']) else s['s_boom1'] if kind == 20 else 0
            assert e.rd16(LB + ob + s['O_STATE']) == expected, (kind, occupant)
            assert e.rd16(LB + ob + s['O_TICS']) == 2
            e.wr16(cell, 0)
            checks += 1
    return dict(cases=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=ROOT/'build/tests/registered-actors/wolf.elf')
    parser.add_argument('--floors', type=int, nargs='*', default=list(range(60)))
    parser.add_argument('--difficulties', type=int, nargs='+', default=[0, 1, 2, 3])
    parser.add_argument('--aim', type=int, default=5000)
    args = parser.parse_args()
    assert PROFILE.key == 'wolf3d'
    rig = Rig(args.elf)
    result = dict(aim=aim(rig, args.aim), fraction=fraction(rig), projectiles=projectiles(rig))
    print(json.dumps(result), flush=True)
    result['setup'] = setup(rig, args.floors, args.difficulties)
    (args.elf.parent/'actor-checks.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Registered native routine checks passed:', len(result['setup']), 'floor/difficulty combinations')


if __name__ == '__main__':
    main()
