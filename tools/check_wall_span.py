"""Check linked span validation and two-cell materials at map boundaries."""
import memmap
import argparse
import itertools
import json
from pathlib import Path

from elf import read
from emu816 import Emu


def fixture(elf, horizontal, reverse, tiles):
    segments, symbols = read(elf)
    e = Emu()
    for segment in segments:
        e.load(segment['address'], segment['data'])
    e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
    fixed, first = 32, 12
    for i, tile in enumerate(tiles):
        cell = (first+i)*64+fixed if horizontal else fixed*64+first+i
        e.wr16((memmap.OLD_VISIBILITY+0x2000)+cell*2, tile)
    left, right = first*64+16, (first+len(tiles)-1)*64+40
    if reverse:
        left, right = 4095-right, 4095-left
    e.wr16(symbols['raySurface'], left)
    e.wr16(symbols['raySurface']+8, right)
    e.wr16(symbols['raySpacing'], 4)
    e.wr16(0x1000+symbols['SCAN'], 4)
    e.wr16(0x1000+symbols['TILE'], fixed|0x8000 if horizontal else fixed*64)
    # Vertical coordinates flip on the greater root side; horizontal on less.
    root = fixed-1 if reverse == horizontal else fixed+1
    e.wr16(0x1000+symbols['ROOTMAP'], (root if horizontal else root*64)*2)
    e.x = 0
    address = symbols['prepareMixedSpan']
    e.call(address >> 16, address & 65535)
    valid, page = bool(e.c), e.rd16(0x1000+symbols['PAGE'])
    expected_valid = all(0 < tile < 64 for tile in tiles)
    assert valid == expected_valid, (horizontal, reverse, tiles, valid)
    assert e.x == 0, 'left anchor not restored'
    if valid and len(set(tiles)) == 1:
        expected = (2*tiles[0]-(2 if horizontal else 1))*256
        assert page == expected, (horizontal, reverse, tiles, page, expected)
    elif valid:
        assert page == 65535
        address = symbols['prepareSplitSpan']
        e.call(address >> 16, address & 65535)
        assert bool(e.c) == (len(tiles) == 2)
        if len(tiles) == 2:
            order = tiles[::-1] if reverse else tiles
            expected = [(2*tile-(2 if horizontal else 1))*256 for tile in order]
            got = [e.rd16(0x1000+symbols[name]) for name in ('PAGE', 'MULW')]
            assert got == expected, (horizontal, reverse, tiles, got, expected)
    return dict(horizontal=horizontal, reverse=reverse, tiles=tiles, valid=valid)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    cases = [(1,), (63,), (2, 2), (2, 3), (63, 1), (3, 2, 3), (2, 2, 2, 2, 2)]
    for tile in (0, 64, 128, 192, 0x8000, 0xffff):
        cases.extend(((tile,), (2, tile), (tile, 2), (2, 3, tile), (2, tile, 3)))
    rows = [fixture(args.elf, horizontal, reverse, tiles)
            for horizontal, reverse, tiles in itertools.product((False, True), (False, True), cases)]
    result = dict(cases=len(rows), result='PASS', rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
