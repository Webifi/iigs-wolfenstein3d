"""Native adaptive/full-column checks for side passages and framed doors.

All four orientations and view sizes are exercised. The extra thin-material
strip is an audit of inherited texture-coordinate approximation, not a claim
that the renderer equals a full-column caster at every material boundary.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from check_wall_openings import Replay, BASE, compare


def scenes(kind, position):
    grid = [1]*4096
    for x in range(8, 55):
        for y in range(29, 32):
            grid[x*64+y] = 0x8000
    if kind == 'passages':
        for x in (18, 26, 34, 42, 50):
            for y in range(24, 38):
                grid[x*64+y] = 0x8000
        shifts, angles = (0, 63, 127, 191), (-24, -12, 0, 12, 24)
    else:
        for y in range(29, 32):
            grid[40*64+y] = 7
        grid[40*64+30] = 128 if kind == 'door' else 2
        shifts, angles = (0, 127, 255), (-12, 0, 12)
    for rotation in range(4):
        cells = grid[:]
        for _ in range(rotation):
            cells = [cells[(63-y)*64+x] for x in range(64) for y in range(64)]
        data = bytearray(8706)
        data[256:8448] = struct.pack('<4096H', *cells)
        struct.pack_into('<H', data, 8448, position)
        struct.pack_into('<H', data, 8576, 1-rotation % 2)
        for shift in shifts:
            for angle in angles:
                x, y = 12*256+shift, 30*256+128
                for _ in range(rotation):
                    x, y = y, 64*256-1-x
                struct.pack_into('<3H', data, 0, x, y, (angle+rotation*256) % 1024)
                yield dict(rotation=rotation, shift=shift, angle=angle), bytes(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', type=Path, default=BASE)
    ap.add_argument('--after', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, default=Path('docs/evidence/rays/wall-openings/synthetic-verified.json'))
    args = ap.parse_args()
    cases = []
    for kind, position in [('passages', 0), ('door', 0), ('door', 128), ('door', 255), ('material-audit', 0)]:
        for view in (160, 214, 240, 320):
            rigs = [Replay(view, args.before), Replay(view, args.after), Replay(view, args.after, True)]
            rows = []
            for pose, data in scenes(kind, position):
                values = [r.run(data) for r in rigs]
                result = compare(values)
                if result['new_bad'] or result['introduced_page_disagreements']:
                    result['details'] = values
                rows.append(dict(**pose, **result))
            case = dict(kind=kind, door_position=position, view=view, rows=rows,
                        old_wrong_planes=sum(len(r['old_bad']) for r in rows),
                        new_wrong_planes=sum(len(r['new_bad']) for r in rows),
                        inherited_material_disagreements=sum(len(r['new_page_disagreements']) for r in rows),
                        introduced_material_disagreements=sum(len(r['introduced_page_disagreements']) for r in rows))
            cases.append(case)
            print({k:v for k,v in case.items() if k != 'rows'}, flush=True)
            args.out.write_text(json.dumps(dict(before_sha256=hashlib.sha256(args.before.read_bytes()).hexdigest(),
                after_sha256=hashlib.sha256(args.after.read_bytes()).hexdigest(), cases=cases), indent=2)+'\n')
    assert all(not c['new_wrong_planes'] and not c['introduced_material_disagreements'] for c in cases)


if __name__ == '__main__':
    main()
