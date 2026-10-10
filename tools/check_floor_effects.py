"""Validate scattered native effect images against sources, recipes, and closure."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct
from effect_closure import floor_effects
from game_profile import read_toml
from map_semantics import MapSemantics
from music_pack import MusicPack
from wolfdata import ROOT, PROFILE, source_data
from wolfaudio import effects, NAMES


def check(out, music):
    receipt=json.loads((out/'effects-floors.json').read_text())
    manifests=json.loads((out/'manifest.json').read_text())
    levels=json.loads((ROOT/'data/sound/levels.json').read_text())['levels']
    doc=read_toml(ROOT/'profiles/audio/native-effects-wolf3d.toml')
    semantics=MapSemantics(PROFILE.resource('map_semantics'))
    source=source_data(); source_effects=effects(); ids={name:i for i,name in enumerate(NAMES)}
    closure=floor_effects();checked=0;difficulty_checks=0
    for floor,level,wanted in zip(receipt['floors'],source.maps(),closure):
        assert floor['floor']==wanted['floor']
        assert set(floor['effects'])==set(wanted['effects'])
        segments=[]
        for load in floor['loads']:
            data=(out/load['file']).read_bytes();assert len(data)==load['bytes']
            assert hashlib.sha256(data).hexdigest()==load['sha256']
            assert any(r['start']<=load['address'] and load['address']+len(data)<=r['end'] for r in receipt['ranges'])
            assert not (load['address']<memmap.GRAY_RECS and load['address']+len(data)>memmap.GRAY_CODE)
            segments.append((load['address'],data))
        def memory(address,length):
            for base,data in segments:
                if base<=address and address+length<=base+len(data):return data[address-base:address-base+length]
            raise AssertionError('effect pointer outside loaded segments')
        head=memory(memmap.SFX_BASE,1456)
        for e in source_effects:
            address,length,fc,priority,size,pages,volume,spare,reserved=struct.unpack_from('<IHHHBBBBH',head,e['id']*16)
            assert priority==e['priority'] and spare==reserved==0
            assert bool(address)==(e['id'] in floor['effects'])
            if address:
                data=memory(address,length);master=(out/f'effect-{e["id"]:02}.pcm').read_bytes()
                row=manifests['effects'][e['id']]
                assert data==master and data[-1]==0 and 0 not in data[:-1]
                assert 0<length<=4096 and len(data)<=pages*256<=4096
                assert size==((pages.bit_length()-1)<<3)|7 and fc==row['fc']
                assert volume==levels[str(e['id'])]['level']
            else:assert length==fc==size==pages==volume==0
            checked+=1
        plan=head[1392:1456];pool,count=plan[:2];assert count<=31 and pool<=48
        owners={};pinned=[]
        for i in range(count):
            sid,page=plan[2+2*i:4+2*i];pinned.append(sid)
            assert sid in floor['effects'];pages=head[sid*16+11]
            assert page%pages==0 and page+pages<=48
            for n in range(page,page+pages):assert n not in owners;owners[n]=sid
        assert sorted(pinned)==floor['pinned']
        # Independently select map placements at each difficulty, then traverse
        # dependencies; do not reuse the generated floor's reason list here.
        for difficulty in range(4):
            roots=set(semantics.document['always_resources'])
            for plane,words in enumerate(level['planes']):
                for code in set(words):
                    row=semantics.lookup.get((plane,code))
                    if row and row.get('parameters',{}).get('minimum_difficulty',0)<=difficulty and 'resource_id' in row:
                        roots.add(row['resource_id'])
            required=set(doc['common'])
            for resource in semantics.closure(roots):required.update(doc['resources'].get(resource['resource_id'],{}))
            assert {ids[n] for n in required}<=set(floor['effects'])
            difficulty_checks+=1
    assert len(receipt['floors'])==60
    for song in music.songs:
        data=(out/f'song-{song.report["id"]:02}.bin').read_bytes()
        assert data==song.data
    report=dict(floors=60,difficulty_cases=difficulty_checks,descriptors_checked=checked,
                prepared_music_banks_byte_identical=len(music.songs),
                maximum_resident_bytes=max(f['resident_bytes'] for f in receipt['floors']),
                maximum_primary_bytes=max(f['bytes'] for f in receipt['floors']),
                maximum_overflow_bytes=max(sum(l['bytes'] for l in f['loads'][1:]) for f in receipt['floors']),
                native_playback_verified=False,native_layout_verified=False)
    (out/'floor-effects-check.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--music-pack',type=Path,required=True);args=ap.parse_args()
    print(json.dumps(check(args.out,MusicPack(args.music_pack,PROFILE)),indent=2))


if __name__=='__main__':main()
