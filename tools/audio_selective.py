"""Select wet captures for the modeled-sample conversion method.

Keep the model's pitch families and voice allocation. Percussion and strong
filter envelopes use actual played contributions from complete Roland parts.
The emitted selection report identifies the source note and fitting settings.
"""
from collections import Counter
from copy import copy
import json
import math
from pathlib import Path

from audio_sampling import Sampler
from game_profile import read_toml, fields, integer, number
from audio_recipes import sha

POLICY = Path(__file__).resolve().parents[1]/'profiles/audio/sampling-defaults.toml'


class CaptureSelectionError(ValueError):
    """Invalid source selection cannot be repaired by shrinking sample tables."""


def sampling_policy(path=POLICY):
    policy = read_toml(path)
    fields(policy, ('format','capture','heuristics'), 'sampling policy')
    integer(policy['format'],1,1,'sampling policy format')
    fields(policy['capture'], ('drum_keys','melodic_programs','decaying_programs'), 'capture policy')
    for name, values in policy['capture'].items():
        if not isinstance(values,list):
            raise ValueError('sampling '+name+' must be an array')
        for value in values:
            integer(value,0 if name=='drum_keys' else 1,127 if name=='drum_keys' else 128,'sampling '+name)
    policy['heuristics']=dict({'root_search_semitones':3,'minimum_hold_improvement':1.5},
                              **policy['heuristics'])
    fields(policy['heuristics'], ('filter_span_cents','root_search_semitones',
                                 'minimum_hold_improvement'), 'sampling heuristics')
    integer(policy['heuristics']['filter_span_cents'],0,24000,'filter span')
    integer(policy['heuristics']['root_search_semitones'],0,12,'root search')
    number(policy['heuristics']['minimum_hold_improvement'],1,10,'hold improvement')
    return policy


def capture_reason(zone, policy):
    if zone.drum and any(n.key in policy['capture']['drum_keys'] for n in zone.notes):
        return 'percussion: retain the synthesizer attack, decay and room'
    if not zone.drum and any(n.preset[1]+1 in policy['capture']['melodic_programs'] for n in zone.notes):
        return 'established instrument sampling default'
    if any(abs(getattr(layer, 'mod_to_fc', 0)) >= policy['heuristics']['filter_span_cents']
           for note in zone.notes for layer in note.layers):
        return 'filter envelope exceeds the configured modeled-sample range'
    return None


def bound_sustained_capture(spec,meta,key):
    """Keep sustained loops before note-off; a baked decay outlives note-off."""
    if spec.get('release_baked'):
        return
    period=1/(440*2**((key-69)/12))
    spec['loop_start']=min(spec.get('loop_start',.16),max(period,meta['hold_seconds']-2.5*period))
    spec['played_hold_seconds']=meta['hold_seconds']


def sustained_alternative(notes,current,spec,heuristics):
    """Prefer a nearby sustained performance over looping an unfinished attack."""
    held=current['end']-current['start']
    target=spec.get('loop_start',0)
    if 'occurrence' in spec or spec.get('release_baked') or held>=target:
        return current
    choices=[n for n in notes if n['velocity']==current['velocity'] and
             abs(n['key']-spec['key'])<=heuristics['root_search_semitones'] and
             n['end']-n['start']>=held*heuristics['minimum_hold_improvement']]
    if not choices:
        return current
    return min(choices,key=lambda n:(-min(target,round((n['end']-n['start'])*140)/140),
                                     abs(n['key']-spec['key']),n['clock140']))


class SelectiveSampler(Sampler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        spec=self.doc.get('doc',{}).get('sampling_policy')
        self.policy_path=(self.recipe.parent/spec).resolve() if spec else POLICY
        self.policy=sampling_policy(self.policy_path)
        self.mode=self.doc.get('doc',{}).get('capture_selection','automatic')
        if self.mode not in ('listed','automatic'):
            raise ValueError('capture_selection must be listed or automatic')

    def selected_note(self, zone):
        if hasattr(zone,'capture_request'):
            spec=zone.capture_request
            matches=[n for n in self.notes if n['channel']==spec['channel'] and n['key']==spec['key']]
            available=[i for i,n in enumerate(matches,1) if (n['channel'],n['clock140'],n['key']) not in getattr(self,'unavailable_captures',set())]
            if not available:
                raise ValueError('no unambiguous played note for capture root '+str(spec['key']))
            # Old held-probe recipes specify a root, not a real performance
            # occurrence. Pick a played note with a sustained body before
            # fitting its loop. A first short articulation may already be in
            # release at the requested loop start.
            if 'occurrence' in spec:
                occurrence=spec['occurrence']
            elif zone.drum:
                velocity=Counter(matches[i-1]['velocity'] for i in available).most_common(1)[0][0]
                occurrence=next(i for i in available if matches[i-1]['velocity']==velocity)
            else:
                occurrence=max(available,key=lambda i:(round((matches[i-1]['end']-matches[i-1]['start'])*140),-matches[i-1]['clock140']))
            note=matches[occurrence-1]
            if not zone.drum and 'occurrence' not in spec and spec.get('loop_start'):
                played={(n.ch+1,n.on,n.key,n.vel) for n in zone.notes if n.half==0}
                alternatives=[n for n in self.notes if
                    (n['channel'],n['clock140'],n['key'],n['velocity']) in played and
                    (n['channel'],n['clock140'],n['key']) not in getattr(self,'unavailable_captures',set())]
                note=sustained_alternative(alternatives,note,spec,self.policy['heuristics'])
                matches=[n for n in self.notes if n['channel']==spec['channel'] and n['key']==note['key']]
                occurrence=matches.index(note)+1
            n=next(n for n in zone.notes if n.half==0 and n.on==note['clock140'] and n.key==note['key'])
            return n,note,occurrence
        if not zone.drum:
            return super().selected_note(zone)
        played = [n for n in zone.notes if n.half == 0 and (n.ch+1,n.on,n.key) not in getattr(self,'unavailable_captures',set())]
        if not played:
            raise ValueError('no unambiguous drum hit in '+zone.name)
        key, velocity = Counter((n.key, n.vel) for n in played).most_common(1)[0][0]
        n = next(n for n in played if (n.key, n.vel) == (key, velocity))
        matches = [m for m in self.notes if m['channel'] == n.ch+1 and m['key'] == key]
        for occurrence, note in enumerate(matches, 1):
            if note['clock140'] == n.on and note['velocity'] == n.vel:
                return n, note, occurrence
        raise ValueError('selected drum hit is absent from the original MIDI')

    def specifications(self, owner, explicit):
        if not self.track_sources:
            raise ValueError('automatic selective captures require complete instrument tracks')
        selected = []
        rows = []
        for zone in owner.zones:
            reason = capture_reason(zone,self.policy) if self.mode=='automatic' else None
            requested = [row for row in explicit if any(n.ch+1 == row['channel'] and n.key == row['key']
                                 for n in zone.notes)]
            overridden=bool(requested)
            rows.append(dict(name=zone.name, channels=sorted({n.ch+1 for n in zone.notes}),
                             keys=sorted({n.key for n in zone.notes}),
                             method='explicit capture' if overridden else 'Roland capture' if reason else 'sample model',
                             reason=reason))
            if requested:
                # Preserve ordered capture normalization when several source
                # roots belong to one modeled region. The final capture owns
                # its waveform; preceding captures establish its amplitude.
                for request in requested:
                    if 'wav' not in request:
                        chosen=copy(zone)
                        chosen.capture_request=request
                        selected.append(chosen)
            elif reason and not overridden:
                selected.append(zone)
        self.track_sources.prepare(selected)
        from audio_performance_pan import apply
        apply(owner,self)
        captures = []
        for zone in selected:
            _, note, occurrence = self.selected_note(zone)
            path, _, meta = self.track_sources.extract(zone, note, note['key'])
            spec = dict(channel=note['channel'], key=note['key'], wav=str(path),
                        bytes=4096, rate=11000, fine_static=False)
            decaying=not zone.drum and note['program'] in self.policy['capture']['decaying_programs']
            if zone.drum or note['program'] in (119,128):
                # Match the existing model's declared drum bandwidth and tail
                # budget. Report the retained interval beside the full source.
                spec['rate'] = owner.q.f_floor * 2.2
                spec['bytes'] = 1 << math.ceil(math.log2(max(256, spec['rate']*owner.q.drum_max+1)))
            else:
                held = meta['hold_seconds']
                spec.update(loop_start=min(.16, held*.45), loop_bytes=512,
                            release_seconds=max(.01, (meta['source_end_frame']-meta['source_start_frame'])/
                                                meta['source_rate']-meta['lead']-held))
            if decaying:
                spec['release_baked']=True
            if hasattr(zone,'capture_request'):
                spec=dict(zone.capture_request)
                spec['wav']=str(path)
                spec['key']=note['key']
            import mussc
            if mussc.strict_tone(zone):
                bound_sustained_capture(spec,meta,note['key'])
            captures.append(spec)
            for row in rows:
                if row['name'] == zone.name and note['key'] in row['keys']:
                    result=dict(selected_note=note, occurrence=occurrence,
                                complete_track=meta, settings=spec)
                    row.setdefault('captures',[]).append(result)
                    row.update(result)
        (self.out/'capture-selection.json').write_text(json.dumps(rows, indent=2)+'\n')
        self.selection = rows
        return [row for row in explicit if 'wav' in row]+captures
