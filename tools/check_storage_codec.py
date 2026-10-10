"""Execute the linked fast decoders on boundary, overlap and asset fixtures."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import random
import struct
from elf import read
from emu816 import Emu
import lzsa1
import lz16


def check_host_boundaries():
    # A de Bruijn sequence of order two has no repeated three-byte strings.
    # It exercises the full-bank literal case without depending on random luck.
    noise=bytes(v for a in range(256) for b in range(a,256)
                for v in ((a,) if a==b else (a,b)))
    assert len(noise)==65536
    try:
        lzsa1.compress(noise)
    except lzsa1.BlockTooLarge:
        pass
    else:
        raise AssertionError('An unrepresentable 65536-byte literal run was accepted')
    for n in (65534,65535):
        packed=lzsa1.compress(noise[:n])
        assert lzsa1.decode(packed,n)==noise[:n]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf',type=Path,default=Path('build/wolf.elf'))
    ap.add_argument('--loader',type=Path,default=Path('build/boot/loader.elf'))
    ap.add_argument('--assets',type=Path)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    check_host_boundaries()
    e=Emu();segments,s=read(args.elf)
    for seg in segments+read(args.loader)[0]:e.load(seg['address'],seg['data'])
    rng=random.Random(20261008)
    cases=[]
    for n in (1,2,3,7,18,127,128,129,249,250,255,256,257,511,512,1024,32767,32768,65535,65536):
        cases.append((f'run-{n}',bytes([73])*n))
        if n<=1024:cases.append((f'noise-{n}',bytes(rng.randrange(256) for _ in range(n))))
    seed=bytes(rng.randrange(256) for _ in range(2048))
    for distance in (1,2,3,255,256,257,511,512,1024,2048):
        cases.append((f'offset-{distance}',(seed[:distance]*8+b'end')[:65536]))
    if args.assets:
        for path in sorted(args.assets.glob('registered-art-*.bin')):
            raw=path.read_bytes()
            if 0<len(raw)<=65536:cases.append((path.name,raw))
    results=[]
    for codec in ('lzsa1','lz16'):
        for name,raw in cases:
            if codec=='lz16':
                stream,stats=lz16.compress(raw);packed=b'\0'+stream
                assert lz16.decode(stream,len(raw))==raw
            else:
                packed=lzsa1.compress(raw);stats={}
                assert lzsa1.decode(packed,len(raw),stats)==raw
            assert len(packed)+2<=65536
            for end_bank in (False,True):
                offset=65536-len(raw) if end_bank else 0
                start=(memmap.ART_BRIGHT+0x20000)+offset
                e.load((memmap.ART_BRIGHT+0x10000),b'\xa5'*0x30000)
                e.load(memmap.BOOT_STAGE,struct.pack('<H',len(raw)&65535)+packed)
                e.wr16(s['BOOT_SEGADDR'],offset);e.wr8(s['BOOT_SEGADDR']+2,0x22)
                e.wr16(s['loadMixed'],1);e.wr16(s['LV_RECORD'],0xbc00);e.wr16(0xbc02,0x4000)
                e.db=e.d=0;e.s=0x1ff;e.mf=1;e.xf=0;e.a=0;e.cycles=0
                e.call(0,s['DecodeFloorUnit'],limit=3_000_000)
                assert bytes(e.m[start:start+len(raw)])==raw,(name,end_bank)
                assert e.m[start-1]==165 and e.m[start+len(raw)]==165,(name,'write outside output')
                assert (e.db,e.d,e.mf,e.xf)==(0,0,1,0),(name,'return context')
                results.append(dict(codec=codec,name=name,end_bank=end_bank,bytes=len(raw),packed=len(packed)+2,
                                    cycles=e.cycles,sha256=hashlib.sha256(raw).hexdigest()))
    args.out.write_text(json.dumps(dict(native_cases=len(results),results=results),indent=2)+'\n')
    print('Native fast codecs:',len(results),'exact cases; bounds and return context passed')


if __name__=='__main__':main()
