"""Check final played note order, shared IRQ ownership and the audio excerpt."""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import wave

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/sound'
disk_hash=hashlib.sha256((ROOT/'build/disk1.po').read_bytes()).hexdigest()
song=json.loads((ROOT/'build/sound/song-03.events.json').read_text())
onsets=[c for _,c in song['onsets']]
source_seconds=json.loads((ROOT/'build/sound/manifest.json').read_text())['songs'][3]['seconds']
loops={}
provenance={}
for filename in ('played-performance.json','played-effects-performance.json'):
    for scenario in json.loads((OUT/filename).read_text()).values():
        for setting in ('off','on'):
            run=scenario[setting]
            provenance[run['name']]=run
for name in ('sound-parentfix-turn-12','sound-parentfix-walk-12','sound-parentfix-turn-12-effects','sound-parentfix-walk-12-effects'):
    p=ROOT/'build/tests'/name
    result=json.loads((p/'result.json').read_text())
    assert result['disk_sha256']==disk_hash and not result['sound_violations'] and not result['input_dropped']
    log=(p/'mame.log').read_text()
    notes=[(float(t),int(c)) for t,c in re.findall(r'^MUSICNOTE ([\d.]+) (\d+)',log,re.M)]
    assert len(notes)>3*len(onsets)
    assert all(channel==onsets[i%len(onsets)] for i,(_,channel) in enumerate(notes))
    durations=[notes[i][0]-notes[i-len(onsets)][0] for i in range(len(onsets),len(notes),len(onsets))]
    origin=provenance[name]
    assert origin['disk_sha256']==disk_hash and origin['elf_sha256']==result['elf_sha256']
    loops[name]=dict(mame=origin['mame'],mame_sha256=origin['mame_sha256'],onsets_in_order=len(notes),loop_seconds=durations,source_loop_seconds=source_seconds,
                     max_loop_error_percent=max(abs(x/source_seconds-1)*100 for x in durations))

p=ROOT/'build/tests/sound-final-capture'
result=json.loads((p/'result.json').read_text());assert result['disk_sha256']==disk_hash
log=(p/'mame.log').read_text()
sources=list(map(int,re.findall(r'^COLLISION_SOURCE (\d+)',log,re.M)))
assert sorted(sources)==[0,29,30] and not result['sound_violations'] and not result['input_dropped']
ready=float(re.search(r'^READY ([\d.]+)',log,re.M)[1])
with wave.open(str(p/'audio.wav'),'rb') as w:
    rate=w.getframerate();channels=w.getnchannels();assert w.getsampwidth()==2
    w.setpos(round((ready+1)*rate));data=w.readframes(5*rate)
values=[x[0] for x in struct.iter_unpack('<'+'h'*channels,data)]
assert len(values)==5*rate and max(map(abs,values))>100 and not any(abs(v)>=32767 for v in values)
mono=OUT/'music-5s.wav'
with wave.open(str(mono),'wb') as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate)
    w.writeframes(struct.pack('<'+'h'*len(values),*values))
report=dict(played=loops,simultaneous_irq_sources=sources,
            irq_capture=dict(mame=result['mame'],mame_sha256=result['mame_sha256']),
            audio=dict(seconds=len(values)/rate,rate=rate,peak=max(map(abs,values)),
                       mame=result['mame'],mame_sha256=result['mame_sha256'],
                       rms=math.sqrt(sum(v*v for v in values)/len(values)),clipped=0,
                       file=str(mono.relative_to(ROOT)),sha256=hashlib.sha256(mono.read_bytes()).hexdigest()),
            disk_sha256=disk_hash,elf_sha256=result['elf_sha256'],physical_validation=False)
(OUT/'music-playback.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
