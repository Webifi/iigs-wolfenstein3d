"""Compare the sprite column marks and masks of two builds on random sprite lists.

The old build marks a world sprite's silhouette columns in addVisible (markWorldColumns, once per
sprite in projection order) and then builds the per-column masks in buildColumnMasks. The new build
does both in buildColumnMasks. Both run the real code in tools/emu816.py on the same random records,
silhouettes, sorted order and wall heights; the marks at $01:B200, the masks at $01:BD00, the owner of
every mask bit and the fallback flag must agree. It also prints the mean nominal cycles of the work.

  python3 tools/check_sprite_masks.py --before OLD.elf [--after build/wolf.elf] [--trials 2000] [--seed 1]

--before is a build that still has markWorldColumns (the two walks), or a build with the fused walk: then both
run the same entry. Pass the same file twice to check the tool.
"""
import argparse
import random
from pathlib import Path

from check_sight_cast import image, ROOT
import memmap
from memmap import projections

REMEMBERED = memmap.REMEMBERED            # trackProjection's first and end column of each object, by object id / 8
SILHOUETTES = memmap.SILHOUETTES
MARKS = memmap.MARKS
MASKS = memmap.COLUMN_MASKS
WIDTH = 160                      # most columns a view has
SENTINEL = memmap.CALL_SENTINEL_LOW

SP_COUNT, SP_HI, SP_N, SP_LIMIT = 0x7c, 0x74, 0x9a, 0xa4


def scene(rnd):
    """Records, silhouettes and the sorted order of one frame."""
    view = rnd.choice([107, 120, 144, 160])
    count = rnd.choice([0, 1, 2, 3, 5, 8, 12, 16, 17, 18, 22])
    weapon = rnd.randrange(count) if count and rnd.random() < 0.7 else -1
    records = []
    for i in range(count):
        hi = rnd.randrange(2, 600, 2)
        if rnd.random() < 0.85:                  # a real silhouette, as addVisible makes it
            left = rnd.randrange(-60, view + 20)
            width = rnd.randrange(1, 130)
            first = rnd.randrange(0, min(8, width))
            last = rnd.randrange(first, width + 1)
            right = left + width
            n = max(0, left + first - 1)
            lim_raw = left + last + 2
            lim = min(view, lim_raw) if lim_raw > 0 else 0
            if lim_raw <= 0 or n >= view:
                n = lim = 0
        else:                                    # any bytes: the tool checks the code, not the formulas
            left = rnd.randrange(-300, 300)
            right = rnd.randrange(1, 400)
            n = rnd.randrange(0, view + 1)
            lim = rnd.randrange(0, view + 1)
        if rnd.random() < 0.08:                  # a first column past 255 spills into the packed end
            n = rnd.randrange(256, 500)
            lim = rnd.randrange(0, view + 1)
        records.append(dict(left=left, right=right, hi=hi, pri=65535 if i == weapon else 0, n=n, lim=lim))
    order = list(range(count))
    rnd.shuffle(order)
    heights = []
    for c in range(WIDTH):
        if rnd.random() < 0.3 and records:
            hi = rnd.choice(records)['hi']
            heights.append(max(0, hi + rnd.choice([-4, -2, 0, 2, 4])))
        else:
            heights.append(rnd.randrange(0, 640, 2))
    # runs of equal walls make long marked spans
    for k in range(rnd.randrange(0, 4)):
        a = rnd.randrange(WIDTH)
        b = min(WIDTH, a + rnd.randrange(1, 60))
        v = rnd.randrange(0, 640, 2)
        heights[a:b] = [v] * (b - a)
    return records, order, heights


def run(rig, new, records, order, heights):
    e, s = rig
    records_base, sorted_base = projections(s)
    e.m[records_base:records_base + 16 * 24] = bytes(16 * 24)
    e.m[MARKS:MARKS + 2 * WIDTH + 4] = bytes(2 * WIDTH + 4)
    e.m[MASKS:MASKS + 2 * WIDTH + 4] = bytes(2 * WIDTH + 4)
    e.m[SILHOUETTES:SILHOUETTES + 64] = bytes(64)
    hbase = (2 << 16) | (s['heightIndex'] & 0xffff)
    for c, h in enumerate(heights):
        e.wr16(hbase + 2 * c, h)
    for i, r in enumerate(records):
        o = records_base + 16 * i
        e.wr16(o, r['left'] & 0xffff)
        e.wr16(o + 2, r['right'] & 0xffff)
        e.wr16(o + 4, r['hi'])
        e.wr16(o + 8, 32 * (i + 1))              # object id; its remembered columns sit at id / 8
        e.wr16(o + 12, r['pri'])
        e.wr16(SILHOUETTES + 2 * i, ((r['lim'] << 8) | r['n']) & 0xffff)
        e.wr16(REMEMBERED + 4 * (i + 1), r['n'])
        e.wr16(REMEMBERED + 4 * (i + 1) + 2, r['lim'])
    for k, i in enumerate(order):
        e.wr16(sorted_base + 2 * k, 16 * i)
    for k in range(16):
        e.wr16((2 << 16) | (s['maskOwners'] & 0xffff) + 2 * k, 0xdead)
    e.wr16((2 << 16) | (s['maskFallback'] & 0xffff), 0xbeef)
    e.d, e.db, e.mf, e.xf, e.s = 0, 2, 0, 0, 0x1fff
    e.wr16(SP_COUNT, len(records))
    c0 = e.cycles
    if not new:
        # addVisible's mark walk, once per world sprite in projection order
        for i, r in enumerate(records):
            if r['pri'] == 65535 or not (r['n'] or r['lim']):
                continue
            e.d, e.db, e.mf, e.xf, e.s = 0, 2, 0, 0, 0x1fff
            e.wr16(SP_HI, r['hi'])
            e.wr16(SP_N, r['n'])
            e.wr16(SP_LIMIT, r['lim'])
            e.x = r['n']
            e.call(2, s['markWorldColumns'] & 0xffff, sentinel=SENTINEL)
    e.d, e.db, e.mf, e.xf, e.s = 0, 2, 0, 0, 0x1fff
    e.call(2, s['buildColumnMasks'] & 0xffff, sentinel=SENTINEL)
    cycles = e.cycles - c0
    world = [i for i in order if records[i]['pri'] != 65535]
    owners = [e.rd16((2 << 16) | (s['maskOwners'] & 0xffff) + 2 * k) for k in range(min(16, len(world)))]
    fallback = e.rd16((2 << 16) | (s['maskFallback'] & 0xffff)) != 0
    return (bytes(e.m[MARKS:MARKS + 2 * WIDTH]), bytes(e.m[MASKS:MASKS + 2 * WIDTH]), owners, fallback), cycles


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--before', type=Path, required=True)
    ap.add_argument('--after', type=Path, default=ROOT / 'build/wolf.elf')
    ap.add_argument('--trials', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    old, new = image(args.before), image(args.after)
    old_fused = 'markWorldColumns' not in old[1]      # a build that already walks marks and masks together
    rnd = random.Random(args.seed)
    bad = 0
    cyc = [0, 0]
    columns = sprites = 0
    for trial in range(args.trials):
        records, order, heights = scene(rnd)
        a, ca = run(old, old_fused, records, order, heights)
        b, cb = run(new, True, records, order, heights)
        cyc[0] += ca
        cyc[1] += cb
        sprites += len(records)
        columns += sum(1 for x in a[1][::2] if x) + sum(1 for x in a[0] if x)
        if a != b:
            bad += 1
            if bad <= 3:
                print('trial', trial, 'differs; marks', a[0] != b[0], 'masks', a[1] != b[1], 'owners', a[2], b[2],
                      'fallback', a[3], b[3])
                for r in records:
                    print('   ', r)
                print('    order', order)
    print('%d trials, %d sprites, %d marked or masked columns: %s' % (
        args.trials, sprites, columns, 'all equal' if not bad else '%d DIFFER' % bad))
    print('mean nominal cycles per frame: %.0f -> %.0f' % (cyc[0] / args.trials, cyc[1] / args.trials))
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
