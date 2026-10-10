"""Render complete mapped instrument tracks and preserve their sampling context."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from audio_recipes import recipe_midi, render
from game_profile import read_toml
from music_score import midi_notes, midi_read


def verify_part(source, rendered, channel):
    """Allow end padding and container changes, but no performance changes."""
    original=[n for n in midi_notes(source) if n['channel']==channel]
    played=midi_notes(rendered)
    fields=('channel','program','bank','key','velocity','tick','end_tick')
    if [[n[k] for k in fields] for n in played]!=[[n[k] for k in fields] for n in original]:
        raise ValueError('instrument-track render changed its notes or instrument assignments')
    source_div,source_events=midi_read(source)
    rendered_div,rendered_events=midi_read(rendered)
    def controls(events):
        return [(e.tick,e.raw) for e in events
                if e.raw[0]&0xf0 not in (0x80,0x90) and e.raw[:2]!=b'\xff\x2f']
    if source_div!=rendered_div or controls(source_events)!=controls(rendered_events):
        raise ValueError('instrument-track render changed its tempo or controller history')
    return played


def track_plan(data):
    """Bind every note to a musical part, not to a source-format instrument ID."""
    notes=midi_notes(data)
    names=read_toml(Path(__file__).resolve().parents[1]/'profiles/audio/gm-programs.toml')['program']
    result=[]
    for channel in sorted({n['channel'] for n in notes}):
        part=[n for n in notes if n['channel']==channel]
        programs=[]
        last=None
        for index,note in enumerate(part,1):
            choice=(note['program'],tuple(note['bank']))
            if choice!=last:
                programs.append(dict(first_note=index,seconds=note['start'],program=choice[0],
                    bank=list(choice[1]),instrument='Standard drum kit' if channel==10 and choice[0]==1
                    else 'Drum kit '+str(choice[0]) if channel==10 else names[str(choice[0])]))
                last=choice
        result.append(dict(channel=channel,programs=programs,note_count=len(part),
                           first_note_seconds=part[0]['start'],last_note_end_seconds=max(n['end'] for n in part),
                           sample_source='complete Roland instrument-track render',
                           isolated_note_substitution=False))
    return result


def tracks(recipe,settings,out):
    data,doc=recipe_midi(recipe)
    out.mkdir(parents=True,exist_ok=True)
    (out/'arrangement.mid').write_bytes(data)
    plan=track_plan(data)
    result=dict(song=doc['name'],arrangement_sha256=hashlib.sha256(data).hexdigest(),
                source_note_count=len(midi_notes(data)),parts=plan,complete=False,
                source='full instrument tracks, including score automation and effects history',
                doc_bank_built=False,listening_accepted=False)
    (out/'tracks.json').write_text(json.dumps(result,indent=2)+'\n')
    for part in plan:
        channel=part['channel'];target=out/f'channel-{channel:02}.wav'
        receipt=render(SimpleNamespace(command='wav',recipe=recipe,settings=settings,out=target,
                                        part=channel,capture=None))
        rendered=(target.with_suffix('.mid')).read_bytes()
        played=verify_part(data,rendered,channel)
        # Non-note events are retained by debug_midi; record them for extraction
        # and later playback comparisons rather than reconstructing note-on state.
        _,events=midi_read(rendered)
        context=[dict(seconds=e.seconds,raw=e.raw.hex()) for e in events
                 if e.raw[0]&0xf0 not in (0x80,0x90) and e.raw[:2]!=b'\xff\x2f']
        part.update(wav=target.name,wav_sha256=receipt['wav_sha256'],
                    midi_sha256=receipt['midi_sha256'],seconds=receipt['seconds'],
                    renderer_sha256=receipt['renderer_sha256'],romset=receipt['romset'],
                    notes=played,controls=context)
        (out/'tracks.json').write_text(json.dumps(result,indent=2)+'\n')
        print(f'{doc["name"]}: channel {channel}, complete track, {len(played)} notes',flush=True)
    result['complete']=True
    (out/'tracks.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    tracks(args.recipe,args.settings,args.out)
