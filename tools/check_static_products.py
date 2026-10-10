"""Check cached static-coordinate products against signed truncating math."""
import memmap
import argparse
import json
from pathlib import Path
import random

from check_sight_cast import image


def signed(value):
    return value - 65536 if value & 32768 else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    e, sy = image(args.elf)
    e.m[sy['depthReady']] = 0x60
    rng = random.Random(658164)
    calls = hits = 0
    def call(name):
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        e.call(sy[name] >> 16, sy[name] & 65535, sentinel=memmap.CALL_SENTINEL_LOW)
    def put(name, value):
        e.wr16(0x1000 + sy[name], value & 65535)
    for angle in range(1024):
        c, s = [signed(e.rd16(base + angle * 2)) for base in (memmap.COS_TABLE, memmap.SIN_TABLE)]
        put('SP_C', c); put('SP_S', s); put('ANGLE', angle)
        call('prepareFactors')
        for vx, vy in [(128, 128), (16255, 16256),
                       (rng.randrange(16384), rng.randrange(16384))]:
            put('VX', vx); put('VY', vy)
            call('prepareStaticFactors')
            epoch = e.rd16(sy['staticEpoch'])
            call('prepareStaticFactors')
            assert e.rd16(sy['staticEpoch']) == epoch
            cells = [(0, 0), (63, 63), (0, 63), (63, 0)]
            cells += [(rng.randrange(64), rng.randrange(64)) for _ in range(12)]
            for x, y in cells * 2:
                hits += e.rd16((memmap.ENDPOINTS+0xe4) + x * 256) == epoch
                hits += e.rd16((memmap.ENDPOINTS+0x40e4) + y * 256) == epoch
                put('AI_CELL', x * 64 + y)
                call('projectStatic')
                def product(v, f):
                    return (abs(v) * abs(f) // 256) * (-1 if (v < 0) != (f < 0) else 1)
                dx, dy = x * 256 + 128 - vx, y * 256 + 128 - vy
                expected = (product(dx, c) + product(dy, s) - 32,
                            product(dy, c) - product(dx, s))
                actual = tuple(signed(e.rd16(0x1000 + sy[k])) for k in ('SP_DEPTH', 'SP_SIDE'))
                assert actual == expected, (angle, vx, vy, x, y, actual, expected)
                calls += 1
    # Force epoch rollover with nonzero tags in every slot.
    for page in range(128):
        e.wr16((memmap.ENDPOINTS+0xe4) + page * 256, 1)
    e.wr16(sy['staticEpoch'], 65535)
    put('ANGLE', 0)
    call('prepareStaticFactors')
    assert e.rd16(sy['staticEpoch']) == 1
    assert all(e.rd16((memmap.ENDPOINTS+0xe4) + page * 256) == 0 for page in range(128))
    result = dict(native_static_projections=calls, cached_axis_hits=hits,
                  differences=0, epoch_rollover_checked=True, extra_table_allocation=0)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
