"""Check the paired native sprite products against separate truncating products."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import random

from check_sight_cast import image


def signed(n):
    return n-65536 if n & 32768 else n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--baseline', type=Path, default=Path('build/combined-8CA54C9B/wolf.elf'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    rigs = [image(p) for p in (args.baseline, args.elf)]
    randomizer = random.Random(9401)
    totals = [0, 0]
    cases = 0
    for angle in range(1024):
        factors = [signed(rigs[0][0].rd16(a+angle*2)) for a in (memmap.COS_TABLE, memmap.SIN_TABLE)]
        for e, sy in rigs:
            e.d, e.db, e.s, e.mf, e.xf = 0x1000, 2, 0x1fff, 0, 0
            for key, value in zip(('SP_C', 'SP_S'), factors):
                e.wr16(0x1000+sy[key], value & 65535)
            e.call(2, sy['prepareFactors'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
        values = [-32768, -16384, -257, -256, -255, -1, 0, 1, 127, 255, 256, 257, 16383, 32767]
        values += [randomizer.randrange(-32768, 32768) for _ in range(24)]
        for value in values:
            expected = [((abs(value)*abs(f)//256)*(-1 if (value < 0) != (f < 0) else 1)) & 65535 for f in factors]
            old, os = rigs[0]
            before = old.cycles
            got = []
            for label in ('productC', 'productS'):
                old.a = value & 65535
                old.nz(old.a, True)
                old.call(2, os[label] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
                got.append(old.a)
            totals[0] += old.cycles-before+12  # caller's two JSRs
            assert got == expected, (angle, value, got, expected)
            new, ns = rigs[1]
            new.a = value & 65535
            new.nz(new.a, True)
            before = new.cycles
            new.call(2, ns['productsCS'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
            totals[1] += new.cycles-before+6
            assert [new.a, new.y] == expected, (angle, value, new.a, new.y, expected)
            assert (new.d, new.db, new.s, new.mf, new.xf) == (0x1000, 2, 0x1fff, 0, 0)
            cases += 1
    result = dict(scope=__doc__, cases=cases, differences=0, nominal_cycles=totals,
                  nominal_cycles_saved_per_pair=(totals[0]-totals[1])/cases,
                  elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
                  baseline_elf_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                  note='Kernel arithmetic only; complete scenes must price early rejection and setup.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
