"""Verify cold/warm height lookups and repeated view changes in native code."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import random

from check_sight_cast import image
from viewgeometry import HEIGHTS, SIZES


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    e, sy = image(args.elf)
    for label, address in sy.items():
        if label.startswith('Progress') and label[8:].isdigit():
            e.wr8(address, 0x6b)
    e.d, e.db, e.s, e.mf, e.xf = 0x1000, 2, 0x1fff, 0, 0
    indices = [min(range(len(HEIGHTS)), key=lambda i: abs(HEIGHTS[i]-h))*2 for h in range(1025)]
    rng = random.Random(20261004)
    cases = depth_cases = cold = warm = 0
    sequence = (0, 0, 1, 1, 2, 3, 3, 1, 3, 0)
    previous = None
    preparation = []
    for index in sequence:
        directory = bytes(e.m[memmap.VIS_STAMPS:memmap.SPARE_33])
        pool = bytes(e.m[memmap.LOGIC_BASE:(memmap.SPRITE_CMDS+0x1be00)])
        start = e.cycles
        e.x = index*2
        e.call(2, sy['PrepareRayPages'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW, limit=10_000_000)
        preparation.append(dict(view=SIZES[index]*2, cycles=e.cycles-start, repeated=index == previous))
        if index == previous:
            assert bytes(e.m[memmap.VIS_STAMPS:memmap.SPARE_33]) == directory
            assert bytes(e.m[memmap.LOGIC_BASE:(memmap.SPRITE_CMDS+0x1be00)]) == pool
        previous = index
        factor = round(SIZES[index]*256/160)
        expected = [indices[min(1024, round(56000/max(d, 1)))*factor//256] for d in range(16384)]
        # Every actor depth, including both sides of all half-page boundaries.
        for depth in range(16384):
            address = memmap.CPU_INFO+(depth//128)*2
            before = e.rd16(address)
            e.a = depth
            e.call(2, sy['HeightOfDepth'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
            assert e.a == expected[depth], (index, depth, e.a, expected[depth])
            assert e.rd16(address) == before & 0x7fff
            depth_cases += 1
        # Exercise the actual wall lookup with different cosines and distances.
        for cosine in range(207, 257):
            samples = [0, 1, 87, 127, 128, 129, 16383, 16384, 32767, 65535]
            samples += [rng.randrange(65536) for _ in range(150)]
            for distance in samples:
                for repeated in range(2):
                    address = memmap.VIS_STAMPS+(cosine-207)*1024+(distance//128)*2
                    was_cold = bool(e.rd16(address) & 0x8000)
                    cold += was_cold
                    warm += not was_cold
                    e.wr16(0x1000+sy['SCAN'], 0)
                    e.wr16(0x1000+sy['DIST'], distance)
                    e.wr16(0x1000+sy['ENTRY'], 0)
                    e.wr16(sy['pixelCos'], (cosine-207)*1024)
                    e.a = 0
                    e.pb, e.pc = sy['keepPlane'] >> 16, sy['keepPlane'] & 65535
                    while (e.pb << 16 | e.pc) != sy['heightRange']:
                        e.step()
                    got = (e.a & 255)*2
                    want = expected[min(distance*cosine//256, 16383)]
                    assert got == want, (index, cosine, distance, got, want)
                    assert not e.rd16(address) & 0x8000
                    assert (e.d, e.db, e.s, e.mf, e.xf) == (0x1000, 2, 0x1fff, 0, 0)
                    cases += 1
    result = dict(scope=__doc__, actor_depth_cases=depth_cases, wall_cases=cases,
                  cold_wall_entries=cold, warm_wall_entries=warm, differences=0,
                  elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
                  view_sequence=[SIZES[i]*2 for i in sequence], preparation=preparation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
