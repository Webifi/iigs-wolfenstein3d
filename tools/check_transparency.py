"""Check both resident sprite modes and the assembled cold switch on every floor.

The interpreter verifies command bytes, source colors, header restoration and
register preservation. It does not replace native pause/resume or timing tests.
"""
import argparse
import json
import struct
from pathlib import Path

import memmap
from elf import read
from emu816 import Emu
from fixed_art import fast_frame, fast_columns_for
from wolfdata import ROOT, PROFILE


def invoke(emu, symbols, name, a=0, long_return=True):
    emu.a, emu.x, emu.y = a, 0x1234, 0x5678
    emu.d, emu.db, emu.s = 0x1100, 2, 0x1fff
    emu.setp(0x83)
    state = (emu.a, emu.x, emu.y, emu.d, emu.db, emu.s, emu.getp())
    before = emu.cycles
    address = symbols[name]
    emu.call(address >> 16, address & 65535, long_return=long_return)
    if name == 'EnsureViewAssets':
        assert state == (emu.a, emu.x, emu.y, emu.d, emu.db, emu.s, emu.getp()), name
    return emu.cycles - before


def check_columns(emu, frame, columns, lights):
    bank = emu.rd16(frame + 196) << 16
    for x, column in enumerate(columns):
        at = bank + emu.rd16(frame + x * 2)
        for top, bottom, raw in sorted(column, reverse=True):
            assert emu.rd16(at) == top | bottom << 8, (hex(frame), x, top, bottom)
            for light in range(4):
                address = (emu.rd8(frame + 198 + light) << 16) + emu.rd16(at + 2 + 2 * light)
                if top < 200:
                    address += top * 2
                expected = bytes(v for c in raw for v in lights[light][c])
                assert bytes(emu.m[address:address + len(expected)]) == expected, (hex(frame), x, light)
            at += 10
        assert emu.rd16(at) == 0, (hex(frame), x, 'extra command')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=ROOT/'build/wolf.elf')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    segments, symbols = read(args.elf)
    emu = Emu()
    for segment in segments:
        emu.load(segment['address'], segment['data'])
    results = []
    for floor in range(PROFILE.floors):
        folder = ROOT/f'build/levels/{floor}'
        rows = json.loads((folder/'registered-art-loads.json').read_text())
        original = [(r['address'], (folder/r['file']).read_bytes()) for r in rows]
        for address, data in original:
            emu.load(address, data)
        frames = json.loads((folder/'sprites.json').read_text())
        offsets = (folder/'spriteFrame.bin').read_bytes()
        lights = json.loads((folder/'pool-colors.json').read_text())
        emu.wr16(symbols['levelIndex'], floor)
        emu.wr16(symbols['overlayWeightView'], 0)
        emu.wr16(symbols['overlayWeaponKey'], floor * 4)
        emu.wr16(symbols['overlayGameCold'], 0)
        timings = []
        for mode in (0, 1, 0):
            emu.wr16(symbols['fastTransparencyOn'], mode)
            timings.append(invoke(emu, symbols, 'EnsureViewAssets'))
            assert emu.rd16(memmap.SPRITE_QUALITY_STATE + 4) == mode
            for key, frame in frames.items():
                if frame['weapon']:
                    continue
                shape = int(key)
                fast = fast_frame(frame.get('mirror_of', shape)) if mode else None
                art, columns = fast if fast else (frame, frame['columns'])
                if fast:
                    columns = fast_columns_for(frame.get('mirror_of', shape), columns, frame['columns'])
                if fast and 'mirror_of' in frame:
                    art = dict(art, left=63-art['right'], right=63-art['left'])
                    columns = columns[::-1]
                address = memmap.SPRITE_CMDS + struct.unpack_from('<H', offsets, shape * 2)[0]
                assert tuple(emu.m[address + 128:address + 130]) == (art['left'], art['right'])
                check_columns(emu, address, columns, lights)
        for address, data in original:
            assert bytes(emu.m[address:address + len(data)]) == data, (floor, hex(address), 'Off restoration')
        results.append(dict(floor=floor, cycles=timings))
        print(f'floor {floor + 1}: original, fast and restored commands/colors exact; cycles {timings}', flush=True)
    for saved, expected in ((0, 0), (1, 1)):
        emu.wr8(memmap.SETTINGS_IN + 30, saved)
        emu.wr8(memmap.SETTINGS_IN + 31, 0xa5)
        invoke(emu, symbols, 'TransparencyLoad')
        assert emu.rd16(symbols['fastTransparencyOn']) == expected
        invoke(emu, symbols, 'TransparencyStore')
        assert emu.rd8(memmap.SETTINGS_IN + 30) == expected
        assert emu.rd8(memmap.SETTINGS_IN + 31) == 0xa5
    args.out.write_text(json.dumps(dict(profile=PROFILE.key, floors=results, settings='passed'), indent=2)+'\n')


if __name__ == '__main__':
    main()
