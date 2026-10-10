"""Check native wall-run lifetime and door-coordinate clamps independently."""
import memmap
import argparse
import json
from pathlib import Path
import random
import struct
import zlib
from model_shared_visibility import Cast
import wolfsim


def expected_runs(grid):
    tags = [0]*4096
    for x in range(64):
        first = 0
        for y in range(64):
            cell = x*64+y
            if not 1 <= grid[cell] <= 63:
                first = y+1
            tags[cell] = (y ^ first) & 63
    for y in range(64):
        first = 0
        for x in range(64):
            cell = x*64+y
            if not 1 <= grid[cell] <= 63:
                first = x+1
            tags[cell] |= ((x ^ first) & 63) << 6
    return struct.pack('<4096H', *tags)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, default=Path('docs/evidence/rays/wall-openings'))
    args = ap.parse_args()
    rig = Cast(214, args.elf)
    e, s = rig.e, rig.symbols
    world = zlib.decompress((args.out/'session-scenes.bin.z').read_bytes())
    grid = list(struct.unpack('<4096H', world[256:8448]))

    def call(name):
        e.call(s[name] >> 16, s[name] & 65535, sentinel=memmap.CALL_SENTINEL_LOW, long_return=True)

    def check():
        address = s['wallRunCells']
        assert e.m[address:address+8192] == expected_runs(grid)

    e.load((memmap.OLD_VISIBILITY+0x2000), struct.pack('<4096H', *grid))
    call('InitWallRuns')
    check()
    rng = random.Random(427)
    cycles = []
    for _ in range(100):
        cell = rng.randrange(4096)
        grid[cell] = rng.choice([0, 0x8000, 1, 2, 63, 128, 129, 192])
        e.wr16((memmap.OLD_VISIBILITY+0x2000)+cell*2, grid[cell])
        e.d, e.db, e.a, e.x, e.y = 0x1100, 0x28, 0x1234, cell, 0xabcd
        before = e.a, e.x, e.y, e.d, e.db, e.s, e.getp()
        start = e.cycles
        call('RefreshWallRuns')
        cycles.append(e.cycles-start)
        assert (e.a, e.x, e.y, e.d, e.db, e.s, e.getp()) == before
        check()
    for cell, value in [(17*64+20, 0), (17*64+20, 1), (17*64+21, 192),
                        (17*64+21, 0), (17*64+22, 128), (17*64+22, 7)]:
        grid[cell] = value or 0x8000
        e.wr8((memmap.OLD_VISIBILITY+0xf000)+cell, 64)
        e.d, e.db, e.a, e.x, e.s = 0x1100, 0x28, value, cell, 0x1fff
        e.call(s['StoreLogicTile'] >> 16, s['StoreLogicTile'] & 65535, sentinel=(memmap.OLD_WORLD+0xff00))
        check()
    for floor in range(10):
        game = wolfsim.Game(floor)
        grid = [(tile if tile & 128 else tile & 63) for tile in game.tilemap]
        e.load((memmap.OLD_VISIBILITY+0x2000), struct.pack('<4096H', *grid))
        e.d, e.db, e.s = 0x1000, 2, 0x1fff
        call('InitWallRuns')
        check()
    (args.out/'table-native.json').write_text(json.dumps(dict(mutations=100,
        store_logic_tile_mutations=6, floors=10, words_per_check=4096,
        registers_and_flags_preserved=True, cycles=cycles,
        table_address=hex(s['wallRunCells'])), indent=2)+'\n')
    count = 0
    for side in (0, 1):
        for cell in (0, 1, 31, 62, 63):
            for offset in (-4, -1, 0, 1, 31, 62, 63, 64, 67):
                raw = cell*64+offset
                if not 0 <= raw < 4096:
                    continue
                index = 32*64+cell if side == 0 else cell*64+32
                for key, value in [('SIDE', side), ('MAPIDX', index), ('RAY', raw), ('TEXU', raw & 63)]:
                    e.wr16(0x1000+s[key], value)
                call('ClampDoorCoordinate')
                expected = max(0, min(63, offset))
                assert e.rd16(0x1000+s['TEXU']) == expected
                assert e.rd16(0x1000+s['RAY']) == cell*64+expected
                count += 1
    (args.out/'door-clamp.json').write_text(json.dumps(dict(cases=count, passed=True,
        rule='Clamp the 8-bit-product coordinate to the actual DDA cell before the sliding-door comparison.'), indent=2)+'\n')
    print('10 floors, 100 mutations, 6 StoreLogicTile calls, 82 door clamps pass')


if __name__ == '__main__':
    main()
