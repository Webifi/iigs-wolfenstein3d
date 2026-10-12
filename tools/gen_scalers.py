"""Compile id's 64-row ScalePost sampling into stock 65816 row loads/stores."""
import memmap
from pathlib import Path
import math
import struct
from buildconfig import config
from viewgeometry import SIZES
import pool_cover
FOUR=config()['colors']=='four'
TRUE=config()['pixels']=='true'
GROUPS=FOUR and config().get('scaler')=='groups' and not TRUE
# The prepared paint enters each scaler by RTS from a pop-only stub at the
# same offset of its own bank, so one list word names the entry.
PREPARED=FOUR and not GROUPS and not TRUE
HEAD=26 if PREPARED else 0
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/gen'
heights=list(range(2,161,2))+list(range(164,641,4))
coverage=pool_cover.plan()
short_code=[]
lines=[]; directory=[]; bank=3; offset=HEAD; totals={};groupmeta=bytearray();group_base=[0]*len(heights)
for n,h in enumerate(heights):
    top=max(0,80-h//2); bottom=min(160,80+h//2)
    texels=[max(0,min(63,((row-(80-h//2))*64)//h)) for row in range(top,bottom)]
    grouped=GROUPS and h>=256
    offsets=[0]*len(texels);mask_offsets={};bounds={};body=[];size=0;prev=-1
    if grouped:
        runs=[]
        for row,tex in zip(range(top,bottom),texels):
            if not runs or runs[-1][0]!=tex:runs.append((tex,[]))
            runs[-1][1].append(row)
        for tex,run in runs:
            start=size
            for row in run:offsets[row-top]=start;bounds[row]=(run[0],run[-1]+1)
            for parity in (0,1):
                selected=[r for r in run if r&1==parity]
                if selected:
                    body.append(f' lda abs:{tex*2+parity},y');size+=3
                    for row in selected:
                        mask_offsets[row]=size+2
                        body.append(f' sta long:0x{memmap.SHR+row*160:06x},x');size+=4
    else:
        for row,tex in zip(range(top,bottom),texels):
            offsets[row-top]=size
            if FOUR or tex!=prev:
                body.append(f' lda abs:{tex*2+(row&1) if FOUR else tex},y');size+=3
            body.append(f' sta long:0x{memmap.SHR+row*160:06x},x');size+=4;prev=tex
    offsets.append(size);body.append(' rtl');size+=1
    if offset+size>65536:
        bank+=1; offset=HEAD
        if PREPARED and bank==4:offset+=sum(min(h,160)*7+1 for h in heights if h<64)
    if bank>5: raise ValueError('scalers exceed three banks')
    if bank not in totals:
        lines.append(f' .section scale{bank}, text, root')
        if PREPARED:
            pending=0xb0+(bank-3)*3
            restore=[' lda #0xb9',f' sta [{pending}]']
            lines.extend([' .byte 0',f'wallOp{bank}: plb',' ply',' plx',*restore,' rts'])
            # Restore the previous temporary exit before entering any row
            # code in this bank. A cut keeps only its exit in the direct page;
            # the list no longer contains a separate restore record.
            lines.extend([f'cutOp{bank}: plb',' plx',' ply',*restore,f' stx dp:{pending}',
                          ' lda #0x6b',f' sta long:0x{bank:02x}0000,x',' plx',' rts'])
        if PREPARED and bank==4:lines.extend(short_code)
    if PREPARED and h<64:
        for local,(row,tex) in enumerate(zip(range(top,bottom),texels)):
            slot=coverage.slot.get((h,row),tex)
            short_code.extend([f' lda abs:{slot*2+(row&1)},y',f' sta long:0x{memmap.SHR+row*160:06x},x'])
        short_code.append(' rtl')
    name='scale_%d'%h
    directory.append((h,bank,offset,top,bottom,offsets,texels,bounds))
    lines.append(name+':');lines.extend(body)
    if grouped:
        group_base[n]=len(groupmeta)
        for row in range(161):
            first,last=bounds.get(row,(row,row))
            groupmeta.extend(struct.pack('<HBB',offset+mask_offsets.get(row,0),first,last))
    offset+=size;totals[bank]=offset
if PREPARED:
    # Flat rows store row k at screen row k-160+b with X=column+b*160, so a
    # span of c rows ending at b enters at row 160-c and needs no exit patch.
    lines.extend(['flatOp: pla',' plx',' rts','flatCode:'])
    lines.extend(' sta long:0x%06x,x'%(memmap.SHR+(k-160)*160) for k in range(160))
    lines.append(' rtl')
    totals[bank]=offset+3+641
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'scalers.s').write_text(' .public flatOp, flatCode\n'+'\n'.join(lines)+'\n' if PREPARED else '\n'.join(lines)+'\n')
index=[min(range(len(heights)),key=lambda n:abs(heights[n]-h)) for h in range(1025)]
inc=[' .section gamedata, data, root']
(OUT/'prepared.inc').write_text('FLATBANK .equ %d\nWALLOP .equ 1\nCUTOP .equ 9\nLASTCUT3 .equ 0xb0\nLASTCUT4 .equ 0xb3\nLASTCUT5 .equ 0xb6\n'%bank if PREPARED else '')
horizontal=bytearray();horizontal_base=[]
for h in heights:
    horizontal_base.append(len(horizontal))
    horizontal.extend(min(63,round((16384 if TRUE else 32768)/h)*col//256) for col in range(h if TRUE else h//2))
for name,values,kind in [('scaleIndex',[n*2 for n in index],'.word'),('scaleHeight',heights,'.word'),('scaleBank',[v[1]|(256 if v[7] else 0) for v in directory],'.word'),('groupBase',group_base,'.word'),('rowCodeBase',[i*322 for i in range(len(heights))],'.word'),('rowTexBase',[i*161 for i in range(len(heights))],'.word'),('texEndpointBase',[i*130 for i in range(len(heights))],'.word'),('scaleWidthRecip',[min(65535,round(32768/h)) for h in heights],'.word')]:
    if name=='groupBase' and not GROUPS:continue
    inc.append(name+': '+kind+' '+','.join(str(v) for v in values))
inc.append('epPage: .word '+','.join(str(i<<8) for i in range(len(heights))))
inc.append('horizontalBase: .word '+','.join(map(str,horizontal_base)))
if GROUPS:
    inc.append('screenStoreBanks: .word '+','.join(str(0xe100|((0x2000+r*160)>>8)) for r in range(160)))
(OUT/'scalers.inc').write_text('\n'.join(inc)+'\n')
assert totals.get(5,0)<=65536, 'scalers exceed bank 5'
print('scalers:',sum(totals.values()),'bytes;',totals)

# One clipped directory per view. Copying a directory happens only on a size
# change; a dirty column needs no row-count multiply or clipping comparisons.
clip=bytearray()
for view in SIZES:
    top=(160-view)//2; bottom=top+view
    fields=[[],[],[],[],[],[]]
    for h,bank,addr,a,b,offsets,texels,bounds in directory:
        first=max(top,a); last=min(bottom,b)
        exitrow=bounds[last-1][1] if bounds else last
        # The prepared list pushes entry-1 for RTS/RTL; store it that way.
        for field,value in zip(fields,(addr+offsets[first-a]-(1 if PREPARED else 0),addr+offsets[exitrow-a],bank,first,last,texels[first-a])):
            field.append(value)
    for field in fields:clip.extend(struct.pack('<%dH'%len(field),*field))
(ROOT/'build/assets').mkdir(parents=True,exist_ok=True)
(ROOT/'build/assets/clips.bin').write_bytes(clip)
inc=['CLIPBYTES .equ %d'%(len(heights)*12),' .section gamedata, data, root',
     'viewClips: .word '+','.join(str(0xB000+i*len(heights)*12) for i in range(len(SIZES)))]
for name in ('viewScaleAddr','viewScaleExit','viewScaleBank','viewScaleTop','viewScaleBottom','viewScaleTex'):
    inc.append(name+': .space %d'%(len(heights)*2))
if not PREPARED:
    inc.append('flatEntry: .word '+','.join('.word0 (flatRows+%d)'%(r*4) for r in range(161)))
    inc.append(' .section gamecode, text, root, noreorder')
    inc.append('flatRows:')
    for row in range(160):inc.append(' sta long:0x%06x,x'%(memmap.SHR+row*160))
    inc.append(' rts')
else:
    inc.append('rowX160: .word '+','.join(str(r*160) for r in range(161)))
(OUT/'clips.inc').write_text('\n'.join(inc)+'\n')

# Arbitrary clipped spans use the same wall scaler; no sprite drawer copy.
rows=bytearray();texrows=bytearray();endpoints=bytearray();endpoint_lut=bytearray()
for h,bank,addr,a,b,offsets,texels,bounds in directory:
    for row in range(161):
        local=min(b-a,max(0,row-a))
        rows.extend(struct.pack('<H',addr+offsets[local]))
        texrows.append(texels[min(len(texels)-1,local)])
    page=bytearray(256)
    for tex in range(65):
        row=max(0,min(160,80-h//2+(tex*h+63)//64))
        endpoints.extend(struct.pack('<H',row))
        page[tex]=row
    # Exact inverse-horizontal bounds share unused endpoint-page bytes.
    # Synthetic floor pools keep their padded bounds in PrepareSprites.
    reciprocal=round((16384 if TRUE else 32768)/h)
    width=h if TRUE else h//2
    for tex in range(65):
        x=min(width,(tex*256+reciprocal-1)//reciprocal) if tex<64 else width
        struct.pack_into('<H',page,65+tex*2,x)
    for index,row in coverage.endpoints_for(h).items():
        assert 200<=index<216, 'pool endpoint overlaps inverse bounds or side limits'
        page[index]=row
    # Whole-billboard rejection in unscaled 8.8 side coordinates. Taking the
    # larger signed edge retains the half-column rounding difference. These
    # words occupy spare page bytes and do not change the RAM allocation.
    for view_index,view in enumerate(SIZES):
        view_width=view*(2 if TRUE else 1)
        left=(view_width-width)//2
        scaled_limit=max(view_width-left,left+width)
        if TRUE:
            scaled_limit=(scaled_limit+1)//2
        limit=(scaled_limit*256+h//2-1)//(h//2)
        struct.pack_into('<H',page,216+view_index*2,limit)
    endpoint_lut.extend(page)
(ROOT/'build/assets/rowcode.bin').write_bytes(rows)
# The boot builds rowcode.bin from the entries (src/iigs/boot_tables.inc).
(OUT/'scaler_entries.inc').write_text('SCALER_HEIGHTS .equ %d\nscaleEntry:   .word %s\n'
                                      % (len(directory),','.join(str(d[2]) for d in directory)))
(ROOT/'build/assets/rowtex.bin').write_bytes(texrows)
(ROOT/'build/assets/texend.bin').write_bytes(endpoints)
(ROOT/'build/assets/sprite-endpoints.bin').write_bytes(endpoint_lut)
(ROOT/'build/assets/horizontal.bin').write_bytes(horizontal)
(ROOT/'build/assets/group-meta.bin').write_bytes(groupmeta)
assert len(groupmeta)<=65536
assert len(horizontal)<=(65536 if TRUE else 32768)
assert len(rows)<=65536 and 0x4200+len(texrows)<=65536 and len(endpoints)<=65536

cache=bytearray()
for col in range(160):cache.extend(struct.pack('<H',(memmap.NP_COLUMN_CACHE+col*1284)&65535))
cache.extend((memmap.NP_COLUMN_CACHE+col*1284)>>16 for col in range(160))
(ROOT/'build/assets/cacheptrs.bin').write_bytes(cache)

# Cold option setup walks complete scaler bodies, including rows hidden by
# persistent view exits. The row counts also cover the short pool copy.
if PREPARED:
    counts=[]; pages=[]
    for bk in range(memmap.SEG_SCALE3 >> 16, (memmap.SEG_SCALE5 >> 16)+1):
        funcs=([(i,d[2],min(d[0],160)) for i,d in enumerate(directory) if d[0]<64] if bk==4 else [])
        funcs += [(i,d[2],min(d[0],160)) for i,d in enumerate(directory) if d[1]==bk]
        counts += [n for i,at,n in funcs]+[0]
        pages += [next((i for i,at,n in reversed(funcs) if at<=page*256),funcs[0][0]) for page in range(256)]
    text=f'BUFFER_SCALER_HEAD .equ {HEAD}\n .section bufferirq, text, root\nbufferScaleRows: .byte '+','.join(map(str,counts))+'\n'
    text+='bufferModulo: .byte '+','.join(str(i*256%160) for i in range(101))+'\n'
    text+=' .section buffersound, text, root\nbufferScalePage: .byte '+','.join(map(str,pages))+'\n'
    (OUT/'buffer_scalers.inc').write_text(text)

# Skip only overlaps meeting this row count. Source length gives a
# conservative upper bound before view clipping or overlap.
wall_band_min_rows = 12
wall_band_minimum = [next((i*2-2 for i,h in enumerate(heights)
                          if (n*h+63)//64 >= wall_band_min_rows), 399)
                     for n in range(65)]
(OUT/'wall_band_minimum.inc').write_text(
    'WALL_BAND_MIN_ROWS .equ %d\n .word %s\n' %
    (wall_band_min_rows, ','.join(map(str, wall_band_minimum))))
