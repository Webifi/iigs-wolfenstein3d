"""Execute crowded mask preparation and compare its exact column coverage."""
import memmap
import argparse
import json
from pathlib import Path
import random

from check_sight_cast import image
from check_sprite_masks import run, scene, WIDTH

EXTRA_MASKS = memmap.EXTRA_MASKS


def dispatch(e, symbols, records, owners, heights, mode, col):
    """Run the real owner selector; intercept drawing only after record dispatch."""
    if mode == 4:
        expected = [i * 16 for i in owners
                    if records[i]['hi'] >= heights[col]
                    and (records[i]['left'] < 0 or records[i]['left'] <= col)
                    and (records[i]['right'] & 65535) > col]
    else:
        masks = [e.rd16(memmap.COLUMN_MASKS + col * 2)] + [
            e.rd16(EXTRA_MASKS + group * 320 + col * 2) for group in range(mode)]
        expected = [i * 16 for ordinal, i in enumerate(owners)
                    if masks[ordinal // 16] & (1 << (ordinal % 16))]
    e.d, e.db, e.pb, e.pc, e.mf, e.xf, e.s = 0x1000, 2, 2, symbols['scanOwners'] & 65535, 0, 0, 0x1fff
    for name, value in [('SP_COUNT', len(records)), ('SCAN', col * 2), ('COL', col), ('HEIGHT', heights[col])]:
        e.wr16(e.d + symbols[name], value)
    actual = []
    for _ in range(20000):
        pc = e.pb * 65536 + e.pc
        if pc == symbols['ownersDone']:
            break
        if pc == symbols['spriteOwner']:
            actual.append(e.x)
            e.pc = e.rd16(e.d + symbols['OLDBOTTOM'])
        else:
            e.step()
    else:
        raise AssertionError('owner selector did not terminate')
    assert actual == expected, (mode, col, actual, expected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--trials', type=int, default=1500)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    old, new = image(args.baseline), image(args.elf)
    rng = random.Random(6581632)
    counts = [0, 1, 15, 16, 17, 18, 31, 32, 33, 34, 47, 48, 49, 63, 64, 65, 66, 80]
    checked = set()
    for trial in range(args.trials):
        count = counts[trial % len(counts)]
        records = []
        while len(records) < count:
            records.extend(scene(rng)[0])
        records = records[:count]
        for r in records:
            r['pri'] = 0
            # Prepared silhouettes never name a column past the largest view.
            # The older generator also exercises arbitrary packed bytes.
            if (((r['lim'] << 8) | r['n']) & 65535) >> 8 > WIDTH:
                r['n'] = r['lim'] = 0
        if count and (trial // len(counts)) % 2:
            records[rng.randrange(count)]['pri'] = 65535
        order = list(range(count))
        rng.shuffle(order)
        heights = scene(rng)[2]
        before, _ = run(old, True, records, order, heights)
        after, _ = run(new, True, records, order, heights)
        assert before == after, (trial, count, 'original masks or restoration marks changed')
        e, symbols = new
        owners = [i for i in order if records[i]['pri'] != 65535]
        checked.add(len(owners))
        mode = e.rd16(symbols['maskFallback'])
        expected_mode = 4 if len(owners) > 64 else max(0, (len(owners) - 1) // 16)
        assert mode == expected_mode, (trial, mode, expected_mode)
        for col in [0, 1, 79, 159, (trial * 37) % 160]:
            dispatch(e, symbols, records, owners, heights, mode, col)
        if len(owners) <= 16 or len(owners) > 64:
            continue  # painter ignores the extra directory in this mode
        expected = [0] * (WIDTH * mode)
        for bit, index in enumerate(owners[16:64]):
            assert e.rd16(memmap.EXTRA_OWNERS + bit * 2) == index * 16
            r = records[index]
            packed = ((r['lim'] << 8) | r['n']) & 65535
            first, limit = packed & 255, packed >> 8
            if limit <= first:
                continue
            for col in range(max(first, r['left'], 0), min(limit, r['right'] & 65535)):
                if heights[col] <= r['hi']:
                    expected[(bit // 16) * WIDTH + col] |= 1 << (bit % 16)
        actual = [e.rd16(EXTRA_MASKS + col * 2) for col in range(WIDTH * mode)]
        assert actual == expected, (trial, count, [(i,a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b], [(i,records[i]) for i in owners[16:32]])
    result = dict(native_lists=args.trials, world_owner_counts=sorted(checked),
                  original_mask_differences=0, extra_mask_differences=0,
                  owner_dispatches=args.trials * 5, extra_runtime_bytes=1058)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
