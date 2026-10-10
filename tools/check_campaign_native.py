"""Check native campaign routes and generated floor/page gray records."""
import hashlib
import json
import struct
import sys
from pathlib import Path
from build_campaign import ABSENT, END, metadata
from game_profile import PROFILES
from wolfdata import ROOT, PROFILE


def main():
    checked={}
    for key in ('shareware','wolf3d','spear','spear-mission2','spear-mission3'):
        game=PROFILES[key]
        m=metadata(game,{name:2 for name in game.campaign.endings})
        assert [f['index'] for f in m['floors']]==list(range(len(game.campaign.floors)))
        for row in m['floors']:
            assert row['ratio_offset']==END or row['ratio_offset']+8<=m['ratio_bytes']
        checked[key]=len(m['floors'])
    wolf=metadata(PROFILES['wolf3d'],{name:2 for name in PROFILES['wolf3d'].campaign.endings})
    assert [e['start'] for e in wolf['episodes']]==[0,10,20,30,40,50]
    assert [wolf['floors'][i]['normal'] for i in (9,19,29,39,49,59)]==[1,11,27,33,45,53]
    assert all(wolf['floors'][i]['victory']==END for i in (8,18,28,38,48,58))
    assert all(wolf['floors'][i]['victory']==ABSENT for i in (17,59))
    assert wolf['ratio_bytes']==64
    assert [wolf['floors'][i]['ending'] for i in (0,10,20,30,40,50)]==[[0,2],[2,2],[4,2],[6,2],[8,2],[10,2]]
    if PROFILE.key!='wolf3d':
        print(json.dumps(dict(campaigns=checked))); return
    sys.path.insert(0,str(ROOT/'tools/frontend'))
    from gray_pair import pair_table,preview_bytes,words_of
    from shared_gray import picture
    assets=ROOT/'build/assets'; local=json.loads((assets/'gray-local.json').read_text())
    gray=(assets/'graytables.bin').read_bytes(); base=local['base']
    assert len(gray)==local['resident_bytes']<=65536
    assert local['floor_address']+local['floor_bytes']==local['page_address']
    assert local['page_address']+local['page_bytes']==local['page_end']<=base+len(gray)
    if local.get('preview_bytes'):
        start=local['preview_address']-base
        assert start>=local['page_end']-base
        assert gray[start:]==(assets/'gray-preview-records.bin').read_bytes()
    def check_records(ptr,data,colors,address):
        for i,pal in enumerate(colors):
            target=struct.unpack_from('<I',ptr,i*4)[0]
            assert address<=target and target+288<=address+len(data)
            at=target-address
            assert data[at:at+288]==pair_table(pal)+preview_bytes(pal)
    for floor in local['floors']:
        raw=(assets/floor['file']).read_bytes(); n=floor['source_floor']
        tints=(ROOT/f'build/palettes/tints-{n+1}.bin').read_bytes()
        assert raw[:320]==tints
        check_records(raw[320:360],raw[512:],[words_of(tints[i:i+32]) for i in range(0,320,32)],local['floor_address'])
        for item,segment in zip(floor['loads'],floor['segments']):
            payload=(ROOT/item['file']).read_bytes()
            assert item['bytes']==segment['bytes']==len(payload)
            assert item['address']==segment['address']
            assert payload==raw[segment['offset']:segment['offset']+segment['bytes']]
    meta=json.loads((ROOT/'build/gen/campaign.json').read_text())
    menu=(assets/'menu.bin').read_bytes(); constants={}
    for line in (ROOT/'build/gen/menu.inc').read_text().splitlines():
        if line.startswith('LUMP_'):
            name,_,value=line.split(); constants[name[5:].lower()]=int(value)
    cache=json.loads((assets/'menu-cache.json').read_text()); cold=set(cache['disk_chunks'])
    directory=(ROOT/'build/gen/menu-cache.inc').read_text().split('menuCacheDirectory:\n')[1].splitlines()
    page_code=(ROOT/'build/gen/menu-pages.inc').read_text()
    vf,vc,_,_=struct.unpack_from('<4H',menu,8+constants['victory']*8)
    assert not cold.intersection(range(vf//8,(vf+vc+7)//8))
    for n in range(meta['ending_pages']):
        name=f'end{n+1}'; index=constants[name]
        first,count,_,size=struct.unpack_from('<4H',menu,8+index*8)
        data=menu[first*512:(first+count)*512]
        assert size==len(data)==32768+local['ending_packet_bytes']
        ptr=data[32768:32768+64]; records=data[32768+512:]
        check_records(ptr,records,[words_of(data[32256+i*32:32288+i*32]) for i in range(16)],local['page_address'])
        for chunk in range(first//8,(first+count+7)//8):
            assert chunk in cold and directory[chunk].strip()=='.long 0'
            assert f'pageChunk{chunk}:' not in page_code
    assert cache['raw_sha256']==hashlib.sha256(menu).hexdigest()
    report=dict(campaigns=checked,registered_floors=len(local['floors']),ending_pages=meta['ending_pages'],
                menu_sha256=cache['raw_sha256'],gray_resident_bytes=len(gray),
                native_runtime_verified=False)
    (assets/'campaign-native-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
