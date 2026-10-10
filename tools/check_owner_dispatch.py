"""Exhaust every nonempty owner mask in both native painter dispatch paths."""
import argparse
import hashlib
import json
from pathlib import Path

from elf import read
from emu816 import Emu


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    segments, s = read(args.elf)
    e = Emu()
    for part in segments:
        e.load(part['address'], part['data'])
    for bit in range(16):
        e.wr16(s['maskOwners']+bit*2, (bit+3)*16)
    lookup = s.get('maskOwnerLookup', s['maskOwner'])
    assert e.rd8(lookup+2) == 0x25
    mask_address = 0x1000+e.rd8(lookup+3)
    cases = 0
    cycles = 0
    for entry, stop in (('maskOwner', 'spriteOwnerNear'), ('fastOwnerBit', 'fastInfo')):
        for mask in range(1, 65536):
            e.pb, e.pc = s[entry] >> 16, s[entry] & 65535
            e.db, e.d, e.s, e.mf, e.xf = 2, 0x1000, 0x5fff, 0, 0
            e.a = mask
            e.wr16(mask_address, mask)
            before = e.cycles
            while (e.pb << 16 | e.pc) != s[stop]:
                e.step()
                assert e.cycles-before < 160, (entry, mask, e.pc)
            bit = (mask & -mask).bit_length()-1
            assert e.x == (bit+3)*16, (entry, mask, e.x)
            assert e.rd16(mask_address) == mask & (mask-1)
            assert (e.db, e.d, e.s, e.mf, e.xf) == (2, 0x1000, 0x5fff, 0, 0)
            cases += 1
            cycles += e.cycles-before
    result = dict(scope=__doc__, cases=cases, differences=0, nominal_cycles=cycles,
                  elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
