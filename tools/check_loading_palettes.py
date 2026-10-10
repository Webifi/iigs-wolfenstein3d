"""Render fixed loading ink over every floor's dimmed reference picture.

This is an offline palette/readability check, not a native scene capture. It
keeps each floor's original palette and uses the existing gray-pair mapping
for its background. The reference renders the spawn view's walls and HUD.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from loading_glyphs import ROWS, LEFT, TOP, pixels, assembly, block


def luminance(rgb):
    def linear(v):
        v /= 255
        return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    return sum(w * linear(v) for w, v in zip((.2126, .7152, .0722), rgb))


def contrast(a, b):
    a, b = sorted((luminance(a), luminance(b)))
    return (b + .05) / (a + .05)


def shape_check(root):
    source = json.loads((root/'data/frontend-fonts/BlackOpsOne-Regular.ttf.6.json').read_text())['glyphs']
    top = min(y for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for y, row in enumerate(source[c]) if '#' in row)
    face = set()
    x = LEFT + 1
    for c in 'LOADING':
        for y, row in enumerate(source[c][top:top+8], TOP+1):
            face.update((x+dx, y) for dx, v in enumerate(row) if v == '#')
        x += len(source[c][0]) + 2
    outline = {(x+dx, y+dy) for x, y in face for dx in (-1,0,1) for dy in (-1,0,1)}
    actual = pixels()
    assert {v for _, _, v in actual} == {0, 1, 13, 14}
    assert {(x,y) for x,y,v in actual if v == 1} == face, 'letter shape changed'
    assert {(x,y) for x,y,v in actual} == outline, 'outline footprint changed'
    assert (root/'src/iigs/loading_sign.inc').read_text() == assembly(), 'generated ink is stale'
    data = block()
    tag, groups, height = struct.unpack_from('<3H', data)
    assert tag == 0xfffc and height == len(ROWS)
    decoded = []
    for y in range(height):
        at = 6 + struct.unpack_from('<H', data, 6+2*y)[0]
        row = []
        for _ in range(groups):
            mask = data[at]; at += 1
            ink = data[at:at+4] if mask != 255 else bytes(4)
            if mask != 255: at += 4
            row.extend(None if mask & (1 << x) else (ink[x//2] >> (4 if x%2 == 0 else 0)) & 15
                       for x in range(8))
        decoded.append(row)
    assert [(LEFT+x,TOP+y,v) for y,row in enumerate(decoded) for x,v in enumerate(row)
            if v is not None] == actual, 'packed word or transparency differs'
    return dict(face_pixels=len(face), outline_pixels=len(outline)-len(face),
                grey_pixels=sum(v in (13,14) for _,_,v in actual), shape_unchanged=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    from PIL import Image
    import reference
    from wolfdata import ROOT, PROFILE
    from frontend.gray_pair import gray_slots
    args.out.mkdir(parents=True, exist_ok=True)
    shape = shape_check(ROOT)
    records = []
    thumbs = []
    for floor in range(PROFILE.floors):
        folder = ROOT/'build/levels'/str(floor)
        meta = json.loads((folder/'map.json').read_text())
        receipt = ROOT/'build/palettes'/f'{floor}.json'
        original = receipt.read_bytes()
        pal = json.loads(original)['palette']
        assert meta['palette'] == pal, (floor, 'palette binding differs')
        reference.ASSETS = folder
        picture, _ = reference.render(meta['spawn'], view=107, interpolate=False)
        words = [sum((c//17) << shift for c,shift in zip(rgb,(8,4,0))) for rgb in pal]
        dim = gray_slots(words)
        rgb = [tuple(pal[dim[n]]) for b in picture for n in (b>>4,b&15)]
        hud = reference.render_hud(dict(levelIndex=floor,score=0,lives=3,health=100,ammo=8,weapon=1,keys=0))
        for y in range(40):
            hp = reference.hud_palette(y)
            hd = gray_slots([sum((c//17) << shift for c,shift in zip(color,(8,4,0))) for color in hp])
            rgb.extend(tuple(hp[hd[n]]) for b in hud[y*160:(y+1)*160] for n in (b>>4,b&15))
        image = Image.new('RGB',(320,200));image.putdata(rgb)
        background = [image.getpixel((x,y)) for x,y,v in pixels() if v == 1]
        for x,y,v in pixels(): image.putpixel((x,y),tuple(pal[v]))
        image.resize((640,400),Image.Resampling.NEAREST).save(args.out/f'floor-{floor+1:02d}@2x.png')
        crop = image.crop((LEFT-2,TOP-2,LEFT+len(ROWS[0])+2,TOP+len(ROWS)+2))
        thumbs.append(crop.resize((crop.width*4,crop.height*4),Image.Resampling.NEAREST))
        for slot in (13,14):
            assert max(pal[slot])-min(pal[slot]) <= 34, (floor, slot, pal[slot], 'edge is not near neutral')
            assert 0 < luminance(pal[slot]) < luminance(pal[1]), (floor, slot, 'edge order')
        body_black = contrast(pal[1],pal[0])
        body_edge = min(contrast(pal[1],pal[s]) for s in (13,14))
        body_background = min(contrast(pal[1],color) for color in background)
        assert body_black >= 10, (floor, 'weak letter stroke')
        assert body_edge >= 3, (floor, 'weak stroke against antialiased edge')
        assert original == receipt.read_bytes(), 'palette was modified'
        records.append(dict(floor=floor+1, slots={str(s):words[s] for s in (0,1,12,13,14,15)},
                            palette_sha256=hashlib.sha256(original).hexdigest(),
                            stroke_black_contrast=body_black, stroke_edge_contrast=body_edge,
                            stroke_background_contrast=body_background))
    sheet = Image.new('RGB',(thumbs[0].width*5,thumbs[0].height*((len(thumbs)+4)//5)),(32,32,32))
    for n,thumb in enumerate(thumbs):sheet.paste(thumb,((n%5)*thumb.width,(n//5)*thumb.height))
    sheet.save(args.out/'all-words@4x.png')
    report = dict(profile=PROFILE.key, floors=len(records), shape=shape,
                  method='Native reference spawn walls and HUD; existing gray-pair indices under the unchanged floor palette. No popup panel, so the word also faces the dimmed picture directly. Offline only.',
                  contrast='(linear-sRGB luminance + 0.05) ratio; edge contrast is reported separately from opaque strokes.',
                  worst={k:min(records,key=lambda r:r[k]) for k in ('stroke_black_contrast','stroke_edge_contrast','stroke_background_contrast')},
                  records=records)
    (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))


if __name__ == '__main__': main()
