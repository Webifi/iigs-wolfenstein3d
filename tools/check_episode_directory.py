"""Check ten- and sixty-floor directories, optionally executing the 65816 reader.

The native fixture supplies disk blocks; it does not test firmware or media I/O.
"""
import argparse
from pathlib import Path
import struct
import unittest

import episode_directory as directory

ELF = None


def fixture(floors):
    counts = [1 + (n * 7) % 11 for n in range(floors)]
    if floors != 10:
        counts[-1] = 64
    offsets, records = [], []
    for floor, count in enumerate(counts):
        offsets.append(len(records) * 8)
        records.extend((n * 512, 0x20 + floor % 16, 128 + floor * 64 + n, 1)
                       for n in range(count))
    steps = [(n * 17) % 256 for n in range(floors)]
    data = directory.create(floors)
    directory.finish(data, offsets, counts, steps, records)
    return data, offsets, counts, steps, records


class DirectoryChecks(unittest.TestCase):
    def test_every_floor_and_last_full_record_page(self):
        for floors in (1, 10, 21, 60):
            data, offsets, counts, steps, records = fixture(floors)
            for floor in range(floors):
                start = offsets[floor] // 8
                self.assertEqual(directory.floor_records(data, floor),
                                 (records[start:start + counts[floor]], steps[floor]))
            with self.assertRaises(ValueError):
                directory.floor_records(data, floors)

    def test_shareware_layout_remains_identical(self):
        data, offsets, counts, steps, records = fixture(10)
        previous = bytearray(1536)
        previous[:8] = b'WOLFEP02'
        struct.pack_into('<HH', previous, 8, 10, len(records))
        struct.pack_into('<20H', previous, 12, *(offsets + counts))
        previous[52:62] = bytes(steps)
        for n, row in enumerate(records):
            struct.pack_into('<4H', previous, 64 + n * 8, *row)
        self.assertEqual(data, previous)

    def test_rejects_overflow_and_bad_pages(self):
        data, offsets, counts, steps, records = fixture(60)
        for where, value in ((12, 2), (12, 63), (14, 0), (14, 65), (16, 256)):
            changed = bytearray(data)
            struct.pack_into('<H', changed, where, value)
            with self.assertRaises(ValueError):
                directory.floor_records(changed, 0)
        counts[-1] = 65
        with self.assertRaises(ValueError):
            directory.finish(data, offsets, counts, steps, records)

    def test_rejects_invalid_record_offsets(self):
        data, offsets, counts, steps, records = fixture(60)
        offsets[0] = -8
        with self.assertRaises(ValueError):
            directory.finish(data, offsets, counts, steps, records)
        data, *_ = fixture(10)
        struct.pack_into('<H', data, 12, 1)
        with self.assertRaises(ValueError):
            directory.floor_records(data, 0)

    def test_native_selects_each_record_page_with_existing_scratch(self):
        if not ELF:
            self.skipTest('pass --elf to execute the native reader')
        from elf import read
        from emu816 import Emu
        segments, symbols = read(ELF)

        class Reader(Emu):
            def step(self):
                if (self.pb << 16 | self.pc) == symbols['directoryBlock']:
                    page = self.rd16(symbols['LV_BLOCK'])
                    buffer = self.rd16(symbols['LV_BUFFER'])
                    self.reads.append(page)
                    self.asserted_buffer = buffer
                    self.load(buffer, self.store[page * 512:(page + 1) * 512])
                    self.pc = (self.pop16() + 1) & 65535
                    self.x, self.y = 0xdead, 0xbeef
                    return
                super().step()

        machine = Reader()
        for segment in segments:
            machine.load(segment['address'], segment['data'])
        for floors in (1, 10, 21, 60):
            machine.store, offsets, counts, steps, records = fixture(floors)
            for floor in range(floors):
                machine.load(0xbc00, machine.store[:1024])
                machine.load(0xc000, bytes([0xa5]) * 512)
                machine.wr16(symbols['loadFloor'], floor)
                machine.d = machine.db = machine.mf = machine.xf = 0
                machine.s = 0x1fff
                machine.reads = []
                machine.call(0, symbols['selectFloorDirectory'], sentinel=0x7f00)
                self.assertEqual(machine.c, 0)
                pointer = machine.rd16(symbols['LV_RECORD'])
                self.assertEqual(machine.rd16(symbols['LV_LEFT']), counts[floor])
                self.assertEqual(machine.rd16(symbols['loadArtSteps']), steps[floor])
                actual = [struct.unpack_from('<4H', machine.m, pointer + n * 8)
                          for n in range(counts[floor])]
                start = offsets[floor] // 8
                self.assertEqual(actual, records[start:start + counts[floor]])
                self.assertEqual(machine.m[0xc000:0xc200], bytes([0xa5]) * 512)
                self.assertEqual(machine.reads, [] if floors == 10 else [3 + floor])
                if machine.reads:
                    self.assertEqual(machine.asserted_buffer, 0xbe00)

        cases = [(60, offset, value, 0) for offset, value in (
            (8, 0), (8, 61), (6, 0), (12, 2), (12, 63),
            (14, 0), (14, 65), (16, 256))]
        cases += [(10, offset, value, 0) for offset, value in (
            (8, 9), (12, 1), (12, 960))]
        cases += [(count, 8, count, count) for count in (1, 10, 21, 60)]
        cases += [(60, 8, 60, 65535)]
        for floors, offset, value, floor in cases:
            machine.store, *_ = fixture(floors)
            struct.pack_into('<H', machine.store, offset, value)
            machine.load(0xbc00, machine.store[:1024])
            machine.wr16(symbols['loadFloor'], floor)
            machine.d = machine.db = machine.mf = machine.xf = 0
            machine.s, machine.reads = 0x1fff, []
            machine.call(0, symbols['selectFloorDirectory'], sentinel=0x7f00)
            self.assertEqual(machine.c, 1, (floors, offset, value, floor))
            self.assertEqual(machine.reads, [])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path)
    args, remaining = parser.parse_known_args()
    ELF = args.elf
    unittest.main(argv=[__file__] + remaining)
