"""Check binary asset coverage, source note edges, DOC bounds and reset setup."""
import memmap
import hashlib
import json
import os
import struct
from build_sound import OUT, MUSIC_START, event_time
from wolfaudio import ROOT
from wolfaudio import RESIDENT, effects, songs
from music_pack import inspect_song
from wolfdata import PROFILE


def main():
    manifest=json.loads((OUT/'manifest.json').read_text())
    bank=(OUT/'effects.bin').read_bytes()
    levels=json.loads((ROOT/'data/sound/levels.json').read_text())['levels']
    checks=0
    for e in effects():
        address,length,fc,priority,size,pages,level,spare,_=struct.unpack_from('<IHHHBBBBH',bank,e['id']*16)
        assert priority==e['priority'] and spare==0
        assert (level>=48)==bool(address) and level==(levels[str(e['id'])]['level'] if address else 0)
        assert bool(address)==(e['id'] in RESIDENT)
        wave=(OUT/f'effect-{e["id"]:02}.pcm').read_bytes()
        assert wave[-1:]==b'\0' and 0 not in wave[:-1]
        # full 8-bit scale: every table peaks at 127 and the loudness is the level byte
        assert not address or max(abs(b-128) for b in wave[:-1])>=126
        assert len(wave)<=4096 and (pages==0 or len(wave)<=pages*256)
        if address:
            assert length==len(wave) and fc and size==((pages.bit_length()-1)<<3)|7
            assert bank[address-memmap.SFX_BASE:address-memmap.SFX_BASE+length]==wave
        else:
            assert length==0 and pages==0
        checks+=1
    report=[]
    if manifest['format']=='Wolf WDM2 SC55':
        for song in manifest['songs']:
            data=(OUT/f'song-{song["id"]:02}.bin').read_bytes()
            magic=data[:4];base,waves=struct.unpack_from('<HH',data,4)
            assert magic in (b'WDP2',b'WDP3') and len(data)<=65536
            assert 0x4000<=base and base+waves<=0xf400 and waves<=180*256
            assert not song.get('missing_notes') and song.get('held_notes_shortened',0)==0
            assert hashlib.sha256(data).hexdigest()==song['cold_sha256']
            inspect_song(data)
            if magic==b'WDP2':
                start,packed,packed_len,hot=struct.unpack_from('<HHHH',data,8)
                assert start==32 and packed+packed_len==len(data) and packed>=start+waves
            else:
                start,pw,ph,hot,table,block,offset,kind=struct.unpack_from('<8H',data,8)
                assert kind in (0,1,2) and table<=1536 and block in (1024,2048)
                assert os.environ.get('WDP3_HUFFMAN')=='1' or (kind==2 and table==0),f'song {song["id"]} needs the Huffman loader (src/iigs/music_blocks.s, -D WDP3_HUFFMAN=1)'
                assert start+pw==offset and offset+ph==len(data) and hot<65536
            report.append(dict(song=song['id'],notes=song.get('source_notes'),bytes=len(data),hot_bytes=hot,doc_bytes=waves))
        assert {song['id'] for song in manifest['songs']}==set(PROFILE.required_music)
        result=dict(effects=checks,resident=len(RESIDENT),songs=report,failures=[],
                    source_note_receipts_present=all('source_notes' in song and 'missing_notes' in song
                                                    for song in manifest['songs']),
                    audio_quality_verified=False,native_playback_verified=False)
        (OUT/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2));return
    if manifest['format']=='Wolf WCP2 Prince':
        for song in manifest['songs']:
            data=(OUT/f'song-{song["id"]:02}.bin').read_bytes()
            magic,base,waves,pw,ph,hot,total,tree=struct.unpack_from('<4s7H',data)
            assert magic==b'WCP2' and total+32==len(data)<=65536
            assert 0x4000<=base and base+waves<=0xf400
            assert tree<=1020 and tree%4==0 and total==tree+pw+ph
            assert hot<=65536 and not song['missing_notes']
            assert hashlib.sha256(data).hexdigest()==song['cold_sha256']
            report.append(dict(song=song['id'],notes=song['sounded_notes'],bytes=len(data),hot_bytes=hot,doc_bytes=waves))
        result=dict(effects=checks,resident=len(RESIDENT),songs=report,failures=[])
        (OUT/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2));return
    for song in songs():
        data=(OUT/f'song-{song["id"]:02}.bin').read_bytes()
        if not song['ticks']:assert not data;continue
        magic,size,waves,base,count,ticks=struct.unpack_from('<4sHHHHI',data)
        assert magic==b'WDC2' and ticks==song['ticks'] and base==MUSIC_START+size
        cpbase,cpcount=struct.unpack_from('<HH',data,16)
        canonical_base,canonical_count=struct.unpack_from('<HH',data,20)
        assert cpbase==base+waves and canonical_base==cpbase+cpcount*26
        assert len(data)==canonical_base+canonical_count<=65536
        assert waves<=0xb400 and 0 not in data[base:cpbase]
        events=json.loads((OUT/f'song-{song["id"]:02}.events.json').read_text())
        assert len(events['blocks'])==count
        registers=bytearray(256);source_on=[];source_off=[]
        for t,r,v in song['events']:
            old=registers[r];registers[r]=v
            if 0xb0<=r<=0xb8:
                if v&32 and not old&32:source_on.append([t,r-0xb0])
                if old&32 and not v&32:source_off.append([t,r-0xb0])
        assert events['onsets']==source_on and events['noteoffs']==source_off
        actual_on=[];pos=MUSIC_START;volumes=bytearray(24);checkpoints=bytearray();canonical=bytearray()
        block_index=0
        for t,commands in events['blocks']:
            if block_index%32==0:checkpoints+=struct.pack('<H',pos)+volumes
            block_index+=1
            alarm,n=struct.unpack_from('<HB',data,pos);pos+=3
            assert n==len(commands) and bool(alarm)==(t<ticks)
            binary=[list(x) for x in struct.iter_unpack('<BB',data[pos:pos+2*n])];pos+=2*n
            assert binary==commands
            for index,(r,v) in enumerate(commands):
                if 0x44<=r<=0x5b:volumes[r-0x44]=v;canonical.append(v)
                assert r&31 in range(4,13)
                assert r&0xe0 in (0,0x20,0x40,0x80,0xa0)
                if r&0xe0==0x80:assert 0x40<=v<0x40+waves//256
                if r&0xe0==0xa0 and v==3:
                    actual_on.append([t,(r&31)-4])
                    following=commands[index+1:index+6]
                    assert len(following)==5 and following[-1]==[r,0]
                    assert all(a!=r for a,_ in following[:-1])
        assert actual_on==[[event_time(t,ticks),c] for t,c in source_on]
        assert pos==base and data[cpbase:canonical_base]==checkpoints and data[canonical_base:]==canonical
        report.append(dict(song=song['id'],onsets=len(source_on),noteoffs=len(source_off),bytes=len(data),doc_bytes=waves))
    result=dict(effects=checks,resident=len(RESIDENT),songs=report,failures=[])
    (OUT/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
