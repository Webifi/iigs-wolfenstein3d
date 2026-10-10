"""Execute linked logical-block translation, including the 32 MiB crossing.

Only firmware reads and drive selection are fixtures. Translation, record
flag decoding and progress-size arithmetic execute as assembled 65816 code.
"""
import json
import struct
from pathlib import Path

from elf import read
from emu816 import Emu


class MissingBlock(Exception):
    pass


class Reader(Emu):
    def __init__(self):
        super().__init__()
        segments, self.sym = read('build/wolf.elf')
        for segment in segments:
            self.load(segment['address'], segment['data'])
        self.selected = None
        self.reads = []

    def step(self):
        pc = self.pb << 16 | self.pc
        if pc == self.sym['selectDisk']:
            self.selected = self.rd8(self.sym['BOOT_DISKNUM'])
            self.pc = (self.pop16()+1) & 65535
            return
        if pc == self.sym['BOOT_readBlock']:
            self.reads.append((self.selected, self.rd16(self.sym['BOOT_PD_BLOCK'])))
            self.c = 0
            self.pc = (self.pop16()+1) & 65535
            return
        if pc == self.sym['badFloor']:
            raise MissingBlock()
        super().step()

    def reset(self):
        self.db, self.d, self.mf, self.xf, self.s = 0, 0, 0, 0, 0x1fff
        self.reads = []


def main():
    r = Reader()
    s = r.sym
    runs = [(0, 60000, 2048, 1), (60000, 5536, 32, 2), (65536, 16000, 5568, 2)]
    table = bytearray(64)
    for i, (start, count, physical, disk) in enumerate(runs):
        struct.pack_into('<4H', table, i*8, start & 65535, count, physical,
                         disk | ((start >> 16) << 8))
    r.load(s['BOOT_BOOTINFO']+36, table)
    r.wr16(s['loadProbe'], 0x8000)
    r.wr16(s['LV_BUFFER'], 0x7000)
    checked = 0
    blocks = {0, 1, 59999, 60000, 60001, 65534, 65535, 65536, 65537, 81535}
    blocks.update(range(0, 81536, 127))
    for probe in (False, True):
        r.wr16(s['probeChecking'], int(probe))
        for block in sorted(blocks):
            r.reset()
            r.wr16(s['LV_BLOCK'], block & 65535)
            r.wr16(s['LV_BLOCK_HI'], block >> 16)
            r.call(0, s['storeBlock'])
            start, count, physical, disk = next(row for row in runs if row[0] <= block < row[0]+row[1])
            assert r.selected == disk
            assert r.rd16(s['BOOT_PD_BLOCK']) == physical+block-start
            assert r.reads == ([] if probe else [(disk, physical+block-start)])
            checked += 1
    for block in (81536, 100000, 131071):
        r.reset()
        r.wr16(s['LV_BLOCK'], block & 65535)
        r.wr16(s['LV_BLOCK_HI'], block >> 16)
        try:
            r.call(0, s['storeBlock'])
        except MissingBlock:
            pass
        else:
            raise AssertionError(('accepted unmapped block', block))
    for wide in (0, 1):
        for high in (0, 1):
            for compressed in (0, 1):
                for kib in (0, 1, 32, 63):
                    flags = 0x20 | compressed*0x100 | kib*0x200 | high*0x8000
                    r.reset()
                    r.wr16(s['loadWide'], wide)
                    r.x = 0xbc00
                    r.wr16(0xbc02, flags)
                    r.call(0, s['recordBlockHigh'])
                    assert r.rd16(s['LV_BLOCK_HI']) == wide*high
                    # Stop after the native record's decode-work calculation.
                    r.reset()
                    r.y = 0xbc00
                    r.pb, r.pc = 0, s['countUnits']
                    while r.pc != s['countDecodeReady']:
                        r.step()
                    expected = ((kib*2 or 128) if compressed else 0) if wide else (flags >> 8) & 254
                    assert r.a == expected, (wide, flags, r.a, expected)
                    checked += 1
    for fast in (0, 1):
        for packed in (0, 1):
            for codec in (0, 1):
                for units in (0, 1, 16, 31):
                    flags=0x22 | packed*0x100 | units*0x200 | codec*0x4000 | 0x8000
                    r.reset();r.wr16(s['loadMixed'],fast);r.y=0xbc00;r.wr16(0xbc02,flags)
                    r.call(0,s['DecodeWorkSize'])
                    expected=(((flags>>8)&(0x3e if fast else 0x7e))*(2 if fast else 1) or 128) if packed else 0
                    assert r.a==expected,(fast,flags,r.a,expected)
                    checked+=1
    result = dict(native_cases=checked, rejected_unmapped=3,
                  logical_crossing=65536, fixtures=['drive selection', 'firmware reads'])
    Path('build/store-block-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)


if __name__ == '__main__':
    main()
