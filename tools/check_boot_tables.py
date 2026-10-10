"""The boot builds tables instead of loading them (src/iigs/boot_tables.inc,
called from BuildRayPartial). Run that linked code in tools/emu816.py on the memory the boot
loader leaves (the program, the logic bank, tables.bin, the word products) and compare every
built byte with the files the tools write (registered_loads.boot_built and ray-partial.bin).

Usage (cwd = a build stage): python3 tools/check_boot_tables.py
"""
import json
import struct
import sys
import time
from pathlib import Path

import memmap
from elf import read
from emu816 import Emu
from mkdisk import elf_segments
from registered_loads import boot_built
from wolfdata import ROOT

ASSETS = ROOT/'build/assets'


def main():
    # The builders read and write these pairs as one run each.
    assert memmap.SIN_TABLE == memmap.COS_TABLE_END and memmap.SIN_ROWS == memmap.COS_ROWS_END
    assert memmap.THRUST_ROWS == memmap.THRUST_INDEX + 562
    emu = Emu()
    _, symbols = read(ROOT/'build/wolf.elf')
    _, segments = elf_segments(ROOT/'build/wolf.elf')
    for address, data in segments:
        emu.m[address:address + len(data)] = data
    built = boot_built()
    partial = (ASSETS/'ray-partial.bin').read_bytes()
    rows = int((ROOT/'build/gen/ray_partial.inc').read_text().split()[2])
    built.append((memmap.RAY_PARTIAL, partial[:rows*512]))
    expected = []
    for address, source in built:
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        if address == memmap.RAY_FIXED:
            # The boot leaves the view directory zero: the view group loads it before any
            # view is drawn (src/iigs/ui_overlays.s EnsureViewAssets).
            at = memmap.WEIGHT_DIRECTORY - memmap.RAY_FIXED
            data = data[:at] + bytes(memmap.WEIGHT_DIRECTORY_SIZE) + data[at + memmap.WEIGHT_DIRECTORY_SIZE:]
        emu.m[address:address + len(data)] = bytes([0xa5]) * len(data)   # every byte must be written
        expected.append((address, data, source.name if isinstance(source, Path) else 'ray-partial.bin'))
    for address, name in ((memmap.LOGIC_BASE, 'logic.bin'), (memmap.TABLES, 'tables.bin'),
                          (memmap.WORD_PRODUCTS, 'word-products.bin'),
                          (memmap.BOOT_TABLE_SEEDS, 'boot-table-seeds.bin')):
        data = (ASSETS/name).read_bytes()
        emu.m[address:address + len(data)] = data
    emu.s, emu.d, emu.db, emu.mf, emu.xf = 0x1fff, 0x1000, 2, 0, 0
    emu.m[emu.d:emu.d + 256] = bytes(range(256))           # the builders put the direct page back
    page = bytes(emu.m[emu.d:emu.d + 256])
    start = time.time()
    entry = symbols['BuildRayPartial']
    emu.call(entry >> 16, entry & 0xffff, long_return=True, limit=60_000_000)
    assert bytes(emu.m[emu.d:emu.d + 256]) == page, 'the direct page changed'
    assert (emu.d, emu.db, emu.mf, emu.xf) == (0x1000, 2, 0, 0), 'registers not restored'
    report = dict(cycles=emu.cycles, seconds_at_2_8_mhz=round(emu.cycles/2.8e6, 3),
                  host_seconds=round(time.time() - start, 1), tables=[])
    bad = 0
    for address, data, name in expected:
        got = bytes(emu.m[address:address + len(data)])
        wrong = sum(1 for x, y in zip(got, data) if x != y)
        first = next((i for i, (x, y) in enumerate(zip(got, data)) if x != y), None)
        report['tables'].append(dict(file=name, address=hex(address), bytes=len(data), differing=wrong,
                                     first_difference=first))
        bad += wrong
    (ROOT/'build/boot-tables.json').write_text(json.dumps(report, indent=2) + '\n')
    for row in report['tables']:
        print(f"{row['file']:24s} {row['address']} {row['bytes']:6d} B, {row['differing']} differing")
    print(f"boot table build: {emu.cycles} cycles ({emu.cycles/2.8e6:.2f} s at 2.8 MHz)")
    if bad:
        sys.exit('boot tables differ from the tool files')


if __name__ == '__main__':
    main()
