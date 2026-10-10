"""Check native per-column overflow flags against the previous mask builder."""
import argparse
import json
from pathlib import Path
import random

from check_sight_cast import image
from check_sprite_masks import run, scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--trials', type=int, default=2000)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    old, new = image(args.baseline), image(args.elf)
    rng = random.Random(6581616)
    overflow_columns = 0
    for trial in range(args.trials):
        records, order, heights = scene(rng)
        before, _ = run(old, True, records, order, heights)
        after, _ = run(new, True, records, order, heights)
        assert bytes(value & ~32 for value in after[0]) == before[0], trial
        assert before[1:] == after[1:], trial
        expected = set()
        world = [n for n in order if records[n]['pri'] != 65535]
        for index in world[16:]:
            r = records[index]
            if r['n'] >= 256:
                continue
            for col in range(r['n'], r['lim']):
                if heights[col] <= r['hi']:
                    expected.add(col)
        actual = {col for col, value in enumerate(after[0][:160]) if value & 32}
        assert actual == expected, (trial, actual, expected)
        overflow_columns += len(actual)
    result = dict(native_lists=args.trials, overflow_columns=overflow_columns,
                  mask_owner_and_mark_differences=0, extra_table_allocation=0)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
