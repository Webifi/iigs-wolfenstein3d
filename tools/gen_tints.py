"""Prebuild WL_PLAY's six damage and three pickup palettes for every floor. The tints of palette 0 are one
record of 10 levels for each floor; those of the 12 status palettes are one record of 10 levels for all floors."""
import json
import struct
from wolfdata import ROOT, PROFILE
from buildconfig import config

ui=[[[round(v/17)*17 for v in c] for c in pal] for pal in json.loads((ROOT/'build/assets/ui.json').read_text())['palettes']]
out=ROOT/'build/palettes'
TINTS=[((0,0,0),0,1)]+[((256,0,0),n,8) for n in range(1,7)]+[((256,248,0),n,20) for n in range(1,4)]
FLOOR_BYTES=len(TINTS)*32
HUD_BYTES=len(TINTS)*len(ui)*32
TINTS_ADDRESS=0x9000
def palette(colors, target, step, divisor):
    raw=bytearray()
    from shared_gray import word
    for slot,color in enumerate(colors):
        c=[max(0,min(15,round((v+int((t-v)*step/divisor))/17)))
           for v,t in zip(color,target)]
        raw+=struct.pack('<H',word(color) if slot>=12 else (c[0]<<8)|(c[1]<<4)|c[2])
    return raw

all_floors=bytearray()
floor_count = len(PROFILE.campaign.floors)
for floor in range(1,floor_count+1):
    colors=json.loads((out/f'{floor-1}.json').read_text())['palette']
    raw=bytearray()
    for target,step,divisor in TINTS:
        raw+=palette(colors,target,step,divisor)
    assert len(raw)==FLOOR_BYTES
    (out/f'tints-{floor}.bin').write_bytes(raw)
    all_floors+=raw
hud=bytearray()
for target,step,divisor in TINTS:
    for pal in ui:
        hud+=palette(pal,target,step,divisor)
assert len(hud)==HUD_BYTES
(out/'tints-status.bin').write_bytes(hud)
selected = config()['floor']-1
resident_floors = all_floors[selected*FLOOR_BYTES:(selected+1)*FLOOR_BYTES]
(ROOT/'build/assets/tints.bin').write_bytes(resident_floors+hud)
hud_base=TINTS_ADDRESS+len(resident_floors)
lines=[' .section gamedata, data, root',
       'damageTint: .byte '+','.join(str(min(6,n//10+1)) if n else '0' for n in range(256)),
       'bonusTint: .byte '+','.join(str(6+min(3,n//6+1)) if n else '0' for n in range(256)),
       'tintFloorOffsets: .word '+','.join(str(0) for n in range(floor_count)),
       'tintStatusSource: .word '+','.join(str(hud_base+n*len(ui)*32) for n in range(len(TINTS)))]
(ROOT/'build/gen/tints.inc').write_text('\n'.join(lines)+'\n')
