"""Check tighter sprite bounds against every captured object's visible runs.

Cover all eight demo cases and the synthetic-pool fallback used by PrepareSprites.
"""
import memmap
import argparse
import json
import random
import struct
from pathlib import Path

import wolfsim
from viewgeometry import HEIGHTS
from check_sight_cast import image


def native_checks(elf):
    e, sy = image(elf)
    rnd = random.Random(556)
    for trial in range(2000):
        hi = rnd.randrange(200)*2
        left = rnd.randrange(-300, 160)
        first, last = rnd.randrange(65), rnd.randrange(64)
        view = rnd.choice([80, 107, 120, 160])
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        for key, value in [('SP_HI', hi), ('SP_BASE', first+last*256), ('SP_LEFT', left)]:
            e.wr16(0x1000+sy[key], value & 65535)
        e.wr16(sy['viewWidth'], view)
        e.call(2, sy['inverseSilhouette'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
        h = HEIGHTS[hi//2]
        reciprocal = round(32768/h)
        def inv(tex):
            return min(h//2, (tex*256+reciprocal-1)//reciprocal) if tex < 64 else h//2
        assert e.rd16(0x1000+sy['SP_N']) == max(0, left+inv(first)), trial
        assert e.a == min(view, max(0, left+inv(last+1))), trial
        e.wr16(0x1000+sy['SP_H'], h)
        e.wr16(0x1000+sy['SP_SHAPE'], 0)
        e.wr16((memmap.OLD_SPRITE_CMDS+0x102), 0)
        e.y = h//2
        e.call(2, sy['scaleSetup'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
        e.x = 0x4321
        e.call(2, sy['padChangedSilhouette'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
        assert e.x == 0x4321
        assert e.rd16(0x1000+sy['SP_N']) == max(0, left+first*h//128-1), trial
        assert e.rd16(0x1000+sy['SP_LIMIT']) == min(view, max(0, left+(last+1)*h//128+2)), trial
        e.wr16((memmap.OLD_SPRITE_CMDS+0x102), 0x8000)
        e.wr16(0x1000+sy['SP_N'], 0x1234)
        e.wr16(0x1000+sy['SP_LIMIT'], 0x5678)
        e.x = 0x4321
        e.call(2, sy['padChangedSilhouette'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
        assert e.x == 0x4321
        assert e.rd16(0x1000+sy['SP_N']) == 0x1234
        assert e.rd16(0x1000+sy['SP_LIMIT']) == 0x5678
    return 2000


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prefix', default='astra4-before')
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, default=Path('build/rays-astra/inverse-model.json'))
    args = ap.parse_args()
    native = native_checks(args.elf)
    hor = Path('build/assets/horizontal.bin').read_bytes()
    ep = Path('build/assets/sprite-endpoints.bin').read_bytes()
    bases, inverses, pos = [], [], 0
    for i, h in enumerate(HEIGHTS):
        bases.append(pos)
        mapping = hor[pos:pos+h//2]
        pos += h//2
        inv = struct.unpack_from('<65H', ep, i*256+65)
        for tex in range(65):
            assert inv[tex] == next((x for x, v in enumerate(mapping) if v >= tex), len(mapping))
        inverses.append(inv)
    results = []
    for view in (214, 320):
        width = view//2
        top = (160-width)//2
        bottom = top+width
        for demo in range(4):
            folder = Path(f'build/tests/{args.prefix}-{view}-{demo}')
            timing = json.loads((folder/'measure.json').read_text())
            slow = {r['frame'] for r in sorted(timing['frame_times'], key=lambda r:-r['ns'])[:20]}
            raw = (folder/'sprite-posts.bin').read_bytes()
            rays = (folder/'ray-posts.bin').read_bytes()
            cmd = Path(f'build/levels/{wolfsim.demo_chunks()[demo]["mapon"]}/spritecmd.bin').read_bytes()
            offset = checked = missing = pools = old_visits = new_visits = runs = 0
            for frame in range(1, timing['frames']+1):
                n = struct.unpack_from('<H', raw, offset)[0]
                offset += 2
                walls = struct.unpack_from(f'<{width}H', rays, (frame-1)*4*view)
                for obj in range(n):
                    left, right, hi, shape, _, h, pri = struct.unpack_from('<7H', raw, offset)
                    offset += 14
                    if left >= 32768:
                        left -= 65536
                    assert h == HEIGHTS[hi//2]
                    cut = max(0, min(31, (max(top, 80-h//2)-(80-h//2))*64//h))
                    first, last = cmd[shape+194+cut*2:shape+196+cut*2]
                    old = max(0, left+first*h//128-1), min(width, left+(last+1)*h//128+2)
                    inv = inverses[hi//2]
                    bounds = max(0, left+inv[first]), min(width, max(0, left+inv[last+1]))
                    if cmd[shape+259] & 128:
                        bounds = old
                        pools += 1
                    for col in range(max(0, left), min(width, right)):
                        if pri != 65535 and hi < walls[col]:
                            continue
                        tex = hor[bases[hi//2]+col-left]
                        ptr = 65536+struct.unpack_from('<H', cmd, shape+2*tex)[0]
                        visible = 0
                        while (pair := struct.unpack_from('<H', cmd, ptr)[0]):
                            a = max(top, ep[hi//2*256+(pair & 255)])
                            b = min(bottom, ep[hi//2*256+(pair >> 8)])
                            visible += a < b
                            ptr += 6
                        checked += 1
                        if visible and not bounds[0] <= col < bounds[1]:
                            missing += 1
                            raise AssertionError((view, demo, frame, shape, h, col, bounds))
                        if frame in slow and pri != 65535:
                            old_visits += old[0] <= col < old[1]
                            new_visits += bounds[0] <= col < bounds[1]
                            runs += visible
            row = dict(view=view, demo=demo, checked_owner_columns=checked, missed_visible_columns=missing,
                       pool_records_kept=pools, old_top20_owner_visits=old_visits,
                       new_top20_owner_visits=new_visits, retained_top20_runs=runs)
            results.append(row)
            print(json.dumps(row), flush=True)
    args.out.write_text(json.dumps(dict(native_inverse_cases=native, native_restoration_cases=native,
                                       inverse_endpoints=13000, cases=results), indent=2)+'\n')


if __name__ == '__main__':
    main()
