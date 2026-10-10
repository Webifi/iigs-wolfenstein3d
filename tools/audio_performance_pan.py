"""Preserve performed drum positions when a static sample pan is insufficient.

GS rhythm NRPN 28 uses zero for random pan, not hard left. Those positions
come from the complete Roland performance's PCM mixer trace. The portable
recipe retains only note-ordinal pan adjustments, never a replacement score.
"""
import math


def dynamic_keys(groups):
    selector={True:[127,127],False:[127,127]}
    registered=True
    played=set();values={};dynamic=set()
    for _,events in groups:
        for kind,ch,a,b in events:
            if ch!=9:continue
            if kind=='on':played.add(a)
            elif kind=='ctl':
                if a in (98,99,100,101):
                    registered=a in (100,101)
                    selector[registered][0 if a in (99,101) else 1]=b
                elif a==121:
                    selector={True:[127,127],False:[127,127]}
                    registered=True
                elif a==6 and not registered and selector[False][0]==28:
                    key=selector[False][1]
                    if b==0 or key in played and values.get(key)!=b:dynamic.add(key)
                    values[key]=b
    return dynamic


def position(register):
    """Express the observed signed PCM mixer gains in the DOC pan scale."""
    left,right=register>>8,register&255
    if left>127 or right>127 or not left+right:
        raise ValueError('performed pan requires positive, nonzero PCM gains')
    theta=math.atan2(right,left)*2/math.pi
    return 128*theta if theta<=.5 else 64+126*(theta-.5)


def observations(parsed,keys):
    pans=parsed.get('pans',{})
    if not pans:raise ValueError('dynamic drum pan requires the PCM-pan track renderer; rebuild it with tools/build_track_renderer.py')
    activations={}
    for voices in parsed['voices'].values():
        for voice in voices:activations.setdefault(voice['slot'],[]).append(voice['frame'])
    for starts in activations.values():starts.sort()
    records=[]
    for ordinal,note in parsed['notes_map'].items():
        if note['key'] not in keys:continue
        if ordinal in parsed['unsafe_notes']:
            raise ValueError('cannot bind performed drum pan to an ambiguous PCM activation')
        histories=[]
        for voice in parsed['voices'][ordinal]:
            slot,start=voice['slot'],voice['frame']
            end=next((f for f in activations[slot] if f>start),parsed['frames'])
            history=[]
            for frame,register in pans.get(slot,[]):
                if start<=frame<end:
                    at=round((frame-start)*140/64000)
                    point=[at,position(register)]
                    if history and history[-1][0]==at:history[-1]=point
                    elif not history or history[-1][1]!=point[1]:history.append(point)
            if not history or history[0][0]!=0:
                raise ValueError('PCM pan trace omits the voice attack')
            histories.append(history)
        if not histories or any(h!=histories[0] for h in histories[1:]):
            raise ValueError('layered drum partials need separate performed pan routing')
        records.append(dict(note_ordinal=ordinal,points=histories[0]))
    # Common fixed positions stay readable as one adjustment per drum key.
    # Keep note ordinals only when the performed positions actually differ.
    compact=[]
    for key in sorted(keys):
        same=[r for r in records if parsed['notes_map'][r['note_ordinal']]['key']==key]
        if not same:continue
        if all(r['points']==same[0]['points'] for r in same[1:]):
            compact.append(dict(drum_key=key,points=same[0]['points']))
        else:compact.extend(same)
    return compact


def apply(owner,sampler):
    records=getattr(sampler,'performed_pan',[])
    keys=getattr(sampler,'dynamic_pan_keys',set())
    if not records and not keys:return
    notes=[n for n in sampler.notes if n['channel']==10]
    by_note={};by_key={}
    for row in records:
        if 'drum_key' in row:
            by_key[row['drum_key']]=row['points']
            continue
        note=notes[row['note_ordinal']-1]
        by_note[note['clock140'],note['key'],note['velocity']]=row['points']
    for note in owner.notes:
        if note.ch!=9:continue
        points=by_note.get((note.on,note.key,note.vel),by_key.get(note.key))
        if note.key in keys and points is None:
            raise ValueError('missing performed pan adjustments for drum key '+str(note.key))
        if points is not None:
            note.performed_pan_track=[(note.on+offset,pan) for offset,pan in points if note.on+offset<note.stop]
