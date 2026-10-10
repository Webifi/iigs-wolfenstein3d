"""Run the built gameplay visibility cast (refreshView) natively and compare it with the source model.

The interpreter of tools/emu816.py executes the real 65816 code of build/wolf.elf on a memory
image built as the loader builds it. Every scene (a map with doors and push walls, a view point
and an angle) must give the model's visited cells; the mean nominal cycles per refresh are
printed so a change can be timed without a MAME run. Random maps cover the door and push wall
paths; demo scenes (the model's frames of the four recorded demos) give the realistic cost.

  python3 tools/check_sight_cast.py --random 300 --demo 0 1 2 3 [--every 8] [--elf build/wolf.elf]
  python3 tools/check_sight_cast.py --partials     # all 900 tangents, nine fraction boundaries, four routines
  python3 tools/check_sight_cast.py --transform 2000   # transformGXGY against fixed_by_frac
  python3 tools/check_sight_cast.py --actors 5000       # TransformActor on random view points and actors
  python3 tools/check_sight_cast.py --stamps 0          # every refresh of demo 0, the stamp value wrapping
  python3 tools/check_sight_cast.py --axes 20           # random maps at view angles on and beside the axes
"""
import memmap
import argparse
import random
import re
import sys
from pathlib import Path

from elf import read
from emu816 import Emu
import wolfsim
from wolfsim import s16, s32, partial_by_step, TILEGLOBAL

ROOT = Path(__file__).resolve().parents[1]
D = 0x1100
LB = memmap.LOGIC_BASE


def image(elf):
    """Code and data segments, then the disk's loads in the order mkdisk applies them."""
    global LB
    e = Emu()
    segments, syms = read(elf)
    LB = syms.get("LOGICBANK", 0x28) << 16
    for s in segments:
        e.load(s['address'], s['data'])
    # Frozen ELFs carry their matching generated tables alongside them.
    # Decoders from different builds need not share the same asset format.
    build = elf.resolve().parent if (elf.resolve().parent/'assets').is_dir() else ROOT/'build'
    a = build / 'assets'
    for p, ad in ((a / 'map.bin', memmap.MAP), (a / 'mullo.bin', memmap.WORD_PRODUCTS), (a / 'mulhi.bin', (memmap.WORD_PRODUCTS+0x10000)),
                  (a / 'tables.bin', memmap.COS_TABLE), (a / 'logic.bin', LB), (a / 'view-height.bin', memmap.VIEW_HEIGHT)):
        e.load(ad, p.read_bytes())
    for line in (a / 'load-list.txt').read_text().splitlines():
        m = re.match(r'(.*)@0x([0-9a-f]+)', line)
        ad = int(m.group(2), 16)
        if ad < memmap.SFX_BASE and 'art-index' not in m.group(1):
            source = Path(m.group(1))
            source = build/source.relative_to('build') if source.parts[0] == 'build' else ROOT/source
            e.load(ad, source.read_bytes())
    return e, syms


class Rig:
    def __init__(self, elf):
        self.e, self.syms = image(elf)
        self.ft = wolfsim.build_tables()[1]
        self.rayang = [s16(self.e.rd16(LB + 0xe3d0 + 2 * i)) for i in range(30)]   # RAYANGLE, byte offsets

    def scene(self, tilemap, doorpos, pwallpos, px, py, angle, keep_stamps=False):
        e, s = self.e, self.syms
        e.m[LB:LB + 4096] = bytes(tilemap)
        for i, v in enumerate(doorpos):
            e.wr16(LB + s['DOORPOS'] + 2 * i, v)
        e.wr16(LB + s['V_pwallpos'], pwallpos)
        if not keep_stamps:
            e.m[LB + s['SPOTVIS']:LB + s['SPOTVIS'] + 4096] = bytes(4096)
            e.wr16(LB + s['V_spotstamp'], 0)
        e.wr16(LB + s['V_laststat'], s['STATICS'])
        o = LB + s['OBJLIST']
        e.wr16(o, px & 0xffff)
        e.wr16(o + 2, (px >> 16) & 0xffff)
        e.wr16(o + 4, py & 0xffff)
        e.wr16(o + 6, (py >> 16) & 0xffff)
        e.wr16(o + s['O_ANGLE'], angle)
        e.wr16(D + s['L_VISDIRTY'], 1)

    def run(self):
        e = self.e
        e.d, e.db, e.mf, e.xf, e.s = D, LB >> 16, 0, 0, 0x1fff
        c0 = e.cycles
        e.call(0x0d, self.syms['refreshView'] & 0xffff, sentinel=0xd7f00)
        return e.cycles - c0

    def cells(self):
        """The cells stamped by the last refresh: those holding the current stamp value."""
        e, s = self.e, self.syms
        stamp = e.rd16(LB + s['V_spotstamp']) & 255
        return {i for i in range(4096) if e.m[LB + s['SPOTVIS'] + i] == stamp}

    def view(self):
        e, s = self.e, self.syms
        vx = e.rd16(LB + s['V_viewx']) | (e.rd16(LB + s['V_viewx_hi']) << 16)
        vy = e.rd16(LB + s['V_viewy']) | (e.rd16(LB + s['V_viewy_hi']) << 16)
        return vx, vy, e.rd16(LB + s['V_viewangle']) * 10

    def model(self, tilemap, doorpos, pwallpos, vx, vy, mid):
        """The source's AsmRefresh rays from wolfsim.Game.cast_ray, over this view point."""
        ft = self.ft
        spot = set()
        focaltx, focalty = vx >> 16, vy >> 16
        xpd = vx & 0xffff
        xpu = (TILEGLOBAL - xpd) & 0xffff
        ypd = vy & 0xffff
        ypu = (TILEGLOBAL - ypd) & 0xffff
        for i in range(30):
            angle = self.rayang[i] // 8 + mid
            angle += 3600 if angle < 0 else -3600 if angle >= 3600 else 0
            if angle < 900:
                xts, yts, xstep, ystep, xp, yp = 1, -1, ft[899 - angle], -ft[angle], xpu, ypd
            elif angle < 1800:
                xts, yts, xstep, ystep, xp, yp = -1, -1, -ft[angle - 900], -ft[1799 - angle], xpd, ypd
            elif angle < 2700:
                xts, yts, xstep, ystep, xp, yp = -1, 1, -ft[2699 - angle], ft[angle - 1800], xpd, ypu
            else:
                xts, yts, xstep, ystep, xp, yp = 1, 1, ft[angle - 2700], ft[3599 - angle], xpu, ypu
            yint = s32(partial_by_step(ystep, xp) + vy)
            xtile = focaltx + xts
            xint = s32(partial_by_step(xstep, yp) + vx)
            ytile = focalty + yts
            label = 'vertcheck'
            while True:
                if label == 'vertcheck':
                    yi = s16(yint >> 16)
                    label = 'horizentry' if ((yi <= ytile) if yts < 0 else (yi >= ytile)) else 'vertentry'
                elif label == 'vertentry':
                    yi = s16(yint >> 16)
                    xspot = ((xtile << 6) + yi) & 0xffff
                    tile = tilemap[xspot]
                    if not tile:
                        label = 'passvert'
                    elif not tile & 0x80:
                        break
                    elif tile & 0x40:
                        part = s32((ystep * pwallpos) & 0xffffffff) >> 6
                        if (s32(yint + part) >> 16) != (yint >> 16):
                            label = 'passvert'
                        else:
                            break
                    else:
                        mid2 = s32(yint + (ystep >> 1))
                        if (mid2 >> 16) != (yint >> 16) or (mid2 & 0xffff) < doorpos[tile & 0x7f]:
                            label = 'passvert'
                        else:
                            break
                elif label == 'passvert':
                    spot.add(xspot)
                    xtile += xts
                    yint = s32(yint + ystep)
                    label = 'vertcheck'
                elif label == 'horizcheck':
                    xi = s16(xint >> 16)
                    label = 'vertentry' if ((xi <= xtile) if xts < 0 else (xi >= xtile)) else 'horizentry'
                elif label == 'horizentry':
                    xi = s16(xint >> 16)
                    yspot = ((xi << 6) + ytile) & 0xffff
                    tile = tilemap[yspot]
                    if not tile:
                        label = 'passhoriz'
                    elif not tile & 0x80:
                        break
                    elif tile & 0x40:
                        part = s32((xstep * pwallpos) & 0xffffffff) >> 6
                        if (s32(xint + part) >> 16) != (xint >> 16):
                            label = 'passhoriz'
                        else:
                            break
                    else:
                        mid2 = s32(xint + (xstep >> 1))
                        if (mid2 >> 16) != (xint >> 16) or (mid2 & 0xffff) < doorpos[tile & 0x7f]:
                            label = 'passhoriz'
                        else:
                            break
                else:
                    spot.add(yspot)
                    ytile += yts
                    xint = s32(xint + xstep)
                    label = 'horizcheck'
        return spot


def check_partials(rig):
    """The four partial products, every tangent record against step * fraction >> 16."""
    e, s = rig.e, rig.syms
    tangents = wolfsim.build_tables()[1]
    fractions = (0, 1, 255, 256, 257, 32767, 32768, 65534, 65535)
    # lsight.s keeps each fraction's two row pointers at L_XL + 0, 6, 12 and 18 (three bytes each)
    routines = (('partialXUp', 'L_XPUP', 0), ('partialXDown', 'L_XPDN', 6),
                ('partialYUp', 'L_YPUP', 12), ('partialYDown', 'L_YPDN', 18))
    cases = failures = 0
    for name, word, pointer in routines:
        for angle, step in enumerate(tangents):
            for fraction in fractions:
                e.d, e.db, e.mf, e.xf, e.s = D, LB >> 16, 0, 0, 0x1fff
                e.wr16(D + s[word], fraction)
                for k, byte in enumerate((fraction & 255, fraction >> 8)):
                    page = e.rd16(memmap.RAY_PRODUCTS_DIRECTORY + 2 * byte)
                    base = D + s['L_XL'] + pointer + 3 * k
                    e.wr8(base, 0)
                    e.wr16(base + 1, page)
                e.wr16(D + s['L_PB'], 0xa55a)
                e.wr16(D + s['L_PB'] + 2, 0xa55a)
                e.x = angle * 16
                e.call(0x0d, s[name] & 0xffff, sentinel=0xd7f00)
                got = e.rd16(D + s['L_PB']) | (e.rd16(D + s['L_PB'] + 2) << 16)
                cases += 1
                if got != step * fraction >> 16:
                    failures += 1
                    if failures < 5:
                        print('PARTIAL', name, 'angle', angle, 'fraction', fraction, 'got', got, 'want', step * fraction >> 16)
    print('partial products: %d cases, %d differ' % (cases, failures))
    return failures


def check_transform(rig, count, seed=5):
    """transformGXGY (the actor and pickup transform) on random view fractions and offsets."""
    e, s = rig.e, rig.syms
    rnd = random.Random(seed)
    gx_, gy_, nx_, ny_ = D + s['L_GX'], D + s['L_GY'], D + s['L_NX'], D + s['L_NY']
    cos, sin = LB + s['V_viewcos'], LB + s['V_viewsin']
    failures = cycles = 0

    def put(addr, value):
        e.wr16(addr, value & 0xffff)
        e.wr16(addr + 2, (value >> 16) & 0xffff)

    for _ in range(count):
        def magnitude():
            return rnd.choice([rnd.randrange(0, 64 << 16), rnd.randrange(0, 1 << 16), rnd.randrange(0, 300), rnd.randrange(0, 1 << 24)])
        gx = magnitude() * rnd.choice([1, -1])
        gy = magnitude() * rnd.choice([1, -1])
        fraction = lambda: rnd.choice([rnd.randrange(0, 65536), 0, 65535, 256, 255, 0x8000])
        fc, fs, sc, ss = fraction(), fraction(), rnd.choice([0, 0x8000]), rnd.choice([0, 0x8000])
        e.wr16(cos, fc)
        e.wr16(cos + 2, sc)
        e.wr16(sin, fs)
        e.wr16(sin + 2, ss)
        offset = rnd.choice([0x4000, 0x2000])
        put(gx_, gx)
        put(gy_, gy)
        e.d, e.db, e.mf, e.xf, e.a, e.s = D, LB >> 16, 0, 0, offset, 0x1fff
        c0 = e.cycles
        e.call(0x0d, s['transformGXGY'] & 0xffff, sentinel=0xd7f00)
        cycles += e.cycles - c0
        got = (e.rd16(nx_) | (e.rd16(nx_ + 2) << 16), e.rd16(ny_) | (e.rd16(ny_ + 2) << 16))
        vc, vs = fc | (sc << 16), fs | (ss << 16)
        want = (s32(wolfsim.fixed_by_frac(gx, vc) - wolfsim.fixed_by_frac(gy, vs) - offset) & 0xffffffff,
                s32(wolfsim.fixed_by_frac(gy, vc) + wolfsim.fixed_by_frac(gx, vs)) & 0xffffffff)
        if got != want:
            failures += 1
            if failures < 5:
                print('TRANSFORM gx', gx, 'gy', gy, 'cos', hex(vc), 'sin', hex(vs), 'offset', hex(offset), 'got', got, 'want', want)
    print('transformGXGY: %d cases, %d differ, mean %.0f nominal cycles' % (count, failures, cycles / count))
    return failures


def check_actor_transform(rig, count, seed=9):
    """TransformActor (what refreshActors runs for a seen actor) against the source's TransformActor.

    A view point and angle give V_viewcos/V_viewsin as refreshView does; an actor stands within ten tiles.
    Carry must be nx >= MINDIST. Shootable actors require O_TRANSX nx and
    O_VIEWX = (|ny|*scale < shootdelta*nx); non-shootable actors leave aim untouched and may omit unused depth writes.
    """
    e, s = rig.e, rig.syms
    rnd = random.Random(seed)
    LOGIC_SCALE, LOGIC_SHOOTDELTA, MINDIST = 164, 24, 0x5800
    rec = LB + s['OBJLIST'] + 3 * 64
    failures = cycles = near = 0
    for _ in range(count):
        angle = rnd.randrange(360)
        vx = (rnd.randrange(1, 63) << 16) | rnd.randrange(65536)
        vy = (rnd.randrange(1, 63) << 16) | rnd.randrange(65536)
        ox = (vx + rnd.randrange(-10 << 16, 10 << 16)) & 0xffffffff
        oy = (vy + rnd.randrange(-10 << 16, 10 << 16)) & 0xffffffff
        for name, off in (('V_viewsin', 0), ('V_viewcos', 360)):
            e.wr16(LB + s[name], e.rd16(LB + s['SINTAB'] + off + 4 * angle))
            e.wr16(LB + s[name + '_hi'], e.rd16(LB + s['SINTAB'] + off + 4 * angle + 2))
        e.wr16(LB + s['V_viewx'], vx & 0xffff)
        e.wr16(LB + s['V_viewx_hi'], vx >> 16)
        e.wr16(LB + s['V_viewy'], vy & 0xffff)
        e.wr16(LB + s['V_viewy_hi'], vy >> 16)
        e.wr16(rec + s['O_X'], ox & 0xffff)
        e.wr16(rec + s['O_X'] + 2, ox >> 16)
        e.wr16(rec + s['O_Y'], oy & 0xffff)
        e.wr16(rec + s['O_Y'] + 2, oy >> 16)
        e.wr16(rec + s['O_VIEWX'], 0xdead)
        shootable = rnd.randrange(2)
        e.wr16(rec + s['O_FLAGS'], shootable)
        obj = rec - LB
        e.wr16(D + s['L_CHECK'], obj)
        e.d, e.db, e.mf, e.xf, e.s, e.x = D, LB >> 16, 0, 0, 0x1fff, obj
        if 'prepareTransformProducts' in s:
            e.wr16(LB+s['V_viewangle'],angle)
            if _ % 3:
                e.call(0x0d,s['prepareTransformProducts']&0xffff,sentinel=0xd7f00)
            else:
                e.wr16(s['transformRowsReady']+1,s['prepareFirstTransform'] & 65535)
            e.x=obj  # preparation is once per refresh in the game, outside this actor's measured cost
        c0 = e.cycles
        e.call(0x0d, s['TransformActor'] & 0xffff, sentinel=0xd7f00)
        cycles += e.cycles - c0
        vc = e.rd16(LB + s['V_viewcos']) | (e.rd16(LB + s['V_viewcos_hi']) << 16)
        vs = e.rd16(LB + s['V_viewsin']) | (e.rd16(LB + s['V_viewsin_hi']) << 16)
        gx, gy = s32(ox - vx), s32(oy - vy)
        nx = s32(wolfsim.fixed_by_frac(gx, vc) - wolfsim.fixed_by_frac(gy, vs) - 0x4000)
        ny = s32(wolfsim.fixed_by_frac(gy, vc) + wolfsim.fixed_by_frac(gx, vs))
        want_carry = nx >= MINDIST
        got_nx = s32(e.rd16(rec + s['O_TRANSX']) | (e.rd16(rec + s['O_TRANSX'] + 2) << 16))
        ok = (not shootable or got_nx == nx) and e.c == int(want_carry)
        if want_carry and shootable:
            near += 1
            ok = ok and e.rd16(rec + s['O_VIEWX']) == int(abs(ny) * LOGIC_SCALE < LOGIC_SHOOTDELTA * nx)
        if not shootable:
            ok = ok and e.rd16(rec + s['O_VIEWX']) == 0xdead
        if not ok:
            failures += 1
            if failures < 5:
                print('ACTOR TRANSFORM view', hex(vx), hex(vy), 'angle', angle, 'actor', hex(ox), hex(oy),
                      'nx got', got_nx, 'want', nx, 'carry', e.c, int(want_carry))
    print('TransformActor: %d cases (%d ahead of the view), %d differ, mean %.0f nominal cycles'
          % (count, near, failures, cycles / count))
    return failures


def random_scene(rnd):
    t = [0] * 4096
    for i in range(64):
        for x, y in ((0, i), (63, i), (i, 0), (i, 63)):
            t[x * 64 + y] = 1 + rnd.randrange(60)
    density = rnd.choice([0.02, 0.06, 0.12, 0.25])
    for x in range(1, 63):
        for y in range(1, 63):
            if rnd.random() < density:
                t[x * 64 + y] = 1 + rnd.randrange(60)
    doorpos = [rnd.choice([0, rnd.randrange(65536), 65535, 0x8000, 0x7fff, 0x8001]) for _ in range(64)]
    for _ in range(rnd.randrange(0, 12)):
        t[rnd.randrange(2, 62) * 64 + rnd.randrange(2, 62)] = 0x80 | rnd.randrange(64)
    for _ in range(rnd.randrange(0, 3)):
        t[rnd.randrange(2, 62) * 64 + rnd.randrange(2, 62)] = 0xc0 | rnd.randrange(64)
    while True:
        tx, ty = rnd.randrange(1, 63), rnd.randrange(1, 63)
        if t[tx * 64 + ty] == 0:
            break
    return (t, doorpos, rnd.randrange(0, 128), (tx << 16) | rnd.randrange(65536),
            (ty << 16) | rnd.randrange(65536), rnd.randrange(360))


def demo_scenes(demo, every):
    """The model's gameplay refreshes of one recorded demo: (tilemap, doors, pwallpos, x, y, angle, cells)."""
    d = wolfsim.demo_chunks()[demo]
    game = wolfsim.Game(d['mapon'], viewwidth=240)
    game.ray_columns = list(range(4, 240, 8))
    scenes, count = [], [0]
    original = wolfsim.Game.wall_refresh

    def hook(self):
        original(self)
        count[0] += 1
        if count[0] % every == 0:
            p = self.player
            scenes.append((list(self.tilemap), list(self.doorposition) + [0] * 64, self.pwallpos, p.x & 0xffffffff,
                           p.y & 0xffffffff, p.angle, {i for i, v in enumerate(self.spotvis) if v}))
    wolfsim.Game.wall_refresh = hook
    try:
        data = d['data']
        for n in range(0, len(data) - len(data) % 3, 3):
            b = data[n]
            cx = data[n + 1] - 256 if data[n + 1] > 127 else data[n + 1]
            cy = data[n + 2] - 256 if data[n + 2] > 127 else data[n + 2]
            if n + 3 == len(data):
                game.playstate = wolfsim.EX_COMPLETED
            game.play_frame(b, cx, cy)
            if game.playstate:
                break
    finally:
        wolfsim.Game.wall_refresh = original
    return scenes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf')
    ap.add_argument('--random', type=int, default=0, help='random scenes to check against the model')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--demo', type=int, nargs='*', default=[], help='demo numbers whose frames are replayed')
    ap.add_argument('--every', type=int, default=8, help='replay every Nth refresh of a demo')
    ap.add_argument('--axes', type=int, default=0, help='random maps at view angles on and beside the axes and diagonals, N each')
    ap.add_argument('--partials', action='store_true', help='check the four partial product routines exhaustively')
    ap.add_argument('--transform', type=int, default=0, help='random inputs for transformGXGY')
    ap.add_argument('--actors', type=int, default=0, help='random actor positions for TransformActor')
    ap.add_argument('--stamps', type=int, nargs='?', const=0, default=None, metavar='DEMO',
                    help='replay every refresh of one demo (default 0) on one memory image without clearing '
                         'the stamps in between, so the stamp value wraps and the clearing sweep runs')
    args = ap.parse_args()
    rig = Rig(args.elf)
    if 'CastLogicView' in rig.syms and (args.random or args.demo or args.axes or args.partials or args.stamps is not None):
        ap.error('this ELF shares the wall cast; use model_shared_visibility.py and check_wall_dda.py --stamp-all-empty; --transform/--actors remain supported')
    failures = check_partials(rig) if args.partials else 0
    if args.transform:
        failures += check_transform(rig, args.transform)
    if args.actors:
        failures += check_actor_transform(rig, args.actors)

    def check(label, t, doors, pw, px, py, angle, want=None):
        nonlocal failures
        doors = doors + [0] * (64 - len(doors))
        rig.scene(t, doors, pw, px, py, angle)
        cycles = rig.run()
        if want is None:
            vx, vy, mid = rig.view()
            want = rig.model(t, doors, pw, vx, vy, mid)
        got = rig.cells()
        if got != want:
            failures += 1
            print('MISMATCH', label, 'extra', sorted(got - want)[:8], 'missing', sorted(want - got)[:8])
        return cycles

    if args.random:
        rnd = random.Random(args.seed)
        total = sum(check('random %d' % i, *random_scene(rnd)) for i in range(args.random))
        print('random scenes %d: mean %.0f nominal cycles per refresh' % (args.random, total / args.random))
    if args.axes:
        rnd = random.Random(args.seed + 100)
        angles = sorted({(base + off) % 360 for base in range(0, 360, 45) for off in (-2, -1, 0, 1, 2)})
        total = count = 0
        for angle in angles:
            for i in range(args.axes):
                t, doors, pw, px, py, _ = random_scene(rnd)
                total += check('axes angle %d scene %d' % (angle, i), t, doors, pw, px, py, angle)
                count += 1
        print('axis scenes %d (%d view angles): mean %.0f nominal cycles per refresh' % (count, len(angles), total / count))
    if args.stamps is not None:
        scenes = demo_scenes(args.stamps, 1)
        bad = 0
        for i, sc in enumerate(scenes):
            t, doors, pw, px, py, angle, want = sc
            rig.scene(t, doors + [0] * (64 - len(doors)), pw, px, py, angle, keep_stamps=i > 0)
            rig.run()
            got = rig.cells()
            if got != want:
                bad += 1
                if bad < 4:
                    print('MISMATCH stamps scene', i, 'extra', sorted(got - want)[:8], 'missing', sorted(want - got)[:8])
        failures += bad
        print('demo %d: %d refreshes without clearing the stamps (stamp value now %d): %d differ'
              % (args.stamps, len(scenes), rig.e.rd16(LB + rig.syms['V_spotstamp']) & 255, bad))
    for demo in args.demo:
        scenes = demo_scenes(demo, args.every)
        total = sum(check('demo %d scene %d' % (demo, i), *sc[:6], want=sc[6]) for i, sc in enumerate(scenes))
        print('demo %d: %d scenes, mean %.0f nominal cycles per refresh' % (demo, len(scenes), total / len(scenes)))
    if failures:
        raise SystemExit('%d scenes differ from the model' % failures)
    print('PASS')


if __name__ == '__main__':
    main()
