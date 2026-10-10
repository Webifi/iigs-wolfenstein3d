"""Execute each full-page palette binding and check its source-derived gray table."""
import memmap
import argparse
import json
from pathlib import Path
import re
import struct
import sys

from elf import read
from emu816 import Emu

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/frontend'))
from gray_pair import pair_table, preview_bytes, words_of


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf')
    args = parser.parse_args()
    segments, symbols = read(args.elf)
    constants = dict((name, int(value)) for name, value in re.findall(
        r'(?m)^LUMP_(\w+)\s+\.equ\s+(\d+)', (ROOT / 'build/gen/menu.inc').read_text()))
    menu = (ROOT / 'build/assets/menu.bin').read_bytes()
    local = '#define CAMPAIGN_COLD_PAGES 1' in (ROOT / 'build/gen/campaign.inc').read_text()
    cases = []
    for name in ('TITLE', 'CREDITS', 'PG13', 'VICTORY',
                 *sorted((n for n in constants if n.startswith('END')), key=lambda n: int(n[3:]))):
        machine = Emu()
        for segment in segments:
            machine.load(segment['address'], segment['data'])
        machine.load(memmap.GRAY_BASE, (ROOT / 'build/assets/graytables.bin').read_bytes())
        if local and name.startswith('END'):
            packet = (ROOT / 'build/assets/gray-local' / (name.lower() + '.bin')).read_bytes()
            address = json.loads((ROOT / 'build/assets/gray-local.json').read_text())['page_address']
            machine.load((memmap.GRAY_PIC+0x100), packet[:64])
            machine.load(address, packet[512:])
        machine.load(memmap.SLOT_REC, bytes([0xcd]) * 64)
        machine.wr16(symbols['streamLump'], constants[name])
        machine.d, machine.db = 0x1100, 0x3f
        pc = symbols['BindFullPicture']
        machine.call(pc >> 16, pc & 65535, long_return=True)
        block = struct.unpack_from('<H', menu, 8 + constants[name] * 8)[0]
        picture = menu[block * 512:block * 512 + 32768]
        for slot in range(16):
            pointer = int.from_bytes(machine.m[memmap.SLOT_REC + slot * 4:(memmap.SLOT_REC+0x4) + slot * 4], 'little')
            colors = words_of(picture[32256 + slot * 32:32288 + slot * 32])
            expected = pair_table(colors) + preview_bytes(colors)
            assert bytes(machine.m[pointer:pointer + 288]) == expected, (
                name, slot, hex(pointer), 'source palette has the wrong gray record')
        cases.append(name.lower())
    print(json.dumps(dict(pages=cases, palette_records=len(cases) * 16,
                          wrong_records=0), indent=2))


if __name__ == '__main__':
    main()
