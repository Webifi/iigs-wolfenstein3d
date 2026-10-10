"""Execute native boot progress counters across the 255/256 boundary."""
import hashlib
import json
from pathlib import Path

from elf import read
from emu816 import Emu

ROOT = Path(__file__).resolve().parents[1]


def main():
    e = Emu()
    segments, s = read(ROOT/'build/boot/loader.elf')
    for segment in segments:
        e.load(segment['address'], segment['data'])
    cases = []
    for disk_step, ram_step in ((1, 511), (127, 128), (137, 256), (255, 257), (256, 255), (511, 1)):
        e.wr8(s['HDR']+13, disk_step//256 | (ram_step//256 << 1))
        e.wr8(s['HDR']+14, disk_step & 255)
        e.wr8(s['HDR']+15, ram_step & 255)
        for mode, step in enumerate((disk_step, ram_step)):
            e.d, e.db, e.mf, e.xf, e.s = 0, 0, 1, 0, 0x1fff
            e.wr8(s['STOREMODE'], mode)
            e.call(0, s['loadStep'], sentinel=0x5f00)
            assert e.a == step and e.mf == 0
            e.wr16(s['STEPLEFT'], e.a)
            e.wr8(s['CELLS'], 32)
            e.mf = 1
            for block in range(1, step*3+2):
                e.call(0, s['stepBar'], sentinel=0x5f00)
                assert e.mf == 1 and e.xf == 0 and e.s == 0x1fff
                assert e.rd8(s['CELLS']) == min(34, 32+block//step)
                assert e.rd16(s['STEPLEFT']) == step-block % step
            cases.append(dict(mode=mode, step=step, blocks=step*3+1))
    result = dict(cases=cases, differences=0,
                  loader_sha256=hashlib.sha256((ROOT/'build/boot/loader.raw').read_bytes()).hexdigest())
    (ROOT/'build/loader-progress-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print('12 native counter cases: exact countdown, cell limit, and register widths through 511 blocks/cell')


if __name__ == '__main__':
    main()
