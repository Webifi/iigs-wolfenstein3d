"""Execute two-axis static indexing and conservative rectangle selection.

Includes map edges, all 400 IDs, removal/reinsertion, and the pickup query's
five-tile X interval. Native picture and complete-frame checks are separate.
"""
import memmap
import argparse
import json
from pathlib import Path
import random

from check_sight_cast import image

BASE = memmap.STATIC_INDEX
BYTES = 25 * 140


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    e, symbols = image(args.elf)
    rng = random.Random(658162)
    world = symbols['LOGICBANK'] << 16
    cells = [(rng.randrange(64), rng.randrange(64)) for _ in range(400)]
    cells[:8] = [(0,0),(0,63),(63,0),(63,63),(1,1),(62,62),(31,32),(32,31)]
    e.load(BASE, bytes(BYTES))
    guard = bytes([0xa7]) * 16
    e.load(BASE + BYTES, guard)

    def index(label, number):
        e.d, e.db, e.mf, e.xf, e.s = 0x1100, world >> 16, 0, 0, 0x1fff
        e.x = symbols['STATICS'] + number * 8
        at = symbols[label]
        e.call(at >> 16, at & 65535, sentinel=memmap.STATIC_TEST_RETURN)
        assert e.x == symbols['STATICS'] + number * 8

    active = set()

    def check_prefixes():
        for group in range(25):
            for axis in range(2):
                for boundary in range(-1, 34):
                    expected = sum(1 << (i % 16) for i in active
                                   if i // 16 == group and cells[i][axis] // 2 < boundary)
                    address = BASE + group * 140 + axis * 70 + (boundary + 1) * 2
                    assert e.rd16(address) == expected, (group, axis, boundary)
        assert bytes(e.m[BASE + BYTES:BASE + BYTES + len(guard)]) == guard

    for number, (x, y) in enumerate(cells):
        record = world + symbols['STATICS'] + number * 8
        e.wr16(record, x * 64 + y)
        e.wr16(record + 2, symbols['SPR_STAT_9'])
        index('AddStaticIndex', number)
        active.add(number)
    check_prefixes()
    removed = rng.sample(range(400), 137)
    for number in removed:
        index('RemoveStaticIndex', number)
        active.remove(number)
    check_prefixes()
    for number in removed:
        index('AddStaticIndex', number)
        active.add(number)
    check_prefixes()

    # The native pickup walk reads prefixes six bytes apart. Coarse bins
    # may include one extra edge tile, which its exact reach test rejects.
    for x in range(64):
        for number, (sx, _) in enumerate(cells):
            group, bit = divmod(number, 16)
            at = BASE + group * 140 + (x & ~1)
            selected = bool((e.rd16(at) ^ e.rd16(at + 6)) & (1 << bit))
            assert selected == (x // 2 - 1 <= sx // 2 <= x // 2 + 1)
            assert not (abs(sx - x) <= 2 and not selected)

    e.m[symbols['projectStatic']] = 0x60
    # Ceiling lights retain their expanded-footprint stamps. Ordinary
    # statics must reach projection without requiring an exact-cell stamp.
    light_ids = {0, 1}
    for number, shape in zip(sorted(light_ids), ('SPR_STAT_4', 'SPR_STAT_14')):
        e.wr16(world + symbols['STATICS'] + number*8 + 2, symbols[shape])
    e.wr16(0x1000 + symbols['ENTRY'], 0)
    e.wr16(0x1000 + symbols['ENTRY'] + 2, 0x33)
    e.wr16(0x1000 + symbols['VISSTAMP'], 1)
    calls = 0
    for trial in range(500):
        for number in light_ids:
            x, y = cells[number]
            e.wr16(memmap.VIS_STAMPS + (x*64+y)*2, trial & 1)
        x0, x1 = sorted(rng.choices(range(64), k=2))
        y0, y1 = sorted(rng.choices(range(64), k=2))
        for label, value in [('staticLowLoad', 0xe000 + (x0 & ~1)),
                             ('staticHighLoad', 0xe006 + (x1 & ~1)),
                             ('staticYLowLoad', 0xe046 + (y0 & ~1)),
                             ('staticYHighLoad', 0xe04c + (y1 & ~1))]:
            e.wr16(symbols[label] + 1, value)
        e.wr16(symbols['staticMaskEnd'], symbols['STATICS'] + 3200)
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        e.x, e.y = 0, symbols['STATICS']
        e.pb, e.pc = 2, symbols['staticGroup'] & 65535
        found = []
        while (e.pb << 16 | e.pc) != symbols['staticsDone']:
            if (e.pb << 16 | e.pc) == symbols['projectStatic']:
                found.append(e.rd16(0x1000 + symbols['SP_OBJ']) // 32)
            e.step()
        expected = [i for i, (x, y) in enumerate(cells)
                    if x0 // 2 - 1 <= x // 2 <= x1 // 2 + 1
                    and y0 // 2 - 1 <= y // 2 <= y1 // 2 + 1
                    and (i not in light_ids or trial & 1)]
        assert found == expected, (trial, found, expected)
        calls += len(found)
    result = dict(prefix_states=3, prefix_words_checked=3 * 25 * 70,
                  pickup_cases=64 * 400, rectangle_cases=500,
                  projection_calls=calls, index_bytes=BYTES,
                  light_stamp_states=2, adjacent_memory_unchanged=True)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
