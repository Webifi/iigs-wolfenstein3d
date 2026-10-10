"""Build each floor's map and palette assets, plus shared ray/scaler tables."""
import collections
import json
import math
import pathlib
import struct
import shutil
from buildconfig import config
from assetspace import Space,WALL_RANGES,segments
import memmap
from native_map_format import wall_material
from wolfdata import ROOT, PROFILE, CONVERSION, maps, vswap, palette, graphics
from palette_sampling import solid_index
from floor_art import ceiling as floor_ceiling, floor_color
from wolfcolor import ordered

OUT = ROOT/'build/assets'


def words(values):
    return struct.pack('<'+'H'*len(values),*(v&65535 for v in values))


def view_palette(pages, pal):
    counts = collections.Counter(c for page in pages for c in page)
    buckets = [list(counts)]
    while len(buckets)<14:
        bucket = max(buckets,key=lambda b: max(max(pal[c][d] for c in b)-min(pal[c][d] for c in b) for d in range(3))*sum(counts[c] for c in b) if len(b)>1 else -1)
        buckets.remove(bucket)
        axis = max(range(3),key=lambda d:max(pal[c][d] for c in bucket)-min(pal[c][d] for c in bucket))
        bucket.sort(key=lambda c:pal[c][axis])
        half=sum(counts[c] for c in bucket)/2; accum=0; cut=1
        for i,c in enumerate(bucket[:-1]):
            accum+=counts[c]
            if accum>=half: cut=i+1; break
        buckets.extend((bucket[:cut],bucket[cut:]))
    result=[(0,0,0),pal[0x19]]
    for b in buckets:
        total=sum(counts[c] for c in b)
        result.append(tuple(round(sum(pal[c][d]*counts[c] for c in b)/total/17)*17 for d in range(3)))
    cmap=[min(range(16),key=lambda i:sum((pal[c][d]-result[i][d])**2 for d in range(3))) for c in range(256)]
    return result,cmap


def loadfont(font):
    chars='0123456789/ DEIKNRSTLOAG'
    height=struct.unpack_from('<H',font)[0]
    offsets=struct.unpack_from('<256H',font,2)
    widths=font[514:770]
    lines=['GLYPH_ROWS .equ 7','ICON_ROWS .equ 9','ICON_BYTES .equ 6','GLYPH_SLASH .equ 10',' .section loader, text', 'PROMPT: .byte '+','.join(str(chars.index(c)) for c in 'INSERT DISK ')+',255', 'GLYPHS: .word '+','.join('glyph%d'%i for i in range(len(chars)))]
    lines.append('LOADINGTEXT: .byte '+','.join(str(chars.index(c)) for c in 'LOADING')+',255')
    for n,c in enumerate(chars):
        width=widths[ord(c)]; stride=(width+1)//2
        pixels=font[offsets[ord(c)]:offsets[ord(c)]+width*height]
        packed=[stride]
        for r in range(7):
            row=[3 if pixels[(r*height//7)*width+x] else 0 for x in range(width)]
            row += [0]*(-len(row)%4)
            packed += [sum(row[x+k]<<(6-2*k) for k in range(4)) for x in range(0,len(row),4)]
        lines.append('glyph%d: .byte '%n+','.join(str(v) for v in packed))
    # Newly drawn plain disk icon; the font comes only from Wolf's own data.
    for label,color in (('ICON_LIT',6),('ICON_DARK',1)):
        icon=[]
        for y in range(9):
            row=[0 if x==11 else (7 if y<3 and 2<=x<8 else (8 if 5<=y<8 and 1<=x<10 else color)) for x in range(12)]
            icon += [(row[x]<<4)|row[x+1] for x in range(0,12,2)]
        lines.append(label+': .byte '+','.join(str(v) for v in icon))
    (ROOT/'build/gen/loadfont.s').write_text('\n'.join(lines)+'\n')


def art_tables(wall_lights,sprite_lights,wall_units,total_units):
    """Header, then per source color: four wall A/B words and
    four sprite words, 16 bytes, read through the direct page."""
    blob=bytearray(16);struct.pack_into('<HH',blob,0,wall_units,total_units)
    for c in range(256):
        for lights in (wall_lights,sprite_lights):
            for light in range(4):
                a,b=lights[light][c] if lights else (0,0)
                blob.extend((a,b))
    return blob


def pack_level(level,pages,sprite_start,colors,colorinfo,out,levels_index):
    out.mkdir(parents=True,exist_ok=True)
    tiles=level['planes'][0];objects=level['planes'][1]
    wall_tiles={material for t in tiles if (material:=wall_material(t)) is not None}
    if 21 in tiles:wall_tiles.add(22)  # only an unflagged elevator switch can be used
    needed=sorted({p for t in wall_tiles for p in (2*(t-1),2*(t-1)+1)} | set(range(sprite_start-8,sprite_start)))
    needed=[p for p in needed if len(pages[p])==4096]
    cfg=config();stride=2
    if (cfg['colors'],cfg['pixels'],cfg.get('scaler'))!=('four','pair','rows'):
        raise ValueError('lit atlases need COLORS=four PIXELS=pair SCALER=rows')
    # One 8-bit source index per texel; identical columns are stored once.
    # Lit A/B copies are made on the IIgs when the floor loads.
    unique={};index=bytearray();texptr=[0]*memmap.WALL_PAGE_COUNT;texbank=[0]*memmap.WALL_PAGE_COUNT
    directory=bytearray();columns={}
    for slot,page in enumerate(needed):
        texptr[page]=slot*256;columns[page]=[]
        for u in range(64):
            key=bytes(pages[page][u*64:(u+1)*64])
            if key not in unique:unique[key]=len(index);index.extend(key)
            address=memmap.ART_BASE+unique[key]*2
            columns[page].append(address)
            directory.extend(struct.pack('<HH',address&65535,address>>16))
    if memmap.COLUMN_DIR+len(directory)>memmap.COLUMN_DIR_END:raise ValueError('column directory overflow')
    (out/'art-index.bin').write_bytes(index)
    (out/'column-dir.bin').write_bytes(directory)
    (out/'art-tables.bin').write_bytes(art_tables(colorinfo['wall_lights'],None,len(index)//64,len(index)//64))
    tilemap=bytearray(4096); doors=[]
    for y in range(64):
        for x in range(64):
            tile=tiles[y*64+x]
            if 90<=tile<=101:
                tilemap[x*64+y]=128+len(doors)
                doors.append(dict(x=x,y=y,vertical=(tile%2==0),lock=(tile-90)//2))
            else: tilemap[x*64+y]=tile if wall_material(tile) is not None else 0
    # Gameplay rays (lsight.s) test no map edge. A ray that leaves the map from
    # an open cell in row 63 reads row 0 (index x*64+64), which stays solid.
    reachable = None
    protected = set()
    if PROFILE.spear:
        from native_map_format import potentially_reachable, pushwall_protected_borders
        from map_semantics import MapSemantics
        semantics = MapSemantics(PROFILE.resource('map_semantics'))
        reachable = potentially_reachable(level['planes'], semantics)
        holes = {y*64+x for i in range(64) for x,y in ((0,i),(63,i),(i,0),(i,63))
                 if tilemap[x*64+y] == 0 and y*64+x in reachable}
        if holes:
            protected = pushwall_protected_borders(level['planes'], semantics, holes)
    for i in range(64):
        for x,y in ((0,i),(63,i),(i,0),(i,63)):
            if reachable is not None and (y*64+x not in reachable or y*64+x in protected):
                continue        # Source padding behind permanently closed walls.
            hole=y==63 and 1<=x<=60 and tilemap[x*64+y]==0
            if not (wall_material(tilemap[x*64+y]) is not None or hole) or objects[y*64+x]==98:
                raise ValueError('map border cell %d,%d is open; gameplay rays have no map-edge test'%(x,y))
    (out/'map.bin').write_bytes(tilemap)
    starts=[(i%64,i//64,t) for i,t in enumerate(objects) if 19<=t<=22]
    assert len(starts)==1
    x,y,t=starts[0]; spawn=dict(x=x*256+128,y=y*256+128,angle=((1-(t-19))*256)%1024)
    source_palette=palette()
    ceiling_slot=solid_index(source_palette[floor_ceiling(levels_index)],colors,CONVERSION['world'])
    floor_slot=solid_index(source_palette[floor_color()],colors,CONVERSION['world'])
    metadata=dict(name=level['name'],level_index=levels_index,pixels=cfg['pixels'],spawn=spawn,doors=doors,textures=needed,palette=colors,ceiling=ceiling_slot,floor=floor_slot,border=8,texel_stride=stride,column_addresses={str(p):a for p,a in columns.items()},directory_offsets={str(p):texptr[p] for p in needed},wall_index_bytes=len(index))
    if len(doors)>64:raise ValueError('source door limit')
    (out/'map.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata,texptr,texbank


def main():
    OUT.mkdir(parents=True,exist_ok=True);(ROOT/'build/gen').mkdir(exist_ok=True)
    levels=maps();pages,sprite_start,_=vswap();pal=palette()
    cfg=config();selected=cfg['floor']-1
    for n,level in enumerate(levels):
        from shared_gray import floor_record
        colorinfo=floor_record(ROOT/'build/palettes'/(str(n)+'.json'))
        colors=colorinfo['palette']
        out=ROOT/'build/levels'/str(n)
        meta,pointers,banks=pack_level(level,pages,sprite_start,colors,colorinfo,out,n)
        print(meta['name'],'doors',len(meta['doors']),'wall index',meta['wall_index_bytes'],'bytes')
        if n==selected:
            metadata,texptr,texbank=meta,pointers,banks
            active=out
    for path in active.iterdir():
        if path.is_file():shutil.copyfile(path,OUT/path.name)
    colors=metadata['palette']
    spawn=metadata['spawn'];doors=metadata['doors']
    table=bytearray(0x4000)
    def place(addr,data): table[addr-0x4000:addr-0x4000+len(data)]=data
    angles=[a*math.tau/1024 for a in range(1024)]
    cs=[math.cos(a) for a in angles]; sn=[-math.sin(a) for a in angles]
    place(0x4000,words([round(c*256) for c in cs])); place(0x4800,words([round(c*256) for c in sn]))
    place(0x5000,bytes((int(c<0)|int(s<0)*2) for c,s in zip(cs,sn)))
    place(0x5400,words([min(65535,round(256/max(abs(c),1e-9))) for c in cs]))
    place(0x5c00,words([min(65535,round(256/max(abs(s),1e-9))) for s in sn]))
    place(0x6400,words([round(abs(c)*256) for c in cs])); place(0x6c00,words([round(abs(s)*256) for s in sn]))
    (OUT/'tables.bin').write_bytes(table[:4096])
    low=bytearray(65536); high=bytearray(65536)
    for a in range(256):
        for b in range(256):
            p=a*b; i=(a<<8)|b; low[i]=p&255; high[i]=p>>8
    (OUT/'mullo.bin').write_bytes(low); (OUT/'mulhi.bin').write_bytes(high)
    lines=[' .section gamedata, data, root','texBase: .word '+','.join(str(v) for v in texptr),'texBank: .byte '+','.join(str(v) for v in texbank),f'spawnX .equ {spawn["x"]}',f'spawnY .equ {spawn["y"]}',f'spawnAngle .equ {spawn["angle"]}',f'CEILING .equ {metadata["ceiling"]*17}',f'FLOOR .equ {metadata["floor"]*17}',f'DOORWALL .equ {sprite_start-8}', 'texOffsets: .word '+','.join(str(i*4) for i in range(64)), 'viewPal: .word '+','.join(str((round(r/17)<<8)|(round(g/17)<<4)|round(b/17)) for r,g,b in colors)]
    for name,values in [('doorTile',[d['x']*64+d['y'] for d in doors]),('doorOrient',[int(d['vertical']) for d in doors])]:
        lines.append(name+': .word '+','.join(str(v) for v in values+[0]*(64-len(values))))
    lines.append(f'DOORCOUNT .equ {len(doors)}')
    (ROOT/'build/gen/asset_constants.inc').write_text('\n'.join(line for line in lines if '.equ' in line)+'\n')
    (ROOT/'build/gen/assets.inc').write_text('\n'.join(lines)+'\n')
    loadfont(graphics()[1])


if __name__=='__main__': main()
