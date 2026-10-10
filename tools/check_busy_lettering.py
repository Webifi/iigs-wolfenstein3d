"""Check linked disk lettering against the approved face and aligned ink slots."""
import argparse
import json
from pathlib import Path

import memmap
from elf import read
from emu816 import Emu
from loading_glyphs import ROWS, assembly, busy_assembly, text_rows
from wolfdata import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    assert (ROOT/'src/iigs/loading_sign.inc').read_text()==assembly()
    assert (ROOT/'src/iigs/busy_signs.inc').read_text()==busy_assembly()
    segments,symbols=read(ROOT/'build/wolf.elf')
    results=[]
    cases=[(0,'LOADING'),(1,'SAVING'),(3,'NEW HIGH SCORE')]+[(2,f'INSERT DISK {i}') for i in range(1,10)]
    for kind,text in cases:
        e=Emu()
        for segment in segments:e.load(segment['address'],segment['data'])
        background=bytes([0x0d,0xef])*16000
        e.load(memmap.SHR,background);expected=bytearray(background)
        rows,width=text_rows(text);left=160-width//2-1;top=89 if kind==3 else 86
        for y,row in enumerate(rows):
            for x,ink in enumerate(row):
                if ink is None:continue
                at=(top+y)*160+(left+x)//2;shift=0 if (left+x)&1 else 4
                expected[at]=(expected[at] & ~(15<<shift))|(ink<<shift)
        e.d,e.db,e.mf,e.xf,e.s=memmap.UI_DP,memmap.MENU>>16,0,0,0x1fff
        def setui(name,value):e.wr16(memmap.UI_DP+getattr(memmap,name),value)
        address=symbols[{0:'strLoading',1:'strSaving',2:'strInsert',3:'strHigh'}[kind]]
        e.load(address,text.encode()+b'\0')
        for name,value in [('U_X',160),('U_Y',top+1),('U_C',12),('U_STR',address&65535),('UC_FIRST',0),('UC_END',32000)]:setui(name,value)
        e.wr16(symbols['busyKind'],kind)
        start=symbols['DrawBusyText'];e.call(start>>16,start&65535,long_return=True)
        actual=bytes(e.m[memmap.SHR:memmap.SHR+32000]);bad=sum(a!=b for a,b in zip(actual,expected))
        assert actual==expected,(text,bad)
        assert e.rd16(memmap.UI_DP+memmap.U_X)==160+width-width//2
        assert e.rd16(memmap.UI_DP+memmap.U_STR)==(address+len(text)+1)&65535
        results.append(dict(text=text,changed_bytes=sum(a!=b for a,b in zip(background,actual)),different_bytes=bad,cycles=e.cycles))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(cases=results,loading_unchanged=True,slots=[0,1,13,14]),indent=2)+'\n')
    print(f'{len(results)} linked signs match; LOADING and untouched pixels remain exact.')


if __name__=='__main__':main()
