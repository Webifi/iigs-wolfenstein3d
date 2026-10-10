"""Keep single-tile wall pictures visible throughout the E1M1 wood corridor.

Execute both linked casters and a full-column native DDA in private interpreter
memory. This checks material selection, not hardware performance. The existing
two-column boundary approximation is counted separately from interior errors.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from check_wall_openings import Replay, compare
import wolfsim


def corridor():
    game = wolfsim.Game(0)
    data = bytearray(8706)
    grid = [(tile if tile & 128 else tile & 63) or 0x8000 for tile in game.tilemap]
    data[256:8448] = struct.pack('<4096H', *grid)
    for i, door in enumerate(game.doors):
        struct.pack_into('<H', data, 8576+2*i, int(door['vertical']))
    return data


def interior(columns, reference):
    return [c for c in columns if 1 < c < len(reference)-2
            and len(set(reference[c-2:c+3])) == 1]


def lost_pictures(pages, reference):
    runs = []
    start = 0
    for end in range(1, len(reference)+1):
        if end == len(reference) or reference[end] != reference[start]:
            if reference[start] == 21 and end-start >= 3 and 21 not in pages[start:end]:
                runs.append([start, end])
            start = end
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-clean-baseline', action='store_true',
                        help='Compare against an already repaired build; still require exact new material coverage.')
    args = parser.parse_args()
    cases = []
    data = corridor()
    for view in (160, 214, 240, 320):
        rigs = [Replay(view, args.before), Replay(view, args.after), Replay(view, args.after, True)]
        rows = []
        for x in (8512, 8576, 8768):
            for y in (4992, 5248, 5504):
                for angle in (256, 262, 268, 274, 280, 286, 292, 298, 304):
                    struct.pack_into('<3H', data, 0, x, y, angle)
                    values = [r.run(data) for r in rigs]
                    diff = compare(values)
                    reference = values[2]['pages']
                    row = dict(pose=[x, y, angle], **diff,
                               old_interior=interior(diff['old_page_disagreements'], reference),
                               new_interior=interior(diff['new_page_disagreements'], reference),
                               old_lost_pictures=lost_pictures(values[0]['pages'], reference),
                               new_lost_pictures=lost_pictures(values[1]['pages'], reference),
                               poster_columns=[[i for i, page in enumerate(v['pages']) if page == 21] for v in values],
                               cycles=[v['cycles'] for v in values])
                    rows.append(row)
        case = dict(view=view, poses=len(rows),
                    old_wrong_planes=sum(len(r['old_bad']) for r in rows),
                    new_wrong_planes=sum(len(r['new_bad']) for r in rows),
                    old_interior_errors=sum(len(r['old_interior']) for r in rows),
                    new_interior_errors=sum(len(r['new_interior']) for r in rows),
                    old_lost_pictures=sum(len(r['old_lost_pictures']) for r in rows),
                    new_lost_pictures=sum(len(r['new_lost_pictures']) for r in rows),
                    old_boundary_errors=sum(len(r['old_page_disagreements'])-len(r['old_interior']) for r in rows),
                    new_boundary_errors=sum(len(r['new_page_disagreements'])-len(r['new_interior']) for r in rows),
                    rows=rows)
        print({k: v for k, v in case.items() if k != 'rows'}, flush=True)
        cases.append(case)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(dict(
            before_sha256=hashlib.sha256(args.before.read_bytes()).hexdigest(),
            after_sha256=hashlib.sha256(args.after.read_bytes()).hexdigest(),
            reference='One native DDA trace per output column; interpreter-only code in bank 50.',
            cases=cases), indent=2)+'\n')
    if not args.allow_clean_baseline:
        assert sum(c['old_interior_errors'] for c in cases) > 0, 'fixture did not reproduce the defect'
    assert all(c['new_wrong_planes'] == c['new_interior_errors'] == c['new_lost_pictures'] == 0 for c in cases)


if __name__ == '__main__':
    main()
