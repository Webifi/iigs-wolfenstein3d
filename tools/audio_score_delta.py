"""Editable source-relative arrangement changes; never a bundled MIDI score.

Note pitches and timing are read from the licensed IMF. Selections reference
one-based notes on an OPL voice. Transposition, timing changes, performance
controls and genuinely added notes are stored separately and explicitly.
"""
from collections import Counter, defaultdict, deque
from difflib import SequenceMatcher
from fractions import Fraction
import hashlib
import statistics
import struct

from music_score import Event, imf_notes, midi_read, vlq


def split_midi(data):
    division,events=midi_read(data)
    active=defaultdict(deque);notes=[];other=[];programs=[1]*16
    for order,event in enumerate(events):
        raw=event.raw;kind=raw[0]&0xf0;channel=(raw[0]&15)+1
        if kind==0xc0:programs[channel-1]=raw[1]+1
        if kind==0x90 and raw[2]:
            active[channel,raw[1]].append(dict(channel=channel,key=raw[1],velocity=raw[2],
                program=programs[channel-1],tick=event.tick,on_order=order,on_track=event.track))
        elif kind==0x80 or kind==0x90 and not raw[2]:
            if active[channel,raw[1]]:
                note=active[channel,raw[1]].popleft()
                note.update(end_tick=event.tick,off_order=order,off_track=event.track,
                            off_velocity=raw[2],off_status=kind)
                notes.append(note)
            else:
                other.append(dict(tick=event.tick,track=event.track,order=order,
                                  channel=channel,stop_key=raw[1],velocity=raw[2],status=kind))
        else:
            row=dict(tick=event.tick,track=event.track,order=order)
            if kind==0xb0:row.update(channel=channel,controller=raw[1],value=raw[2])
            elif kind==0xc0:row.update(channel=channel,program=raw[1]+1)
            elif kind==0xe0:row.update(channel=channel,bend=raw[1]+128*raw[2])
            elif kind==0xd0:row.update(channel=channel,pressure=raw[1])
            elif kind==0xa0:row.update(channel=channel,key_pressure=raw[1],value=raw[2])
            else:
                # Metadata and SysEx contain no played note stream. Keep exact
                # bytes so setup ordering and tempo retain their meaning.
                row['message']=raw.hex(' ')
            other.append(row)
    if any(active.values()):raise ValueError('unterminated MIDI notes')
    return division,sorted(notes,key=lambda n:n['on_order']),other


def match_notes(source,target,drum):
    if not source or not target:return [],0
    a=[n['key'] for n in source];b=[n['key'] for n in target]
    if drum:
        # Onsets, not the GM drum-key assignment, identify the source part.
        if len(a)==len(b):return list(zip(range(len(a)),range(len(b)))),0
        a=[round((n['tick']-source[0]['tick'])/(source[-1]['tick']-source[0]['tick'] or 1)*1000) for n in source]
        b=[round((n['tick']-target[0]['tick'])/(target[-1]['tick']-target[0]['tick'] or 1)*1000) for n in target]
        shifts=[0]
    else:
        shifts={y-x for x,y in zip(a,b)} if len(a)==len(b) else set()
        if len(shifts)==1:
            shift=next(iter(shifts))
            return list(zip(range(len(a)),range(len(b)))),shift
        shifts=range(-36,37)
    best=(0,0,0,[])
    for shift in shifts:
        blocks=SequenceMatcher(None,[k+shift for k in a],b,autojunk=False).get_matching_blocks()
        pairs=[(block.a+i,block.b+i) for block in blocks for i in range(block.size)]
        item=(len(pairs),-abs(shift),shift,pairs)
        if item[:3]>best[:3]:best=item
    pairs=best[3]
    # Equal-sized gaps between matched phrases are changed notes, not a
    # deletion followed by a copied phrase. Retain their source references.
    filled=list(pairs)
    anchors=[(-1,-1)]+pairs+[(len(source),len(target))]
    for (a1,b1),(a2,b2) in zip(anchors,anchors[1:]):
        if a2-a1==b2-b1:
            filled.extend((a1+i,b1+i) for i in range(1,a2-a1))
    return sorted(filled),best[2]


def common(values,default=0):
    return Counter(values).most_common(1)[0][0] if values else default


def derive(raw,midi,pairings=()):
    fm,_,_=imf_notes(raw)
    division,target,controls=split_midi(midi)
    voices={ch:[n for n in fm if n['channel']==ch] for ch in range(1,10)}
    groups=defaultdict(list)
    for note in target:groups[note['channel'],note['key'] if note['channel']==10 else -1].append(note)
    parts=[];selected=added=0
    for (channel,drum_key),notes in sorted(groups.items()):
        candidates=[p['opl_channel'] for p in pairings if p['midi_channel']==channel and
                    p.get('drum_key',-1)==drum_key]
        choices=[]
        for ch in candidates or range(1,10):
            pairs,transpose=match_notes(voices[ch],notes,channel==10)
            choices.append((len(pairs),-(abs(len(voices[ch])-len(notes))),-ch,ch,pairs,transpose))
        _,_,_,ch,pairs,transpose=max(choices,key=lambda v:v[:3])
        source=voices[ch]
        if not pairs:raise ValueError('no source-relative note correspondence for MIDI channel '+str(channel))
        intervals=[Fraction(notes[b2]['tick']-notes[b1]['tick'],source[a2]['tick']-source[a1]['tick'])
                   for (a1,b1),(a2,b2) in zip(pairs,pairs[1:])
                   if source[a2]['tick']>source[a1]['tick'] and notes[b2]['tick']>notes[b1]['tick']]
        time_scale=statistics.median(intervals) if intervals else Fraction(1)
        offset=common([notes[b]['tick']-round(source[a]['tick']*time_scale) for a,b in pairs])
        lengths=[Fraction(notes[b]['end_tick']-notes[b]['tick'],source[a]['end_tick']-source[a]['tick'])
                 for a,b in pairs if source[a]['end_tick']>source[a]['tick']]
        duration_scale=statistics.median(lengths) if lengths else time_scale
        duration_offset=common([notes[b]['end_tick']-notes[b]['tick']-
            round((source[a]['end_tick']-source[a]['tick'])*duration_scale) for a,b in pairs])
        part=dict(source_channel=ch,channel=channel,transpose=transpose,
                  time_scale=[time_scale.numerator,time_scale.denominator],start_offset=offset,
                  duration_scale=[duration_scale.numerator,duration_scale.denominator],duration_offset=duration_offset,
                  velocity=common([n['velocity'] for n in notes]),
                  on_track=common([n['on_track'] for n in notes]),off_track=common([n['off_track'] for n in notes]),
                  off_velocity=common([n['off_velocity'] for n in notes]),off_status=common([n['off_status'] for n in notes]),
                  notes=[],add=[])
        if channel==10:part['drum_key']=drum_key
        matched={b:a for a,b in pairs}
        for b,n in enumerate(notes):
            row=dict(order=[n['on_order'],n['off_order']])
            if b in matched:
                a=matched[b];s=source[a];row['source_note']=a+1
                changes=dict(start_delta=n['tick']-(round(s['tick']*time_scale)+offset),
                    duration_delta=(n['end_tick']-n['tick'])-(round((s['end_tick']-s['tick'])*duration_scale)+duration_offset),
                    key_delta=n['key']-(drum_key if channel==10 else s['key']+transpose))
                row.update({k:v for k,v in changes.items() if v})
                selected+=1
            else:
                row.update(tick=n['tick'],length=n['end_tick']-n['tick'],key=n['key']);added+=1
            for key in ('velocity','on_track','off_track','off_velocity','off_status'):
                if n[key]!=part[key]:row[key]=n[key]
            part['notes' if b in matched else 'add'].append(row)
        parts.append(part)
    form=struct.unpack_from('>H',midi,8)[0]
    doc=dict(format=1,source_sha256=hashlib.sha256(raw).hexdigest(),division=division,midi_format=form,
             selected_notes=selected,added_notes=added,parts=parts,controls=controls)
    restored=reconstruct(raw,doc)
    if [(e.tick,e.track,e.raw) for e in midi_read(restored)[1]]!=[(e.tick,e.track,e.raw) for e in midi_read(midi)[1]]:
        raise ValueError('source-relative arrangement did not preserve the MIDI event performance')
    return doc


def reconstruct(raw,doc):
    if doc['format']!=1:raise ValueError('unsupported source-relative score format')
    if hashlib.sha256(raw).hexdigest()!=doc['source_sha256']:raise ValueError('source-relative score requires its original AdLib source')
    fm,_,_=imf_notes(raw);events=[]
    for p in doc['parts']:
        source=[n for n in fm if n['channel']==p['source_channel']]
        for addition,rows in ((False,p['notes']),(True,p.get('add',[]))):
            for row in rows:
                if addition:tick,length,key=row['tick'],row['length'],row['key']
                else:
                    if not 1<=row['source_note']<=len(source):raise ValueError('source_note is outside its AdLib voice')
                    s=source[row['source_note']-1]
                    tick=round(s['tick']*Fraction(*p['time_scale']))+p['start_offset']+row.get('start_delta',0)
                    length=round((s['end_tick']-s['tick'])*Fraction(*p['duration_scale']))+p['duration_offset']+row.get('duration_delta',0)
                    key=p.get('drum_key',s['key']+p['transpose'])+row.get('key_delta',0)
                ch=p['channel']-1
                for off in (False,True):
                    prefix='off' if off else 'on'
                    status=row.get('off_status',p['off_status']) if off else 0x90
                    velocity=row.get('off_velocity',p['off_velocity']) if off else row.get('velocity',p['velocity'])
                    event=Event(tick+length if off else tick,row.get(prefix+'_track',p[prefix+'_track']),bytes([status+ch,key,velocity]))
                    events.append((row['order'][int(off)],event))
    for row in doc['controls']:
        ch=row.get('channel',1)-1
        if 'controller' in row:raw_event=bytes([0xb0+ch,row['controller'],row['value']])
        elif 'program' in row:raw_event=bytes([0xc0+ch,row['program']-1])
        elif 'bend' in row:raw_event=bytes([0xe0+ch,row['bend']&127,row['bend']>>7])
        elif 'pressure' in row:raw_event=bytes([0xd0+ch,row['pressure']])
        elif 'key_pressure' in row:raw_event=bytes([0xa0+ch,row['key_pressure'],row['value']])
        elif 'stop_key' in row:raw_event=bytes([row['status']+ch,row['stop_key'],row['velocity']])
        else:
            raw_event=bytes.fromhex(row['message'])
            if raw_event[0] not in (0xf0,0xf7,0xff):raise ValueError('only metadata/SysEx may use raw messages')
        events.append((row['order'],Event(row['tick'],row['track'],raw_event)))
    tracks=defaultdict(list)
    for _,event in sorted(events,key=lambda row:row[0]):tracks[event.track].append(event)
    output=b'MThd'+struct.pack('>IHHH',6,doc['midi_format'],len(tracks),doc['division'])
    for track in sorted(tracks):
        body=bytearray();previous=0
        for event in sorted(tracks[track],key=lambda e:e.tick):
            body+=vlq(event.tick-previous)+event.raw;previous=event.tick
        output+=b'MTrk'+struct.pack('>I',len(body))+body
    return output


def write(path,doc):
    """One readable line per selection/change, not opaque packed event data."""
    import json
    def value(v):return json.dumps(v,ensure_ascii=False)
    def scalar(row):return [k+' = '+value(v) for k,v in row.items() if not isinstance(v,list) or not v or not isinstance(v[0],dict)]
    lines=['# Notes come from the matching licensed AdLib source. No original note sequence is stored.',
           '# source_note is one-based within source_channel; omitted source notes are not selected.',
           '# time_scale/duration_scale are rational [numerator, denominator]; deltas use MIDI ticks.',
           '# [[parts]] selects/transforms a voice; add contains only explicitly added notes.',
           '# order preserves simultaneous-event ordering; track preserves original MIDI setup order.']
    lines+=scalar({k:v for k,v in doc.items() if k not in ('parts','controls')})
    for p in doc['parts']:
        lines+=['','[[parts]]']+scalar({k:v for k,v in p.items() if k not in ('notes','add')})
        for key in ('notes','add'):
            lines+=[key+' = [']
            lines+=['  { '+', '.join(k+' = '+value(v) for k,v in row.items())+' },' for row in p[key]]
            lines+= [']']
    for row in doc['controls']:lines+=['','[[controls]]']+scalar(row)
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
