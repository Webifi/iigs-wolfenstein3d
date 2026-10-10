"""Execute the linked EP03/EP04 reader, including full pages and bad headers.

Disk reads are fixtures. The native validation and selection execute in Emu816.
"""
import json
import struct
from pathlib import Path
import episode_directory as directory
from elf import read
from emu816 import Emu


class Reader(Emu):
    def __init__(self):
        super().__init__()
        segments, self.symbols = read('build/wolf.elf')
        for segment in segments:
            self.load(segment['address'], segment['data'])

    def step(self):
        s = self.symbols
        if self.pb<<16 | self.pc == s['directoryBlock']:
            page = self.rd16(s['LV_BLOCK'])
            buffer = self.rd16(s['LV_BUFFER'])
            self.reads.append(page)
            assert 0 <= page < len(self.store)//512
            self.load(buffer, self.store[page*512:(page+1)*512])
            self.x, self.y = 0xdead, 0xbeef
            self.pc = (self.pop16()+1)&65535
            return
        super().step()

    def invoke(self, index, auxiliary=False, succeeds=True):
        s = self.symbols
        self.load(0xbc00, self.store[:1024])
        self.load(0xc000, b'\xa5'*512)
        self.reads = []
        self.wr16(s['loadFloor'], index)
        self.wr16(s['loadAux'], int(auxiliary))
        self.db, self.d, self.mf, self.xf, self.s = 0, 0, 0, 0, 0x1fff
        self.call(0, s['selectFloorDirectory'])
        assert self.c == int(not succeeds), (index, auxiliary, self.c)
        assert self.m[0xc000:0xc200] == b'\xa5'*512, 'directory scratch overrun'
        if succeeds:
            expected = (directory.auxiliary_records(self.store, index) if auxiliary else
                        directory.floor_records(self.store, index)[0])
            count = self.rd16(s['LV_LEFT'])
            at = self.rd16(s['LV_RECORD'])
            actual = [struct.unpack_from('<4H', self.m, at+n*8) for n in range(count)]
            assert actual == expected


def main():
    r = Reader()
    accepted = rejected = 0
    for pages, wide, fast in ((1, False, False), (2, False, False), (2, True, False), (2, True, True), (2, True, 2), (2, True, 3)):
        data = directory.create(60, 309, record_pages=pages, wide_blocks=wide, fast_codecs=fast)
        counts = [pages*64 if f == 59 else 1+f%23 for f in range(60)]
        records, offsets = [], []
        for count in counts:
            offsets.append(len(records)*8)
            records.extend((n*512, 0x20, 2048+n, 1) for n in range(count))
        directory.finish(data, offsets, counts, [0]*60, records)
        groups = [[(n*512, 0x21, 4096+n, 1) for n in range(pages*64-1 if i==308 else 1+i%17)]
                  for i in range(309)]
        directory.finish_auxiliary(data, groups)
        r.store = data
        for auxiliary, count in ((False, 60), (True, 309)):
            for index in range(count):
                r.invoke(index, auxiliary); accepted += 1
                assert len(r.reads) == pages
            r.invoke(count, auxiliary, False); rejected += 1
        changes = [(12, 2, False), (14, 0, False), (14, pages*64+1, False),
                   (16, 256, False), (404, 3+60*pages-1, True),
                   (406, 0, True), ((3+60*pages)*512, pages*64, True),
                   ((3+60*pages)*512+2, 1, True)]
        if pages == 2: changes.append((12, 4, False))
        for at, value, auxiliary in changes:
            bad = bytearray(data);struct.pack_into('<H', bad, at, value)
            r.store = bad;r.invoke(0, auxiliary, False);rejected += 1
    result = dict(accepted=accepted, rejected=rejected, native_reader=True,
                  fixture='disk block reads only', scratch_bytes=1024)
    Path('build/ep04-directory-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)


if __name__ == '__main__': main()
