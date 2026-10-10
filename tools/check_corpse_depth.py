"""Check the native corpse near-plane guard against the full parent transform.

Exercise every view angle just inside/outside the exact cutoff, far positions,
shootable actors, and both cold and warm coefficient setup. No MAME process.
"""
import argparse
import json
import math
import random
from pathlib import Path

from check_sight_cast import D, LB, image
import wolfsim as w


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', type=Path, required=True)
    ap.add_argument('--after', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    rigs = [image(args.before), image(args.after)]
    sine = w.build_tables()[2]
    rng = random.Random(781)
    cases = []
    for angle in range(360):
        theta = math.radians(angle)
        for delta in (-512, -1, 0, 1, 512):
            depth = 0x5800+0x4000+delta
            lateral = rng.randrange(-8 << 16, 8 << 16)
            gx = round(depth*math.cos(theta)+lateral*math.sin(theta))
            gy = round(-depth*math.sin(theta)+lateral*math.cos(theta))
            cases.append((angle, gx, gy, 0))
    cases.extend((rng.randrange(360), rng.randrange(-63 << 16, 63 << 16),
                  rng.randrange(-63 << 16, 63 << 16), rng.randrange(2)) for _ in range(6000))
    cycles = [[0, 0], [0, 0]]
    counts = [0, 0]
    fallback = 0
    for trial, (angle, gx, gy, shootable) in enumerate(cases):
        counts[shootable] += 1
        expected = w.fixed_by_frac(gx, sine[angle+90])-w.fixed_by_frac(gy, sine[angle])-0x4000
        outputs = []
        for k, (e, s) in enumerate(rigs):
            obj = s['OBJLIST']+3*64
            for name, value in (('V_viewcos', sine[angle+90]), ('V_viewsin', sine[angle]),
                                ('V_viewx', 0), ('V_viewy', 0)):
                e.wr16(LB+s[name], value & 65535)
                e.wr16(LB+s[name+'_hi'], value >> 16 & 65535)
            for name, value in (('O_X', gx), ('O_Y', gy), ('O_TRANSX', 0x12345678)):
                e.wr16(LB+obj+s[name], value & 65535)
                e.wr16(LB+obj+s[name]+2, value >> 16 & 65535)
            e.wr16(LB+obj+s['O_FLAGS'], shootable)
            e.wr16(LB+obj+s['O_VIEWX'], 0xdead)
            e.wr16(D+s['L_CHECK'], obj)
            e.d, e.db, e.mf, e.xf, e.s = D, 0x28, 0, 0, 0x1fff
            if trial % 3:
                e.call(0x0d, s['prepareTransformProducts'] & 65535, sentinel=0xd7f00)
            else:
                e.wr16(s['transformRowsReady']+1, s['prepareFirstTransform'] & 65535)
            e.x = obj
            start = e.cycles
            e.call(0x0d, s['TransformActor'] & 65535, sentinel=0xd7f00)
            cycles[k][shootable] += e.cycles-start
            transx = w.s32(e.rd16(LB+obj+s['O_TRANSX']) | e.rd16(LB+obj+s['O_TRANSX']+2) << 16)
            outputs.append((e.c, transx, e.rd16(LB+obj+s['O_VIEWX'])))
        assert outputs[0][0] == outputs[1][0] == int(expected >= 0x5800), (trial, cases[trial], outputs)
        assert outputs[0][1] == expected, (trial, outputs)
        if shootable:
            assert outputs[0] == outputs[1], (trial, outputs)
        else:
            assert outputs[1][2] == 0xdead, (trial, outputs)
            assert outputs[1][1] in (expected, 0x12345678), (trial, outputs)
            fallback += outputs[1][1] == expected
    report = dict(cases=len(cases), near_plane_cases=1800, corpse_cases=counts[0],
                  shootable_cases=counts[1], corpse_exact_fallbacks=fallback,
                  mean_nominal_cycles={name: [c[n]/counts[n] for c in cycles]
                                       for n, name in enumerate(('corpse', 'shootable'))},
                  exact_visibility=True, exact_shootable_projection=True,
                  skipped_fields='Unused corpse aim and (outside the guard) depth only')
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
