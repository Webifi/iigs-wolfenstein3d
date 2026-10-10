"""Execute active-view weapon code and endpoint setup against source pixels."""
import memmap
import json
import struct
from pathlib import Path
from elf import read
from emu816 import Emu
from build_weapon_masks import source_pixels
from wolfdata import ROOT, PROFILE
from registered_art import ENDPOINT_ORIGINALS
from viewgeometry import SIZES
import pool_cover


def main():
    e = Emu()
    assets = ROOT/'build/assets'
    segments, symbols = read(ROOT/'build/wolf.elf')
    for segment in segments:
        e.load(segment['address'], segment['data'])
    original = bytearray((assets/'sprite-endpoints.bin').read_bytes())
    # View clipping must preserve live coordinate products and their epochs.
    for page in range(128):
        struct.pack_into('<3H', original, page*256+224,
                         page*509 & 65535, page*733 & 65535, 177)
    original = bytes(original)
    e.load(memmap.ENDPOINTS, original)
    e.load(ENDPOINT_ORIGINALS, (assets/'registered-endpoints.bin').read_bytes())
    slots = list(range(65))+list(range(200, 200+len(pool_cover.feature_starts())*2))
    transitions = []
    for old in range(4):
        e.wr16(symbols['endpointView'], 65535)
        for current in (old, *range(4)):
            view = SIZES[current]
            top = (160-view)//2
            e.wr16(symbols['viewTop'], top)
            e.wr16(symbols['viewBottom'], top+view)
            e.d,e.db,e.mf,e.xf,e.s,e.x=0x1000,2,0,0,0x1fff,current*2
            at=symbols['clipSpriteEndpoints'];before=e.cycles
            e.call(at>>16, at&65535, long_return=True, sentinel=memmap.TEST_RETURN)
            expected = bytearray(original)
            for page in range(0, len(original), 256):
                for tex in slots: expected[page+tex] = min(top+view, max(top, original[page+tex]))
            assert e.m[memmap.ENDPOINTS:memmap.ENDPOINTS+len(expected)] == expected, (old,current)
            transitions.append(dict(previous=old, current=current, cycles=e.cycles-before))
    full = (assets/'weapon-mask-full.bin').read_bytes()
    pixels = [[source_pixels(full, pose, vi) for pose in range(20)] for vi in range(4)]
    screen = bytes([0xa7])*32000
    cases = 0
    for floor in range(PROFILE.floors):
        folder = ROOT/f'build/levels/{floor}'
        colors = (folder/'weapon-pixels-00.bin').read_bytes()
        groups = json.loads((folder/'view-weapon-loads.json').read_text())
        for vi,rows in enumerate(groups):
            for row in rows: e.load(row['address'], (ROOT/row['file']).read_bytes())
            for pose in range(20):
                e.load(memmap.SHR,screen)
                expected = bytearray(screen)
                for address, source in pixels[vi][pose].items(): expected[address]=colors[source]
                address = e.rd16(memmap.WEAPON_ENTRIES+pose*4) | e.rd16((memmap.WEAPON_ENTRIES+0x2)+pose*4)<<16
                e.d,e.db,e.mf,e.xf,e.s=0x1000,0xe1,0,0,0x1fff
                e.call(address>>16,address&65535,long_return=True,sentinel=memmap.TEST_RETURN)
                assert e.m[memmap.SHR:memmap.SHR_SCB] == expected, (floor,vi,pose)
                assert (e.db,e.mf,e.xf,e.s)==(0xe1,0,0,0x1fff)
                cases += 1
    result=dict(endpoint_transitions=transitions,endpoint_rows=len(original),weapon_cases=cases,
                expected='source projection and exact converted colors',scope='native routine checks')
    (ROOT/'build/registered-view-check.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Passed',len(transitions),'endpoint transitions and',cases,'native weapon drawings')


if __name__ == '__main__': main()
