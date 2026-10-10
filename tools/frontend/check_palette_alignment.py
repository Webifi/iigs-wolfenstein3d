"""Check color capacity and decoded pixels independently of slot ordering."""
import json
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import shared_gray as gray

rng = random.Random(7012)
for trial in range(500):
    source = [rng.randrange(4096) for _ in range(16)]
    if trial % 2:
        source = [rng.choice(source[:1 + trial % 15]) for _ in range(16)]
    keep = 1 + trial % 16
    aligned = gray.align_palette(source, keep)
    assert set(source) <= set(aligned), 'alignment replaced a color'
    if len(set(source[:keep])) == keep:
        assert len(set(aligned)) == 16, 'a copied slot is still a copy'
    assert gray.align_palette(aligned, keep) == aligned, 'a second pass moved a color'
    assert source[:keep] == aligned[:keep], 'fixed prefix moved'
    assert [aligned[i] for i in gray.remap(source, aligned)] == source

pixels = 0
provenance = json.loads((ROOT/'build/assets/frontend-source.json').read_text())
pages = ROOT/'build/frontend/native/pages'/(provenance['inputs']['profile'] + '-' + provenance['cache_identity'])
for name in ('title', 'credits', 'pg13', 'end1', 'end2'):
    source = (pages/f'{name}.bin').read_bytes()
    aligned = gray.picture(source)
    before = struct.unpack_from('<256H', source, 32256)
    after = struct.unpack_from('<256H', aligned, 32256)
    for p in range(16):
        assert set(before[p*16:p*16+16]) <= set(after[p*16:p*16+16])
    for y in range(200):
        palette = source[32000+y] & 15
        for x in range(320):
            shift = 4 if x % 2 == 0 else 0
            old = source[y*160+x//2] >> shift & 15
            new = aligned[y*160+x//2] >> shift & 15
            assert before[palette*16+old] == after[palette*16+new], (name, x, y)
            pixels += 1

# The font palette has no duplicate filler color or reserved blank entry.
# Its transparent marker is carried by the glyph encoding, not by RGB.
assert len(set(gray.STEEL)) == 16
assert [gray.STEEL[i] for i in gray.INK] == [n*0x111 for n in range(16)]
assert set(gray.OVERLAY_INK) <= {0, 1, 12, 13, 14, 15}
assert gray.OVERLAY_INK[gray.TRANSPARENT_INK] == gray.TRANSPARENT_INK
assert gray.INK[0] == 0 and gray.INK[15] == 1
assert gray.STEEL == tuple(gray.align_palette(list(gray.STEEL)))
print(json.dumps(dict(result='PASS', arbitrary_palettes=500, picture_pixels=pixels,
                      menu_distinct_colors=len(set(gray.STEEL)),
                      bright_index=gray.INK[15], transparent_index=gray.TRANSPARENT_INK)))
