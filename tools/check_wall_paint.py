"""Check wall-band tables, independent settings and preservation of the draw buffer."""
import hashlib
import json
from pathlib import Path
import random
import sys

import argparse
S = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--elf', type=Path, default=S/'build/wolf.elf')
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
from elf import read
from emu816 import Emu
import memmap

elf = args.elf
parts, sy = read(elf)
e = Emu()
for p in parts:
    e.load(p['address'], p['data'])
e.load(memmap.WALL_COLUMNS, b'\xff'*memmap.WALL_COLUMNS_SIZE)
rng = random.Random(31077)
expected = {}
expected_fits = {}
heights = list(range(2,161,2))+list(range(164,641,4))
for i in range(256):
    token = ((i*241) % (memmap.WALL_PAINT_META_SIZE//4))*16
    source = memmap.SHARED_SOURCE+i*128
    if i < 64:
        colors = [0x2233 if j < i else 0x4455 for j in range(64)]
    else:
        colors = []
        while len(colors) < 64:
            colors.extend([rng.randrange(65536)]*rng.randrange(1, 20))
        colors = colors[:64]
    e.load(source, b''.join(c.to_bytes(2, 'little') for c in colors))
    e.wr16(memmap.WALL_LIGHT_POINTERS+token+12, source&65535)
    e.wr16(memmap.WALL_LIGHT_POINTERS+token+14, (source>>16)<<8)
    # Repeated directory entries must share the same descriptor.
    for index in (i, i+256):
        e.wr16(memmap.WALL_COLUMNS+index*4, token)
    runs = []
    a = 0
    for b in range(1, 65):
        if b == 64 or colors[b] != colors[a]:
            runs.append((a, b, colors[a]))
            a = b
    best = max(runs, key=lambda r: (max(0, min(r[1], 48)-max(r[0], 16)), -r[0]))
    expected[memmap.WALL_PAINT_META+token//4] = bytes(best[:2])+best[2].to_bytes(2, 'little')
    length = best[1]-best[0]
    minimum_rows = (12-1)*64//length+1
    minimum_index = next((i*2-2 for i,h in enumerate(heights) if h>=minimum_rows),399)
    expected_fits[memmap.WALL_PAINT_CODE+sy['wallBandMinHeight']-sy['wallBandTemplate']+length*2] = minimum_index.to_bytes(2,'little')

# Uncached keys must not overwrite the adjacent running program.
e.wr16(memmap.WALL_COLUMNS+512*4, memmap.WALL_PAINT_META_SIZE*4)
e.wr16(memmap.WALL_COLUMNS+513*4, 0xfff0)

dispatch = bytes((0x4c, sy['tightLoop']&255, (sy['tightLoop']>>8)&255))
template = bytes(e.m[sy['wallBandTemplate']:sy['wallBandTemplateEnd']])
assert len(template) <= memmap.WALL_PAINT_CODE_SIZE

def refresh(view, buffered, hold, enabled=1):
    e.wr16(sy['viewWidth'], view)
    e.wr16(sy['viewTop'], (160-view)//2)
    e.wr16(sy['viewBottom'], (160-view)//2+view)
    e.wr16(sy['bufferOn'], buffered)
    e.wr16(sy['screenHold'], hold)
    e.wr16(sy['wallPaintOn'], enabled)
    e.d, e.db, e.mf, e.xf, e.s = memmap.UI_DP, 2, 0, 0, 0x1fff
    e.a, e.x, e.y = 0x1357, 0x2468, 0x369a
    e.call(sy['WallPaintRefresh']>>16, sy['WallPaintRefresh']&65535, True)
    assert (e.d, e.db, e.s, e.a, e.x, e.y) == (memmap.UI_DP, 2, 0x1fff, 0x1357, 0x2468, 0x369a)

for view, buffered in ((v,b) for v in (80,107,120,160) for b in (0,1)):
    fill=0x55 if view<120 else 0xaa
    e.load(memmap.DRAW_BUFFER, bytes([fill])*memmap.DRAW_BUFFER_SIZE)
    refresh(view, buffered, 0)
    assert e.m[memmap.DRAW_BUFFER:memmap.DRAW_BUFFER_END] == bytes([fill])*memmap.DRAW_BUFFER_SIZE
    want_template=bytearray(template)
    top=(160-view)//2
    patches={name:((view+1)&~1)-2 for name in ('wallBandGateHeight','wallBandNewHeight','wallBandOldHeight','wallBandSourceHeight')}
    patches.update(wallBandBottom=top+view,wallBandTop=top,wallBandRowStart=top*2)
    for name,value in patches.items():
        at=sy[name]-sy['wallBandTemplate']+1
        want_template[at:at+2]=value.to_bytes(2,'little')
    actual=e.m[memmap.WALL_PAINT_CODE:memmap.WALL_PAINT_CODE+len(template)]
    assert actual == want_template, (view,[(i,a,b) for i,(a,b) in enumerate(zip(actual,want_template)) if a!=b][:8])
    for at, want in expected.items():
        assert e.m[at:at+4] == want, (at, e.m[at:at+4], want)
    for at,want in expected_fits.items():
        assert e.m[at:at+2] == want, (at,e.m[at:at+2],want)
    assert bytes(e.m[sy['tightDispatch']:sy['tightDispatch']+3]) != dispatch

for view, buffered, hold, enabled in ((107,0,0,0),(160,1,0,0),(160,0,1,1),(160,1,1,1)):
    e.load(memmap.DRAW_BUFFER, b'\x5a'*memmap.DRAW_BUFFER_SIZE)
    refresh(view, buffered, hold, enabled)
    assert bytes(e.m[sy['tightDispatch']:sy['tightDispatch']+3]) == dispatch
    assert e.m[memmap.DRAW_BUFFER:memmap.DRAW_BUFFER+memmap.DRAW_BUFFER_SIZE] == b'\x5a'*memmap.DRAW_BUFFER_SIZE

def call(name):
    e.d, e.db, e.mf, e.xf, e.s = memmap.UI_DP, 2, 0, 0, 0x1fff
    e.call(sy[name] >> 16, sy[name] & 65535, True)

assert len({painting + walls for painting in (0, 1) for walls in (2, 4)}) == 4
# Repeated option-state cases need the setters and hooks. The native demo
# and menu tests exercise the full scaler rewrite when buffering changes.
e.wr8(sy['bufferPatchAll'], 0x6b)
settings = []
assert 'WallPaintUpgrade' not in sy
for painting in (0,1,255):
    for walls in (4,2,255):
        for kind in (1,2,3):
            e.wr8(memmap.SETTINGS_IN+29, painting)
            e.wr8(memmap.SETTINGS_IN+58, walls)
            e.wr16(sy['viewTestKind'], kind)
            call('WallPaintLoad')
            enabled = int(kind>=2) if walls==255 else walls>>2
            assert e.rd16(sy['wallPaintOn']) == enabled
            assert e.rd16(sy['bufferOn']) == (1 if painting==1 else 0)
            call('WallPaintStore')
            assert e.rd8(memmap.SETTINGS_IN+58) == walls
            assert e.rd8(memmap.SETTINGS_IN+29) == painting
            for _ in range(2):
                old_buffer = e.rd16(sy['bufferOn'])
                old_walls = e.rd16(sy['wallPaintOn'])
                call('WallPaintToggle')
                assert e.rd16(sy['wallPaintOn']) == 1-old_walls
                assert e.rd8(memmap.SETTINGS_IN+58) == 4-2*old_walls
                assert e.rd16(sy['bufferOn']) == old_buffer
                call('PaintingToggle')
                assert e.rd16(sy['bufferOn']) == 1-old_buffer
                assert e.rd8(memmap.SETTINGS_IN+29) == 1-old_buffer
                assert e.rd16(sy['wallPaintOn']) == 1-old_walls
            settings.append(dict(painting=painting,walls=walls,kind=kind))

result = dict(settings=settings, columns=256, repeated_directory_entries=256, buffer_preservation_checks=8,
              views=[80,107,120,160], minimum_height_lengths=len(expected_fits),
              disabled_cases=4, template_bytes=len(template),
              elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
args.out.write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
