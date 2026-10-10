"""Compare linked casters at identical captured world states.

Records are the 8,706-byte fast-RAM snapshots written by replay_pacing.py.
Cycle counts come from the 65816 interpreter, not hardware frame timing.
The comparison includes every wall-column descriptor and geometric plane.
"""
import argparse
import hashlib
import json
from pathlib import Path

from check_wall_openings import Replay


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('records', type=Path)
    ap.add_argument('--before', type=Path, required=True)
    ap.add_argument('--after', type=Path, required=True)
    ap.add_argument('--view', type=int, required=True)
    ap.add_argument('--stride', type=int, default=1)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    data = args.records.read_bytes()
    assert data and len(data) % 8706 == 0
    assert args.stride > 0
    rigs = [Replay(args.view, p) for p in (args.before, args.after)]
    rows = []
    for index in range(0, len(data)//8706, args.stride):
        world = data[index*8706:(index+1)*8706]
        values, descriptors = [], []
        for rig in rigs:
            rig.run(world)
            values.append(rig.run(world))
            e, symbols = rig.r.e, rig.r.symbols
            descriptors.append(b''.join(
                bytes(e.rd8(symbols[name]+i) for i in range(args.view))
                for name in ('heightIndex', 'sourceAddr', 'sourceBank')))
        exact = (descriptors[0] == descriptors[1]
                 and values[0]['planes'] == values[1]['planes'])
        rows.append(dict(record=index+1, exact=exact,
                         cycles=[v['cycles'] for v in values]))
        if len(rows) % 100 == 0:
            print(f'{len(rows)} poses, {sum(not r["exact"] for r in rows)} differences', flush=True)
    report = dict(
        measure='Nominal 65816 wall-caster cycles; not complete frame timing.',
        view=args.view, stride=args.stride, poses=len(rows),
        differences=sum(not r['exact'] for r in rows),
        mean_cycle_change=sum(r['cycles'][1]-r['cycles'][0] for r in rows)/len(rows),
        worst_cycle_change=max(r['cycles'][1]-r['cycles'][0] for r in rows),
        hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (args.records, args.before, args.after)}, rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))
    assert report['differences'] == 0


if __name__ == '__main__':
    main()
