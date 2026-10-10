"""Execute the linked registered visited-floor settings migration and roundtrip."""
import hashlib
import json
from pathlib import Path

from elf import read
from emu816 import Emu

ROOT = Path(__file__).resolve().parents[1]


def main():
    segments, symbols = read(ROOT/'build/wolf.elf')
    e = Emu()
    for section in segments:
        e.load(section['address'], section['data'])
    bitmap = symbols['visitMask']
    settings = 0x7c00
    seed = bytes((i*17+5)&255 for i in range(512))

    def call(name):
        e.db, e.d, e.s = 0x3f, 0x1200, 0x1fff
        e.mf, e.xf = 0, 0
        e.x, e.y = 0x4567, 0x1234
        e.call(symbols[name]>>16, symbols[name]&65535, long_return=True)
        assert (e.db,e.d,e.s,e.x,e.y,e.mf,e.xf)==(0x3f,0x1200,0x1fff,0x4567,0x1234,0,0)

    masks = [0, (1<<60)-1] + [1<<floor for floor in range(60)]
    for mask in masks:
        e.load(settings, seed)
        e.load(bitmap, mask.to_bytes(8,'little'))
        call('StoreVisitedFloors')
        written = bytes(e.m[settings:settings+512])
        assert all(written[i]==seed[i] for i in range(512) if i not in (16,17,*range(21,28)))
        assert written[21]==1
        assert written[16:18]+written[22:28]==(mask|1).to_bytes(8,'little')
        e.load(bitmap, b'\xff'*8)
        call('LoadVisitedFloors')
        assert int.from_bytes(e.m[bitmap:bitmap+8],'little')==mask|1
        assert bytes(e.m[settings:settings+512])==written
    for version in (0,2,255):
        for low in (0,2,0x200,0xffff):
            e.load(settings, seed)
            e.wr8(settings+21, version)
            e.wr16(settings+16, low)
            e.load(bitmap, b'\xff'*8)
            call('LoadVisitedFloors')
            assert int.from_bytes(e.m[bitmap:bitmap+8],'little')==(low&0x3ff)|1
    report=dict(roundtrips=len(masks),legacy_cases=12,neighbor_settings_preserved=True,
                elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
    (ROOT/'build/registered-visited-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
