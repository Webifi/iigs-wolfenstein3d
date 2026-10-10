"""Execute sprite command selection after a transparent owner changes banks.

Synthetic columns isolate the cache lifetime; full MAME comparisons still
check actual floors, complete pictures and frame costs.
"""
import memmap
import json
from pathlib import Path
from elf import read
from emu816 import Emu


def execute(e, start, stop):
    e.pb, e.pc = start >> 16, start & 65535
    for _ in range(1000):
        if e.pb << 16 | e.pc == stop:
            return
        e.step()
    raise AssertionError(('selection did not finish', hex(e.pb << 16 | e.pc)))


def main():
    segments, s = read('build/wolf.elf')
    e = Emu()
    for segment in segments:
        e.load(segment['address'], segment['data'])
    checks = 0
    for bank in (0, 1, 0x30, 0x41):
        for intervening in (0, 1, 8, 0x32, 0x41):
            if bank == intervening:
                continue
            # Record 64 retains its scale/light cache. Record 80 has an empty
            # source column in another bank and must leave that cache intact.
            for rec, header, command_bank, pointer in (
                    (64, 0x200, bank, 0xb100), (80, 0x400, intervening, 0xb200)):
                e.wr16(s['SPR_RECORDS']+rec+14, 3)
                e.wr16(s['ownerInfo']+rec+10, header)
                e.wr16(s['ownerInfo']+rec+12, command_bank)
                e.wr16(memmap.SPRITE_CMDS+header+10, pointer)
                e.wr16(command_bank*65536+pointer, 0)
            e.wr8((memmap.HORIZONTAL+0x3), 5)
            for branch, stop in (('fastInfo', 'fastRun'), ('lightRecord', 'lightRun')):
                e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
                e.wr16(0x102e, 0)  # COL
                e.wr16(0x1030, 0)  # SCAN
                e.wr16(0x1038, 0xff00)  # transparent owner continuation
                e.wr16(0x10fa, 64)  # cached scale/light record
                e.x = 80
                execute(e, s['spriteOwnerNear'], memmap.CALL_SENTINEL_LOW)
                assert e.rd16(0x10fa) == 64
                assert e.rd8(0x1070) == intervening
                e.wr16(s['heightIndex'], 0)
                e.wr16(0x102c, 0)  # cached wall height
                e.wr16(0x10a2, 0x3456)  # cached owner row-code base
                e.wr16(0x1082, 0x1704)  # cached art/scaler banks
                e.wr16(0x10ea, 6)  # cached light-word offset
                e.x = 64
                execute(e, s[branch], s[stop])
                assert e.rd16(0x106e) == 0xb100
                assert e.rd8(0x1070) == bank, (branch, bank, intervening)
                assert (e.rd16(0x10a2), e.rd16(0x1082), e.rd16(0x10ea)) == (0x3456, 0x1704, 6)
                checks += 1
    result = dict(native_cases=checks, transparent_owner=True, cached_scale_preserved=True)
    Path('build/registered-command-cache.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)


if __name__ == '__main__':
    main()
