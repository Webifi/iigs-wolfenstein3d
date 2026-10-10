"""Capture played MIDI notes and fit their emulator output to DOC tables."""
from collections import Counter, defaultdict
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from audio_recipes import debug_midi, render, sha
from game_profile import read_toml
from source_identity import source_bytes
from music_score import midi_notes, midi_read


def power2(n):
    return 1 << math.ceil(math.log2(max(256, n)))


def one_shot(zone):
    # Synth Drum and Gunshot carry their pitch/noise evolution in the capture.
    # A stationary harmonic loop cannot represent that percussion trajectory.
    return zone.drum or zone.notes[0].preset[1] in (118,127) or zone.r.mode not in (1,3)


def minimum_sample_rate(zone):
    """Keep pitched tones above one DOC byte per output sample.

    GM Synth Drum and Gunshot follow the percussion fitting policy even on
    a melodic MIDI channel, as they do in the original instrument converter.
    """
    from audio_fit import DOC_RATE
    if zone.drum or zone.notes[0].preset[1] in (118,127):
        return 6000
    return DOC_RATE*(513/512)/min(sp for n in zone.notes for _,sp in n.freqs)


def note_contexts(data):
    """Keep sounding-state changes distinct, including GS/NRPN messages."""
    _, events = midi_read(data)
    controllers = [dict() for _ in range(16)]
    programs, sysex = [0]*16, []
    bends = [8192]*16
    parameters = [dict() for _ in range(16)]
    selector = [('rpn',127,127)]*16
    result = {}
    for e in events:
        kind, channel = e.raw[0] & 0xf0, e.raw[0] & 15
        if kind == 0xf0 and e.raw[0] != 0xff:
            sysex.append(e.raw.hex())
        elif kind == 0xb0:
            cc, value = e.raw[1:]
            controllers[channel][cc] = value
            if cc in (98,99,100,101):
                family = 'nrpn' if cc in (98,99) else 'rpn'
                msb, lsb = (99,98) if family=='nrpn' else (101,100)
                selector[channel] = (family,controllers[channel].get(msb,127),controllers[channel].get(lsb,127))
            elif cc in (6,38):
                key = selector[channel]
                old = parameters[channel].get(key,(0,0))
                parameters[channel][key] = (value,old[1]) if cc==6 else (old[0],value)
            elif cc in (96,97):
                key=selector[channel]
                old=parameters[channel].get(key,(0,0))
                v=max(0,min(16383,old[0]*128+old[1]+(1 if cc==96 else -1)))
                parameters[channel][key]=(v>>7,v&127)
            elif cc==121:
                controllers[channel]={7:controllers[channel].get(7,100),10:controllers[channel].get(10,64)}
                bends[channel]=8192
        elif kind == 0xc0:
            programs[channel] = e.raw[1]
        elif kind == 0xe0:
            bends[channel] = e.raw[1]+128*e.raw[2]
        elif kind == 0x90 and e.raw[2]:
            result[e.clock140, channel, e.raw[1], e.raw[2]] = (
                programs[channel], tuple(sorted(controllers[channel].items())), tuple(sysex),
                bends[channel], tuple(sorted(parameters[channel].items())))
    return result


class Sampler:
    def __init__(self, recipe, settings, data, doc, out, auto_fit, overrides, preserved=None):
        self.recipe, self.settings, self.data, self.doc = recipe, settings, data, doc
        self.out = Path(out)
        self.notes = midi_notes(data)
        self.source_holds = {(n['clock140'],n['channel']-1,n['key'],n['velocity']):n['end']-n['start']
                             for n in self.notes}
        self.contexts = note_contexts(data)
        from audio_performance_pan import dynamic_keys
        from doccompiler.midiread import read_midi
        self.dynamic_pan_keys=dynamic_keys(read_midi(data)[0])
        self.auto_fit, self.overrides = auto_fit, overrides
        self.cache, self.reports = {}, []
        self.fit_cache, self.compare_cache = {}, {}
        self.comparison_path=self.out/'comparison-cache.json'
        comparison_inputs=[Path(__file__).parent/name for name in
            ('audio_sampling.py','audio_fit.py','audio_context_fit.py','audio_timbre.py','audio_dsp.py')]
        comparison_inputs+=sorted((Path(__file__).parent/'doccompiler').glob('*.py'))
        self.comparison_identity=sha(recipe.read_bytes()+(preserved.model.read_bytes() if preserved else settings.read_bytes())+
            b''.join(source_bytes(p) for p in comparison_inputs))
        if self.comparison_path.exists():
            saved=json.loads(self.comparison_path.read_text())
            if saved.get('code_sha256')==self.comparison_identity:
                self.compare_cache={tuple(k):v for k,v in saved['comparisons']}
        self.timbre_cache = {}
        self.scoring_cache = {}
        self.power_cache = {}
        self.preserved=preserved
        if preserved:
            from audio_intermediate import PreservedSources
            self.track_sources=PreservedSources(self,preserved)
            return
        renderer = read_toml(settings)['renderer']
        executable = (settings.parent/renderer['executable']).resolve()
        roms = (settings.parent/renderer['rom_directory']).resolve()
        self.renderer_sha256 = sha(executable.read_bytes())
        self.rom_inputs = {p.relative_to(roms).as_posix():sha(p.read_bytes()) for p in sorted(roms.rglob('*')) if p.is_file()}
        self.romset = renderer['romset']
        self.track_sources = None
        if doc.get('doc',{}).get('capture_source')=='instrument-track':
            from audio_track_sampling import TrackSources
            self.track_sources=TrackSources(self)

    def render_cached(self, output, part=None, capture=None, hold_seconds=None, probe_key=None, neutral_bend=False):
        data = debug_midi(self.data,self.doc,part,capture,steady=bool(capture),hold_seconds=hold_seconds,probe_key=probe_key,neutral_bend=neutral_bend)
        receipt = output.with_suffix('.json')
        if output.exists() and receipt.exists():
            old = json.loads(receipt.read_text())
            if (old.get('render_requested_midi_sha256',old.get('capture_requested_midi_sha256',old.get('midi_sha256')))==sha(data) and old.get('wav_sha256')==sha(output.read_bytes())
                    and old.get('renderer_sha256')==self.renderer_sha256
                    and old.get('rom_inputs')==self.rom_inputs and old.get('romset')==self.romset
                    and old.get('render_policy', {'reset':'gs','end':'release'} if '-r' in old.get('command',[]) and old['command'][old['command'].index('-r')+1]=='gs' and old['command'][old['command'].index('--end')+1]=='release' else {})==self.doc['render']):
                return
        render(SimpleNamespace(command='wav',recipe=self.recipe,settings=self.settings,
                               out=output,part=part,capture=capture,capture_static=bool(capture),
                               capture_hold_seconds=hold_seconds,capture_probe_key=probe_key,capture_neutral_bend=neutral_bend))

    def references(self):
        if self.preserved:
            # The portable package retains the measured settings, not full
            # song/part renders. Offline builds do not repeat synthesis QA.
            return
        folder = self.out/'reference'
        for channel in [None]+sorted({n['channel'] for n in self.notes}):
            output = folder/('full.wav' if channel is None else f'channel-{channel:02}.wav')
            self.render_cached(output,part=channel)

    def split(self, owner):
        """Choose common played roots, then separate velocity and MIDI context.

        Root selection must not depend on velocity, controllers or note length:
        those captures need a common pitch for their response comparisons.
        Drum keys and explicit per-key overrides remain independent.
        """
        entries=[]
        pitch_families=defaultdict(list)
        for old in owner.zones:
            for n in old.notes:
                context=self.contexts.get((n.on,n.ch,n.key,n.vel))
                if context is None:
                    raise ValueError('missing played MIDI context')
                pinned=any(row['channel']==n.ch+1 and row.get('key',-1)==n.key for row in self.overrides)
                pin=n.key if old.drum or pinned else None
                hold=self.source_holds[n.on,n.ch,n.key,n.vel]
                # Releasing during the attack can change the synth's decay,
                # even at the same pitch and velocity. Keep those actual
                # played articulations distinct before measured sharing.
                articulation=(round(hold*1000) if not old.drum and hold<=owner.q.attack else None)
                timbre=context[:3]+context[4:]
                bank=tuple((cc,value) for cc,value in context[1] if cc in (0,32))
                # Preserve the original converter's multisample boundaries.
                # Two keyboard regions of one program can have different
                # attacks and levels; transposing one capture across their
                # boundary cannot be repaired by a common velocity curve.
                region=getattr(getattr(old,'r',None),'g',{}).get('sampleID')
                family=(n.ch,n.preset,bank,old.drum,pin,region)
                entries.append((old,n,timbre,articulation,pin,family))
                pitch_families[family].append(n)
        roots={}
        for family,notes in pitch_families.items():
            clusters=defaultdict(list)
            first=None
            for key in sorted({n.key for n in notes}):
                if first is None or key-first>11:
                    first=key
                clusters[first].append(key)
            for keys in clusters.values():
                counts=Counter(n.key for n in notes if n.key in keys and n.half==0)
                root=min(counts,key=lambda key:(-counts[key],key))
                for key in keys:
                    roots[family,key]=root
        families=defaultdict(list)
        for old,n,timbre,articulation,pin,family in entries:
            families[n.ch,timbre,articulation,pin,roots[family,n.key],family[-1]].append((old,n))
        zones=[]
        for (channel,context,articulation,pin,root,region),family in families.items():
            hold=(max(self.source_holds[n.on,n.ch,n.key,n.vel] for _,n in family)
                  if articulation is not None else
                  max(1.,max((n.off-n.on)/140*2**((n.key-root)/12) for _,n in family)))
            velocities=defaultdict(list)
            for old,n in family:
                velocities[n.vel].append((old,n))
            for velocity,selected in velocities.items():
                common=Counter(id(old) for old,n in selected).most_common(1)[0][0]
                z=copy.copy(next(old for old,n in selected if id(old)==common))
                z.notes=[n for _,n in selected]
                z.probe_root,z.probe_hold=root,hold
                z.capture_region=region
                z.capture_baked_articulation=articulation is not None
                z.name=f'channel {channel+1}, program {z.notes[0].preset[1]+1}, velocity {velocity}, keys {min(n.key for n in z.notes)}-{max(n.key for n in z.notes)}'
                for n in z.notes:
                    n.z=z
                zones.append(z)
        owner.zones=zones

    def selected_note(self, z):
        played=[n for n in z.notes if n.half==0 and (n.ch+1,n.on,n.key) not in getattr(self,'unavailable_captures',set())]
        if not played:
            raise ValueError('no unambiguous played note in instrument region '+z.name)
        counts = Counter(n.key for n in played)
        key = counts.most_common(1)[0][0]
        possible = [n for n in played if n.key == key]
        n = max(possible, key=lambda x: (x.off-x.on, -x.on))
        # A rare long note at another pitch must not replace the part's usual
        # attack: changing the WAV rate stretches its envelope as well as its
        # pitch. Retain the longest real performance at the most-played key.
        matches = [m for m in self.notes if m['channel'] == n.ch+1 and m['key'] == key]
        for occurrence, note in enumerate(matches, 1):
            if note['clock140'] == n.on and note['velocity'] == n.vel:
                return n, note, occurrence
        raise ValueError('cannot locate the captured note occurrence')

    def capture_source(self, z):
        if hasattr(z,'capture_input'):
            return z.capture_input
        from audio_music import wav_read
        n, note, occurrence = self.selected_note(z)
        root = n.key if z.drum else z.probe_root
        if getattr(self,'track_sources',None):
            target,digest,receipt=self.track_sources.extract(z,note,root)
            rate,channels=wav_read(target)
            lead=round(receipt['lead']*rate)
            dc=[sum(c[:lead])/lead for c in channels]
            source=[(l-dc[0]+r-dc[1])*.5 for l,r in zip(*channels)][lead:]
            hold=receipt['hold_seconds']
            z.probe_hold=hold
            z.capture_input=n,note,occurrence,root,hold,target,digest,rate,source
            return z.capture_input
        held_tone = not one_shot(z)
        hold = (z.probe_hold if getattr(z,'capture_baked_articulation',False) else
                max(z.probe_hold,note['end']-note['start'])) if held_tone else None
        midi = debug_midi(self.data, self.doc, capture=(n.ch+1, n.key, occurrence),steady=True,
                          hold_seconds=hold,probe_key=None if z.drum else root,neutral_bend=not z.drum)
        probe = midi_notes(midi)
        expected = note['channel'],note['program'],note['bank'],root,n.vel
        if len(probe) != 1 or (probe[0]['channel'],probe[0]['program'],probe[0]['bank'],probe[0]['key'],probe[0]['velocity']) != expected:
            raise ValueError('capture probe changed the selected instrument or its MIDI context')
        digest = sha(midi)
        target = self.out/'captures'/(digest+'.wav')
        if digest not in self.cache:
            self.render_cached(target,capture=(n.ch+1,n.key,occurrence),hold_seconds=hold,
                               probe_key=None if z.drum else root,neutral_bend=not z.drum)
            rate, channels = wav_read(target)
            receipt = json.loads(target.with_suffix('.json').read_text())
            lead = round(receipt['lead']*rate)
            quiet = min(lead,round(receipt.get('quiet_lead_seconds',receipt['lead'])*rate))
            dc = [sum(c[lead-quiet:lead])/quiet for c in channels]
            mono = [(l-dc[0]+r-dc[1])*.5 for l,r in zip(*channels)][lead:]
            # Keep the entire audible decay; never shorten to fill a table.
            self.cache[digest] = rate, mono, channels, dc
        rate, source, channels, dc = self.cache[digest]
        z.capture_input = n,note,occurrence,root,hold,target,digest,rate,source
        return z.capture_input

    def prepare(self, owner):
        """Match measured responses before spending RAM on their waveforms."""
        if getattr(self,'track_sources',None):
            self.track_sources.prepare(owner.zones)
            from audio_performance_pan import apply
            apply(owner,self)
        for z in owner.zones:
            n,note,occurrence,root,hold,target,digest,rate,source = self.capture_source(z)
            threshold=max(2/32768,max(map(abs,source))*10**(-owner.q.tail_db/20))
            last=next((i+1 for i in range(len(source)-1,-1,-1) if abs(source[i])>=threshold),1)
            z.measured_source = rate,source[:last]
            for n in z.notes:
                n.capture_audible_seconds=last/rate
                n.capture_reference=(rate,z.measured_source[1],hold,digest)
            z.capture = dict(key=root,velocity=n.vel,controller_context=self.contexts[n.on,n.ch,n.key,n.vel],
                             capture_sha256=sha(target.read_bytes()),program=note['program'],bank=list(note['bank']))
        self.deduplicate(owner)

    def fit_bank(self, owner, budget=180):
        """Spend pages where they improve the measured played instrument most."""
        from audio_context_fit import fit_contexts
        try:
            return fit_contexts(self, owner, budget)
        finally:
            self.save_comparisons()

    def save_comparisons(self):
        if hasattr(self,'comparison_path'):
            self.comparison_path.write_text(json.dumps(dict(code_sha256=self.comparison_identity,
                comparisons=list(self.compare_cache.items())))+'\n')

    def fit_options(self, owner, z, original, per_channel):
        from audio_timbre import score_tone
        variants={}
        pinned_attack=any('attack_seconds' in row and any(
            n.ch+1==row['channel'] and row.get('key',n.key) in (-1,n.key) for n in z.notes)
            for row in self.overrides)
        attacks=[original.attack]
        if not one_shot(z) and not pinned_attack:
            attacks=sorted({original.attack}|{a for a in (.08,.06,.04,.02) if a<original.attack},reverse=True)
        trials=[(attack,None,None) for attack in attacks]
        if one_shot(z):
            owner.build(z)
            # Percussion competes for pages by its measured loss too.
            # A locally best drum cannot reserve the entire bank before
            # the other instruments have offered their alternatives.
            trials=[(original.attack,row['rate'],None) for row in z.capture_fit['attempts']]
        for attack,candidate_rate,allocation_bytes in trials:
            owner.q=copy.copy(original)
            owner.q.attack=attack
            self.candidate_rate=candidate_rate
            self.candidate_allocation=allocation_bytes
            try:
                owner.build(z)
            except ValueError as error:
                if str(error)=='captured melodic attack exceeds its pinned max_bytes':
                    continue
                raise
            finally:
                owner.q=original
                self.candidate_rate=None
                self.candidate_allocation=None
            if z.kind=='attack' and allocation_bytes is None:
                match=z.capture.get('loop',{}).get('instrument_match')
                if match:
                    trials.extend((attack,None,a['bytes']) for a in match['alternatives']
                                  if a['bytes']!=match['selected_allocation'])
            pages=(len(z.table)+255)//256+(len(z.ltable)+255)//256
            if z.kind=='attack' or all(hasattr(n,'capture_reference') for n in z.notes):
                rate,source=z.measured_source
                metrics=score_tone(z,source,rate,self.scoring_cache)
            else:
                metrics=dict(distance=z.capture_fit['chosen']['metrics']['worst_db'])
            weight=sum(1/per_channel[n.ch] for n in z.notes if n.half==0)
            z.capture['representation_match']=metrics
            item=dict(pages=pages,error=metrics['distance']*weight,state=dict(z.__dict__))
            if pages not in variants or item['error']<variants[pages]['error']:
                variants[pages]=item
        if not variants:
            raise ValueError('no captured representation satisfies the sample override: '+z.name)
        print(f'{owner.name}: {z.name}: measured {len(variants)} page sizes',file=sys.stderr,flush=True)
        return [variants[p] for p in sorted(variants)]

    def durations(self, owner):
        """Recolour the measured note intervals, without old SF2 voice cutoffs."""
        for n in owner.notes:
            z=n.z
            reference=getattr(n,'capture_reference',None)
            if reference is not None and z.kind=='attack' and not getattr(z,'capture_envelope_baked_release',False):
                rate,source,held,_=reference
                end=n.off+math.ceil(max(0.,len(source)/rate-held)/n.sp*140)
            else:
                end=(n.on+math.ceil(getattr(n,'capture_audible_seconds',z.capture['source_seconds'])/n.sp*140)
                 if getattr(z,'capture_envelope_baked_release',False) else
                 n.on+math.ceil(z.dur/n.sp*140) if z.kind=='oneshot' else
                 n.off+math.ceil(n.r.release/n.sp*140))
            n.stop=min(owner.length,end)
            if n.r.excl:
                following=[m.on for m in owner.notes if m.ch==n.ch and m.r.excl==n.r.excl and m.on>n.on]
                if following:n.stop=min(n.stop,min(following))

    def tail_level(self, owner, note, tick):
        """Rank an already released voice by its captured audible energy."""
        import mussc
        from audio_fit import curve_value
        z=note.z
        reference=getattr(note,'capture_reference',None)
        rate,source=reference[:2] if reference is not None else z.measured_source
        key=((reference[3],rate,len(source)) if reference is not None else
             (z.capture['capture_sha256'],len(source),z.capture.get('loop',{}).get('bandwidth_hz')))
        if key not in self.power_cache:
            prefix=[0.]
            for v in source:prefix.append(prefix[-1]+v*v)
            self.power_cache[key]=prefix
        prefix=self.power_cache[key]
        def power(seconds):
            lo=max(0,min(len(source),round(seconds*rate)))
            hi=min(len(source),lo+round(.02*rate))
            return max(1e-30,(prefix[hi]-prefix[lo])/max(1,hi-lo))
        seconds=(tick-note.on)/140
        held=(note.off-note.on)/140
        age=seconds*note.sp
        envelope=0.
        if z.kind=='attack' and seconds>held and not getattr(z,'capture_envelope_baked_release',False):
            probe_hold=reference[2] if reference is not None else z.capture['probe_hold_seconds']
            age=probe_hold+(seconds-held)*note.sp
            envelope=10*math.log10(power(max(0.,held*note.sp-.02))/power(max(0.,probe_hold-.02)))
        # A shared table's gain/response corrections are already represented
        # in the note's own capture. Applying them here again mis-ranks tails.
        level=10*math.log10(power(age))+envelope+(0. if reference is not None else getattr(note,'capture_level_db',0.))
        curve=None if reference is not None else getattr(note,'capture_response_curve',None)
        if curve:level-=curve_value(curve,age)
        volume=next(v for t,v in reversed(note.vols) if t<=tick)
        if volume<=0:return -1000.
        level-=mussc.channel_attenuation(owner.name,note.preset,volume)-mussc.channel_attenuation(owner.name,note.preset,note.capture_volume)
        return level+mussc.cal_db(owner.name,note)

    def install(self, owner, z):
        import mussc
        import musdsp
        import capture_tone
        n,note,occurrence,root,hold,target,digest,rate,source = self.capture_source(z)
        shared_variants = z.capture.get('shared_variants',[]) if hasattr(z,'capture') else []
        pinned = [row for row in self.overrides if row['channel']==n.ch+1 and row.get('key', -1) in (-1,n.key)]
        override = pinned[0] if pinned else {}
        bandwidth=override.get('bandwidth_hz')
        trim_key=('trimmed-source',digest,rate,len(source),bandwidth,owner.q.tail_db)
        if trim_key not in self.fit_cache:
            if bandwidth and bandwidth*2.2<rate:
                source=musdsp.resample(musdsp.resample(source,rate,bandwidth*2.2),bandwidth*2.2,rate)
            original_seconds=len(source)/rate
            threshold=max(2/32768,max(map(abs,source))*10**(-owner.q.tail_db/20))
            last=next((i+1 for i in range(len(source)-1,-1,-1) if abs(source[i])>=threshold),1)
            self.fit_cache[trim_key]=source[:last],original_seconds
        source,original_seconds=self.fit_cache[trim_key]
        z.measured_source=(rate,source)
        z.capture_context = True
        z.capture_root = root
        z.capture_bend = n.bends[0][1] if z.drum else 0.
        for played in z.notes:
            played.sp = 1 if z.drum else 2**((played.key-root)/12)
            # Native vibrato and the instrument's pitch envelope are in the
            # capture. Only score bends belong in the runtime pitch stream.
            played.freqs = [(t, played.sp*2**((bend-z.capture_bend)/12)) for t,bend in played.bends]
            played.capture_volume = max(1, played.vols[0][1])
            played.r = copy.copy(played.r)
            played.r.atten = 0
        # The same audible waveform is retained in each attempt; automatic
        # fits may lower a percussion rate, but never truncate its tail.
        requested = override.get('bandwidth_hz', owner.q.f_drum)*2.2
        if one_shot(z):
            minimum = minimum_sample_rate(z)
            from audio_fit import choose_sample, sample_candidates
            # Select against the played instrument once. Shortening melodic
            # attacks must not silently impose a lower percussion rate too.
            maximum = override.get('max_bytes',32768)
            fit_key = (digest,len(source),bandwidth,maximum,override.get('rate'),self.auto_fit,minimum)
            if fit_key not in self.fit_cache:
                options = sample_candidates(source, rate, max_bytes=maximum, rate=override.get('rate'),
                                            auto_fit=self.auto_fit, minimum_rate=minimum,resolution='music')
                attempts = [{k:v for k,v in c.items() if k!='pcm'} for c in options]
                self.fit_cache[fit_key] = choose_sample(options), attempts, options
            chosen, attempts, options = self.fit_cache[fit_key]
            selected_rate=getattr(self,'candidate_rate',None)
            if selected_rate is not None:
                chosen=next(c for c in options if c['rate']==selected_rate)
            requested = chosen['rate']
            table = [(v-128)*chosen['peak']/127 for v in chosen['pcm'][:-1]]
            z.kind = 'oneshot'
            z.loop_len = 0
            z.nat = z.nat_len = 0
            z.morph_basis = None
            z.baked_timpani = True
            z.s_mid = 1
            z.s_min, z.s_max = min(p.sp for p in z.notes), max(p.sp for p in z.notes)
            owner.finish(z, table, None, requested)
            z.capture_fit = dict(chosen={k:v for k,v in chosen.items() if k!='pcm'}, attempts=attempts)
            for played in z.notes:
                played.r.release = 30 # the recording contains the actual release
                played.capture_release = False
        else:
            spec = dict(channel=n.ch+1, key=root, wav=str(target), bytes=4096,
                        rate=rate, loop_start=min(.16, hold*.45), gain_db=0,
                        measured_amplitude=True, release_seconds=max(.01,len(source)/rate-hold),
                        fine_static=True, release_baked=getattr(z,'capture_baked_articulation',False),
                        source_seconds=len(source)/rate, bend_semitones=z.capture_bend,
                        use_spare_attack=True,
                        maximum_bytes=override.get('max_bytes'), requested_rate=override.get('rate'),
                        allocation_bytes=getattr(self,'candidate_allocation',None),
                        bandwidth_hz=bandwidth)
            capture_tone.install(owner,z,spec)
        record = dict(channel=n.ch+1, key=root, source_key=n.key, probe_hold_seconds=hold,
                      program=note['program'],bank=list(note['bank']),
                      velocity=n.vel, occurrence=occurrence,
                      waveform_bend_semitones=z.capture_bend,
                      wav=str(target), capture_sha256=sha(target.read_bytes()), rate=z.rate,
                      bytes=len(z.table), loop_bytes=len(z.ltable), source_seconds=len(source)/rate,
                      original_seconds=original_seconds,tail_threshold_db=owner.q.tail_db,
                      measured_amplitude=True, controller_context=self.contexts[n.on,n.ch,n.key,n.vel],
                      fit=getattr(z,'capture_fit',None), native_response_verified=False,
                      loop=getattr(z,'capture',None), fit_step=owner.fit_step,
                      minimum_read_step=min(p for played in z.notes for t,p in played.freqs)*z.rate/mussc.DOC_RATE,
                      step_one_bytes=power2(len(source)/rate*mussc.DOC_RATE+1),
                      controls='complete played instrument track' if getattr(self,'track_sources',None) else
                               'note-on state; score pitch and level changes applied by the player')
        if getattr(self,'track_sources',None):
            record['track_capture']=json.loads(target.with_suffix('.json').read_text())
        if shared_variants:
            record['shared_variants'] = shared_variants
        z.capture = record
        # Reused notes keep their score lengths. A sampled decay may continue
        # only until the following note needs that voice.
        for voice in sorted({p.voice for p in owner.notes if p.z is z and 0 <= p.voice < 24}):
            notes = sorted((p for p in owner.notes if p.voice == voice), key=lambda p:p.on)
            for i, played in enumerate(notes):
                if played.z is z:
                    stop = notes[i+1].on if i+1<len(notes) else owner.length
                    played.stop = max(played.stop, min(stop, played.on+math.ceil(len(source)/rate/played.sp*140)))
        self.reports.append(record)

    def deduplicate(self, owner):
        """Reuse measured velocity variants only after comparing their output.

        Compare the actual output at one probe pitch for the same program
        and bank. Controller history may include defaults or changes to other
        drum keys; it need not reserve another waveform when the captures
        match. Each note retains its own controls, pan and measured gain.
        The measured tolerance never increases because the bank is full.
        """
        if getattr(owner,'captures_deduplicated',False):
            return
        owner.captures_deduplicated=True
        from audio_fit import match_response, comparable_sources, comparison_holds
        groups=defaultdict(list)
        for z in owner.zones:
            c=z.capture
            n=z.notes[0]
            groups[z.drum,n.preset,tuple(c.get('bank',(0,0))),c['key'],
                   round(z.probe_hold*1000) if getattr(z,'capture_baked_articulation',False) else None].append(z)
        kept=[]
        for zones in groups.values():
            if hasattr(self,'doc'):
                print(f'{self.doc["name"]}: comparing {len(zones)} played captures, channel {zones[0].notes[0].ch+1}',file=sys.stderr,flush=True)
            # The loudest measured compatible capture retains the most signal
            # above the renderer's quantization floor. A common quiet note is
            # not a better template simply because it occurs more often.
            ordered=sorted(zones,key=lambda z:(-z.capture_input[4] if getattr(self,'track_sources',None) and not z.drum else 0,
                           -sum(v*v for v in z.measured_source[1])/max(1,len(z.measured_source[1]))))
            templates=[]
            for z in ordered:
                # Explicit sample settings protect that sound from merging.
                if any(row['channel']==z.notes[0].ch+1 and row.get('key',z.capture['key']) in (-1,z.capture['key']) for row in self.overrides):
                    kept.append(z);continue
                rate,values=z.measured_source
                noise_floor=max(2/32768,max(map(abs,values))*10**(-owner.q.tail_db/20))
                matched=[]
                for main in templates:
                    sr,ref,compared=comparable_sources(main,z)
                    if z.capture['key']!=main.capture['key']:
                        continue
                    key=(main.capture['capture_sha256'],len(ref),z.capture['capture_sha256'],len(values),noise_floor)
                    if key not in self.compare_cache:
                        self.compare_cache[key]=match_response(ref,compared,sr,noise_floor=noise_floor,
                                                               holds=comparison_holds(main,z),
                                                               fundamental=440*2**((z.capture['key']-69)/12))
                    metrics=self.compare_cache[key]
                    if metrics['compatible']:
                        matched.append((metrics['after']['worst_db'],main,metrics))
                if not matched:
                    templates.append(z)
                    kept.append(z)
                    continue
                _,main,metrics=min(matched,key=lambda row:row[0])
                gain=metrics['gain_db']
                for n in z.notes:
                    n.z=main
                    n.capture_level_db=gain
                    n.capture_response_curve=metrics['curve_db']
                    n.capture_response_hold=(None if getattr(main,'capture_baked_articulation',False)
                                             else main.capture_input[4])
                    main.notes.append(n)
                main.capture.setdefault('shared_variants',[]).append(dict(
                    channel=z.notes[0].ch+1,velocity=z.capture['velocity'],gain_db=gain,metrics=metrics,
                    controller_context=z.capture['controller_context'],
                    needs_audition=True))
        owner.zones=kept
        self.save_comparisons()
        for z in kept:
            c=z.capture
            z.name=(f'channel {z.notes[0].ch+1}, program {c["program"]}, reference velocity {c["velocity"]}, '
                    f'keys {min(n.key for n in z.notes)}-{max(n.key for n in z.notes)}')

    def report(self, info=None):
        (self.out/'capture-report.json').write_text(json.dumps(dict(
            source='Roland emulator output under the actual score context',
            captures=[z['capture'] for z in info['zones']] if info else self.reports,
            listening_accepted=False), indent=2)+'\n')
