"""Verify resident menu chunks and the disks after removing the manual."""
import memmap
import argparse,json,re,struct
from pathlib import Path
from b1 import decode
from elf import read
from mkdisk import picture_order
from shared_gray import picture as align_picture, tally as align_tally
ROOT=Path(__file__).resolve().parents[1]


def disk_files(data):
    files={}
    for block in range(2,6):
        for slot in range(13):
            if block==2 and slot==0:continue
            e=data[block*512+4+slot*39:][:39]
            if e[0]>>4:
                files[e[1:1+(e[0]&15)].decode()]=dict(blocks=int.from_bytes(e[19:21],'little'),size=int.from_bytes(e[21:24],'little'))
    return files


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path);a=ap.parse_args()
    assets=ROOT/'build/assets';raw=(assets/'menu.bin').read_bytes()
    cache=json.loads((assets/'menu-cache.json').read_text())
    regions={}
    for name,start,end,size,region in re.findall(r'^(\w+)\s+([0-9a-f]{6})-([0-9a-f]{6})\s+([0-9a-f]{6})\s+(\w+)\s+\d+$',(ROOT/'build/wolf.lst').read_text(),re.M):
        start,end,size=(int(v,16) for v in (start,end,size))
        r=regions.setdefault(region,dict(bytes=0,start=start,end=end));r['bytes']+=size;r['end']=max(r['end'],end)
    segments,symbols=read(ROOT/'build/wolf.elf')
    for glyphs, bank in (('steelGlyphs',0x0f),('mediumGlyphs',0x0f),('smallGlyphs',0x3f)):
        assert symbols[glyphs]>>16==bank,(glyphs,hex(symbols[glyphs]),'font bank table mismatch')
    assert not ({'HelpScreen','ReadHelpChunk','DrawReadingGlyph','helpPage','f2_g'} & symbols.keys())
    checked_chunks=0
    for i,ptr in enumerate(cache['directory']):
        if ptr:
            r=next(r for r in cache['regions'] if r['start']<=ptr<r['end'])
            encoded=(assets/r['file']).read_bytes()[ptr-r['start']:]
        else:
            if 'pageChunk'+str(i) not in symbols: continue
            ptr=symbols['pageChunk'+str(i)]
            seg=next(s for s in segments if s['address']<=ptr<s['address']+len(s['data']))
            encoded=seg['data'][ptr-seg['address']:]
        got=encoded[:4096] if i in cache['raw_chunks'] else decode(encoded,4096)
        assert got==raw[i*4096:(i+1)*4096].ljust(4096,b'\0'),i
        checked_chunks+=1
    names=[name for number,name in sorted((int(number),name[5:].lower()) for name,_,number in (line.split() for line in (ROOT/'build/gen/menu.inc').read_text().splitlines() if line.startswith('LUMP_')))]
    from frontend.native_assets import title,picture
    native_count=0
    for i,ptr in enumerate(cache['native_directory']):
        if not ptr: continue
        first,count,stage,size=struct.unpack_from('<4H',raw,8+i*8)
        source=raw[first*512:(first+count)*512]
        expected=(picture if names[i].startswith(('preview','portrait','episode')) else title)(source)
        region=next(r for r in cache['regions'] if r['start']<=ptr<r['end'])
        assert region['end']<=region['limit'] and ptr+len(expected)<=region['end']
        assert (assets/region['file']).read_bytes()[ptr-region['start']:][:len(expected)]==expected,names[i]
        native_count+=1
    for i,r in enumerate(cache['regions']):
        assert r['end']<=r['limit']
        for q in cache['regions'][i+1:]: assert r['limit']<=q['start'] or q['limit']<=r['start']
    assert raw[:5]==b'WMNU\x02' and raw[5]==len(names)
    for name,address in (('common',memmap.UI_STAGE),('font',memmap.UI_BOOT_FONT)):
        i=names.index(name);first,count,stage,size=struct.unpack_from('<4H',raw,8+i*8)
        data=(assets/f'ui-boot-{name}.bin').read_bytes()
        assert data==raw[first*512:(first+count)*512],name
        assert len(data)<=4096 and f'ui-boot-{name}.bin@0x{address:06x}' in (assets/'menu-cache-loads.txt').read_text()
    assert (assets/'ui-boot-font.bin').read_bytes().startswith((assets/'frontend-font.bin').read_bytes())
    for i,name in enumerate(names):
        if name not in ('title','credits','pg13','tally','victory','end1','end2'):continue
        first,count,stage,size=struct.unpack_from('<4H',raw,8+i*8)
        source=(ROOT/'build/frontend/native/pages'/(name+'.bin')).read_bytes()
        # Packing stores aligned indices. RGB preservation is checked separately
        # by check_palette_alignment.py; raw source-byte equality is obsolete.
        expected=(align_tally(source,json.loads((ROOT/'build/frontend/native/pages/constants.json').read_text()))
                  if name=='tally' else align_picture(source,name=='victory'))
        assert raw[first*512:first*512+size]==expected,name
    disks={}
    for p in [*sorted((ROOT/'build').glob('disk[1-5].po')),ROOT/'build/wolf-hd.po']:
        data=p.read_bytes();files=disk_files(data);assert 'WOLF.HELP' not in files,p
        assert data[520]<=44,p
        if data[518]==1:assert data[960:1024]==bytes(picture_order()),p
        disks[p.name]=files
    assert not any((assets/n).exists() for n in ('help.bin','help-pack.json','help-range.json'))
    words=json.loads((assets/'ui-words.json').read_text())
    result=dict(regions=regions,disks=disks,menu_cache=cache,words=words,chunks_exact=checked_chunks,native_records_exact=native_count,full_pages_preserved=7,help_symbols=0,help_files=0,build_id=f"{int.from_bytes((ROOT/'build/disk1.po').read_bytes()[944:948],'little'):08X}")
    if a.baseline:
        before=json.loads(a.baseline.read_text())
        result['freed_link_bytes']={k:before['regions'][k]['bytes']-v['bytes'] for k,v in regions.items() if before['regions'][k]['bytes']!=v['bytes']}
        result['removed_file_blocks_per_disk']={k:v['WOLF.HELP']['blocks'] for k,v in before['disks'].items()}
        result['net_used_file_block_reduction']={k:sum(f['blocks'] for f in before['disks'][k].values())-sum(f['blocks'] for f in v.values()) for k,v in disks.items()}
    out=ROOT/'build/frontend/native/asset-proof.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('regions','disks','menu_cache','words')},indent=2))

if __name__=='__main__':main()
