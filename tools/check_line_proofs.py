"""Compare generated blocked-sight lookups with the linked exact map walker."""
import memmap
import json
import random
import struct
from pathlib import Path
from elf import read
from emu816 import Emu
from line_proofs import geometry, DESCRIPTOR, SIGNATURE
from wolfdata import ROOT, PROFILE


def check():
    e = Emu()
    sections, sy = read(ROOT/'build/wolf.elf')
    for section in sections:
        e.load(section['address'], section['data'])
    e.load(memmap.WORD_PRODUCTS, (ROOT/'build/assets/word-products.bin').read_bytes())
    e.load(memmap.RAY_PRODUCTS_DIRECTORY, (ROOT/'build/assets/ray-products-directory.bin').read_bytes())
    rng = random.Random(65816)
    results = []

    def invoke(name, x=0, long_return=False):
        e.d, e.db, e.mf, e.xf, e.s, e.x = 0x1100, 0x30, 0, 0, 0x1fff, x
        pc = sy[name]
        e.call(pc >> 16, pc & 65535, long_return=long_return, sentinel=(memmap.REGISTERED_LOGIC_SPARE+0xfe0))
        return bool(e.c)

    for floor in range(PROFILE.floors):
        folder = ROOT/f'build/levels/{floor}'
        proof = json.loads((folder/'line-proofs.json').read_text())
        logic = (folder/'logic.bin').read_bytes()
        e.load(memmap.LOGIC_BASE, logic)
        bank, tag = struct.unpack_from('<HH', logic, DESCRIPTOR)
        assert (bank, tag) == (proof['metadata_bank'], SIGNATURE if proof['enabled'] else 0)
        for row in proof['loads']:
            e.load(row['address'], (ROOT/row['file']).read_bytes())
        raw = (folder/'source-planes.bin').read_bytes()
        cells, _ = geometry(raw)
        tilemap = bytearray(4096)
        for x in range(64):
            for y in range(64):
                tile = raw[y*64+x]
                tilemap[x*64+y] = tile if 0 < tile < 64 else (128+(y*64+x)%64 if 90 <= tile <= 101 else 0)
        e.load(memmap.LOGIC_BASE+sy['TILEMAP'], tilemap)
        if proof['enabled']:
            for number, (x, y) in enumerate(cells, 1):
                cell = x*64+y
                assert e.rd16(bank*65536+0x4000+cell*2) == number//8
                assert e.rd16(bank*65536+0x6000+cell*2) == 1 << (number & 7)
                pointer = e.rd16(bank*65536+cell*4) | e.rd16(bank*65536+cell*4+2) << 16
                assert any(r['address'] <= pointer and pointer+proof['stride'] < r['address']+r['bytes']
                           for r in proof['loads'][:-1])
        if floor == 0 and proof['enabled']:
            # Relocate and poison the old directory to catch fixed-bank loads.
            metadata = bytes(e.m[bank*65536:bank*65536+32768])
            e.load(0x400000, metadata)
            e.load(bank*65536, bytes(32768))
            e.wr16(memmap.LOGIC_BASE+DESCRIPTOR, 0x40)
        invoke('InitLineRegions')
        for setting in range(3):
            # The proof excludes every moving wall source; opening all doors
            # and removing those walls tests the most permissive live geometry.
            for x, y in cells:
                cell = x*64+y
                original = tilemap[cell]
                value = 0 if setting == 0 else original
                if setting == 2 and not value and rng.random() < .015:
                    value = 1
                e.m[memmap.LOGIC_BASE+sy['TILEMAP']+cell] = value
            for door in range(64):
                e.wr16(memmap.LOGIC_BASE+sy['DOORPOS']+door*2, (0, 32768, 65535)[setting])
            invoke('RecountLineRegions', long_return=True)
            for case in range(100):
                points = []
                for obj in (sy['OBJLIST']+64, sy['OBJLIST']):
                    tile = rng.choice(cells)
                    coordinates = [n*256+rng.randrange(256) for n in tile]
                    points.extend(coordinates)
                    for axis, value in zip(('X', 'Y'), coordinates):
                        e.wr16(memmap.LOGIC_BASE+obj+sy['O_'+axis], (value << 8) & 65535)
                        e.wr16(memmap.LOGIC_BASE+obj+sy['O_'+axis]+2, value >> 8)
                        e.wr16(memmap.LOGIC_BASE+obj+sy['O_TILE'+axis], value >> 8)
                e.wr16(memmap.LOGIC_BASE+sy['V_plux'], points[2])
                e.wr16(memmap.LOGIC_BASE+sy['V_pluy'], points[3])
                original = invoke('lineOriginal', sy['OBJLIST']+64)
                accelerated = invoke('CheckLine', sy['OBJLIST']+64)
                assert original == accelerated, (floor, setting, case, points)
        results.append(dict(floor=floor, enabled=proof['enabled'], comparisons=300))
    return dict(floors=results, comparisons=300*len(results),
                checks='linked 65816 exact fallback, metadata relocation, floor invalidation, doors and moving walls')


if __name__ == '__main__':
    result = check()
    (ROOT/'build/line-proofs-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result['comparisons'], 'native arithmetic comparisons passed')
