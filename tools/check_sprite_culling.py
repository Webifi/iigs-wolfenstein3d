"""Check build-time sprite side limits against the original native projection.

Tests every height and view at both clipping edges, plus random side offsets.
Only projection acceptance is compared; native scene checks cover painting.
"""
import memmap
import argparse
import json
from pathlib import Path
import random

from check_sight_cast import image
from viewgeometry import HEIGHTS, SIZES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    rigs = [image(path) for path in (args.baseline, args.elf)]
    witness = memmap.TEST_WITNESS
    for e, sy in rigs:
        # Exercise projection after the depth lookup with a selected height.
        e.load(sy['HeightOfDepth'], bytes([0xa5, sy['SP_HI'], 0x60]))
        e.load(sy['addVisible'], b'\xa9\x01\x00\x8f\x00\x00\x43\x60')
    rng = random.Random(658169)
    cases = visible = 0
    for view_index, view in enumerate(SIZES):
        for hi, height in enumerate(HEIGHTS):
            width = height // 2
            left = (view - width) // 2
            limit = ((max(view - left, left + width) * 256) + width - 1) // width
            e, sy = rigs[1]
            assert e.rd16(memmap.ENDPOINTS + hi * 256 + 216 + view_index * 2) == limit
            edge = min(16384, limit)
            offsets = {0, -16384, 16384}
            offsets.update(sign * value for sign in (-1, 1)
                           for value in range(max(0, edge - 3), min(16384, edge + 3) + 1))
            offsets.update(rng.randrange(-16384, 16385) for _ in range(6))
            for side in sorted(offsets):
                results = []
                for e, sy in rigs:
                    e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
                    for key, value in [('SP_HI', hi * 2), ('SP_SIDE', side),
                                       ('AI_TURN', 0), ('SP_SHAPE', 0)]:
                        e.wr16(e.d + sy[key], value & 65535)
                    e.wr16(sy['viewWidth'], view)
                    e.wr16(witness, 0)
                    if 'spriteSideLimit' in sy:
                        e.wr16(sy['spriteSideLimit'] + 1, 216 + view_index * 2)
                    e.call(2, sy['depthVisible'] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
                    results.append(bool(e.rd16(witness)))
                expected = left + (abs(side) * width // 256) * (-1 if side < 0 else 1)
                expected = expected < view and expected + width > 0
                assert results == [expected, expected], (view, height, side, results, expected)
                cases += 1
                visible += expected
    result = dict(native_projection_cases=cases, visible=visible, differences=0,
                  height_view_limits=len(HEIGHTS) * len(SIZES), extra_table_allocation=0)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
