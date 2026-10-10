"""Check resident bounds and transition-only overlays for four stored lights.

This checks the built assets and ELF. Native transition and timing checks are
still required: disjoint addresses alone cannot prove overlay lifetimes.
"""
import json
import re
import struct
from pathlib import Path

from elf import read
from wolfdata import ROOT, PROFILE
import memmap


def menu_buffer_bound():
    """Bound the encoded rows used by Difficulty and FloorSelect menus."""
    source=ROOT/'src/iigs'
    main=(source/'ui_main.s').read_text()
    # Only listPictures 1/2 use RowSelectInit; display previews bypass it.
    assert re.search(r'lda abs:\.word0 \(listPictures\)\s+beq listRowInkDone\s+'
                     r'cmp ##3\s+bcs listRowInkDone',main)
    assert main.count('jsl long:RowSelectInit')==1
    widths=[]
    for name,label in (('ui_main.s','NewGame'),('ui_frontend.s','FloorSelect')):
        body=(source/name).read_text().split(label+':',1)[1]
        match=re.search(r'lda ##(\d+)\s+sta dp:UL_WIDTH',body)
        assert match,(name,'menu width needs a new row-cache bound')
        widths.append(int(match[1]))
    row=(source/'ui_rowcache.s').read_text()
    height=int(re.search(r'lda ##(\d+)\s+sta dp:RC_HEIGHT',row)[1])
    row_bytes=max(((width+7)&~3)//2 for width in widths)
    # Each changed byte costs a distance/value pair. Allow extra skip bytes
    # for the entire screen extent, plus the zero terminator.
    encoded=2*row_bytes*height+(160*height+253)//254+1
    front=(source/'frontend.inc').read_text()
    box={k:int(re.search(r'(?m)^'+k+r'\s+\.equ\s+(\d+)',front)[1])
         for k in ('BOX_W','BOX_H')}
    busy=(box['BOX_W']//2+1)*box['BOX_H'] # pixels and saved SCBs
    assert max(encoded,busy)<=3200,('menu buffer exceeds reserved space',encoded,busy)
    return dict(row_widths=widths,encoded_row_bound=encoded,busy_bytes=busy,reserved_bytes=3200)


def check():
    from check_registered_assets import memory
    return memory()


if __name__=='__main__':
    result=check()
    out=ROOT/'build/depth-memory.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('Four light atlases fit ROM01 + 4 MiB; product rows, thrust rows and runtime bounds verified.')
