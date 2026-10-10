"""Check floor-mark coverage, contrast, scaler addresses and stock RAM bounds."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct
from elf import read
from wolfdata import ROOT, palette, sprite, vswap
from viewgeometry import HEIGHTS, SIZES
import pool_cover as pool


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--all-palettes',action='store_true');args=ap.parse_args()
    data,base,_=vswap();native,syms=read(ROOT/'build/wolf.elf')
    banks={s['address']>>16:s['data'] for s in native if s['address'] in (memmap.SCALE3,memmap.SCALE4)}
    rows=(ROOT/'build/assets/rowcode.bin').read_bytes()
    endpoints=(ROOT/'build/assets/sprite-endpoints.bin').read_bytes()
    report=dict(sprites=[],views=list(SIZES),source_sha256=hashlib.sha256((ROOT/'game-data/shareware/VSWAP.WL1').read_bytes()).hexdigest())
    for h in HEIGHTS:
        if h>=64:continue
        hi=HEIGHTS.index(h)
        for y in range(80-h//2,80+h//2):
            address=struct.unpack_from('<H',rows,hi*322+y*2)[0]
            original=banks[3][address:address+7];alternative=banks[4][address:address+7]
            assert original[0]==alternative[0]==0xb9 and original[3:]==alternative[3:]
            tex=(y-(80-h//2))*64//h
            assert struct.unpack_from('<H',alternative,1)[0]==pool.plan().slot.get((h,y),tex)*2+(y&1)
    for floor in (range(10) if args.all_palettes else (2,)):
        floor_index=json.loads((ROOT/f'build/levels/{floor}/map.json').read_text())['floor']
        floor_byte=floor_index*17
        if args.all_palettes:
            records=json.loads((ROOT/f'build/levels/{floor}/sprites.json').read_text())
            lights=json.loads((ROOT/f'build/levels/{floor}/pool-colors.json').read_text())
        for page,feature in pool.pages().items():
            low,high,_=pool.page_endpoints()[page]
            if args.all_palettes:
                if str(page) not in records:continue
                strips=[next((raw for a,b,raw in col if a==low and b==high),None)
                        for col in records[str(page)]['columns']]
            else:
                art=sprite(data[base+page]);columns=[[] for _ in range(64)]
                for x,c in enumerate(art['columns'],art['left']):columns[x]=c
                p=json.loads((ROOT/f'build/palettes/{floor}.json').read_text())
                colors=pool.Colors(p['sprite_lights'],p['palette'],floor_index)
                strips=pool.strips(columns,feature,colors);lights=p['sprite_lights']
            measurements=[]
            for h in range(2,65,2):
                hi=HEIGHTS.index(h);first,last=pool.endpoint_bytes(h,[feature[0]])[feature[0]]
                assert endpoints[hi*256+low]==first and endpoints[hi*256+high]==last
                count=visible=0
                for y in range(first,last):
                    slot=pool.plan().slot[h,y] if h<64 else (y-(80-h//2))*64//h
                    lit=[]
                    for col in range(h//2):
                        x=min(63,round(32768/h)*col//256)
                        byte=floor_byte if strips[x] is None else lights[-1][strips[x][slot]][y&1]
                        lit.append(byte!=floor_byte)
                        count+=(byte>>4==1)+(byte&15==1)
                        visible+=(byte>>4!=floor_index)+(byte&15!=floor_index)
                    if feature[2]=='light' and any(lit):
                        a=lit.index(True);b=len(lit)-list(reversed(lit)).index(True)
                        assert all(lit[a:b]),(feature[3],h,y,'hole in light row')
                measurements.append(dict(height=h,white_pixels=count,visible_pixels=visible))
            first_visible=next(m['height'] for m in measurements if m['visible_pixels'])
            assert all(m['visible_pixels'] for m in measurements if m['height']>=first_visible)
            if feature[2]=='light':
                assert all(a['white_pixels']<=b['white_pixels'] for a,b in zip(measurements,measurements[1:]))
                if floor==2:assert all(m['white_pixels']>0 for m in measurements if m['height']>=8)
            report['sprites'].append(dict(floor=floor,floor_index=floor_index,first_visible_height=first_visible,name=feature[3],source_rows=list(feature[:2]),measurements=measurements))
    report['memory']=[]
    for floor in range(10):
        stats=json.loads((ROOT/f'build/levels/{floor}/sprite-stats.json').read_text())
        assert stats['index_bytes']<=262144
        report['memory'].append(dict(floor=floor,index_bytes=stats['index_bytes'],art_free_bytes=(262144-stats['index_bytes'])*2*len(json.loads((ROOT/f'build/palettes/{floor}.json').read_text())['wall_lights'])))
    for segment in native:
        assert segment['address']+segment['size']<=memmap.FAST_RAM_END
    target=ROOT/('build/pool-all-palettes.json' if args.all_palettes else 'build/pool-check.json');target.write_text(json.dumps(report,indent=2)+'\n');print(target)


if __name__=='__main__':main()
