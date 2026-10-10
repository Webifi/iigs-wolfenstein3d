"""Execute floor loading/probing with unchanged shareware payloads in Emu816.

Disk firmware and progress drawing are fixtures. The linked loader, store-map
translation, block copier and B1 decoder execute natively in the interpreter.
This is not a firmware, media, palette-compositor or complete-game timing test.
"""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct

import episode_directory as directory
from elf import read
from emu816 import Emu
from mkdisk import HDR_BUILD


def indexed_store(source, floors=60):
    """Repeat the ten real payload sets in a larger directory, without new art."""
    target = directory.create(floors)
    extra = len(target) // 512 - 3
    target[1024:1536] = source[1024:1536]
    for offset in range(1088, 1536, 8):
        if struct.unpack_from('<H', target, offset + 6)[0]:
            block = struct.unpack_from('<H', target, offset + 4)[0]
            struct.pack_into('<H', target, offset + 4, block + extra)
    target.extend(source[1536:])
    offsets, counts, steps, rows = [], [], [], []
    for floor in range(floors):
        records, art_steps = directory.floor_records(source, floor % 10)
        offsets.append(len(rows) * 8)
        counts.append(len(records))
        steps.append(art_steps)
        rows.extend((address, flags, block + extra, count)
                    for address, flags, block, count in records)
    directory.finish(target, offsets, counts, steps, rows)
    return target


class Loader(Emu):
    def __init__(self, elf, boot, store, floppy=False):
        super().__init__()
        self.segments, self.symbols = read(elf)
        for segment in read(boot)[0] + self.segments:
            self.load(segment['address'], segment['data'])
        s = self.symbols
        self.store, self.reads, self.progress, self.headers = store, [], [], []
        self.fail_block = None
        self.wr16(s['bootComplete'], 1)
        self.wr16(s['progressExtra'], 0)
        info = s['BOOT_BOOTINFO']
        self.load(info, bytes(100))
        self.wr16(info, 0x4244)
        self.wr8(info + 2, 0x50 if floppy else 0x70)
        self.wr8(info + 18, 1)
        self.wr16(info + 12, 0x1234)
        self.wr16(info + 14, 0x5678)
        # One contiguous firmware volume, with a nonzero physical block offset.
        self.physical_offset = 101
        self.load(info + 36, struct.pack('<4H', 0, len(store) // 512,
                                        self.physical_offset, 1))
        self.progress_hooks = {s[name]: name for name in
                               ('ProgressAdd', 'ProgressRemaining', 'ProgressPlan')}

    def rts(self):
        self.pc = (self.pop16() + 1) & 65535

    def step(self):
        pc = self.pb << 16 | self.pc
        s = self.symbols
        if pc == s['BOOT_readBlock']:
            block = self.rd16(s['BOOT_PD_BLOCK']) - self.physical_offset
            buffer = self.rd16(s['BOOT_PD_BUF'])
            self.reads.append(block)
            assert 0 <= block < len(self.store) // 512, block
            self.c = int(block == self.fail_block)
            if not self.c:
                self.load(buffer, self.store[block * 512:(block + 1) * 512])
            self.x, self.y = 0xdead, 0xbeef
            self.rts()
            return
        if pc == s['BOOT_readHeader2']:
            self.headers.append(self.rd8(s['BOOT_DISKNUM']))
            self.load(s['BOOT_HDR'] + HDR_BUILD, struct.pack('<2H', 0x1234, 0x5678))
            self.c = 0
            self.rts()
            return
        if pc in self.progress_hooks:
            self.progress.append((self.progress_hooks[pc], self.a))
            self.rts()
            self.pb = self.pop8()
            return
        super().step()

    def invoke(self, floor, probe=False, success=True):
        self.reads, self.progress, self.headers = [], [], []
        s = self.symbols
        # Exercise preservation of the caller's direct page, bank and registers.
        self.a, self.x, self.y = floor, 0x1234, 0x5678
        self.d, self.db, self.s, self.mf, self.xf = 0x1100, 2, 0x1fff, 0, 0
        self.wr8(memmap.SHADOW, 0xf5)
        screen = bytes(self.m[memmap.SHR:memmap.RAW_PLANES])
        self.call(0, s['ProbeFloorData' if probe else 'LoadFloorData'],
                  long_return=True, limit=8_000_000)
        assert self.c == int(not success), (floor, probe, self.c)
        assert (self.x, self.y, self.d, self.db, self.s, self.mf, self.xf) == (
            0x1234, 0x5678, 0x1100, 2, 0x1fff, 0, 0)
        assert self.rd8(memmap.SHADOW) == 0xf5
        assert bytes(self.m[memmap.SHR:memmap.RAW_PLANES]) == screen, 'legacy screen writes'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    parser.add_argument('--boot', type=Path, default=Path('build/boot/loader.elf'))
    parser.add_argument('--store', type=Path, default=Path('build/assets/episode.bin'))
    parser.add_argument('--manifest', type=Path, default=Path('build/assets/episode.json'))
    parser.add_argument('--baseline-elf', type=Path)
    parser.add_argument('--out', type=Path, default=Path('build/ep03-loader-check.json'))
    args = parser.parse_args()
    source = args.store.read_bytes()
    assert source[:8] == b'WOLFEP02'
    manifest = json.loads(args.manifest.read_text())
    result = dict(scope=__doc__, loads=[], probes=0, rejected=0)
    stores = [('EP02', source, range(10)),
              ('EP03', indexed_store(source), (0, 9, 10, 20, 59))]
    for kind, store, loaded_floors in stores:
        for floppy in (False, True):
            machine = Loader(args.elf, args.boot, store, floppy)
            floor_count = struct.unpack_from('<H', store, 8)[0]
            for floor in range(floor_count):
                before = bytes(machine.m[0x10000:memmap.FAST_RAM_END])
                machine.invoke(floor, probe=True)
                assert bytes(machine.m[0x10000:memmap.FAST_RAM_END]) == before, 'probe replaced assets'
                assert machine.reads == ([0, 1] if kind == 'EP02' else [0, 1, 3 + floor])
                result['probes'] += 1
            machine.invoke(floor_count, probe=True, success=False)
            result['rejected'] += 1
            # Full copies/decodes need only one firmware-unit type; the other
            # pass checks the unit-dependent directory progress credits.
            if floppy:
                expected = [11] * (2 if kind == 'EP02' else 3)
                machine.invoke(0, probe=True)
                assert [value for name, value in machine.progress if name == 'ProgressAdd'] == expected
                continue
            for floor in loaded_floors:
                machine.invoke(floor)
                records, steps = directory.floor_records(store, floor)
                expected_reads = [0, 1] if kind == 'EP02' else [0, 1, 3 + floor]
                for _, _, block, count in records:
                    expected_reads.extend(range(block, block + count))
                assert machine.reads == expected_reads
                for unit in (u for u in manifest if u['level'] == floor % 10):
                    data = machine.m[unit['address']:unit['address'] + unit['bytes']]
                    assert hashlib.sha256(data).hexdigest() == unit['sha256'], (floor, unit['asset'])
                assert machine.rd16(machine.symbols['loadArtSteps']) == steps
                entry = dict(directory=kind, floor_index=floor, source_floor_index=floor % 10,
                             block_reads=len(machine.reads), progress=machine.progress)
                if kind == 'EP02' and args.baseline_elf:
                    baseline = Loader(args.baseline_elf, args.boot, source)
                    baseline.invoke(floor)
                    assert baseline.reads == machine.reads
                    assert baseline.progress == machine.progress
                    entry['baseline_reads_and_progress_equal'] = True
                result['loads'].append(entry)
                print(kind, 'floor', floor, 'payloads, reads and progress verified', flush=True)
        # A failed second/root page or EP03 record page must unwind cleanly.
        for failed in ((1,) if kind == 'EP02' else (1, 3)):
            machine = Loader(args.elf, args.boot, store)
            machine.fail_block = failed
            machine.invoke(0, probe=True, success=False)
            result['rejected'] += 1
    result['elf_sha256'] = hashlib.sha256(args.elf.read_bytes()).hexdigest()
    result['store_sha256'] = hashlib.sha256(source).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print('Verified', len(result['loads']), 'loads,', result['probes'], 'probes;',
          'firmware, disk exchange and progress drawing were not exercised.')


if __name__ == '__main__':
    main()
