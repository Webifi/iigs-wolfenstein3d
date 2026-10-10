"""The native saved-world stream (src/iigs/gamesave.s) against tools/save_format.py.

emu816 sets each floor up with the real code, changes the world with the game's own
routines (PushWall, MovePWalls, KillActor) and with direct writes, then runs
gsWorldOut: its bytes must equal save_format.encode. The floor is set up again and
gsWorldIn decodes those bytes: every saved byte of bank $30 must equal the changed
world. Modes: fresh (nothing changed), random, wild (random bytes anywhere too, for
the G section), worst (every pushwall pushed, every actor killed, every static taken,
every door changed).

Usage (cwd = the build's root): python3 tools/check_save_stream.py [--floors ...] [--modes ...]
"""
import argparse
import random
import struct
import time

import save_format as F
import memmap
from check_save_bound import Rig, LB

SENTINEL2 = memmap.CODE_TAIL
SENTINEL_D = memmap.REGISTERED_LOGIC_SPARE + 0xff0
DP = 0x1100                 # LOGICDP and UI_DP


class StreamRig(Rig):
    def near(self, name, db=None, x=0):
        e = self.e
        address = self.s[name]
        bank = address >> 16
        e.d, e.mf, e.xf, e.s = DP, 0, 0, 0x1fff
        e.db = (LB >> 16) if db is None else db
        e.a, e.x, e.y = 0, x, 0
        before = e.cycles
        e.call(bank, address & 0xffff, long_return=False,
               sentinel=SENTINEL2 if bank == 2 else SENTINEL_D, limit=60_000_000)
        return e.cycles - before

    def w(self, offset, value=None):
        if value is None:
            return self.e.rd16(LB + offset)
        self.e.wr16(LB + offset, value & 0xffff)

    def bank30(self):
        return bytearray(self.e.m[LB:LB + 0x10000])


def push_walls(rig, rng, raw, fraction):
    s = rig.s
    starts = [p for p in range(4096) if raw[4096 + p] == F.PUSHABLE]
    rng.shuffle(starts)
    for n, p in enumerate(starts):
        if rng.random() > fraction:
            continue
        y, x = divmod(p, 64)
        rig.e.wr16(DP + s['L_X'], x)
        rig.e.wr16(DP + s['L_Y'], y)
        rig.e.wr16(DP + s['L_ARG'], rng.randrange(4))
        rig.w(s['V_pwallstate'], 0)
        rig.near('PushWall')
        steps = 0
        while rig.w(s['V_pwallstate']):
            rig.w(s['OBJLIST'] + s['O_AREA'], rng.randrange(37))
            rig.w(s['V_tics'], rng.choice([1, 2, 3, 4, 8]))
            rig.near('MovePWalls')
            steps += 1
            if n == len(starts) - 1 and steps > rng.randrange(1, 60):
                break                   # the last one stays in motion


def kill_all(rig, rng, share):
    s = rig.s
    obs = []
    ob = rig.w(s['OBJLIST'] + s['O_NEXT'])
    while ob:
        obs.append(ob)
        ob = rig.w(ob + s['O_NEXT'])
    for ob in obs:
        if rng.random() > share or not rig.w(ob + s['O_FLAGS']) & 1:
            continue
        if rng.random() < .5:           # the corpse lands off its marked cell
            rig.e.wr16(LB + ob + s['O_X'] + 2, (rig.w(ob + s['O_X'] + 2) + rng.choice([-1, 1])) & 63)
        rig.e.wr16(DP + s['L_OB'], ob)
        rig.near('KillActor', x=ob)


def take_statics(rig, rng, share):
    s = rig.s
    for i in range((rig.w(s['V_laststat']) - F.STATICS) // 8):
        o = F.STATICS + 8 * i
        if rig.w(o + 4) & 2 and rig.w(o + 2) != 0xffff and rng.random() < share:
            rig.w(o + 2, 0xffff)


def random_world(rig, rng, wild):
    s = rig.s
    for i in range(rig.w(s['V_doornum'])):
        if rng.random() < .6:
            rig.w(F.DOORPOS + 2 * i, rng.choice([0, 0xffff, rng.randrange(65536)]))
            rig.w(F.DOORACT + 2 * i, rng.randrange(4))
            rig.w(F.DOORTICS + 2 * i, rng.randrange(400))
            if rng.random() < .5:
                rig.w(F.ACTORAT + 2 * rig.w(F.DOORTILE + 2 * i), 0)
    for i in range(37):
        rig.e.wr8(LB + F.AREABYPLAYER + i, rng.randrange(2) if rng.random() < .97 else rng.randrange(256))
    for _ in range(rng.randrange(0, 60)):
        u, v = rng.randrange(37), rng.randrange(37)
        val = rng.randrange(1, 5)
        rig.e.wr8(LB + F.AREACONNECT + u * 37 + v, val)
        rig.e.wr8(LB + F.AREACONNECT + v * 37 + u, val)
    for _ in range(rng.randrange(0, 400)):
        rig.w(F.ACTORAT + 2 * rng.randrange(4096),
              rng.choice([0, F.OBJLIST + 64 * rng.randrange(150), rng.randrange(65536)]))
    if wild:
        for _ in range(rng.randrange(1, 25)):
            lo, hi = rng.choice(F.regions())
            rig.e.wr8(LB + rng.randrange(lo, hi), rng.randrange(256))


def change(rig, rng, raw, mode):
    s = rig.s
    if mode == 'worst':
        push_walls(rig, rng, raw, 1.0)
        kill_all(rig, rng, 1.0)
        take_statics(rig, rng, 1.0)
        for i in range(rig.w(s['V_doornum'])):
            rig.w(F.DOORPOS + 2 * i, 0x8000 + i)
            rig.w(F.DOORACT + 2 * i, 0)
            rig.w(F.DOORTICS + 2 * i, 299)
            rig.w(F.ACTORAT + 2 * rig.w(F.DOORTILE + 2 * i), 0)
        take_statics(rig, rng, 1.0)                 # the drops too
    elif mode in ('random', 'wild'):
        push_walls(rig, rng, raw, rng.random())
        kill_all(rig, rng, rng.random())
        take_statics(rig, rng, rng.random())
        random_world(rig, rng, mode == 'wild')


def compare(a, b, what):
    for lo, hi in F.regions():
        if lo == F.OBJLIST:
            continue                    # the object list travels raw
        if a[lo:hi] != b[lo:hi]:
            bad = next(i for i in range(lo, hi) if a[i] != b[i])
            raise AssertionError('%s: offset %04x is %02x, not %02x' % (what, bad, a[bad], b[bad]))


def run_case(rig, floor, difficulty, rng, mode):
    s = rig.s
    fresh, raw = rig.floor(floor, difficulty)
    change(rig, rng, raw, mode)
    live = rig.bank30()
    laststat, doornum = F.w16(live, s['V_laststat']), F.w16(live, s['V_doornum'])
    enc = rig.near('gsWorldOut', db=2)
    over = rig.e.rd16(s['gsBitOver'])
    data = bytes(rig.e.m[s['GS_WORLD']:s['GS_WORLD'] + rig.e.rd16(s['gsWorldLen'])])
    logic = bytes(live)                 # STATINFO and the class table are in the logic image
    ref, sizes = F.encode(fresh, live, raw, logic, laststat, doornum)
    if over:
        assert len(ref) > F.HEADER and len(ref) > memmap.SAVE_BLOCKS * 512 - F.WORLD, (floor, mode, len(ref))
        return dict(floor=floor + 1, mode=mode, over=True)
    assert data == ref, (floor + 1, mode, len(data), len(ref), sizes)
    again, _ = rig.floor(floor, difficulty)
    compare(again, fresh, 'floor %d set up again' % (floor + 1))
    rig.e.m[s['GS_WORLD']:s['GS_WORLD'] + len(data)] = data
    rig.e.wr16(s['gsWorldLen'], len(data))
    rig.e.wr16(s['gsHeader'] + F.LASTSTAT, laststat)        # GS_LASTSTAT
    dec = rig.near('gsWorldIn', db=2)
    assert not rig.e.rd16(s['gsBitOver']), (floor + 1, mode, 'the decoder flagged an error')
    compare(rig.bank30(), live, 'floor %d %s decode' % (floor + 1, mode))
    return dict(floor=floor + 1, mode=mode, bytes=len(data), sizes=sizes, enc=enc, dec=dec)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--floors', type=int, nargs='*', default=list(range(60)))
    ap.add_argument('--modes', nargs='+', default=['fresh', 'random', 'wild', 'worst'])
    ap.add_argument('--difficulty', type=int, default=3)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    rig = StreamRig()
    rng = random.Random(args.seed)
    start, n = time.time(), 0
    for floor in args.floors:
        for mode in args.modes:
            row = run_case(rig, floor, args.difficulty, rng, mode)
            n += 1
            if 'over' in row:
                print(row, flush=True)
                continue
            print('%2d %-6s %5d bytes  encode %8d decode %8d cycles  %s' % (
                row['floor'], row['mode'], row['bytes'], row['enc'], row['dec'],
                {k: (v + 7) // 8 for k, v in row['sizes'].items() if k in 'KSDARG'}), flush=True)
    print('passed', n, 'cases in %.0f s' % (time.time() - start))


if __name__ == '__main__':
    main()
