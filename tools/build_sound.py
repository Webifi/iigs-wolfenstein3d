"""Compile source effects into bounded DOC banks and install prepared music."""
import memmap
import argparse
import hashlib
import json
import math
import os
import struct
import wave
from collections import defaultdict
from pathlib import Path
from wolfaudio import DATA, ROOT, NAMES, RESIDENT, DOC_RATE, DIGI, effects, songs, patch, pitch
from doc_song import encode_song, MUSIC_START
from adlib_render import Envelope, attenuation, scale_level, cycle
from effect_size import plan_bytes, reduced_bank
from effect_sources import selected_samples
from music_pack import MusicPack, selected_pack
from wolfdata import PROFILE, source_data
from game_profile import read_toml, fields, integer

OUT=ROOT/'build/sound'
MOD_DB=(0,8,20,48)
SFX_BASE=memmap.SFX_BASE
# Gray code begins at $3AD800 in the current engine. Effect data must end first.
EFFECT_LIMIT=memmap.GRAY_CODE-SFX_BASE
# FC 1096, table 4096, resolution 7. DOC clock 26320 Hz plays at 7042.65625 Hz,
# 0.006% above the Sound Blaster rate 1000000/142.
PLAY_FC=1096
PLAY_RATE=7043
MUSIC_BASE=memmap.MUSIC_BASE
EVENT_QUANTUM=7



def event_time(t,ticks):
    return ticks if t==ticks else min(ticks,((t+EVENT_QUANTUM//2)//EVENT_QUANTUM)*EVENT_QUANTUM)


def compile_song(song):
    if not song['ticks']:
        return b'',dict(id=song['id'],name=song['name'],empty=True)
    registers=bytearray(256)
    grouped=defaultdict(list)
    for t,r,v in song['events']:grouped[t].append((r,v))
    # Preserve original edges in the source ledger; batch after rendering.
    # Silent or unchanged envelope samples create no wake.
    times=sorted(set(grouped)|set(range(0,song['ticks'],35))|{song['ticks']})
    env=[[Envelope(),Envelope()] for _ in range(9)]
    current=[None]*9;waves={};doc=bytearray();blocks=[];previous=0
    onsets=[];offs=[]
    for t in times:
        for c in range(9):
            p=patch(registers,c);fn,bl,_=pitch(registers,c)
            for op in range(2):env[c][op].advance((t-previous)/700,p[op],p[4+op],p[6+op],fn,bl)
        retrigger=set();dirty=set()
        for r,v in grouped[t]:
            old=registers[r];registers[r]=v
            if old!=v:
                if 0xa0<=r<=0xa8 or 0xb0<=r<=0xb8 or 0xc0<=r<=0xc8:dirty.add(r&15)
                for channel,slot in enumerate((0,1,2,8,9,10,16,17,18)):
                    if r&0xe0 in (0x20,0x40,0x60,0x80,0xe0) and r&31 in (slot,slot+3):dirty.add(channel)
            if r==0xbd and v&32:raise ValueError('unexpected rhythm mode')
            if 0xb0<=r<=0xb8:
                c=r-0xb0
                for e in env[c]:e.gate(bool(v&32))
                if v&32 and not old&32:retrigger.add(c);onsets.append((t,c))
                if old&32 and not v&32:offs.append((t,c))
        commands=[]
        for c in range(9):
            if t%35 and c not in dirty and t!=song['ticks']:continue
            p=patch(registers,c);fn,bl,freq=pitch(registers,c);osc=c+4
            if not fn or env[c][1].db>=96 and c not in retrigger:
                if current[c] and current[c][2]:
                    commands.append((0x40+osc,0))
                    current[c]=(current[c][0],current[c][1],0)
                continue
            if p[10]&1:raise ValueError('unexpected additive music patch')
            if c in retrigger:
                for op in range(2):
                    # Resolve the sub-sample attack at the event itself.
                    env[c][op].advance(1/700,p[op],p[4+op],p[6+op],fn,bl)
            level_db=env[c][1].db+scale_level(p[3],fn,bl)
            lfo=(t//35)*35/700
            if p[1]&128:level_db+=(1-math.cos(lfo*math.tau*3.7))*.5
            volume=max(0,min(127,round(127*attenuation(level_db))))
            md=env[c][0].db+scale_level(p[2]&192,fn,bl)
            if p[0]&128:md+=(1-math.cos(lfo*math.tau*3.7))*.5
            variant=min(MOD_DB,key=lambda x:abs(md-x))
            key=(p[0]&15,p[1]&15,p[2]&63,p[8]&3,p[9]&3,p[10],variant)
            if volume and key not in waves:
                page=0x40+len(doc)//256
                if page>=0xff:raise ValueError('instrument wave RAM overflow')
                waves[key]=page;doc+=cycle(p,variant)
            page=waves.get(key,0x40)
            if p[1]&64:freq*=2**(7*math.sin(lfo*math.tau*6.4)/1200)
            fc=round(freq*.5*131072/DOC_RATE)
            if not 0<fc<65536:raise ValueError('DOC pitch range')
            old=current[c]
            new=(fc,page,volume)
            if c in retrigger or old is None:
                commands.extend(((0xa0+osc,3),(osc,fc&255),(0x20+osc,fc>>8),
                                 (0x80+osc,page),(0x40+osc,volume),(0xa0+osc,0)))
            else:
                if fc&255!=old[0]&255:commands.append((osc,fc&255))
                if fc>>8!=old[0]>>8:commands.append((0x20+osc,fc>>8))
                if page!=old[1] and volume:commands.append((0x80+osc,page))
                if volume!=old[2]:commands.append((0x40+osc,volume))
            current[c]=new
        if commands:blocks.append((t,commands))
        previous=t
    if not blocks or blocks[0][0]!=0:blocks.insert(0,(0,[]))
    if blocks[-1][0]!=song['ticks']:blocks.append((song['ticks'],[]))
    # Merge nearby writes without dropping or reordering any note. A 10-ms
    # grid bounds a source edge's displacement to three original IMF ticks.
    merged=[]
    for t,commands in blocks:
        t=event_time(t,song['ticks'])
        if merged and merged[-1][0]==t:merged[-1][1].extend(commands)
        else:merged.append((t,list(commands)))
    blocks=merged
    bounded=[]
    for t,commands in blocks:
        while bounded and t-bounded[-1][0]>140:bounded.append((bounded[-1][0]+140,[]))
        bounded.append((t,commands))
    blocks=bounded
    image,packed=encode_song(blocks,doc,song['ticks'])
    report=dict(id=song['id'],name=song['name'],ticks=song['ticks'],seconds=song['ticks']/700,
                **packed,waves=len(waves),
                event_quantum_ticks=EVENT_QUANTUM,max_source_shift_ms=3*1000/700,
                source_onsets=len(onsets),source_noteoffs=len(offs))
    (OUT/f'song-{song["id"]:02}.events.json').write_text(json.dumps(dict(blocks=blocks,onsets=onsets,noteoffs=offs),separators=(',',':'))+'\n')
    return bytes(image),report


def descriptor_pcm(data):
    """The descriptor stores both lengths in 16 bits."""
    if len(data)<=65535 and sum(2+len(c) for c in effect_chunks(data))<=65535:
        return data
    lo,hi=1,min(len(data),65535)
    while lo<hi:
        mid=(lo+hi+1)//2
        if sum(2+len(c) for c in effect_chunks(data[:mid]))<=65535:lo=mid
        else:hi=mid-1
    return data[:lo]


def effect_chunks(data):
    chunks=[]
    while len(data)>4088 or not chunks and len(data)>1023:
        limit=1023 if not chunks else min(4095,len(data)-1)
        end=min(range(max(1,limit-127),limit+1),key=lambda i:(abs(data[i-1]-128),-i))
        chunks.append(data[:end]+b'\0')
        data=data[end:]
    chunks.append(data+b'\0'*8)
    return chunks


def effect_ranges(path):
    doc=read_toml(path);fields(doc,('format','ranges'),'effect memory')
    integer(doc['format'],1,1,'effect memory format')
    ranges=doc['ranges']
    if not isinstance(ranges,list) or not ranges:raise ValueError('effect memory needs at least one range')
    for i,r in enumerate(ranges):
        fields(r,('name','start','end'),'effect memory range')
        integer(r['start'],0,0xffffff,'effect start');integer(r['end'],r['start']+1,0x1000000,'effect end')
        if r['start']<memmap.GRAY_RECS and r['end']>memmap.GRAY_CODE:
            raise ValueError('effect range overlaps resident gray code/index at $3AD800-$3B07FF')
        if any(r['start']<p['end'] and r['end']>p['start'] for p in ranges[:i]):
            raise ValueError('effect ranges overlap')
    if ranges[0]['start']!=SFX_BASE or ranges[0]['end']-SFX_BASE<1456:
        raise ValueError('first effect range must hold descriptors and plan at $390000')
    return ranges


def effect_image(reduced, plan, resident, ranges):
    """Keep the descriptor/plan ABI; sample pointers can name separate RAM ranges."""
    chunks=[bytearray(87*16+len(plan))]+[bytearray() for _ in ranges[1:]]
    chunks[0][87*16:]=plan
    addresses={};dedup={}
    for e in reduced:
        data=bytes(e['samples'])+b'\0';address=0
        if e['id'] in resident:
            key=hashlib.sha256(data).digest()
            if key not in dedup:
                for region,chunk in zip(ranges,chunks):
                    if len(chunk)+len(data)<=region['end']-region['start']:
                        dedup[key]=region['start']+len(chunk);chunk+=data;break
                else:
                    raise ValueError(f'effect {e["name"]} does not fit assigned RAM ranges; samples were not lowered')
            address=dedup[key]
        addresses[e['id']]=address
        size=(e['size_code']<<3)|7
        struct.pack_into('<IHHHBBBBH',chunks[0],e['id']*16,address,len(data) if address else 0,
                         e['fc'] if address else 0,e['priority'],size if address else 0,
                         e['pages'] if address else 0,e['level'] if address else 0,0,0)
    return [bytes(c) for c in chunks],addresses


def main():
    global OUT
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=OUT)
    ap.add_argument('--effect-ranges',type=Path,help='registered effect RAM ranges TOML (primary plus optional overflow)')
    ap.add_argument('--effect-limit',type=lambda n:int(n,0),default=EFFECT_LIMIT,help='reserved native effect bytes at $390000; default ends before current gray code')
    ap.add_argument('--effect-samples',type=Path,help='preserved effects/ym3812 directory with samples.toml (default: audio-source for the selected game)')
    source=ap.add_mutually_exclusive_group()
    source.add_argument('--imf',action='store_true')
    source.add_argument('--music-pack',type=Path,default=selected_pack(),help='prepared music folder or pack.toml')
    args=ap.parse_args()
    if not 1456 <= args.effect_limit <= 0x50000:
        raise ValueError('effect-limit must be 1456..327680 bytes')
    if PROFILE.sounds > 87:
        raise ValueError('effect catalog exceeds the native 87-descriptor bank')
    if args.effect_samples:os.environ['WOLF_EFFECT_SAMPLES']=str(args.effect_samples.resolve())
    prepared=None if args.imf else MusicPack(args.music_pack,PROFILE)
    OUT=args.out
    OUT.mkdir(parents=True,exist_ok=True)
    reduced,plans=reduced_bank()
    coverage=None
    from effect_closure import floor_effects
    coverage=floor_effects()
    ranges=(effect_ranges(args.effect_ranges or ROOT/'profiles/audio/effect-memory-wolf3d.toml'))
    resident=set(coverage[0]['effects'])
    plan=plan_bytes(plans[:1])
    chunks,addresses=effect_image(reduced,plan,resident,ranges)
    bank=chunks[0]
    floor_payloads={}
    for entry,plan_row in zip(coverage,plans):
        floor_payloads[entry['floor']]=effect_image(reduced,plan_bytes([plan_row]),set(entry['effects']),ranges)[0]
    rows=[]
    for e in reduced:
        data=bytes(e['samples'])+b'\x00'
        if data[-1]!=0 or 0 in data[:-1] or len(data)>e['pages']*256:
            raise ValueError(f'effect {e["id"]} does not fit its one-shot table')
        (OUT/f'effect-{e["id"]:02}.pcm').write_bytes(data)
        with wave.open(str(OUT/f'effect-{e["id"]:02}.wav'),'wb') as f:
            f.setparams((1,1,max(1,round(e['rate'])),0,'NONE','not compressed'));f.writeframes(data[:-1])
        address=addresses[e['id']]
        rows.append(dict(id=e['id'],name=e['name'],priority=e['priority'],bytes=len(data),
                         table_bytes=e['pages']*256,stream_bytes=len(data),chunks=1,
                         chunk_bytes=[len(data)],rate=round(e['rate']),fc=e['fc'],pages=e['pages'],
                         digitized=e['id'] in DIGI,resident=bool(address),address=address,
                         sha256=hashlib.sha256(data).hexdigest()))
    (OUT/'effects.bin').write_bytes(bank)
    floors=[]
    for entry,plan_row in zip(coverage,plans):
        ident=entry['floor'];parts=floor_payloads[ident]
        name=f'effects-floor-{ident:02d}.bin';load=[]
        for n,(part,region) in enumerate(zip(parts,ranges)):
            if not part:continue
            file=name if n==0 else f'effects-floor-{ident:02d}-overflow-{n:02d}.bin'
            (OUT/file).write_bytes(part)
            load.append(dict(file=file,address=region['start'],bytes=len(part),
                             sha256=hashlib.sha256(part).hexdigest()))
        (OUT/f'effects-floor-{ident:02d}-loads.json').write_text(json.dumps(load,indent=2)+'\n')
        floors.append(dict(floor=ident,file=name,address=SFX_BASE,bytes=len(parts[0]),
                           resident_bytes=sum(map(len,parts)),loads=load,
                           effects=entry['effects'],resources=entry['resources'],reasons=entry['reasons'],
                           pinned=sorted(plan_row['placed']),difficulty_independent=True))
    (OUT/'effects-floors.json').write_text(json.dumps(dict(format=1,profile=PROFILE.key,
        address=SFX_BASE,ranges=ranges,plan_offset=87*16,plan_stride=64,
        plan_records_per_bank=1,maximum_resident_bytes=max(f['resident_bytes'] for f in floors),
        floors=floors),indent=2)+'\n')
    from effect_sources import manifest as effect_manifest
    folder=selected_samples(PROFILE)
    (OUT/'effect-sources.json').write_text(json.dumps(effect_manifest(source_data(),folder),indent=2)+'\n')
    reports=[]
    if args.imf:
        for song in songs():
            data,report=compile_song(song);reports.append(report)
            (OUT/f'song-{song["id"]:02}.bin').write_bytes(data)
    else:
        for song in prepared.songs:
            report=song.report;data=song.data;reports.append(report)
            (OUT/f'song-{report["id"]:02}.bin').write_bytes(data)
    report=dict(format='Wolf WDC2 IMF' if args.imf else 'Wolf WDM2 SC55' if all(s.get('format')=='WDM2' for s in reports) else 'Wolf WCP2 Prince',effects=rows,songs=reports,effects_bytes=max((f['resident_bytes'] for f in floors),default=len(bank)),
                resident_effects=max((len(f['effects']) for f in floors),default=len(RESIDENT)),ram_reserved=6*65536,
                ram_peak=len(bank)+max(s.get('bytes',0) for s in reports),
                doc_layout=dict(effects=[0,16384],instruments=[16384,62464],spare=[62464,65280],timer=[65280,65536]),
                source_hashes={PROFILE.document['files'][n]:hashlib.sha256(source_data().read(n)).hexdigest() for n in ('AUDIOHED','AUDIOT','VSWAP')})
    report.update(floor_local_effects=True,effects_floor_count=len(floors),effect_ranges=ranges,
                  native_layout_verified=False,ram_reserved=sum(r['end']-r['start'] for r in ranges)+65536,
                  ram_peak=report['effects_bytes']+max(s.get('bytes',0) for s in reports))
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    gen=ROOT/'build/gen';gen.mkdir(exist_ok=True)
    (gen/'sound_ids.inc').write_text('\n'.join(f'{name} .equ {i}' for i,name in enumerate(NAMES))+f'\n#define SFX_FLOOR_LOCAL 1\nSFX_FLOORS .equ {len(plans)}\n')
    print(json.dumps({k:report[k] for k in ('effects_bytes','resident_effects','ram_peak','ram_reserved')},indent=2))
    for s in reports:
        if not s.get('empty'):
            print(s['name'],s['bytes'],s['doc_bytes'],
                  str(round(s['wakes_per_second'],2))+' wakes/s' if 'wakes_per_second' in s else 'prepared bank')


if __name__=='__main__':main()
