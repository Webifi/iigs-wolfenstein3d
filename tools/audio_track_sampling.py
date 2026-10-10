"""Capture played note contributions while the entire instrument track runs.

Requires the output-only mixer tap in tools/sc55/track-capture.patch. MIDI,
firmware voice allocation, filters, envelopes and controller timing are never
edited for capture. The retained voice contributions feed the real wet mixer.
"""
import array
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import wave

from audio_recipes import sha
from audio_tracks import verify_part
from game_profile import read_toml
from music_score import midi_notes


def trace_read(path):
    notes, voices, pans, end = {}, {}, {}, None
    for line in path.read_text().splitlines():
        row=line.split()
        if row[0]=='N':
            ordinal,ch,key,velocity,frame=map(int,row[1:])
            notes[ordinal]=dict(channel=ch,key=key,velocity=velocity,frame=frame)
        elif row[0]=='V':
            ordinal,slot,frame,pitch,stop,loop=map(int,row[1:])
            voices.setdefault(ordinal,[]).append(dict(slot=slot,frame=frame,pitch=pitch,stop=stop,loop=loop))
        elif row[0]=='P':
            slot,frame,register=map(int,row[1:])
            pans.setdefault(slot,[]).append((frame,register))
        elif row[0]=='E':
            end=dict(notes=int(row[1]),frames=int(row[2]),register_hash=row[3])
        else:
            raise ValueError('unknown Roland track trace event')
    if not end or end['notes']!=len(notes) or set(voices)-set(notes):
        raise ValueError('Roland trace has an incomplete score or unknown note binding')
    unsafe=set(notes)-set(voices)
    unsafe.update(i+1 for i in tuple(unsafe) if i+1 in notes)
    # The firmware receives MIDI asynchronously. Closely spaced note-ons can
    # reach it before the preceding note's partials start. Keep the complete
    # performance, but never extract a note with an ambiguous ownership tag.
    for ordinal,note in notes.items():
        if ordinal>1 and note['frame']-notes[ordinal-1]['frame']<=3200:
            unsafe.update((ordinal-1,ordinal))
    for ordinal,activations in voices.items():
        onset=notes[ordinal]['frame']
        following=notes.get(ordinal+1,{}).get('frame',end['frames'])
        if any(not onset<=a['frame']<following or a['frame']-onset>3200 for a in activations):
            unsafe.add(ordinal)
    return dict(notes_map=notes,voices=voices,pans=pans,unsafe_notes=sorted(unsafe),**end)


def capture_groups(notes, silence=8.):
    """Pack independent captures into full renders with generous tail spacing."""
    groups=[]
    for ordinal,note in sorted(notes.items(),key=lambda item:item[1]['start']):
        for group in groups:
            if note['start']>=group[-1][1]['end']+silence:
                group.append((ordinal,note));break
        else:
            groups.append([(ordinal,note)])
    return groups


def ac_rms(values):
    """The SC-55 wet mixer can settle to a slightly different idle DC value."""
    center=sum(values)/max(1,len(values))
    return math.sqrt(sum((v-center)**2 for v in values)/max(1,len(values)))


def bind_percussion(parsed):
    """Resolve overlapping drum note-ons from this performance's PCM voices.

    Learn sample signatures from single-key groups, then eliminate those
    signatures from mixed groups. Never guess a drum from a GM sample ID.
    Ambiguous groups remain unavailable for extraction.
    """
    if not parsed['notes_map'] or any(n['channel']!=10 for n in parsed['notes_map'].values()):
        return parsed
    groups=[]
    for ordinal,note in parsed['notes_map'].items():
        if not groups or note['frame']-groups[-1][-1][1]['frame']>3200:
            groups.append([])
        groups[-1].append((ordinal,note))
    activations=[v for vs in parsed['voices'].values() for v in vs]
    signature=lambda v:(v['pitch'],v['stop'],v['loop'])
    rows=[]
    for group in groups:
        first,last=group[0][1]['frame'],group[-1][1]['frame']
        actual=[v for v in activations if first<=v['frame']<=last+3200]
        rows.append((group,actual,{signature(v) for v in actual}))
    mapping={};ambiguous=set()
    for _ in range(256):
        before=(dict(mapping),set(ambiguous))
        for group,actual,signatures in rows:
            if len(actual)!=len(group) or len({n['key'] for _,n in group})!=len(group):
                continue
            keys={n['key'] for _,n in group}
            known={mapping[s] for s in signatures if s in mapping}
            if known-keys:
                # Different drum keys can share PCM pitch and bounds. Remove
                # that signature from the global key classifier; the other
                # voices of an onset may still identify this one uniquely.
                ambiguous.update(s for s in signatures if s in mapping and mapping[s] not in keys)
                mapping={s:k for s,k in mapping.items() if s not in ambiguous}
                known={mapping[s] for s in signatures if s in mapping}
            remaining=keys-known
            if len(remaining)==1:
                key=next(iter(remaining))
                for sig in signatures-mapping.keys()-ambiguous:mapping[sig]=key
        if (mapping,ambiguous)==before:break
    bound={}
    for group,actual,signatures in rows:
        keys=[n['key'] for _,n in group]
        if len(actual)!=len(group) or len(set(keys))!=len(keys):
            continue
        local={id(v):mapping[signature(v)] for v in actual if signature(v) in mapping}
        if not set(local.values())<=set(keys) or len(set(local.values()))!=len(local):continue
        missing=set(keys)-set(local.values())
        unknown=[v for v in actual if id(v) not in local]
        if len(missing)==len(unknown)==1:local[id(unknown[0])]=next(iter(missing))
        if len(local)!=len(actual):continue
        for ordinal,note in group:
            voices=[v for v in actual if local[id(v)]==note['key']]
            if voices and all(note['frame']<=v['frame']<=note['frame']+3200 for v in voices):
                bound[ordinal]=voices
    return dict(parsed,voices=bound,unsafe_notes=sorted(set(parsed['notes_map'])-set(bound)),
                binding='PCM signatures learned from the complete percussion performance')


def score_ordinals(parsed, played):
    """Match simultaneous note-ons by identity, not renderer sort order."""
    from collections import defaultdict,deque
    pending=defaultdict(deque)
    for note in played:pending[note['channel'],note['key'],note['velocity']].append(note)
    result={}
    for ordinal,actual in parsed['notes_map'].items():
        key=actual['channel'],actual['key'],actual['velocity']
        if not pending[key]:raise ValueError('renderer trace differs from the complete MIDI performance')
        note=pending[key].popleft()
        result[note['tick'],note['key'],note['velocity']]=ordinal
    if any(pending.values()):raise ValueError('renderer trace lost MIDI note-ons')
    return result


class TrackSources:
    def __init__(self,sampler):
        self.sampler=sampler
        cfg=read_toml(sampler.settings)['renderer']
        if not cfg.get('track_executable'):
            raise ValueError('instrument-track capture requires renderer.track_executable; see tools/sc55/README.md')
        self.executable=(sampler.settings.parent/cfg['track_executable']).resolve()
        self.renderer_hash=sha(self.executable.read_bytes())
        if cfg.get('track_executable_sha256') and cfg['track_executable_sha256']!=self.renderer_hash:
            raise ValueError('track renderer hash differs from its configuration')
        self.roms=(sampler.settings.parent/cfg['rom_directory']).resolve()
        self.folder=sampler.out/'track-captures'
        self.folder.mkdir(parents=True,exist_ok=True)
        self.baselines={}
        self.outputs={}
        self.ordinals={}
        self.extractions={}

    def retained(self,target,digest,meta):
        from audio_intermediate import note_key
        self.extractions[note_key(meta['played_note'],meta['root_key'])]=(target,digest,meta)
        return target,digest,meta

    def render(self,channel,selected=None):
        sampler=self.sampler
        reference=sampler.out/'reference'/f'channel-{channel:02}.wav'
        midi=reference.with_suffix('.mid')
        tag='baseline' if selected is None else sha(','.join(map(str,selected)).encode())[:20]
        output=self.folder/f'ch{channel:02}-{tag}.wav'
        trace=output.with_suffix('.trace')
        receipt=output.with_suffix('.json')
        activations=([f'{v["frame"]}:{v["slot"]}' for i in selected
                      for v in self.baselines[channel][1]['voices'][i]] if selected is not None else None)
        identity=dict(renderer_sha256=self.renderer_hash,midi_sha256=sha(midi.read_bytes()),
                      rom_inputs=sampler.rom_inputs,romset=sampler.romset,selected_notes=selected,
                      selected_activations=activations,
                      reset=sampler.doc['render']['reset'],mode='whole-track output-only mixer capture v2')
        if receipt.exists() and output.exists() and trace.exists():
            old=json.loads(receipt.read_text())
            if all(old.get(k)==v for k,v in identity.items()) and old['wav_sha256']==sha(output.read_bytes()) and old['trace_sha256']==sha(trace.read_bytes()):
                return output,trace,old
        env=os.environ.copy()
        env.pop('SC55_CAPTURE_NOTES',None)
        env.pop('SC55_CAPTURE_ACTIVATIONS',None)
        env['SC55_CAPTURE_TRACE']=str(trace.resolve())
        if selected is not None:env['SC55_CAPTURE_ACTIVATIONS']=','.join(activations)
        command=[str(self.executable),'-d',str(self.roms),'--romset',sampler.romset,
                 '-r',sampler.doc['render']['reset'],'--end','cut','-f','s16','--quiet',
                 '-o',str(output.resolve()),str(midi.resolve())]
        subprocess.run(command,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1800)
        if not trace.exists():raise ValueError('renderer does not implement the required full-track capture protocol')
        parsed=bind_percussion(trace_read(trace))
        if selected and set(selected).intersection(parsed['unsafe_notes']):
            raise ValueError('selected capture has ambiguous partial ownership')
        played=verify_part(sampler.data,midi.read_bytes(),channel)
        if len(played)!=parsed['notes']:
            raise ValueError('renderer trace lost notes from the complete instrument track')
        score_ordinals(parsed,played)
        identity.update(wav_sha256=sha(output.read_bytes()),trace_sha256=sha(trace.read_bytes()),
                        complete_track_note_count=len(played),register_hash=parsed['register_hash'])
        receipt.write_text(json.dumps(identity,indent=2)+'\n')
        return output,trace,identity

    def prepare(self,zones):
        sampler=self.sampler
        wanted={}
        for zone in zones:
            _,note,_=sampler.selected_note(zone)
            channel=note['channel']
            part=[n for n in sampler.notes if n['channel']==channel]
            ordinal=next(i for i,n in enumerate(part,1) if n['tick']==note['tick'] and n['key']==note['key'] and n['velocity']==note['velocity'])
            zone.track_note_ordinal=ordinal
            wanted.setdefault(channel,{})[ordinal]=note
        from audio_performance_pan import observations
        keys=sampler.dynamic_pan_keys
        if keys:wanted.setdefault(10,{})
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs={pool.submit(self.render,ch):ch for ch in wanted}
            for job in as_completed(jobs):
                channel=jobs[job];output,trace,receipt=job.result()
                reference=sampler.out/'reference'/f'channel-{channel:02}.wav'
                if sha(reference.read_bytes())!=receipt['wav_sha256']:
                    raise ValueError('instrumented renderer changes ordinary Roland playback')
                parsed=bind_percussion(trace_read(trace))
                self.baselines[channel]=trace,parsed
                if channel==10 and keys:sampler.performed_pan=observations(parsed,keys)
                self.ordinals[channel]=score_ordinals(parsed,[n for n in sampler.notes if n['channel']==channel])
                print(f'{sampler.doc["name"]}: channel {channel} full-track renderer is byte-identical',file=sys.stderr,flush=True)
            sampler.unavailable_captures=set()
            for channel,(_,parsed) in self.baselines.items():
                for note in sampler.notes:
                    if note['channel']==channel and self.ordinals[channel][note['tick'],note['key'],note['velocity']] in parsed['unsafe_notes']:
                        sampler.unavailable_captures.add((channel,note['clock140'],note['key']))
            wanted={}
            for zone in zones:
                _,note,_=sampler.selected_note(zone)
                channel=note['channel']
                ordinal=self.ordinals[channel][note['tick'],note['key'],note['velocity']]
                if ordinal in self.baselines[channel][1]['unsafe_notes']:
                    raise ValueError('no unambiguous played capture for the requested note')
                zone.track_note_ordinal=ordinal
                wanted.setdefault(channel,{})[ordinal]=note
            # A changed grouping can still use an earlier full-track render
            # containing the same selected note. Validate that render through
            # the ordinary cache path; do not render the performance again
            # just because another requested note is now in a different group.
            reused=set()
            for channel,notes in wanted.items():
                remaining=set(notes)
                for receipt_path in sorted(self.folder.glob(f'ch{channel:02}-*.json')):
                    old=json.loads(receipt_path.read_text())
                    selected=old.get('selected_notes')
                    if not selected or not remaining.intersection(selected):continue
                    if any(i in self.baselines[channel][1]['unsafe_notes'] for i in selected):continue
                    output,trace,receipt=self.render(channel,selected)
                    if trace.read_bytes()!=self.baselines[channel][0].read_bytes():
                        raise ValueError('cached mixer capture changed the firmware trace')
                    for ordinal in remaining.intersection(selected):
                        self.outputs[channel,ordinal]=output,receipt
                        reused.add((channel,ordinal))
                    remaining.difference_update(selected)
                    if not remaining:break
            groups=[(ch,group) for ch,notes in wanted.items() for group in
                    capture_groups({i:n for i,n in notes.items() if (ch,i) not in reused})]
            print(f'{sampler.doc["name"]}: reusing {len(reused)} verified played-note captures',file=sys.stderr,flush=True)
            jobs={pool.submit(self.render,ch,[i for i,n in group]):(ch,group) for ch,group in groups}
            for done,job in enumerate(as_completed(jobs),1):
                channel,group=jobs[job];output,trace,receipt=job.result()
                if trace.read_bytes()!=self.baselines[channel][0].read_bytes():
                    raise ValueError('mixer capture changed the firmware register or voice trace')
                for ordinal,note in group:self.outputs[channel,ordinal]=output,receipt
                print(f'{sampler.doc["name"]}: complete-track capture {done}/{len(groups)}, channel {channel}, {len(group)} selected notes',file=sys.stderr,flush=True)

    def extract(self,zone,note,root):
        """Crop the selected contribution; normalize pitch by WAV rate only."""
        channel=note['channel'];ordinal=zone.track_note_ordinal
        full,receipt=self.outputs[channel,ordinal]
        identity=dict(track_wav_sha256=receipt['wav_sha256'],trace_sha256=receipt['trace_sha256'],
                      note_ordinal=ordinal,source_key=note['key'],root_key=root,extraction_revision=3,
                      renderer_sha256=self.renderer_hash,
                      voice_activations=self.baselines[channel][1]['voices'][ordinal],
                      note_binding=self.baselines[channel][1].get('binding','separated note-on and partial activation'))
        digest=sha(json.dumps(identity,sort_keys=True).encode())
        target=self.sampler.out/'captures'/(digest+'.wav')
        if target.exists() and target.with_suffix('.json').exists():
            meta=json.loads(target.with_suffix('.json').read_text())
            if meta.get('wav_sha256')==sha(target.read_bytes()):return self.retained(target,digest,meta)
        with wave.open(str(full)) as wav:
            rate=wav.getframerate()
            if (rate,wav.getnchannels(),wav.getsampwidth())!=(64000,2,2):raise ValueError('unexpected track render format')
            frames=wav.getnframes()
            # The trace records the score event's output frame, before the
            # firmware's real MIDI latency and its complete instrument attack.
            onset=self.baselines[channel][1]['notes_map'][ordinal]['frame']
            begin=max(0,onset-round(.05*rate))
            following=[self.baselines[channel][1]['notes_map'][i]['frame'] for i in receipt['selected_notes'] if i>ordinal]
            end=min(following,default=frames)-round(.05*rate) if following else frames
            wav.setpos(begin);values=array.array('h',wav.readframes(end-begin))
            if sys.byteorder!='little':values.byteswap()
        sides=[list(values[c::2]) for c in range(2)];lead=onset-begin
        padding=0
        if lead<1:
            # A score may start at frame zero. The traced interval before its
            # first PCM activation is still idle output, not invented audio.
            # Extend that measured constant prefix so the reducer can use its
            # usual pre-note DC window without changing the played attack.
            quiet=min(v['frame'] for v in self.baselines[channel][1]['voices'][ordinal])-begin
            if quiet<16:raise ValueError('capture has no measured idle interval before its first partial')
            idle=[c[max(0,quiet-64):quiet] for c in sides]
            if any(ac_rms(c)>3 for c in idle):raise ValueError('initial capture prefix is not quiet')
            padding=round(.05*rate)
            sides=[[round(sum(q)/len(q))]*padding+c for c,q in zip(sides,idle)]
            lead=padding
        dc=[sum(c[:lead])/lead for c in sides]
        # An earlier selected note must have died away before this crop.
        if any(math.sqrt(sum((v-d)**2 for v in c[:lead])/lead)>3 for c,d in zip(sides,dc)):
            raise ValueError('capture group has an audible preceding tail; increase its spacing')
        mono=[((a-dc[0])+(b-dc[1]))*.5 for a,b in zip(*sides)]
        peak=max(map(abs,mono[lead:]),default=0)
        if peak<4:raise ValueError('selected full-track note is below the renderer precision floor')
        threshold=max(2.,peak*.0001)
        block=6400;last=lead
        for at in range(lead,len(mono),block):
            chunk=mono[at:at+block]
            if ac_rms(chunk)>threshold:last=at+len(chunk)
        end=min(len(mono),last+block)
        tail=mono[max(lead,end-block):end]
        if ac_rms(tail)>threshold:
            diagnostic=dict(channel=channel,ordinal=ordinal,file=str(full),peak=peak,dc=dc,
                            tail_rms=math.sqrt(sum(v*v for v in tail)/max(1,len(tail))),threshold=threshold,
                            begin=begin,onset=onset,end=begin+end,source_frames=frames)
            (self.folder/'tail-failure.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
            raise ValueError(f'full-track contribution has not reached silence: channel {channel}, note {ordinal}')
        # A rate change maps a real played pitch to the common comparison root.
        # No new note is synthesized and no held duration is invented.
        ratio=2**((note['key']-root)/12)
        new_rate=round(rate/ratio)
        target.parent.mkdir(parents=True,exist_ok=True)
        payload=array.array('h',(max(-32768,min(32767,v)) for frame in zip(*(c[:end] for c in sides)) for v in frame))
        if sys.byteorder!='little':payload.byteswap()
        with wave.open(str(target),'wb') as wav:
            wav.setparams((2,2,new_rate,0,'NONE','not compressed'));wav.writeframes(payload.tobytes())
        meta=dict(identity,wav_sha256=sha(target.read_bytes()),rate=new_rate,lead=lead/new_rate,
                  quiet_lead_seconds=lead/new_rate,hold_seconds=(note['end']-note['start'])*rate/new_rate,
                  source='complete instrument track; output-only voice selection; original MIDI unchanged',
                  source_rate=rate,source_start_frame=begin-padding,source_end_frame=begin+end-padding,
                  padded_idle_frames=padding,
                  renderer_sha256=self.renderer_hash,register_trace_verified=True,
                  rom_inputs=self.sampler.rom_inputs,romset=self.sampler.romset,
                  played_note=note,tail_silence_verified=True,isolated_note_probe=False)
        target.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
        return self.retained(target,digest,meta)
