"""Compare every repacked world texel and unchanged weapon command on ten floors."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct

from sprite_banks import FRAME_BANK_TABLE
from wolfdata import ROOT


def check(before, after):
    results=[]
    for floor in range(10):
        a,b=before/str(floor),after/str(floor)
        old,new=[(p/'spritecmd.bin').read_bytes() for p in (a,b)]
        oi,ni=[(p/'art-index.bin').read_bytes() for p in (a,b)]
        shapes=json.loads((a/'sprites.json').read_text())
        assert shapes==json.loads((b/'sprites.json').read_text())
        fs=(a/'spriteFrame.bin').read_bytes()
        assert fs==(b/'spriteFrame.bin').read_bytes()
        wall=json.loads((a/'map.json').read_text())['wall_index_bytes']
        assert oi[:wall]==ni[:wall]
        assert len(ni)<=262144 and len(new)==131072
        runs=texels=0
        for i,shape in shapes.items():
            frame=struct.unpack_from('<H',fs,2*int(i))[0]
            assert old[frame:frame+260]==new[frame:frame+260]
            bank=new[FRAME_BANK_TABLE+(frame>>8)]
            if not shape['weapon']:assert 0x10<=bank<0x18
            for x,col in enumerate(shape['columns']):
                ptr=struct.unpack_from('<H',old,frame+x*2)[0]+65536
                for top,bottom,raw in sorted(col,reverse=True):
                    pair,os,ob=struct.unpack_from('<3H',old,ptr)
                    np,ns,nb=struct.unpack_from('<3H',new,ptr)
                    assert pair==np==top|(bottom<<8)
                    if shape['weapon']:
                        assert (os,ob)==(ns,nb)
                    else:
                        assert nb==bank
                        bias=2*top if top<200 else 0
                        oo=((ob<<16)+os+bias-memmap.ART_BASE)//2
                        no=((nb<<16)+ns+bias-memmap.ART_BASE)//2
                        assert oi[oo:oo+len(raw)]==ni[no:no+len(raw)]==bytes(raw)
                        assert ns+bias+len(raw)*2<=65536
                        texels+=len(raw)
                    runs+=1;ptr+=6
                assert old[ptr:ptr+2]==new[ptr:ptr+2]==b'\0\0'
        for entry in json.loads((a/'sprite-loads.json').read_text()):
            name=entry['file'];assert (a/name).read_bytes()==(b/name).read_bytes()
        results.append(dict(floor=floor,shapes=len(shapes),runs=runs,world_texels=texels,
                            old_index_bytes=len(oi),new_index_bytes=len(ni),
                            index_sha256=hashlib.sha256(ni).hexdigest(),
                            commands_sha256=hashlib.sha256(new).hexdigest()))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,default=ROOT/'build/frame-bank-before')
    p.add_argument('--after',type=Path,default=ROOT/'build/levels')
    p.add_argument('--out',type=Path,default=ROOT/'build/frame-bank-art.json')
    args=p.parse_args();result=check(args.before,args.after)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(f"{sum(r['shapes'] for r in result)} shapes, {sum(r['runs'] for r in result)} runs, "
          f"{sum(r['world_texels'] for r in result)} world texels: exact")
