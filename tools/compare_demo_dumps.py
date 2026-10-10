"""Compare the ray arrays, sprite records and paint inputs that two runs of tools/demo_check.py dumped.

Run tools/demo_check.py N --ray-posts --name PREFIX-N (N = 0 to 3) for each build, then

  python3 tools/compare_demo_dumps.py NEW OLD [--ignore-array 1]

NEW and OLD are the run folder prefixes, for example build/tests/chk-new and build/tests/chk-old. This byte comparison
is a bug finder; intentional quality trials also need old/new/difference pictures and gameplay checks.
The arrays are heightIndex, hitPlane, sourceAddr and sourceBank in this order, 0 to 3;
--view 320 compares the full-width dumps; --ignore-array 1 skips hitPlane, which differs from builds before 74f5f92. The demo states are compared by
demo_check.py itself: its output must read "native frames N model frames N end DEMOEND" without "first difference".
"""
import argparse
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('new')
    ap.add_argument('old')
    ap.add_argument('--view',type=int,choices=(160,214,240,320),default=214)
    ap.add_argument('--ignore-array', type=int, nargs='*', default=[])
    args = ap.parse_args()
    block=args.view
    ok = True
    for demo in range(4):
        new, old = Path('%s-%d' % (args.new, demo)), Path('%s-%d' % (args.old, demo))
        a = (old / 'ray-posts.bin').read_bytes()
        b = (new / 'ray-posts.bin').read_bytes()
        if len(a) != len(b):
            print('demo %d: the dumps have different sizes %d and %d' % (demo, len(a), len(b)))
            ok = False
            continue
        frames = len(a) // (4 * block)
        bad = sum(1 for f in range(frames) for k in range(4) if k not in args.ignore_array
                  and a[(f * 4 + k) * block:(f * 4 + k + 1) * block] != b[(f * 4 + k) * block:(f * 4 + k + 1) * block])
        sprites = (old / 'sprite-posts.bin').read_bytes() == (new / 'sprite-posts.bin').read_bytes()
        paint = (old / 'paint-inputs.bin').read_bytes() == (new / 'paint-inputs.bin').read_bytes()
        print('demo %d: %d frames, %d array blocks differ, sprite records %s, paint inputs %s'
              % (demo, frames, bad, 'equal' if sprites else 'DIFFER', 'equal' if paint else 'DIFFER'))
        ok &= bad == 0 and sprites and paint
    print('EXACT' if ok else 'MISMATCH')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
