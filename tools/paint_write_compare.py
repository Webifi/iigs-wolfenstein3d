"""Compare write-only paint_twice captures and their unperturbed top-20 times."""
import argparse
import json
from pathlib import Path
from frame_capture import capture_index, clean_paint_result, compact_capture, read_frame


def case(path):
    return json.loads((path / 'result.json').read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('before', type=Path)
    ap.add_argument('after', type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--keep-captures', action='store_true',
                    help='keep raw streams after a successful comparison for further diagnosis')
    args = ap.parse_args()
    rows = []
    for after in sorted(args.after.glob('d*-v*')):
        before = args.before / after.name
        old, new = case(before), case(after)
        assert old['frames'] == new['frames']
        paths = [p / 'frames.pixels' for p in (before, after)]
        aa, bb = (capture_index(p) for p in paths)
        assert aa['frames'] == bb['frames'] == new['frames']
        different = []
        for i, (x, y) in enumerate(zip(aa['frame_sha256'], bb['frame_sha256']), 1):
            if x != y:
                raw = [read_frame(p, i) for p in paths]
                count = sum(a != b for a, b in zip(*raw)) if all(v is not None for v in raw) else None
                different.append(dict(frame=i, bytes=count))
        hashes = bb['frame_sha256']
        top = lambda r: sum(sorted((f['ns'] for f in r['frame_times']), reverse=True)[:20]) / 20e6
        row = dict(case=after.name, frames=new['frames'], differing_frames=different,
                   before_top20_ms=top(old), after_top20_ms=top(new),
                   before_seconds=old['seconds'], after_seconds=new['seconds'], pixel_sha256=hashes)
        rows.append(row)
        print(after.name, 'different', len(different), 'top20 %.3f -> %.3f ms' % (top(old), top(new)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(cases=rows), indent=2) + '\n')
    if any(r['differing_frames'] for r in rows):
        raise SystemExit('Pictures differ')
    cases = [root / row['case'] for row in rows for root in (args.before, args.after)]
    if not args.keep_captures and all(clean_paint_result(path) for path in cases):
        for path in cases:
            compact_capture(path / 'frames.pixels')


if __name__ == '__main__':
    main()
