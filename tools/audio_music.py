"""Convert one music recipe; pack orchestration and receipts stay with the CLI."""
import array
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import wave
from audio_recipes import checked,quote,recipe_midi,render,sha
from game_profile import integer,number,profile,read_toml
from music_pack import inspect_song
from music_score import midi_read

ROOT=Path(__file__).resolve().parents[1]


def verify_compiled_instruments(midi, notes):
    """Check performed parts as well as pitches; descriptor IDs are unrelated."""
    from collections import Counter
    from music_score import midi_notes
    selected = Counter((n['clock140'], n['channel'], n['key'], n['velocity'], n['program'])
                       for n in midi_notes(midi))
    compiled = Counter((n['tic'], n['ch'] + 1, n['key'], n['velocity'], n['program'][1] + 1)
                       for n in notes)
    if selected != compiled:
        raise ValueError('compiled instrument assignments differ from the selected MIDI parts: '
                         + repr(list((selected - compiled).elements())[:8]))



def relative(settings, value):
    return (Path(settings).parent / value).resolve()



def wav_read(path):
    with wave.open(str(path), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2):
            raise ValueError('expected mono/stereo 16-bit PCM WAV: '+str(path))
        rate, channels = wav.getframerate(), wav.getnchannels()
        values = array.array('h', wav.readframes(wav.getnframes()))
        if sys.byteorder != 'little':
            values.byteswap()
    return rate, [[x / 32768 for x in values[c::channels]] for c in range(channels)]



def music(args,compiler_inputs=None):
    compiler_inputs={} if compiler_inputs is None else compiler_inputs
    licensed=None
    if getattr(args,'licensed_imf',None):
        licensed=args.licensed_imf.read_bytes()
    elif getattr(args,'preserved_samples',None):
        from audio_intermediate import validate_dos
        sources=validate_dos(args.preserved_samples,profile(args.profile),args.data,getattr(args,'shared_data',None))
        licensed=sources[read_toml(args.recipe)['name']]
    data, doc = recipe_midi(args.recipe,licensed_imf=licensed)
    cfg = doc.get('doc', {})
    from audio_levels import conversion_level_mode, source_reference_receipt
    level_mode = conversion_level_mode(cfg, bool(getattr(args, 'preserved_samples', None)))
    allowed = {'capture_policy', 'capture_source', 'fallback_reason', 'quality', 'levels', 'pan', 'detune',
               'capture', 'planning_anchor', 'measured_envelopes', 'auto_fit', 'auto_levels', 'sample', 'auto_captures', 'auto_balance', 'sampling_policy', 'capture_selection','song_gain_steps','loop_layout','level_mode'}
    if cfg.keys()-allowed:
        raise ValueError('unknown [doc] fields: '+', '.join(sorted(cfg.keys()-allowed)))
    capture_source = cfg.get('capture_source', 'isolated-note')
    if capture_source not in ('instrument-track', 'isolated-note'):
        raise ValueError('unknown DOC capture source')
    loop_layout=cfg.get('loop_layout','full')
    if loop_layout not in ('full','repeated-endpoint'):raise ValueError('unknown DOC loop layout')
    policy = cfg.get('capture_policy', 'all-captured')
    if policy=='all-captured' and loop_layout!='full':
        raise ValueError('all-captured uses full sample loops')
    if policy not in ('all-captured', 'calibrated-sf2-and-captures'):
        raise ValueError('unknown DOC capture policy')
    if policy != 'all-captured' and not cfg.get('fallback_reason', '').strip():
        raise ValueError('the SF2 fallback requires a written doc.fallback_reason')
    if policy == 'all-captured' and cfg.get('capture'):
        raise ValueError('all-captured uses [[doc.sample]] overrides; explicit doc.capture entries belong to the calibrated fallback policy')
    preserved=None
    if getattr(args,'preserved_samples',None):
        sys.path.insert(0,str(ROOT/'tools/doccompiler'))
        from audio_intermediate import PreservedSong
        preserved=PreservedSong(args.preserved_samples,doc['name'],data)
        font=preserved.model
    else:
        settings = read_toml(args.settings)
        font = relative(args.settings, settings['soundfont']['file'])
        font_data = font.read_bytes()
        if settings['soundfont'].get('sha256') and sha(font_data) != settings['soundfont']['sha256']:
            raise ValueError('SoundFont hash differs from settings')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    midi = out/'source.mid'
    midi.write_bytes(data)
    calibration = {k: cfg[k] for k in ('levels', 'pan', 'detune', 'planning_anchor', 'measured_envelopes','song_gain_steps') if k in cfg}
    captures = []
    for index, spec in enumerate(cfg.get('capture', [])):
        spec = dict(spec)
        allowed = {'channel', 'key', 'occurrence', 'wav', 'sha256', 'bytes', 'rate', 'loop_bytes',
                   'loop_start', 'gain_db', 'release_baked', 'release_seconds', 'fine_static', 'use_spare_attack'}
        if spec.keys()-allowed:
            raise ValueError('unknown capture fields: '+', '.join(sorted(spec.keys()-allowed)))
        if 'wav' not in spec and capture_source == 'instrument-track':
            if not cfg.get('auto_captures'):
                raise ValueError('whole-track explicit captures require doc.auto_captures = true')
            integer(spec['channel'],1,16,'capture channel')
            integer(spec['key'],0,127,'capture key')
            captures.append(spec)
            continue
        integer(spec['channel'], 1, 16, 'capture.channel')
        integer(spec['key'], 0, 127, 'capture.key')
        integer(spec['bytes'], 256, 32768, 'capture.bytes')
        if spec['bytes'] & (spec['bytes']-1):
            raise ValueError('capture.bytes must be a power of two')
        number(spec['rate'], 1000, 192000, 'capture.rate')
        occurrence = spec.pop('occurrence', 1)
        if spec.get('wav'):
            capture = relative(args.recipe, spec['wav'])
            checked(capture, spec.pop('sha256'))
        else:
            capture = out/f'capture-{index:02}.wav'
            render(SimpleNamespace(command='wav', recipe=args.recipe, out=capture,
                                   settings=args.settings, part=None,
                                   capture=(spec['channel'], spec['key'], occurrence)))
        spec['wav'] = str(capture)
        captures.append(spec)
    calibration['captures'] = captures
    source_fitting=level_mode=='source' and not preserved
    # Each invocation runs in its own process; the shared converter uses module
    # globals while allocating its voices and preparing sample families.
    sys.path.insert(0, str(ROOT/'tools/doccompiler'))
    import build as compiler
    quality = cfg.get('quality', {})
    for key, value in quality.items():
        if not hasattr(compiler.mussc.Q, key) or key.startswith('_') or type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('unknown/non-numeric DOC quality setting: '+key)
    auto_fit = cfg.get('auto_fit', True)
    if type(auto_fit) is not bool:
        raise ValueError('doc.auto_fit must be true or false')
    auto_levels = cfg.get('auto_levels', True)
    if type(auto_levels) is not bool:
        raise ValueError('doc.auto_levels must be true or false')
    overrides = cfg.get('sample', [])
    for row in overrides:
        if row.keys()-{'channel', 'key', 'attack_seconds', 'bandwidth_hz', 'tail_db', 'rate', 'max_bytes'}:
            raise ValueError('unknown per-sample override')
        integer(row['channel'], 1, 16, 'sample.channel')
        integer(row.get('key', -1), -1, 127, 'sample.key')
        if 'rate' in row:
            number(row['rate'], 2000, 192000, 'sample.rate')
        if 'max_bytes' in row:
            integer(row['max_bytes'], 256, 32768, 'sample.max_bytes')
            if row['max_bytes'] & (row['max_bytes']-1):
                raise ValueError('sample.max_bytes must be a power of two')
        for key, lo, hi in (('attack_seconds', .001, 2), ('bandwidth_hz', 100, 20000), ('tail_db', 20, 96)):
            if key in row:
                number(row[key], lo, hi, 'sample.'+key)
    sampler = None
    selector = None
    if policy == 'all-captured':
        from audio_sampling import Sampler
        sampler = Sampler(args.recipe, args.settings, data, doc, out, auto_fit, overrides, preserved=preserved)
        sampler.references()
    automatic_captures = cfg.get('auto_captures', False)
    if type(automatic_captures) is not bool:
        raise ValueError('doc.auto_captures must be true or false')
    if automatic_captures:
        if policy != 'calibrated-sf2-and-captures':
            raise ValueError('doc.auto_captures belongs to the modeled-sample and capture policy')
        from audio_selective import SelectiveSampler
        selector = SelectiveSampler(args.recipe, args.settings, data, doc, out, auto_fit, overrides, preserved=preserved)
        selector.references()
    balance = cfg.get('auto_balance', automatic_captures)
    if preserved and balance:raise ValueError('automatic rebalancing requires synthesis references; edit saved levels/pan offline')
    if type(balance) is not bool:
        raise ValueError('doc.auto_balance must be true or false')
    if source_fitting and 'auto_balance' not in cfg:
        balance=True
    if balance and not (sampler or selector):
        raise ValueError('automatic balance requires independently rendered Roland parts')
    source_references = source_reference_receipt(sampler or selector) if source_fitting else None
    passes = []
    from music_score import midi_notes
    _, events = midi_read(data)
    moving_pan = {channel for channel in range(1,17) if len({e.raw[2] for e in events
        if len(e.raw)==3 and e.raw[0]==0xb0+channel-1 and e.raw[1]==10}) > 1}
    for attempt in range(3 if balance else 1):
        info = compiler.build(midi, font, out, doc['name'], calibration, quality, policy, auto_fit, overrides, sampler, auto_levels, selector, loop_layout=loop_layout,
                              preserved_font=preserved.font if preserved else None,source_levels=level_mode=='source',
                              record_sources=getattr(args,'record_sources',True))
        verify_compiled_instruments(data, json.loads((out/'notes.json').read_text()))
        if preserved or not (sampler or selector):
            break
        from audio_preview import compare_solos
        comparison = compare_solos(out,info,write_diagnostics=getattr(args,'model_diagnostics',False),source_levels=source_fitting)
        if source_fitting:
            # Freeze the register encoding gain before correcting source levels.
            # Re-maximizing it on each pass would undo the measured correction.
            calibration['song_gain_steps']=(info.get('level_calibration') or {}).get('level_lift_steps',0)
        passes.append(dict(calibration=json.loads(json.dumps(calibration)), parts=comparison['parts']))
        (out/'balance-passes.json').write_text(json.dumps(passes,indent=2)+'\n')
        if not balance or attempt==2:
            break
        changes = False
        for row in comparison['parts']:
            channel = row['channel']
            keys = ([f'k{key:02}' for key in sorted({n['key'] for n in midi_notes(data) if n['channel']==10})]
                    if channel==10 else [f'ch{channel:02}'])
            for key in keys:
                if key in cfg.get('levels',{}) and not source_fitting:
                    continue
                delta = row['level_correction_db']
                if abs(delta) > (20*math.log10(2)/16 if source_fitting else .25):
                    levels = calibration.setdefault('levels',{})
                    levels[key] = round(levels.get(key,0.)+delta,4)
                    changes = True
            key = f'ch{channel:02}'
            if channel!=10 and channel not in moving_pan and key not in cfg.get('pan',{}):
                pan = calibration.setdefault('pan',{})
                if pan.get(key)!=row['reference_pan']:
                    pan[key] = row['reference_pan']
                    changes = True
        if not changes:
            break
    if (sampler or selector) and not preserved:
        info['solo_comparison'] = comparison
        info['automatic_balance'] = dict(enabled=balance,passes=len(passes),
                                        calibration=calibration,
                                        method=('absolute isolated Roland levels at a fixed DOC output scale' if source_fitting
                                                else 'isolated Roland part levels relative to one common song gain; fixed wet pan'))
    info['level_mode']=level_mode
    if source_fitting:
        if source_reference_receipt(sampler or selector) != source_references:
            raise ValueError('Roland reference files changed during DOC conversion')
        info['source_references'] = source_references
        (out/'source-reference.json').write_text(json.dumps(source_references, indent=2)+'\n')
    verify_compiled_instruments(data, json.loads((out/'notes.json').read_text()))
    info['compiler_sources'] = compiler_inputs
    from audio_dsp import BACKEND
    info['comparison_fft'] = BACKEND
    info['capture_source'] = capture_source
    if 'defaults' in doc:
        info['instrument_defaults_sha256'] = sha((args.recipe.parent/doc['defaults']['file']).read_bytes())
    from collections import Counter
    from music_score import midi_notes
    instruments = Counter((n['channel'],n['program'],n['bank']) for n in midi_notes(data))
    names = read_toml(ROOT/'profiles/audio/gm-programs.toml')['program']
    info['selected_instruments'] = [dict(channel=ch,program=program,bank=list(bank),notes=count,
        name='Drum kit' if ch==10 else names[str(program)])
        for (ch,program,bank),count in sorted(instruments.items())]
    if sampler or selector:
        if sampler:
            sampler.report(info)
        if selector:
            info['capture_selection'] = selector.selection
            info['sampling_policy_sha256'] = sha(selector.policy_path.read_bytes())
    info['needs_audition']=True
    bank = (out/'stored.bin').read_bytes()
    check = inspect_song(bank)
    info.update(check, recipe_sha256=sha(args.recipe.read_bytes()), cold_sha256=sha(bank),
                listening_accepted=False, native_playback_verified=False)
    if preserved:
        info['preserved_source']=dict(package=str(preserved.package),
            expected_bank_sha256=preserved.meta['expected_bank_sha256'],
            identical_to_full_build=info['cold_sha256']==preserved.meta['expected_bank_sha256'])
        if getattr(args,'require_identical',False) and not info['preserved_source']['identical_to_full_build']:
            raise ValueError('rebuilt bank differs from the full-build receipt: '+doc['name'])
    if getattr(args,'preserve_samples',None):
        if preserved:raise ValueError('export intermediates from a synthesis build, not an offline rebuild')
        from audio_intermediate import export_song
        source_sampler=sampler or selector
        if not source_sampler or not source_sampler.track_sources:
            raise ValueError('preserving intermediates requires complete instrument-track captures')
        export_song(args.preserve_samples,args.recipe,data,font,source_sampler,info)
    (out/'info.json').write_text(json.dumps(info, indent=2)+'\n')
    lines = ['# Auto-fit results. See docs/AUDIO_BUILD.md for plain-language tuning.',
             '# Copy a [[doc.sample]] example into the original recipe to pin an override.',
             '# This report is regenerated; the original recipe is never rewritten.',
             f'auto_fit = {str(auto_fit).lower()}', f'pages_used = {info["pages"]}',
             f'pages_available = 180', f'fit_step = {info["fit_step"]}']
    for zone in info['zones']:
        lines += ['', '[[sample]]', 'name = '+quote(zone['name']),
                  'channels = '+quote(zone['channels']), 'keys = '+quote(zone['keys']),
                  f'rate = {zone["rate"]}', f'bytes = {zone["bytes"]}', f'loop_bytes = {zone["loop_bytes"]}',
                  f'attack_seconds = {zone["attack_seconds"]}',
                  '# Override example (place in your song recipe):', '# [[doc.sample]]',
                  f'# channel = {zone["channels"][0]}', f'# key = {zone["keys"][0]}',
                  '# attack_seconds = 0.12 # retain more of the original start of the note',
                  '# bandwidth_hz = 6000  # retain more high-frequency detail']
    (out/'fitted-samples.toml').write_text('\n'.join(lines)+'\n')
    return {k: info[k] for k in ('song', 'pages', 'bytes', 'source_notes', 'held_notes_shortened',
                                'capture_policy', 'uncaptured_zones', 'cold_sha256')}

