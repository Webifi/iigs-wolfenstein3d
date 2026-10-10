"""Approved front-end lettering and layouts; no original menu backdrop art."""
import importlib.util,json,struct,sys,subprocess,shutil
from pathlib import Path
from wolfdata import ROOT, PROFILE, CONVERSION, source_data
HERE=ROOT/'tools/frontend/lettering'
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT/'tools/frontend'))
import render as letters
from shared_gray import INK, STEEL, TRANSPARENT_INK, shade_table, remap, picture, preview, tally


def prepare(size=12):
    work=ROOT/'build/frontend/native';work.mkdir(parents=True,exist_ok=True)
    name='BlackOpsOne-Regular.ttf'+('' if size==12 else f'.{size}')+'.json'
    cached=work/name
    approved=ROOT/'data/frontend-fonts'/name
    if not cached.exists() and approved.is_file():shutil.copyfile(approved,cached)
    if cached.exists():return work
    exe=work/'rasterize'
    if sys.platform!='darwin':
        raise ValueError('Missing prepared glyph input: '+str(approved)+'. Regenerate it with the developer font tools on macOS.')
    if not exe.exists():subprocess.run(['swiftc','-O',str(HERE/'rasterize.swift'),'-o',str(exe)],check=True)
    return work


def font_data(size=12):
    face=letters.Face('BlackOpsOne-Regular.ttf',prepare(size),size=size)
    widths=[];offsets=[];blob=bytearray();records={}
    for code in range(32,127):
        c=chr(code).upper()
        if c==' ':widths.append(5);offsets.append(0);continue
        if c not in face.glyphs:c='?'
        rows=face.glyphs[c];w=len(rows[0]);widths.append(w+2)
        if c not in records:
            sc=letters.Screen(letters.blank(320,200,0x111));face.draw(sc,c,1,1)
            ink=[row[:w+2] for row in sc.rows[:face.height+2]]
            # The source $111 marks transparent pixels; its encoded nibble follows the aligned font palette.
            used=[y for y,row in enumerate(ink) if any(v!=0x111 for v in row)]
            top,bottom=min(used),max(used)
            ink=ink[top:bottom+1]
            packed=[]
            for row in ink:
                vals=[INK[v&15] for v in row]
                if len(vals)&1:vals.append(TRANSPARENT_INK)
                packed.extend((a<<4)|b for a,b in zip(vals[::2],vals[1::2]))
            records[c]=len(blob)
            blob+=bytes([w+2,len(ink),top])+bytes(packed)
        offsets.append(records[c])
    return face,widths,offsets,blob


def title_data():
    titles = lettering_asset('headings')
    from assets import has_logo
    if not has_logo():
        del titles['Wolfenstein 3-D']
    return titles


def lettering_asset(name):
    """All editions share the approved pixels and row-band palettes."""
    return json.loads((ROOT/'data/frontend-lettering'/f'{name}.json').read_text())


def preview_title(name):
    return lettering_asset('preview-titles')[name]


def install(m):
    (ROOT/'build/gen/steel-constants.inc').write_text(f'STEEL_TRANSPARENT .equ {TRANSPARENT_INK}\n')
    (ROOT/'build/gen/steel-palette.inc').write_text('              .word '+','.join(f'0x{c:03x}' for c in STEEL)+'\n')
    role_shades = (0, 15, 12, 5, 13, 12, 10, 8, 8, 8, 8, 12, 11, 7, 4, 3)
    (ROOT/'build/gen/steel-slots.inc').write_text('              .byte '+','.join(str(INK[g]) for g in role_shades)+'\n')
    face,widths,offsets,font=font_data()
    small,sw,so,sf=font_data(6)
    assert small.height==8
    medium,mw,mo,mf=font_data(8)
    assert medium.height==11
    titles=title_data()
    # Split at a glyph boundary: the prefix uses the font buffer; the remainder
    # uses steelGlyphs. Offsets and bank bytes must select the same half.
    cold=3584;split=max(i for i in set(offsets) if i<=cold)
    (ROOT/'build/assets/frontend-font.bin').write_bytes(font[:split])
    asm=['              .public steelWidths, steelOffsets, steelBanks', 'steelWidths:']+m.bytes_lines(widths+[0])
    asm+=['steelOffsets:']
    ptrs=[(0xa100+o) if o<split else o-split for o in offsets]
    for i in range(0,len(ptrs),8):asm.append('              .word '+', '.join('0x%04x'%p if offsets[i+j]<split else '.word0 (steelGlyphs + %d)'%p for j,p in enumerate(ptrs[i:i+8])))
    asm+=['steelBanks:']+m.bytes_lines([0xe0 if o<split else 0x0f for o in offsets]+[0])
    asm+=['steelBright:']+m.bytes_lines(shade_table(True))
    asm+=['steelMuted:']+m.bytes_lines(shade_table(False))
    asm+=['              .public steelBright, steelMuted','              .extern steelGlyphs']
    (ROOT/'build/gen/steel-extra.inc').write_text('\n'.join(['              .public steelGlyphs','steelGlyphs:']+m.bytes_lines(font[split:])+['              .public mediumGlyphs','mediumGlyphs:']+m.bytes_lines(mf))+'\n')
    asm+=['              .public smallWidths, smallOffsets, smallBanks', 'smallWidths:']+m.bytes_lines(sw+[0])
    asm+=['smallOffsets:']
    for i in range(0,len(so),8):asm.append('              .word '+', '.join('.word0 (smallGlyphs + %d)'%o for o in so[i:i+8]))
    asm+=['smallBanks:']+m.bytes_lines([0x3f]*96)
    asm+=['smallGlyphs:']+m.bytes_lines(sf)
    asm+=['              .extern mediumGlyphs','mediumWidths:']+m.bytes_lines(mw+[0])
    asm+=['mediumOffsets:']
    for i in range(0,len(mo),8):asm.append('              .word '+', '.join('.word0 (mediumGlyphs + %d)'%o for o in mo[i:i+8]))
    asm+=['mediumBanks:']+m.bytes_lines([0x0f]*96)
    print('small/medium fonts',len(sf),len(mf),'bytes')
    (ROOT/'build/gen/steel-font.inc').write_text('\n'.join(asm)+'\n')
    print('steel font',len(font),'bytes;',split,'slow,',len(font)-split,'menu')
    return titles

def encode_title(cv):
    rows=[list(row) for row in cv['indices']];w=cv['width'];h=cv['height']
    out=bytearray(struct.pack('<HHH',w,h,len(cv['bands'])))
    used_by_palette={}
    for band in cv['bands']:
        used_by_palette.setdefault(band['palette'],set()).update(v for row in rows[band['start']:band['end']] for v in row if v is not None)
    for band in cv['bands']:
        out+=bytes([band['start'],band['end'],band['palette'],0])
        used=used_by_palette[band['palette']]
        # The same fill the gray catalog stored, so this band's table exists.
        import gray_catalog
        pal=gray_catalog.band_palette(band, used)
        mapping=remap([int(c,16) for c in band['colors_0rgb']],pal)
        for y in range(band['start'],band['end']):
            rows[y]=[None if c is None else mapping[c] for c in rows[y]]
        def neutral(c):return (c>>8&15)==(c>>4&15)==(c&15)
        mapping=[min((i for i,c in enumerate(pal) if neutral(c) and (c&15)<=5),key=lambda i:abs((pal[i]&15)-g)) for g in range(16)]
        addr=gray_catalog.offset_of(pal)
        out+=struct.pack('<16H',*pal)+bytes(mapping[:6])+bytes(v<<4 for v in mapping[:6])+struct.pack('<I', addr)[:3]+bytes(1)
    from frontend.build_words import block
    phase=((320-w)//2)&1
    both=cv.get('cursor',False)
    first=block(rows,0) if both or phase==0 else b''
    second=block(rows,1) if both or phase==1 else b''
    out+=struct.pack('<HH',4 if first else 65535,4+len(first) if second else 65535)
    out+=first+second
    return bytes(out)


def build_lumps(m,art,fonts,titles):
    # Page conversions are reusable only for the same source and converter.
    from attract_assets import page_inputs, digest
    meta=json.loads((ROOT/'build/gen/campaign.json').read_text())
    source=source_data()
    identity,provenance=page_inputs(ROOT,source,CONVERSION,art.pal)
    cache=ROOT/'build/frontend/native/pages'/(PROFILE.key+'-'+identity)
    cache.mkdir(parents=True,exist_ok=True)
    names=('title','credits','pg13','tally','victory')+tuple(f'end{i+1}' for i in range(meta['ending_pages']))
    if not all((cache/(n+'.bin')).exists() for n in names):
        old,dirs,_=m.legacy_build_lumps(art,{})
        for n,first,count,stage,size in dirs:
            if n in names:(cache/(n+'.bin')).write_bytes(old[first*512:first*512+size])
        (cache/'constants.json').write_text(json.dumps(m.PAGE_CONSTS))
        (cache/'source.json').write_text(json.dumps(provenance,indent=2)+'\n')
    import art_pages
    (cache/'title.bin').write_bytes(art_pages.record(*art_pages.new_title(source.graphics_layout['roles'].get('title', source.graphics_layout['roles'].get('title_top')))))
    constants=json.loads((cache/'constants.json').read_text())
    pages={name:(tally((cache/(name+'.bin')).read_bytes(),constants) if name=='tally'
                  else picture((cache/(name+'.bin')).read_bytes(),name=='victory')) for name in names}
    from make_boot_picture import build as build_boot_picture
    boot_receipt = build_boot_picture(ROOT, PROFILE.key)
    m.PAGE_CONSTS.update(constants)
    import art_lumps
    (ROOT/'build/assets/pages-check.json').write_text(json.dumps(art_lumps.checks(pages['victory'],[pages[n] for n in ('end1','end2')]))+'\n')
    for key,name in [('Difficulty','difficulty'),('New Game','floors')]:
        titles[key]=preview_title(name)
    import gray_catalog
    from frontend.episode_previews import build as build_episode_previews
    episode_previews = build_episode_previews()
    from frontend.preview_art import build_portraits
    portraits = build_portraits()
    gray_catalog.build(titles,cache)
    for name in names:
        if name.startswith('end'): pages[name] += (ROOT/'build/assets/gray-local'/f'{name}.bin').read_bytes()
    blob=bytearray(1024);directory=[];pics={};title_offsets={}
    def add(name,data,stage=0):
        data+=bytes(-len(data)%512);directory.append((name,len(blob)//512,len(data)//512,stage,len(data)));blob.extend(data)
    provenance['converted_pages']={name:digest(data) for name,data in pages.items()}
    provenance['boot_cover']=dict(kind='project PNG', **boot_receipt)
    (ROOT/'build/assets/frontend-source.json').write_text(json.dumps(provenance,indent=2)+'\n')
    # Common lettering and cursor are decoded once at boot and never overwritten by a page.
    from frontend.native_assets import title as native_title
    # GT's graphics omit the small Wolf logo; its own Options heading fits here.
    heading=titles.get('Wolfenstein 3-D',titles['Options'])
    common=bytearray(native_title(encode_title(heading)))
    cursors = lettering_asset('cursors')
    for label in ('cursor1', 'cursor2', 'smallcursor1', 'smallcursor2'):
        cv = cursors[label]
        off=len(common)
        common+=encode_title(cv)
        pics['common',label]=(off,cv['width']//2,cv['height'])
    assert len(common)<=0x1800,len(common)
    add('common',bytes(common),0)
    add('font', (ROOT/'build/assets/frontend-font.bin').read_bytes(),0x1800)
    blob.extend(bytes(-len(blob)%4096))
    for name,word in [('main','Options'),('newgame','Difficulty'),('load','Load Game'),('save','Save Game'),('options','Display & Sound'),('controls','Key Setup'),('scores','High Scores'),('floors','New Game'),('controltop','Controls'),('bench','Benchmark')]:
        title_offsets[name]=0x1800;add(name,encode_title(titles[word]),0x1800)
    raw_chunks=(directory[-1][1]+7)//8
    blob.extend(bytes(-len(blob)%4096))
    for n,path in enumerate(portraits):add(f'portrait{n}',b'',0x1800)
    m.PAGE_CONSTS['EPISODE_PREVIEW_BASE'] = len(directory)
    for n,path in enumerate(episode_previews):add(f'episode{n}',preview(path.read_bytes()),0x1800)
    blob.extend(bytes(-len(blob)%4096))
    from psyched_picture import build as psyched_picture, X, Y, WIDTH, HEIGHT, RECORD
    m.PAGE_CONSTS['PSYCHED_BLOCK'] = len(blob) // 512
    plate = psyched_picture()
    blocks = (len(plate) + 4095) // 4096 * 8
    m.PAGE_CONSTS.update(PSYCHED_BLOCKS=blocks, PSYCHED_X=X, PSYCHED_Y=Y,
                        PSYCHED_WB=WIDTH // 2, PSYCHED_ROWS=HEIGHT, PSYCHED_RECORD=RECORD)
    blob.extend(plate.ljust(blocks * 512, b'\0'))
    resident=None
    for name in names:
        if name=='victory':blob.extend(bytes(-len(blob)%4096));resident=len(blob)//4096
        if name.startswith('end'):blob.extend(bytes(-len(blob)%4096))
        add(name,pages[name])
    assert len(directory)<=126
    blob[:6]=b'WMNU\x02'+bytes([len(directory)])
    for i,(_,first,count,stage,size) in enumerate(directory):struct.pack_into('<HHHH',blob,8+8*i,first,count,stage,size)
    (ROOT/'build/assets/menu-resident.json').write_text(json.dumps(dict(first_chunk=resident,raw_chunks=raw_chunks))+'\n')
    return bytes(blob),directory,pics


def configure(m):
    titles=install(m)
    m.legacy_build_lumps=m.build_lumps
    m.build_lumps=lambda art,fonts:build_lumps(m,art,fonts,titles)
    m.ITEM_X,m.ITEM_Y,m.ITEM_STEP=99,32,16
    m.CT_X,m.CT_Y,m.CT_STEP,m.CT_VALUE_X=46,50,12,282
    class TitleDL:
        def __init__(self,offset=0x1800,y=5):self.offset=offset;self.y=y
        def asm(self,label,pics):return [label+':',f'              .word 4, {self.offset}, {self.y}, 0']
    m.SCREENS=[(n,lambda off=off:TitleDL(off,0 if off==0 else 5)) for n,off in [('dlMain',0),('dlNewGame',0x1800),('dlOptions',0x1800),('dlScores',0x1800),('dlControls',0x1800),('dlLoad',0x1800),('dlSave',0x1800),('dlFloors',0x1800)]]
