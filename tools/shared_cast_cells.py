"""Compare the cells of the gameplay visibility rays with the cells of the wall cast's rays.

One shared cast for both would give gameplay the cells that the wall anchors visit. This tool replays
every Nth gameplay refresh of the four recorded demos in the source model (tools/wolfsim.py) and, from
the same pose, walks an integer DDA with the renderer's pixel angles (one ray every STRIDE columns, a
ray ends at the first wall cell). It prints how many cells each side visits and in how many refreshes
the wall rays see every gameplay cell, and writes docs/evidence/rays/shared-cast-cells.json.

  python3 tools/shared_cast_cells.py [--every 8]
"""
import argparse
import json
import math

import check_sight_cast as c
from check_sight_cast import ROOT


def renderer_cells(tilemap, px32, py32, angle360, view, stride):
    x = (px32 >> 8) & 0xffff
    y = (py32 >> 8) & 0xffff                      # 8.8 tile units
    a1024 = round(angle360 * 1024 / 360) % 1024
    th = a1024 * math.tau / 1024
    px = x - int(round(math.cos(th) * 256) * 87 / 256)
    py = y + int(round(math.sin(th) * 256) * 87 / 256)
    cells = set()
    for col in range(0, view, stride):
        offset = round(math.atan(((view - 1) / 2 - col) / (view / 2) * (0x10000 / (2 * (0x5700 + 0x5800)))) * 1024 / math.tau)
        ang = (a1024 + offset) % 1024
        cs = math.cos(ang * math.tau / 1024)
        sn = -math.sin(ang * math.tau / 1024)
        sx, sy = (-1 if cs < 0 else 1), (-1 if sn < 0 else 1)
        dx = min(65535, round(256 / max(abs(cs), 1e-9)))
        dy = min(65535, round(256 / max(abs(sn), 1e-9)))
        mx, my = px >> 8, py >> 8
        tx = dx * ((256 - (px & 255)) if sx > 0 else px & 255) // 256
        ty = dy * ((256 - (py & 255)) if sy > 0 else py & 255) // 256
        cells.add(mx * 64 + my)
        for _ in range(128):
            if tx < ty:
                tx = min(65535, tx + dx)
                mx += sx
            else:
                ty = min(65535, ty + dy)
                my += sy
            if not (0 <= mx < 64 and 0 <= my < 64):
                break
            cells.add(mx * 64 + my)
            if tilemap[mx * 64 + my]:             # the wall cell itself; doors and push walls end a ray here too
                break
    return cells


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--every', type=int, default=8)
    args = ap.parse_args()
    out = []
    for demo in range(4):
        scenes = c.demo_scenes(demo, args.every)
        for view, stride in ((214, 16), (214, 1), (320, 16), (320, 1)):
            gs = rs = inter = sub = sup = 0
            for (t, doors, pw, px, py, ang, want) in scenes:
                r = renderer_cells(t, px, py, ang, view, stride)
                gs += len(want)
                rs += len(r)
                inter += len(want & r)
                sub += want <= r
                sup += r <= want
            n = len(scenes)
            row = dict(demo=demo, view=view, renderer_stride_columns=stride, frames=n, gameplay_cells=round(gs / n, 1),
                       renderer_cells=round(rs / n, 1), common_cells=round(inter / n, 1),
                       frames_with_all_gameplay_cells_seen_by_renderer=sub,
                       frames_with_all_gameplay_cells_seen_by_renderer_pct=round(100 * sub / n),
                       frames_where_renderer_sees_nothing_extra=sup)
            out.append(row)
            print(row)
    note = ('Visited cells of the gameplay rays (source model, wolfsim) against the cells of the renderer rays '
            '(integer DDA, every Nth column, ray ends at the first wall cell), on every eighth refresh of each demo.')
    (ROOT / 'docs/evidence/rays/shared-cast-cells.json').write_text(json.dumps(dict(note=note, cases=out), indent=1))


if __name__ == '__main__':
    main()
