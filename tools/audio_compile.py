#!/usr/bin/env python3
"""Compile editable music/effect recipes into bounded native DOC assets."""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
from source_identity import source_bytes
import struct
import subprocess
import sys
import shutil
from types import SimpleNamespace
import wave

from audio_recipes import checked, quote, recipe_midi, render, sha
from audio_music import wav_read,relative,verify_compiled_instruments
from game_profile import fields, integer, number, profile, read_toml
from music_pack import inspect_song
from music_score import Event, midi_write, midi_read

ROOT = Path(__file__).resolve().parents[1]
DOC_RATE = 894886 / 34


def wav_write(path, rate, channels):
    if not channels or len({len(c) for c in channels}) != 1:
        raise ValueError('mismatched WAV channels')
    values = array.array('h', (max(-32768, min(32767, round(v*32767)))
                             for frame in zip(*channels) for v in frame))
    if sys.byteorder != 'little':
        values.byteswap()
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((len(channels), 2, round(rate), 0, 'NONE', 'not compressed'))
        wav.writeframes(values.tobytes())


def renderer(midi, settings_path, output):
    settings = read_toml(settings_path)['renderer']
    executable = relative(settings_path, settings['executable'])
    roms = relative(settings_path, settings['rom_directory'])
    if not executable.is_file() or not roms.is_dir():
        raise ValueError('set renderer executable and ROM directory in renderer.toml')
    if settings.get('executable_sha256') and sha(executable.read_bytes()) != settings['executable_sha256']:
        raise ValueError('renderer executable hash differs from settings')
    output.parent.mkdir(parents=True, exist_ok=True)
    source = output.with_suffix('.mid')
    source.write_bytes(midi)
    command = [str(executable), '-d', str(roms), '--romset', settings['romset'],
               '-r', 'gs', '--end', 'cut', '-f', 's16', '--quiet',
               '-o', str(output.resolve()), str(source.resolve())]
    division, events = midi_read(midi)
    last_note=max((e.seconds for e in events if e.raw[0]&0xf0 in (0x80,0x90)),default=0)
    while True:
        duration=events[-1].seconds
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=max(60,duration*10+30))
        except subprocess.TimeoutExpired as error:
            raise ValueError('layer renderer exceeded its bounded render time') from error
        rate, channels = wav_read(output)
        quiet=True
        for side in channels:
            dc=sum(side[:round(.05*rate)])/max(1,round(.05*rate))
            peak=max((abs(v-dc) for v in side),default=0)
            tail=side[-round(.1*rate):]
            quiet &= math.sqrt(sum((v-dc)**2 for v in tail)/max(1,len(tail)))<=max(2/32768,peak*.001)
        if quiet:break
        tail=duration-last_note
        if tail>=29.999:
            raise ValueError('layer remains audible after 30 seconds; inspect its MIDI controls')
        end=round((last_note+min(30,max(2,tail*2)))*1000)
        # Layer MIDI uses a fixed 1000 Hz tick clock.
        midi=midi_write(division,[e for e in events if e.raw[:2]!=b'\xff\x2f']+[Event(end,0,b'\xff\x2f\x00')])
        source.write_bytes(midi)
        division,events=midi_read(midi)
    if rate != 64000 or len(channels) != 2 or not channels[0]:
        raise ValueError('renderer did not return 64 kHz stereo audio')
    return dict(renderer_sha256=sha(executable.read_bytes()), romset=settings['romset'],
                rom_inputs={p.name: sha(p.read_bytes()) for p in sorted(roms.iterdir()) if p.is_file()},
                midi_sha256=sha(midi), wav_sha256=sha(output.read_bytes()),
                tail_silence_verified=True, tail_seconds=duration-last_note)


def compiler_sources():
    return {p.relative_to(ROOT).as_posix():sha(source_bytes(p)) for p in
        list((ROOT/'tools/doccompiler').glob('*.py'))+
        [ROOT/'tools'/name for name in ('source_identity.py','native_host.py','host_kernels.c','audio_plan.py','audio_plan.c','audio_numeric.py','audio_music.py','audio_compile.py','audio_recipes.py','audio_sampling.py',
         'audio_preview_native.py','audio_preview_kernel.c','audio_fit.py','audio_performance_pan.py','audio_context_fit.py','audio_timbre.py','audio_dsp.py','audio_preview.py','audio_levels.py','audio_resample.py',
         'music_score.py','instrument_defaults.py','audio_tracks.py','audio_track_sampling.py','audio_selective.py','audio_defaults.py','audio_intermediate.py','audio_score_delta.py')]+[ROOT/'profiles/audio/sample-models.toml',ROOT/'profiles/audio/source-levels.toml']}


def music(args):
    from audio_music import music as convert_music
    sources=compiler_sources() if getattr(args,'record_sources',True) else {}
    return convert_music(args,sources)

def layer_midi(raw, layer, rate):
    """FM frequency bytes describe a contour; Roland programs supply timbre."""
    allowed = {'role', 'program', 'bank_msb', 'bank_lsb', 'transpose', 'velocity', 'gain_db',
               'delay_seconds', 'length_scale', 'release_seconds', 'fixed_key', 'pan', 'reverb', 'chorus', 'expression', 'drum',
               'volume', 'expression_shape'}
    if layer.keys()-allowed:
        raise ValueError('unknown layer fields: '+', '.join(sorted(layer.keys()-allowed)))
    for k, lo, hi in (('program', 1, 128), ('bank_msb', 0, 127), ('bank_lsb', 0, 127),
                      ('velocity', 1, 127), ('transpose', -48, 48)):
        integer(layer[k], lo, hi, 'layer.'+k)
    length, = struct.unpack_from('<I', raw)
    if len(raw) < 23+length or not length:
        raise ValueError('truncated or empty original effect contour')
    block = raw[22] & 7
    scale = layer.get('length_scale', 1.0)
    delay = layer.get('delay_seconds', 0.0)
    number(scale, .05, 20, 'layer.length_scale')
    number(delay, 0, 10, 'layer.delay_seconds')
    ev = [Event(0, 0, b'\xff\x51\x03\x0f\x42\x40')]
    shape = layer.get('expression_shape', 'constant')
    if shape not in ('constant', 'contour-gesture'):
        raise ValueError('unknown effect expression shape')
    if shape != 'constant' and 'expression' in layer:
        raise ValueError('choose expression or expression_shape, not both')
    for cc, value in ((0, layer['bank_msb']), (32, layer['bank_lsb']), (7, layer.get('volume',127)), (11, layer.get('expression',110 if shape != 'constant' else 127)),
                      (10, layer.get('pan', 64)), (91, layer.get('reverb', 0)), (93, layer.get('chorus', 0)),
                      (101, 0), (100, 0), (6, 24), (38, 0), (101, 127), (100, 127)):
        integer(value, 0, 127, 'layer controller')
        ev.append(Event(0, 0, bytes([0xb0, cc, value])))
    ev.append(Event(0, 0, bytes([0xc0, layer['program']-1])))
    contour = raw[23:23+length]+b'\0'
    gestures = {}
    start = 0
    while start < length:
        if not contour[start]:
            start += 1
            continue
        end = start+1
        while contour[end]:
            end += 1
        span = 12*math.log2(max(contour[start:end])/min(contour[start:end]))
        kind = 'impact' if (end-start)/rate*scale < .22 else 'swell' if span > 10 and (end-start)/rate*scale > .4 else 'tone'
        for i in range(start,end):
            t = (i-start)/max(1,end-start-1)
            value = (127-70*t if kind == 'impact' else
                     48+79*t/.25 if kind == 'swell' and t < .25 else
                     127-55*(t-.8)/.2 if kind == 'swell' and t > .8 else
                     64+63*t/.08 if kind == 'tone' and t < .08 else
                     127-48*(t-.82)/.18 if kind == 'tone' and t > .82 else 127)
            gestures[i] = 127 if end-start == 1 else round(value)
        start = end
    held = None
    for i, fn in enumerate(contour):
        tick = round((.05+delay+i/rate*scale)*1000)
        if not fn:
            if held is not None:
                ev.append(Event(tick, 0, bytes([0x80, held, 0])))
                held = None
            continue
        if shape == 'contour-gesture':
            ev.append(Event(tick, 0, bytes([0xb0, 11, gestures[i]])))
        frequency = fn * (3579545/72) / 2**(20-block)
        pitch = 69+12*math.log2(frequency/440)+layer['transpose']
        if layer.get('fixed_key', -1) >= 0:
            pitch = layer['fixed_key']
        # Low effect contours can fall below MIDI key zero while remaining
        # representable by the configured 24-semitone bend range.
        number(pitch, -24, 151, 'effect pitch (adjust transpose/fixed_key)')
        key = max(0,min(127,round(pitch)))
        if held is None or abs(pitch-held) > (23.5 if shape == 'contour-gesture' else 24):
            if held is not None:
                ev.append(Event(tick, 0, bytes([0x80, held, 0])))
            held = key
            retrigger = True
        else:
            retrigger = False
        bend = max(0, min(16383, round(8192+(pitch-held)*8192/24)))
        ev.append(Event(tick, 0, bytes([0xe0, bend & 127, bend >> 7])))
        if retrigger:
            ev.append(Event(tick, 0, bytes([0x90, held, layer['velocity']])))
    tail = layer.get('release_seconds', 2.0)
    number(tail, 0, 30, 'layer.release_seconds')
    ev.append(Event(tick+round(tail*1000), 0, b'\xff\x2f\x00'))
    return midi_write(1000, ev)


def effect(args):
    doc = read_toml(args.recipe)
    if doc.get('format') != 1 or doc.get('kind') != 'effect':
        raise ValueError('expected a format-1 effect recipe')
    if doc.keys()-{'format', 'kind', 'name', 'priority', 'source', 'layer', 'doc'}:
        raise ValueError('unknown effect recipe fields')
    raw = checked(args.recipe.parent/doc['source']['file'], doc['source']['sha256'])
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    layers = []
    if doc['source']['kind'] == 'pcm-u8':
        rate = doc['source']['rate']
        integer(rate, 1000, 192000, 'source.rate')
        pcm = [(v-128)/128 for v in raw]
    elif doc['source']['kind'] == 'adlib-effect-contour':
        if not args.settings:
            raise ValueError('layered effects require --settings renderer.toml')
        if len(doc.get('layer', [])) < 2:
            raise ValueError('synthetic effects require at least two explicit Roland layers')
        if len(doc['layer'])>8 or sum(bool(layer.get('drum')) for layer in doc['layer'])>1:
            raise ValueError('use at most eight layers and one shared drum-kit layer')
        rate=64000
        combined=[]
        common_gain=max(layer.get('gain_db',0.) for layer in doc['layer'])
        number(common_gain,-60,24,'layer.gain_db')
        melodic=iter([0,1,2,3,4,5,6,7,8,10,11,12,13,14,15])
        end=0
        for index, layer in enumerate(doc['layer']):
            gain=layer.get('gain_db',0.)
            number(gain,-60,24,'layer.gain_db')
            layer=dict(layer)
            if 'expression' in layer and gain!=common_gain:
                raise ValueError('set either relative layer gain_db or explicit expression, not both')
            # The emulator applies each layer's fader before its shared effects.
            if layer.get('expression_shape','constant') != 'constant':
                if gain != common_gain:
                    raise ValueError('set volume for layers with an expression shape, not relative gain_db')
            else:
                layer.setdefault('expression',max(1,round(127*10**((gain-common_gain)/40))))
            if type(layer.get('drum',False)) is not bool:
                raise ValueError('layer.drum must be true or false')
            channel=9 if layer.get('drum') else next(melodic)
            _,events=midi_read(layer_midi(raw,layer,doc['source']['rate']))
            part=[]
            for event in events:
                end=max(end,event.tick)
                if event.raw[:2]==b'\xff\x2f':continue
                raw_event=event.raw
                if raw_event[0]<0xf0:raw_event=bytes([(raw_event[0]&0xf0)|channel])+raw_event[1:]
                part.append(Event(event.tick,0,raw_event))
            combined+=part
            target=out/f'layer-{index+1:02}.wav'
            receipt=renderer(midi_write(1000,part+[Event(end,0,b'\xff\x2f\x00')]),args.settings,target)
            layers.append(dict(role=layer['role'],channel=channel+1,expression=layer.get('expression'),
                               expression_shape=layer.get('expression_shape','constant'),**receipt))
        full=out/'roland-combined.wav'
        combined_receipt=renderer(midi_write(1000,combined+[Event(end,0,b'\xff\x2f\x00')]),args.settings,full)
        _,channels=wav_read(full)
        lead=round(.05*rate)
        dc=[sum(c[:lead])/lead for c in channels]
        pcm=[(l-dc[0]+r-dc[1])*.5*10**(common_gain/20) for l,r in zip(*channels)][lead:]
    else:
        raise ValueError('unknown effect source kind')
    cfg = dict(dict(auto_fit=True, tail_db=60., max_seconds=10., fade_seconds=0., volume=255), **doc.get('doc',{}))
    if cfg.keys()-{'rate', 'tail_db', 'max_seconds', 'fade_seconds', 'volume', 'auto_fit'}:
        raise ValueError('unknown effect.doc setting')
    if type(cfg['auto_fit']) is not bool:
        raise ValueError('effect.doc.auto_fit must be true or false')
    if 'rate' in cfg:
        number(cfg['rate'], 2000, 64000, 'effect.doc.rate')
    number(cfg['tail_db'], 20, 96, 'effect.doc.tail_db')
    number(cfg['max_seconds'], .01, 30, 'effect.doc.max_seconds')
    number(cfg['fade_seconds'], 0, 1, 'effect.doc.fade_seconds')
    integer(cfg['volume'], 1, 255, 'effect.doc.volume')
    if not pcm:
        raise ValueError('empty effect')
    # Tail trimming is explicit and reported. The start remains at score time.
    peak = max(map(abs, pcm)) or 1
    threshold = peak * 10**(-cfg['tail_db']/20)
    last = max((i+1 for i, v in enumerate(pcm) if abs(v) > threshold), default=1)
    original_seconds = len(pcm)/rate
    pcm = pcm[:last]
    if len(pcm)/rate > cfg['max_seconds']:
        raise ValueError('effect exceeds doc.max_seconds; adjust the recipe explicitly')
    sys.path.insert(0, str(ROOT/'tools/doccompiler'))
    fade = min(len(pcm), round(rate*cfg['fade_seconds']))
    for i in range(fade):
        pcm[-fade+i] *= (fade-i-1)/fade
    from audio_fit import fit
    chosen, attempts = fit(pcm, rate, max_bytes=4096, rate=cfg.get('rate'), auto_fit=cfg['auto_fit'])
    encoded, size, fc, actual_rate = chosen['pcm'], chosen['table_bytes'], chosen['fc'], chosen['rate']
    (out/'effect.pcm').write_bytes(encoded)
    source_peak = max(1,max(map(abs,pcm)))
    wav_write(out/'source.wav', rate, [[v/source_peak for v in pcm]])
    wav_write(out/'doc.wav', actual_rate, [[(v-128)/128 for v in encoded[:-1]]])
    report = dict(name=doc['name'], priority=doc['priority'], recipe_sha256=sha(args.recipe.read_bytes()),
                  bytes=len(encoded), table_bytes=size, pages=size//256, size_code=(size//256).bit_length()-1,
                  fc=fc, rate=actual_rate, level=cfg['volume'], pcm_sha256=sha(encoded),
                  original_seconds=original_seconds, seconds=len(pcm)/rate, layers=layers,
                  combined_render=combined_receipt if layers else None,
                  auto_fit=cfg['auto_fit'], fit_attempts=attempts, metrics=chosen['metrics'],
                  needs_audition=not chosen['metrics']['within_half_db'], listening_accepted=False)
    (out/'info.json').write_text(json.dumps(report, indent=2)+'\n')
    (out/'fitted-sample.toml').write_text(
        '# To pin this result, copy this [doc] table into the original effect recipe.\n'
        '# Delete rate to let auto-fit choose again. No musical knowledge is required.\n'
        f'[doc]\nauto_fit = true\nrate = {chosen["requested_rate"]}\n'
        f'tail_db = {cfg["tail_db"]}\nvolume = {cfg["volume"]}\n')
    return report


def compile_pack(args):
    """Build every named recipe in a catalog and publish a checked manifest."""
    game = profile(args.profile)
    preserved=getattr(args,'preserved_samples',None)
    if not preserved and (args.recipe/'intermediate.toml').exists():preserved=args.recipe
    if preserved:
        from audio_intermediate import validate_dos
        licensed_songs=validate_dos(preserved,game,args.data,getattr(args,'shared_data',None))
    is_music = args.kind == 'music-pack'
    exporting=getattr(args,'preserve_samples',None)
    if exporting:
        if not is_music or preserved:raise ValueError('preserve samples only from a synthesis music-pack build')
        if exporting.exists() and any(exporting.iterdir()):
            raise ValueError('intermediate output is not empty; choose a new folder to preserve any existing edits')
    folder = args.recipe/('songs' if is_music else 'effects')
    if not folder.is_dir():
        raise ValueError('expected the generated recipes folder containing songs/ and effects/')
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    recipes = {}
    for path in sorted(folder.glob('*.toml')):
        doc = read_toml(path)
        if doc['name'] in recipes:
            raise ValueError('duplicate named recipe: '+doc['name'])
        recipes[doc['name']] = path
    if is_music:
        catalog = game.required_music
    else:
        catalog_path = ROOT/'profiles/audio'/('effects-spear.toml' if game.spear else 'effects-wolf3d.toml')
        catalog = {e['id']:e['name'] for e in read_toml(catalog_path)['effect']}
    lines = ['format = 1', 'catalog = '+quote(game.document['engine'])]
    if is_music:
        lines += ['player = "wdm2"']
    quality = []
    def compile_one(item):
        sid,name=item
        if name not in recipes:
            raise ValueError('missing recipe for '+name)
        work = out/'details'/name
        command = [sys.executable, str(Path(__file__).resolve()), 'music' if is_music else 'effect',
                   str(recipes[name].resolve()), '--out', str(work)]
        if args.settings:
            command += ['--settings', str(args.settings.resolve())]
        if preserved:
            command += ['--preserved-samples',str(preserved.resolve()),'--data',str(args.data.resolve()),'--profile',args.profile]
            if args.shared_data:command += ['--shared-data',str(args.shared_data.resolve())]
            if args.require_identical:command += ['--require-identical']
        if getattr(args,'preserve_samples',None):command += ['--preserve-samples',str(args.preserve_samples.resolve())]
        if is_music and getattr(args,'model_diagnostics',False):command += ['--model-diagnostics']
        if is_music and preserved and not exporting:
            from audio_song_cache import compile_song
            info,ran=compile_song(args,recipes[name].resolve(),preserved.resolve(),licensed_songs[name],work)
        else:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            work.mkdir(parents=True,exist_ok=True)
            (work/'build.log').write_text(result.stdout)
            if result.returncode:
                raise ValueError(name+' failed; see '+str(work/'build.log'))
            info = json.loads((work/'info.json').read_text())
            ran=True
        filename = f'{"song" if is_music else "effect"}-{sid:02}.bin'
        data = (work/('stored.bin' if is_music else 'effect.pcm')).read_bytes()
        (out/filename).write_bytes(data)
        entry = ['', '[[songs]]' if is_music else '[[effects]]', 'name = '+quote(name),
                  'file = '+quote(filename), 'sha256 = '+quote(sha(data))]
        if not is_music:
            entry += [f'id = {sid}',f'rate = {info["rate"]}',f'table_bytes = {info["table_bytes"]}',
                      f'volume = {info["level"]}',f'priority = {info["priority"]}']
        print('Compiled' if ran else 'Reused',name,flush=True)
        return entry,dict(name=name,listening_accepted=False,needs_audition=info.get('needs_audition',True))
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os,tempfile
    jobs=min(getattr(args,'jobs',1),int(os.environ.get('WOLF_JOBS',getattr(args,'jobs',1))))
    if not 1<=jobs<=16:
        raise ValueError('--jobs must be between 1 and 16')
    completed={};failures=[]
    with tempfile.TemporaryDirectory(prefix='wolf-song-workers-') as worker_pool:
        args.worker_pool=worker_pool;args.worker_count=jobs
        if is_music and preserved:
            import native_host,audio_plan
            native_host.library();audio_plan.library()
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            pending={pool.submit(compile_one,item):item[0] for item in sorted(catalog.items())}
            for future in as_completed(pending):
                try:completed[pending[future]]=future.result()
                except ValueError as error:
                    failures.append(str(error))
                    print(str(error),flush=True)
    if failures:raise ValueError('Audio pack incomplete: '+'; '.join(sorted(failures)))
    for sid in sorted(completed):
        entry,report=completed[sid]
        lines += entry
        quality.append(report)
    manifest = out/'pack.toml'
    manifest.write_text('\n'.join(lines)+'\n')
    if is_music:
        from music_pack import MusicPack
        MusicPack(manifest,args.profile)
    else:
        from effects_pack import EffectsPack
        EffectsPack(manifest,args.profile)
    if exporting:
        from audio_intermediate import finish_package
        finish_package(exporting,game)
    (out/'quality-report.json').write_text(json.dumps(quality,indent=2)+'\n')
    return dict(profile=game.key,files=len(quality),manifest=str(manifest),listening_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('music', 'effect', 'music-pack', 'effects-pack'))
    parser.add_argument('recipe', type=Path)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', default='shareware')
    parser.add_argument('--preserve-samples',type=Path,help='export portable source samples and editable intermediate recipes')
    parser.add_argument('--preserved-samples',type=Path,help='recompile from a preserved package without synthesis tools')
    parser.add_argument('--data',type=Path,help='matching licensed DOS files for preserved audio')
    parser.add_argument('--shared-data',type=Path)
    parser.add_argument('--require-identical',action='store_true',help='reject offline results that differ from their full-build receipts')
    parser.add_argument('--model-diagnostics',action='store_true',help='also write raw float DOC-model diagnostics; not native listening WAVs')
    parser.add_argument('--jobs',type=int,default=1,help='independent song/effect compiler processes (1-16)')
    args = parser.parse_args()
    from audio_provenance import begin, failed
    previous=begin(args.out, dict(kind=args.kind, profile=args.profile))
    try:
        offline=args.preserved_samples or (args.recipe/'intermediate.toml').is_file()
        if args.require_identical and not offline:raise ValueError('--require-identical requires preserved samples')
        if args.kind in ('music','music-pack') and not args.settings and not offline:
            raise ValueError('music compilation requires --settings renderer.toml')
        method = compile_pack if args.kind.endswith('-pack') else music if args.kind == 'music' else effect
        from audio_provenance import command_inputs, begin, complete, failed
        identity = command_inputs(args)
        begin(args.out, identity)
        try:
            result = method(args)
            receipt = complete(args.out, identity)
            if args.kind=='music-pack' and offline:
                from audio_provenance import discard_generated
                discard_generated(previous)
        except Exception as error:
            failed(args.out, error)
            raise
        print(json.dumps(dict(result, audio_build_identity=receipt['identity']), indent=2))
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        failed(args.out, error)
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    main()
