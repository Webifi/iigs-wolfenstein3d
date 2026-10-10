"""Reconstruct old/new native wall layers for the pinned opening fixtures."""
import memmap
import argparse
import json
from pathlib import Path
import struct
import zlib
from check_wall_openings import Replay, BASE, compare
from check_wall_opening_scenes import scenes
from reference import light, png
from wolfdata import vswap


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--after', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--out', type=Path, default=Path('docs/evidence/rays/wall-openings/native-gallery'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    folder = args.out.parent
    report = json.loads((folder/'session-verified.json').read_text())
    records = zlib.decompress((folder/'session-scenes.bin.z').read_bytes())
    palette = json.loads(Path('build/palettes/0.json').read_text())
    pages = vswap()[0]
    directory = b''.join(struct.pack('<HH', (memmap.ART_BASE+p*8192+u*128)&65535,
                           (p<<8)|((memmap.ART_BASE+p*8192+u*128)>>16))
                         for p in range(106) for u in range(64))
    html = ['<!doctype html><meta charset="utf-8"><title>Opening repair</title>',
            '<style>body{background:#222;color:white;font:16px sans-serif}img{image-rendering:pixelated;max-width:33%}</style>',
            '<h1>Old / repaired / difference</h1>',
            '<p>Native cast outputs reconstructed as a wall-only layer. These are not MAME screenshots; sprites, weapon and HUD are omitted. No wall sample density or source art changed. Magenta marks changed bytes.</p>']
    evidence = []
    for case in report['cases']:
        view = case['view']
        index = max(range(len(case['rows'])), key=lambda n: len(case['rows'][n]['old_bad']))
        selected = [('session', records[index*8706:(index+1)*8706], case['rows'][index]['pose'])]
        # Pick the strongest missing doorway example at each width.
        pair = [Replay(view, BASE), Replay(view, args.after)]
        for position in (0, 128):
            best = None
            for pose, data in scenes('door', position):
                values = [r.run(data) for r in pair]
                changes = sum(a!=b for a,b in zip(values[0]['planes'],values[1]['planes']))
                if best is None or changes>best[0]:best=(changes,pose,data)
            selected.append((f'door-{position}', best[2], best[1]))
        for label, data, pose in selected:
            pictures = []
            for r in pair:
                e,s = r.r.e,r.r.symbols
                e.load(memmap.OLD_WALL_COLUMNS,directory)
                r.run(data)
                pixels = bytearray(160*160)
                top = (160-view//2)//2
                for c in range(view//2):
                    h=e.rd16(s['scaleHeight']+e.rd16(s['heightIndex']+2*c))
                    bank=e.rd16(s['sourceBank']+2*c);page=bank>>8
                    address=((bank&255)<<16)|e.rd16(s['sourceAddr']+2*c)
                    u=(address-memmap.ART_BASE-page*8192)//128
                    assert 0<=u<64
                    colors=palette['wall_lights'][light(h,view//2)]
                    for y in range(top,top+view//2):
                        if y<80-h//2:index=0x1d
                        elif y>=80+h//2:index=0x19
                        else:index=pages[page][u*64+max(0,min(63,(y-(80-h//2))*64//h))]
                        pixels[y*160+top+c]=colors[index][y&1]
                pictures.append(pixels)
            name=f'{label}-{view}'
            for suffix,pixels in zip(('old','new'),pictures):png(args.out/f'{name}-{suffix}.png',pixels,palette['palette'])
            delta=bytes(255 if a!=b else 0 for a,b in zip(*pictures))
            png(args.out/f'{name}-diff.png',delta,[(0,0,0)]*15+[(255,0,255)])
            html += [f'<h2>{label}, view {view}</h2><p>{pose}</p>', ''.join(f'<img src="{name}-{p}.png">' for p in ('old','new','diff'))]
            evidence.append(dict(name=name,pose=pose,changed_bytes=sum(bool(b) for b in delta)))
    (args.out/'index.html').write_text('\n'.join(html)+'\n')
    (args.out/'summary.json').write_text(json.dumps(evidence,indent=2)+'\n')


if __name__ == '__main__':
    main()
