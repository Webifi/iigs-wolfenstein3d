"""World palette slots stay identical on every row; distance is per column."""
import json
import struct
from wolfdata import ROOT
from buildconfig import config
from viewgeometry import SIZES

cfg=config();meta=json.loads((ROOT/'build/assets/map.json').read_text());colors=meta['palette']
# Palettes 0 and 1 are the base view and id status art. Slots 8/11 keep the
# frame fixed on view rows; the row's palette covers its whole 320-pixel width.
palettes=[colors]
for step in range(8):
    palettes.append(colors)
raw=bytearray()
for pal in palettes:
    for r,g,b in pal:raw+=struct.pack('<H',(r//17<<8)|(g//17<<4)|(b//17))
(ROOT/'build/assets/shading.bin').write_bytes(raw)
# Light is per column (pre-shaded art); every view row uses palette 0.
lines=[' .section gamedata, data, root']
(ROOT/'build/gen/shading.inc').write_text('\n'.join(lines)+'\n')
(ROOT/'build/assets/shading.json').write_text(json.dumps(dict(palettes=palettes,steps=[0,4,6,8],horizon_gain=.68))+'\n')
