"""Verify the coarse aim comparison and exact boundary fallback in linked code."""
import memmap
import json
import random
from elf import read
from emu816 import Emu
from wolfdata import ROOT


def main():
    machine = Emu()
    sections, symbols = read(ROOT/'build/wolf.elf')
    for section in sections:
        machine.load(section['address'], section['data'])
    machine.load(memmap.WORD_PRODUCTS, (ROOT/'build/assets/word-products.bin').read_bytes())
    rng = random.Random(65816)
    depths = {0x5800, 0x5801, (64 << 16)-1}
    for whole in range(65):
        for fraction in (0, 1, 32767, 32768, 65534, 65535):
            depths.add(max(0x5800, (whole << 16)+fraction))
    depths.update(rng.randrange(0x5800, 64 << 16) for _ in range(2000))
    cases = 0
    for nx in sorted(depths):
        boundary = nx*symbols['LOGIC_SHOOTDELTA']//symbols['LOGIC_SCALE']
        for ny in (0, boundary-1, boundary, boundary+1, rng.randrange(64 << 16)):
            for ny in (ny, -ny):
                obj = symbols['OBJLIST']+64
                machine.d, machine.db, machine.mf, machine.xf, machine.s = 0x1100, 0x30, 0, 0, 0x1fff
                for name, value in (('L_NX', nx), ('L_NY', ny)):
                    address = machine.d+symbols[name]
                    machine.wr16(address, value & 65535)
                    machine.wr16(address+2, (value >> 16) & 65535)
                machine.wr16(machine.d+symbols['L_CHECK'], obj)
                at = symbols['actorAim']
                machine.call(at >> 16, at & 65535, sentinel=(memmap.REGISTERED_LOGIC_SPARE+0xfe0))
                actual = machine.rd16(memmap.LOGIC_BASE+obj+symbols['O_VIEWX'])
                expected = int(abs(ny)*symbols['LOGIC_SCALE'] < nx*symbols['LOGIC_SHOOTDELTA'])
                assert actual == expected and machine.c, (nx, ny, actual, expected)
                cases += 1
    result = dict(cases=cases, exact=True, fractional_boundary_fallback=True)
    (ROOT/'build/actor-aim-precision.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)


if __name__ == '__main__':
    main()
