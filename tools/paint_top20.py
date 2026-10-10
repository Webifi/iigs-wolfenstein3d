"""Mean of the 20 slowest frames of each case, from the FRAME lines of the second run of a paint_check.

Usage: python3 tools/paint_top20.py TESTDIR [TESTDIR ...]   (names under build/tests; the last one is
compared with the first). This is the review's acceptance measure (a one-frame change under 0.7 ms is noise).
"""
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / 'build/tests'


def frames(d, demo, view, run=1):
    p = ROOT / d / f'd{demo}-v{view}' / str(run) / 'mame.log'
    return [float(t) * 1000 for f, n, t in re.findall(r'^FRAME (\d+) (\d+) ([\d.]+)$', p.read_text(), re.M)]


def top(fr, n=20):
    s = sorted(fr, reverse=True)[:n]
    return sum(s) / len(s)


dirs = sys.argv[1:]
print('%-8s' % 'case', *['%14s' % d[-14:] for d in dirs], '  change% (first -> last)', '   total s')
tot = [0.0] * len(dirs)
for view in (214, 320):
    for demo in range(4):
        vals = []
        for d in dirs:
            fr = frames(d, demo, view)
            vals.append((top(fr), sum(fr) / 1000))
        ch = (vals[-1][0] - vals[0][0]) / vals[0][0] * 100 if len(vals) > 1 else 0
        print('d%d v%d  ' % (demo, view), *['%14.2f' % v[0] for v in vals], '  %+7.2f' % ch, '  ', ' '.join('%.3f' % v[1] for v in vals))
        for i, v in enumerate(vals): tot[i] += v[0]
print('mean top20 over cases:', *['%.2f' % (x / 8) for x in tot], '  change %+.2f%%' % ((tot[-1] - tot[0]) / tot[0] * 100 if len(dirs) > 1 else 0))
