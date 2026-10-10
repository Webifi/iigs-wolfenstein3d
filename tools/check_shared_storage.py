"""Reconstruct every campaign floor from the packed shared-art store."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct

import storage_codec
from registered_loads import art_rows
from wolfdata import ROOT, PROFILE


def expand(memory, plan):
    count,credit=struct.unpack_from('<HH',plan,2048)
    if not count or len(plan)!=2052+count*18:raise ValueError('Invalid shared-art plan size')
    for at in range(2052,len(plan),18):
        source=struct.unpack_from('<H',plan,at)[0]
        entry,reserved,loops=struct.unpack_from('<BBH',plan,at+14)
        if entry>1 or reserved or not loops:raise ValueError('Invalid shared-art run')
        n=loops*2-entry
        if source<0x8000 or source&1 or source+n*2>0x10000:raise ValueError('Shared source outside staging window')
        indices=struct.unpack_from('<%dH'%n,memory,memmap.BOOT_STAGE+source)
        if any(i>510 or i&1 for i in indices):raise ValueError('Invalid palette offset')
        for light in range(4):
            bias=int.from_bytes(plan[at+2+light*3:at+5+light*3],'little')
            dest=(bias+source)&0xffffff
            if dest+n*2>len(memory) or dest>>16!=(dest+n*2-1)>>16:raise ValueError('Shared destination outside bank')
            pixels=b''.join(plan[light*512+i:light*512+i+2] for i in indices)
            memory[dest:dest+len(pixels)]=pixels


def check(store):
    data=store.read_bytes();items=json.loads(store.with_suffix('.json').read_text())
    checked=0
    for floor in range(PROFILE.floors):
        memory=bytearray(b'\xa5'*0x440000)
        for item in items:
            if item['group']!=f'floor/{floor}':continue
            start=item['first_block']*512;payload=data[start:start+item['blocks']*512]
            address=item['address'];size=item['bytes'];codec=item['codec']
            if codec=='sparse':raw=storage_codec.decode_sparse(payload,size,memory[address:address+size])
            else:
                raw=storage_codec.decode(payload,size,codec)
                assert hashlib.sha256(raw).hexdigest()==item['sha256'],item
            if codec=='plan':
                memory[memmap.SHARED_PLAN:memmap.SHARED_PLAN+size]=raw;expand(memory,raw)
            else:memory[address:address+size]=raw
        for row in art_rows(floor):
            expected=(ROOT/row['file']).read_bytes();a=row['address']
            assert memory[a:a+len(expected)]==expected,(floor,row['file'])
            checked+=len(expected)
    return dict(floors=PROFILE.floors,exact_art_bytes=checked)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--store',type=Path,default=Path('build/assets/episode.bin'));ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    result=check(args.store);args.out.write_text(json.dumps(result,indent=2)+'\n');print(result)


if __name__=='__main__':main()
