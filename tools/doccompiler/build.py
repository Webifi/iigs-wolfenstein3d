"""Per-song SC-55 conversion into the WDM2 music stream.

Produces candidates, fit evidence and register streams for native validation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import os
import copy

import unit2
import base_events
from base_events import convert, mussc, musbank, muspan, sf2, read_midi
import wolfpan
import inspect
from source_identity import function_source
from capture_levels import loop_attenuation

_LEVEL_POLICY = mussc.LIFT_MAX, mussc.HEAD, mussc.KNEE
# Scores with very quiet notes can use the native player's final song gain.
# Keep the historical quantization for existing prepared arrangements.
mussc.Q.native_level_range = 0


def held_note_shortened(note):
    """A decaying model can reach its silence threshold while the key is held."""
    if note['kind']=='oneshot' or note['stop']>=note['off']:
        return False
    silent=note.get('model_silent_at')
    return silent is None or note['stop']<silent


def calibrate_register_range(data, requested_lift=None):
    """Use the native song gain to retain precision without changing balance.

    Inspect encoded exponents, before their conversion to eight-bit registers.
    One gain for the complete score puts its loudest part at full scale; no
    exponent clips and explicit silence remains silence at every master level.
    """
    player = unit2.Player(data, symbolic=True)
    levels = []
    volumes=[127]*24
    active=[False]*24
    pairs=set()
    for _ in range(500000):
        _, writes = player.wake()
        levels.extend(value for reg,value in writes
                      if reg & 224 == 64 and 4 <= reg & 31 < 28 and value != 127)
        for reg,value in writes:
            voice=(reg&31)-4
            if not 0<=voice<24:continue
            if reg&224==64:volumes[voice]=value
            elif reg&224==160:active[voice]=not value&1
        for voice in range(0,24,2):
            pair=tuple(volumes[i] if active[i] else 127 for i in (voice,voice+1))
            if pair!=(127,127):pairs.add(pair)
        if not player.y:
            break
    else:
        raise ValueError('song level analysis did not reach its loop boundary')
    if not levels:
        raise ValueError('song contains no audible volume writes')
    minimum = min(levels)
    def volume(level,lift):
        return 0 if level==127 else unit2.volume(max(0,level-lift))
    # Each DOC oscillator has its own eight-bit volume register. A stereo
    # pair is not one oscillator with a shared 255-squared power allowance.
    # Reserve effects voices/RAM in allocation; do not invent a second gain
    # ceiling here that changes the established music level.
    lift=minimum if requested_lift is None else requested_lift
    if type(lift) is not int or not 0<=lift<127:
        raise ValueError('song gain must be an integer from 0 through 126')
    result = bytearray(data)
    result[20] = lift
    return bytes(result), dict(method=('one song gain using the full oscillator register range' if requested_lift is None
                                      else 'explicit song gain from the conversion settings'),
                              level_lift_steps=lift, level_lift_db=lift*6.020599913279624/8,
                              previous_peak_register=unit2.volume(max(0,minimum-data[20])),
                              peak_register=unit2.volume(max(0,minimum-lift)),
                              peak_pair_power=max((sum(volume(v,lift)**2 for v in pair) for pair in pairs),default=0),
                              register_limit=255, clipped_exponents=sum(v<lift for v in levels))

# Captured drum one-shots may use the long-release shortcut.
# A pitched SC-55 capture may instead need a measured, score-triggered release.
_plan=function_source(mussc.ScSong.plan)
_plan=_plan.replace('    def plan(self):','def wolf_plan(self):')
_plan='\n'.join(line[4:] if line.startswith('    ') else line for line in _plan.splitlines())
_needle='if baked and r.release > 1.0:'
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,'if baked and r.release > 1.0 and not getattr(n,"capture_release",False):')
_needle="baked = z.kind == 'oneshot' and (z.drum or getattr(z,'baked_timpani',False))"
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,_needle+" or getattr(z,'capture_held',False)")
_needle='                if db > TAIL_DB:'
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,'                if hasattr(z,"capture_envelope"):\n                    from capture_tone import note_db,envelope_db\n                    if getattr(z,"capture_modeled",False):\n                        if z.capture_envelope_baked_release:db=envelope_db(z,secs*sp)\n                        else:db+=envelope_db(z,min(secs,(off-n.on)*TIC)*sp)\n                    else:db = note_db(z, secs, (off-n.on)*TIC, sp, t>=self.switch_at[id(n)])\n'+_needle)
_needle='if getattr(z,"baked_attack_tics",0):exact.add(sw)'
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,'if getattr(z,"baked_attack_tics",0) or getattr(z,"capture_held",False):exact.add(sw)')
_plan=_plan.replace('                if db > TAIL_DB:', '                db += wolf_measured_envelope(n, secs)\n                if db > TAIL_DB:')
_plan=_plan.replace('                if db > TAIL_DB:', '                db += wolf_response_envelope(n, secs)\n                if db > TAIL_DB:')
# A targeted envelope correction must not silently recalibrate every other
# part through the derived top/lift. Capture and optionally pin its measured
# predecessor's anchor; source defaults remain unchanged without that key.
_anchor_top='    top = min(us) if us else 0.0'
assert _plan.count(_anchor_top)==1
_plan=_plan.replace(_anchor_top, _anchor_top+'\n    if getattr(self,"planning_anchor",None):top=self.planning_anchor["top"]')
_anchor_lift='    self.lift_db = lift * 6.02 / 32.0'
assert _plan.count(_anchor_lift)==1
_plan=_plan.replace(_anchor_lift, '    if self.q.native_level_range:lift=max(0,int(top//16)*16)\n    if getattr(self,"planning_anchor",None):lift=self.planning_anchor["lift"]\n    self.planning_reference=dict(top=top,lift=lift)\n'+_anchor_lift)
_plan=_plan.replace('amp = (n.vel / 127.0) ** 2', 'amp = 1.0 if getattr(z, "capture_context", False) else (n.vel / 127.0) ** 2')
_plan=_plan.replace('dv = channel_attenuation(self.name, n.preset, cv)', 'dv = (channel_attenuation(self.name, n.preset, cv) - channel_attenuation(self.name, n.preset, n.capture_volume)) if getattr(z, "capture_context", False) else channel_attenuation(self.name, n.preset, cv)')
_plan=_plan.replace('base -= cal_db(self.name, n) * 32.0 / 6.02', 'base -= (cal_db(self.name, n) + getattr(n,"capture_level_db",0.0)) * 32.0 / 6.02')
_needle='qs.append((float(base + (16 if t < both else 0) + dv * 32.0 / 6.02), db * 32.0 / 6.02))'
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,'qs.append((float(base + (wolf_loop_attenuation(z,t,self.switch_at[id(n)]) if z.kind=="attack" else 0) + (16 if t < both else 0) + dv * 32.0 / 6.02), db * 32.0 / 6.02))')
mussc.wolf_loop_attenuation=loop_attenuation
_needle='    self.schedule(tracks, exact)'
assert _plan.count(_needle)==1
_plan=_plan.replace(_needle,'''    if self.q.native_level_range:
        # Restore the source scale after envelope and pan quantization. The
        # native song gain is applied later, before eight-bit volume output.
        for voice in tracks:
            for tr in voice:
                for i,value in enumerate(tr[4]):
                    if type(value) is int and value!=MUTE:
                        tr[4][i]=min(MUTE,value+int(lift/4))
    wolf_source_levels(tracks)
'''+_needle)
from audio_plan import accelerate, note_levels
mussc.wolf_note_levels=note_levels
_plan=accelerate(_plan)
exec(compile(_plan,'Doom plan with measured captured-note release','exec'),mussc.__dict__)

_schedule=function_source(mussc.ScSong.schedule)
_schedule='\n'.join(line[4:] if line.startswith('    ') else line for line in _schedule.splitlines())
_schedule=_schedule.replace('def schedule(self, tracks, exact):','def wolf_schedule(self, tracks, exact):',1)
_needle='0 if getattr(n.z,"baked_attack_tics",0) else q.sw_early'
assert _schedule.count(_needle)==1
_schedule=_schedule.replace(_needle,'0 if getattr(n.z,"baked_attack_tics",0) or getattr(n.z,"capture_held",False) else q.sw_early')
exec(compile(_schedule,'Captured attacks switch with their measured envelope','exec'),mussc.__dict__)


_layout=function_source(convert.WolfSong.layout)
_layout='\n'.join(line[4:] if line.startswith('    ') else line for line in _layout.splitlines())
_layout=_layout.replace('[(1, len(zone.table), extras, i)', '[(getattr(zone,"size",256)//256, len(zone.table), extras, i)')
_layout=_layout.replace('def layout(self):','def aligned_layout(self):',1)
exec(compile(_layout,'Wolf aligned filter family layout','exec'),convert.__dict__)

class WolfSong(convert.WolfSong):
    captures = []
    evidence = None
    capture_factory = None
    capture_selector = None
    schedule = mussc.wolf_schedule
    def allocate(self,groups):
        notes=super().allocate(groups)
        # The MUS allocator labels every percussion preset as kit zero.
        # Font.regions already selects the performed MIDI kit; retain that
        # identity for capture grouping and the compiled instrument ledger.
        for note in notes:
            if note.ch==9:note.preset=(128,self.sf.kit)
        return notes
    def __init__(self,name,lump,font,quality,budget=None):
        if not self.capture_factory:
            super().__init__(name,lump,font,quality,budget)
            return
        # Use the shared score allocator, but every waveform and envelope in
        # this path comes from an emulator capture. SF2 regions only describe
        # the starting instrument family and whether its body can sustain.
        self.name,self.sf,self.q=name,font,quality
        groups,self.length=mussc.dmxmus.parse_mus(lump)
        self.extra_tables=[]
        self.notes=self.allocate(groups)
        self.choose()
        self.capture_factory.prepare(self)
        if self.capture_factory.auto_fit:
            self.capture_factory.fit_bank(self,getattr(self.capture_factory,'page_budget',180))
        else:
            for zone in self.zones:self.build(zone)
        self.layout()
        self.capture_factory.durations(self)
        muspan.prepare(self,groups)
        muspan.fixed(self,groups)
        self.plan()
    def choose(self):
        super().choose()
        if self.capture_factory:
            self.capture_factory.split(self)
    def finish(self, z, tab, lt, R):
        if lt and z.notes and z.notes[0].preset[0] != 128 and z.notes[0].preset[1] not in (118,127):
            dc = sum(lt)/len(lt)
            peak = max(map(abs, tab + list(lt))) or 1.
            if abs(dc)*127/peak > .5:
                lt = [v-dc for v in lt]
                # Join the corrected loop without a DC step at the switch.
                join = max(1, round(getattr(z, 'attack', len(tab)/R)*R))
                tab = [v-dc*min(1.,i/join) for i,v in enumerate(tab)]
                z.removed_loop_dc = dc
        result = super().finish(z, tab, lt, R)
        if self.capture_factory and lt:
            # A quiet body must not consume the attack's volume headroom.
            # Both tables use their full byte range; the scheduler changes
            # their measured register gain with the table switch.
            from capture_levels import normalize
            normalize(z)
        return result
    def build(self,z):
        if not self.capture_factory and getattr(self,'capture_loops',False) and hasattr(z,'capture'):
            return
        original = self.q
        chosen = [row for row in self.sample_overrides if any(
            n.ch == row['channel']-1 and (row.get('key', -1) < 0 or n.key == row['key']) for n in z.notes)]
        if len(chosen) > 1:
            raise ValueError('sample overrides overlap for '+z.name)
        if chosen:
            row = chosen[0]
            self.q = copy.copy(self.q)
            if 'attack_seconds' in row:
                self.q.attack = row['attack_seconds']
                z.attack_len = row['attack_seconds']
            if 'bandwidth_hz' in row:
                z.f_keep = row['bandwidth_hz']
                self.q.f_mel = self.q.f_drum = self.q.f_cym = row['bandwidth_hz']
            if 'tail_db' in row:
                self.q.tail_db = row['tail_db']
        try:
            if self.capture_factory:
                self.capture_factory.install(self,z)
            else:
                super().build(z)
        finally:
            self.q = original
    def layout(self):
        if self.capture_factory:
            self.capture_factory.deduplicate(self)
        if self.capture_selector and not getattr(self, '_selected_captures', False):
            self._selected_captures = True
            from audio_selective import CaptureSelectionError
            try:
                self.captures = self.capture_selector.specifications(self, self.captures)
            except ValueError as error:
                raise CaptureSelectionError(str(error)) from error
        if getattr(self,'capture_loops',False) and self.captures and not getattr(self,'_captures_applied',False):
            self._captures_applied=True
            import captured
            captured.install(self,self.captures)
        try:
            return convert.aligned_layout(self)
        finally:
            if self.evidence:
                rows=[dict(name=z.name,program=z.notes[0].preset if z.notes else None,rate=getattr(z,'rate',None),
                    bytes=len(getattr(z,'table',[])),loop_bytes=len(getattr(z,'ltable',[])),
                    keys=sorted({n.key for n in z.notes})) for z in self.zones]
                self.evidence.write_text(json.dumps(rows,indent=2)+'\n')
    def plan(self):
        # Apply explicit captures before scheduling register writes.
        if self.captures and not getattr(self,'_captures_applied',False):
            import captured
            captured.install(self, self.captures)
        # Over-budget candidates cannot be emitted; planning does not change layout.
        if self.low < 64:
            raise ValueError(f"{244-self.low} pages")
        mussc.wolf_plan(self)


def build(midi_path, font_path, folder, name, calibration, quality, capture_policy, auto_fit=True, sample_overrides=(), capture_factory=None, auto_levels=True, capture_selector=None, loop_layout="full", preserved_font=None, source_levels=False, record_sources=True):
    n, sid, label = 0, 0, 'recipe'
    FONT = Path(font_path)
    folder = Path(folder)
    tone_safe, capture_loops, batched = True, True, True
    from source_identity import source_bytes
    build_sources={str(p):hashlib.sha256(source_bytes(p)).hexdigest() for p in Path(__file__).parent.glob('*.py')} if record_sources else {}
    if tone_safe:
        import tone_safe as safe
        if loop_layout not in ('full','repeated-endpoint'):raise ValueError('unknown sample loop layout')
        if getattr(mussc,'wolf_loop_layout',loop_layout)!=loop_layout:
            raise ValueError('different loop layouts require separate compiler processes')
        safe.ALL_L=loop_layout=='full'
        safe.install(mussc)
        mussc.wolf_loop_layout=loop_layout
        WolfSong.loop_layout=loop_layout
    groups, length, metadata = read_midi(midi_path)
    source_groups = groups
    groups, kit, drum_pan = convert.adapt(groups,captured=bool(capture_factory),performed_pan=bool(capture_factory or capture_selector))
    mussc.VOICES = 24
    musbank.VMAX = 255
    muspan.range = lambda *a: range(24) if a == (14,) else range(*a)
    muspan.prepare = wolfpan.prepare
    muspan.levels = wolfpan.levels
    # Apply only corrections supplied for this song; unrelated title or
    # instrument corrections would alter the calibration of other parts.
    cal = calibration or {}
    mussc.wolf_calibration=cal
    # Establish useful precision before pan/envelope levels are quantized.
    # Raising an already quantized, very quiet register stream cannot recover
    # its lost velocity response. Captured dynamics need no inherited knee.
    # The modeled method quantizes under its original planning headroom,
    # then lifts the finished register stream. Changing that order changes
    # individual rounded note levels, even with the same final song gain.
    precision_lift = auto_levels and capture_factory is not None and not source_levels
    mussc.LIFT_MAX = 0. if source_levels else (96. if precision_lift else _LEVEL_POLICY[0])
    mussc.HEAD = 0 if source_levels or precision_lift else _LEVEL_POLICY[1]
    mussc.KNEE = False if source_levels or capture_factory else _LEVEL_POLICY[2]
    WolfSong.planning_anchor = None if source_levels else cal.get('planning_anchor')
    def measured_envelope(note,seconds):
        spec=cal.get('measured_envelopes',{}).get(f'ch{note.ch+1:02}')
        if not spec:return 0.
        assert note.vel==spec['velocity'], 'unmeasured velocity cannot inherit envelope correction'
        assert spec['cc7']==spec['cc11']==127 and all(v==127 for _,v in note.vols), 'unmeasured controller state'
        points=spec['by_key'][str(note.key)]
        if seconds<=points[0][0]:return points[0][1]
        for (a,x),(b,y) in zip(points,points[1:]):
            if seconds<=b:return x+(y-x)*(seconds-a)/(b-a)
        return points[-1][1]
    mussc.wolf_measured_envelope=measured_envelope
    def response_envelope(note,seconds):
        from audio_fit import curve_value
        curve=getattr(note,'capture_response_curve',None)
        if not curve:return 0.
        held=getattr(note,'capture_response_hold',None)
        age=seconds*note.sp
        if held is not None and seconds>(note.off-note.on)/140:
            age=held+(seconds-(note.off-note.on)/140)*note.sp
        return curve_value(curve,age)
    mussc.wolf_response_envelope=response_envelope
    # A static wet SC-55 solo can have room energy on the nominally silent
    # side. These measured constant-power positions approximate that return.
    # Never replace a moving score pan with one static measurement.
    for part,p in cal.get('pan',{}).items():
        if not part.startswith('ch'):continue
        ch=int(part[2:])-1
        actual={b for _,ev in groups for k,c,a,b in ev if k=='ctl' and c==ch and a==10}
        if len(actual)>1:raise ValueError(('static correction on moving pan',part))
        groups=[(t,[(k,c,a,p if k=='ctl' and c==ch and a==10 else b) for k,c,a,b in ev]) for t,ev in groups]
        groups[0][1].append(('ctl',ch,10,p))
    WolfSong.captures = cal.get('captures', [])
    WolfSong.capture_factory = capture_factory
    WolfSong.capture_selector = capture_selector
    WolfSong.sample_overrides = sample_overrides
    WolfSong.capture_loops = capture_loops
    mussc.cal_db = lambda name, note: (0. if source_levels else cal.get('levels', {}).get(
        f'k{note.key:02}' if note.ch == 9 else f'ch{note.ch+1:02}', 0.))
    from audio_levels import adjust_track_levels
    mussc.wolf_source_levels = lambda tracks: adjust_track_levels(tracks,cal.get('levels',{})) if source_levels else None
    mussc.dmxmus.parse_mus = lambda _: (groups, length)
    font = convert.Font(preserved_font or sf2.SF2(str(FONT)), kit, drum_pan,
                        hashlib.sha256(FONT.read_bytes()).hexdigest())
    overrides = dict(quality)
    if capture_factory:
        # Keep the established melodic root grouping. Capturing the played
        # response does not require a separate sample for every keyboard zone;
        # the sampler still measures each note's response at the common root.
        # Distinct drum keys retain their own captured sound.
        overrides.update(min_drum=0)
    quality = {}
    attempts = []
    folder.mkdir(parents=True, exist_ok=True)
    def log_fit(step, result):
        row = dict(step=step, quality=dict(quality), result=result)
        if capture_factory:row['doc_page_budget']=capture_factory.page_budget
        attempts.append(row)
        (folder/"fit-attempts.json").write_text(json.dumps(attempts, indent=2)+"\n")
    steps = ([dict(attack=a) for a in (.12,.10,.08,.06,.04,.03)] if capture_factory else mussc.STEPS)
    for step, changes in enumerate(steps if auto_fit else [{}]):
        WolfSong.fit_step = step
        changes=dict(changes)
        if capture_factory:capture_factory.page_budget=changes.pop('doc_page_budget',180)
        quality.update(changes)
        quality.update(overrides)
        # A level-only rebuild can reuse its already measured waveform fit.
        # This does not skip fitting for a new waveform candidate.
        WolfSong.evidence = folder/f"layout-step-{step}.json"
        try:
            s = WolfSong('W_' + name, b'', font, mussc.Q(**quality), 191)
            if s.low < 64:
                raise ValueError(f'{244-s.low} pages')
            missing = [z.name for z in s.zones if z.notes and not getattr(z, 'capture', None)]
            if missing and capture_policy == 'all-captured':
                raise ValueError('uncaptured instrument zones: ' + ', '.join(missing))
            abstract, tags, notes = {}, {}, []
            state = [None] * 24
            # Chorus without RAM or CPU: the partner voice of a stereo pair plays a few cents sharp, so the
            # pair beats as the SC-55's layers and chorus do (cal['detune'] = {'chNN': cents}).
            detune = {int(k[2:]) - 1: float(v) for k, v in cal.get('detune', {}).items()}
            voice_cents = [0.] * 24
            for t, events in sorted(s.wakes.items()):
                if t >= length:
                    continue
                seq = []
                for kind, v, val in events:
                    if kind == 'on':
                        note, lev, fc = val
                        d = s.zone_of[id(note)]
                        voice_cents[v] = detune.get(note.ch, 0.) if note.half == 1 else 0.
                        if voice_cents[v]:
                            fc = max(1, min(65535, round(fc * 2 ** (voice_cents[v] / 1200))))
                        seq.append(('on', v, (d, fc, lev)))
                        state[v] = [d, fc, lev]
                        tags.setdefault(t, []).append((v, base_events.tag_of(note)))
                        if note.half == 0:
                            notes.append(dict(tic=t, ch=note.ch, key=note.key, velocity=note.vel,
                                              off=note.off, stop=note.stop, voice=v, kind=note.z.kind,
                                              program=note.preset))
                            if not hasattr(note.z,'measured_source'):
                                notes[-1]['model_silent_at']=s.sound_end(note,None)
                            reference=getattr(note,'capture_reference',None)
                            if reference is not None:
                                notes[-1].update(sample=d,capture_reference=reference[3],
                                    capture_hold_seconds=reference[2],
                                    capture_level_db=getattr(note,'capture_level_db',0.),
                                    capture_response_hold=getattr(note,'capture_response_hold',None),
                                    capture_response_curve=getattr(note,'capture_response_curve',[]))
                    elif kind == 'morph':
                        if getattr(val, 'extra_page', False):
                            seq.append(('page', v, val.page))
                        else:
                            d = s.zones.index(val)
                            seq.append(('table', v, (d, state[v][1], state[v][2])))
                            state[v][0] = d
                    else:
                        if kind == 'ctl':
                            val ^= 0x10  # MIDI side 0=left; DOC channel 1=left.
                        if kind == 'fc' and voice_cents[v]:
                            val = max(1, min(65535, round(val * 2 ** (voice_cents[v] / 1200))))
                        seq.append((kind, v, val))
                        if kind == 'fc':
                            state[v][1] = val
                        if kind == 'lev':
                            state[v][2] = val
                abstract[t] = seq
            stream, pitches, timeline = unit2.encode(abstract, length)
            descriptors = [(s.pages[i], z.size, 2 if z.kind == 'oneshot' else 0,
                            s.lpages[i] if z.kind == 'attack' else s.pages[i],
                            z.loop_len if z.kind == 'attack' else z.size) for i, z in enumerate(s.zones)]
            waves = base_events.doc_image(s)
            header = unit2.image_header(pitches, descriptors, waves, s.low, length,
                                        channels=[1-(v&1) for v in range(24)])
            # The host command plan is unbounded; only the emitted native bank
            # must fit. Save it before packing so a failed pack is inspectable.
            import base64
            (folder/'command-plan.json').write_text(json.dumps(dict(
                header=base64.b64encode(header).decode(),
                stream=base64.b64encode(stream).decode(),
                waves=base64.b64encode(waves).decode(),timeline=timeline))+'\n')
            batch_stats={}
            if batched:
                import prepared
                data,timeline,batch_stats=prepared.best_rows(header,
                    prepared.rows(header+stream),waves,timeline)
            else:
                data=unit2.image(stream,pitches,descriptors,waves,s.low,length,
                                 channels=[1-(v&1) for v in range(24)])
            level_calibration = None
            if auto_levels or 'song_gain_steps' in cal:
                data, level_calibration = calibrate_register_range(data,cal.get('song_gain_steps'))
            stored, margin = unit2.storage(data)
            log_fit(step, f"fits {244-s.low} pages and {len(stored)} stored bytes")
            break
        except ValueError as error:
            log_fit(step, str(error))
            print(name, 'quality', step, error, flush=True)
            if capture_selector:
                from audio_selective import CaptureSelectionError
                if isinstance(error,CaptureSelectionError):
                    raise
            if capture_factory:
                from audio_timbre import BankAllocationError
                if isinstance(error,BankAllocationError):
                    # The global fitter already tried every shorter attack.
                    # Removing its larger alternatives cannot make the same
                    # minimum smaller, so do not repeat that failed search.
                    raise
                if not isinstance(error,unit2.ColdBankOverflow):
                    # Invalid capture inputs and command-layout errors are not
                    # evidence that a different sample rate would help.
                    raise
            if capture_factory and auto_fit and isinstance(error,unit2.ColdBankOverflow):
                # Wave RAM and the packed bank are separate limits. Retain
                # the same measured candidates and give the allocator a
                # smaller page allowance based on the actual byte overflow.
                pages=capture_factory.page_budget-max(1,(error.required_bytes-65536+255)//256)
                if pages>0:
                    steps.insert(step+1,dict(changes,doc_page_budget=pages))
    else:
        raise ValueError('no fit within DOC RAM and native bank limits; see fit-attempts.json and pin or adjust individual samples')
    source = Counter((t, ch, key, vel) for t, ev in source_groups for k, ch, key, vel in ev if k == 'on')
    played = Counter((x['tic'], x['ch'], x['key'], x['velocity']) for x in notes)
    assert source == played, ('onsets changed', list((source-played).elements())[:20])
    shortened = [x for x in notes if held_note_shortened(x)]
    if shortened:
        (folder/'shortened-notes.json').write_text(json.dumps(shortened,indent=2)+'\n')
        raise ValueError(f'{len(shortened)} held notes shortened')
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'unit.bin').write_bytes(data)
    (folder/'stored.bin').write_bytes(stored)
    (folder/'waves.bin').write_bytes(waves)
    # Render the encoded player's writes at the encoder's source-event times;
    # actual alarm timing is audited separately against the assembly trace.
    source_times = {pos: t for t, pos in timeline}
    player = unit2.Player(data)
    rendered = []
    t = 0
    while True:
        pos = player.y
        if pos in source_times:
            t = source_times[pos]
            for v, tag in tags.get(t, []):
                rendered.append(f'T {t*5} {v+4} {tag}')
        wait, writes = player.wake()
        for reg, val in writes:
            if reg & 31 < 28:
                rendered.append(f'W {t*5} {reg} {val}')
        t += wait
        if player.y == 0:
            break
    (folder/'stereo.txt').write_text('\n'.join(rendered)+'\n')
    info = dict(song=name, number=n, id=sid, label=label, pages=244-s.low,
                doc_base=s.low*256, seconds=length/140, ticks700=length*5, fit_step=step,
                unit_bytes=len(data), stored_bytes=len(stored), expansion_margin=margin,
                stream_bytes=int.from_bytes(data[6:8],'little'), descriptors=len(descriptors), pitches=len(pitches),
                source_notes=sum(source.values()), held_notes_shortened=0,
                planned_wakes=len(timeline), calibration=cal,
                batch_stats=batch_stats, tone_safe=tone_safe, capture_loops=capture_loops,
                fit_attempts=attempts,
                fit_allocation=getattr(s,'fit_allocation',None),
                pan_allocation=getattr(s,'pan_stats',{}),
                planning_reference=getattr(s,'planning_reference',None),
                build_sources=build_sources, uncaptured_zones=missing, capture_policy=capture_policy,
                sample_model_aliases=[dict(bank=bank,performed_program=program+1,model_program=modeled+1)
                    for (bank,program),modeled in sorted(font.model_aliases.items())],
                auto_fit=auto_fit, sample_overrides=sample_overrides, loop_layout=loop_layout,
                level_calibration=level_calibration,source_level_planning=source_levels,
                midi_sha256=metadata['sha256'], font_sha256=hashlib.sha256(FONT.read_bytes()).hexdigest(),
                unit_sha256=hashlib.sha256(data).hexdigest(),
                filter_tables=[dict(zone=i,page=v.page,bytes=len(v.table),size=getattr(v,'size',256),rate=z.rate,program=z.notes[0].preset,keys=sorted({n.key for n in z.notes})) for i,z in enumerate(s.zones) if z.notes for v in getattr(z,'morph_family',[]) if getattr(v,'extra_page',False) and v.table],
                zones=[dict(name=z.name, kind=z.kind, rate=z.rate, bytes=len(z.table),
                            loop_bytes=len(z.ltable) if z.kind=='attack' else 0,
                            capture=getattr(z,'capture',None),
                            exact_attack_fc=getattr(z,'exact_fc_main',None),
                            exact_attack_samples=getattr(z,'exact_attack_samples',None),
                            exact_attack_keys=getattr(z,'exact_attack_keys',None),
                            required_rate=getattr(z,'required_rate',None),
                            program=z.notes[0].preset, keys=sorted({n.key for n in z.notes}),
                            channels=sorted({n.ch+1 for n in z.notes}), attack_seconds=getattr(z,'attack',0.0),
                            bandwidth_hz=getattr(z,'f_keep',None)) for z in s.zones])
    (folder/'info.json').write_text(json.dumps(info, indent=2)+'\n')
    (folder/'notes.json').write_text(json.dumps(notes)+'\n')
    return info
