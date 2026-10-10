"""Check full weapon draws and every pose transition against original scalers.

The oracle reads the frozen baseline's actual LDA operands, original full
weapon records, and each floor's original serialized pixels. It does not
use the drawer generator's sampling, pairing, or grouping functions.
"""
import memmap
import argparse
import json
from pathlib import Path
import struct

from check_sight_cast import image
from elf import read
from emu816 import Emu
from viewgeometry import SIZES, HEIGHTS, weapon_height

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline-elf', required=True, type=Path)
    args = ap.parse_args()
    e, s = image(ROOT/'build/wolf.elf')
    baseline = Emu()
    for segment in read(args.baseline_elf)[0]:
        baseline.load(segment['address'], segment['data'])
    for part in json.loads((ROOT/'build/assets/weapon-drawer-loads.json').read_text()):
        e.load(part['address'], (ROOT/'build/assets'/part['file']).read_bytes())
    masks = (ROOT/'build/assets/weapon-mask-full.bin').read_bytes()
    compact = (ROOT/'build/assets/weapon-mask.bin').read_bytes()
    rows = (ROOT/'build/assets/rowcode.bin').read_bytes()
    background = bytes((n*73+19) & 255 for n in range(32000))
    results = []
    screen = memmap.SHR  # Native checks also verify complete display integration.
    transition_cases = 0

    def call(name):
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        before = e.cycles
        address = s[name]
        e.call(address >> 16, address & 65535, long_return=True, sentinel=memmap.TEST_RETURN)
        assert (e.db, e.mf, e.xf, e.s) == (2, 0, 0, 0x1fff), name
        return e.cycles-before

    for floor in (9, 0, 8, 1, 7, 2, 6, 3, 5, 4):
        palette = (ROOT/f'build/levels/{floor}/weapon-palette.bin').read_bytes()
        e.load(memmap.WEAPON_PALETTE, palette)
        patch_cycles = call('patchWeaponPalette')
        source = (ROOT/f'build/levels/{floor}/weapon-pixels-0.bin').read_bytes()
        cases = []
        for vi, view in enumerate(SIZES):
            height = weapon_height(view)
            hi = HEIGHTS.index(height)
            width, left = height//2, (view-height//2)//2
            screen_left = (160-view)//2
            pictures, directories = [], []
            for pose in range(20):
                expected = bytearray(background)
                directory = struct.unpack_from('<H', masks, 2*(pose*4+vi))[0]
                new_directory = struct.unpack_from('<H', compact, 2*(pose*4+vi))[0]
                for col in range(left-2, left+width+2):
                    pointer = struct.unpack_from('<H', masks, directory+2*col)[0]
                    new_pointer = struct.unpack_from('<H', compact, new_directory+2*col)[0]
                    assert masks[pointer:pointer+2] == compact[new_pointer:new_pointer+2]
                    for n in range(masks[pointer]):
                        bounds, _, tex, banks, _ = struct.unpack_from('<5H', masks, pointer+2+n*10)
                        assert struct.unpack_from('<H', compact, new_pointer+2+n*2)[0] == bounds
                        for y in range(bounds & 255, bounds >> 8):
                            code = struct.unpack_from('<H', rows, hi*322+2*y)[0] | ((banks & 255) << 16)
                            assert baseline.rd8(code) == 0xb9
                            offset = ((tex+baseline.rd16(code+1)) & 65535)-0xc800
                            expected[y*160+screen_left+col] = source[offset]
                    assert compact[new_pointer+2+2*masks[pointer]:new_pointer+4+2*masks[pointer]] == b'\0\0'
                pictures.append(expected)
                directories.append(new_directory)
                e.load(screen, background)
                e.wr16(0x1000+s['FIRST'], 1)
                e.wr16(s['levelState'], 0)
                e.wr16(s['weaponMaskTable'], new_directory)
                # FIRST must bypass even a matching transition directory.
                e.wr16(s['oldWeaponMaskTable'], struct.unpack_from(
                    '<H', compact, 2*(((pose-1) % 20)*4+vi))[0])
                e.wr16(s['weapon'], pose//5)
                e.wr16(s['weaponFrame'], pose % 5)
                e.wr16(s['weaponViewIndex'], vi*2)
                cycles = call('drawWeaponPose')
                actual = e.m[screen:screen+32000]
                assert actual == expected, (floor, view, pose, sum(a != b for a,b in zip(actual,expected)))
                cases.append(dict(view=view*2, pose=pose, cycles=cycles))
            for pose in range(20):
                # The full-draw oracle above also identifies the new silhouette;
                # use the original coverage records, including background-color texels.
                covered = []
                directory = struct.unpack_from('<H', masks, 2*(pose*4+vi))[0]
                for col in range(left-2, left+width+2):
                    pointer = struct.unpack_from('<H', masks, directory+2*col)[0]
                    for n in range(masks[pointer]):
                        bounds = struct.unpack_from('<H', masks, pointer+2+n*10)[0]
                        covered.extend(y*160+screen_left+col
                                       for y in range(bounds & 255, bounds >> 8))
                for previous in range(20):
                    expected = bytearray(pictures[previous])
                    for at in covered:
                        expected[at] = pictures[pose][at]
                    e.load(screen, pictures[previous])
                    e.wr16(0x1000+s['FIRST'], 0)
                    e.wr16(s['weaponMaskTable'], directories[pose])
                    e.wr16(s['oldWeaponMaskTable'], directories[previous])
                    e.wr16(s['weapon'], pose//5)
                    e.wr16(s['weaponFrame'], pose % 5)
                    call('drawWeaponPose')
                    actual = e.m[screen:screen+32000]
                    assert actual == expected, (floor, view, previous, pose,
                                                sum(a != b for a,b in zip(actual,expected)))
                    transition_cases += 1
        # Unchanged and absent weapons must leave every background byte intact.
        e.load(screen, background)
        e.wr16(0x1000+s['FIRST'], 0)
        e.wr16(s['weaponMaskTable'], 1234)
        e.wr16(s['oldWeaponMaskTable'], 1234)
        call('drawWeaponPose')
        assert e.m[screen:screen+32000] == background
        e.wr16(0x1000+s['FIRST'], 1)
        e.wr16(s['levelState'], 1)
        call('drawWeaponPose')
        assert e.m[screen:screen+32000] == background
        results.append(dict(floor=floor, palette_patch_cycles=patch_cycles, cases=cases))
    out = ROOT/'build/weapon-drawer-check.json'
    out.write_text(json.dumps(dict(cases=800, transition_cases=transition_cases,
                                  compared_bytes=(800+transition_cases)*32000, differences=0,
                                  scope=__doc__, floors=results), indent=2)+'\n')
    print('800 full draws and', transition_cases, 'transitions exact; palette update',
          results[0]['palette_patch_cycles'], 'nominal cycles')


if __name__ == '__main__':
    main()
