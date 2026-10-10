"""Authenticate audio against its recipes, inputs, compiler and produced files."""
import hashlib
import json
import time
from pathlib import Path

from audio_build_cache import digest, inputs
from game_profile import read_toml
from source_identity import source_digest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = 'audio-build.json'


def compiler_files(root=ROOT):
    tools = Path(root)/'tools'
    paths = list((tools/'doccompiler').glob('*.py'))
    paths += list(tools.glob('audio_*.c'))
    paths += [p for p in tools.glob('audio_*.py') if p.stem not in
              ('audio_complete','audio_compare','audio_bench','audio_build_cache')]
    paths += [tools/name for name in ('source_identity.py','audio_preview_kernel.c','game_profile.py','music_score.py','instrument_defaults.py',
        'music_pack.py','effects_pack.py','effect_sources.py','effect_size.py','build_sound.py','dos_data.py',
        'wolfsim.py','wolfaudio.py','doc_song.py')]
    paths += list((Path(root)/'profiles/audio').glob('*.toml'))
    return {p.relative_to(root).as_posix():source_digest(p) for p in sorted(set(paths)) if p.is_file()}


def recipe_paths(recipe, offline=False):
    found = set()
    def visit(path):
        path = Path(path).resolve()
        if path in found:return
        if not path.is_file():raise ValueError('Missing audio dependency: '+str(path))
        found.add(path)
        if path.suffix != '.toml':return
        def walk(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    # Preserved recipes resolve this virtual IMF from --data.
                    if offline and key=='original':continue
                    if key in ('file','wav','sampling_policy') and isinstance(item,str):visit(path.parent/item)
                    else:walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(read_toml(path))
    path = Path(recipe)
    if path.is_dir():
        for song in sorted(path.glob('songs/*.toml')):visit(song)
        for effect in sorted(path.glob('effects/*.toml')):visit(effect)
        found.add(path.resolve())
    else:visit(path)
    return sorted(found)


def command_inputs(args, root=ROOT):
    offline=bool(getattr(args,'preserved_samples',None) or (Path(args.recipe)/'intermediate.toml').is_file())
    paths = recipe_paths(args.recipe, offline=offline)
    if getattr(args,'profile',None):
        from game_profile import profile
        paths.append(profile(args.profile).path)
    for key in ('preserved_samples','data','shared_data'):
        value = getattr(args,key,None)
        if value:paths.append(Path(value).resolve())
    settings = getattr(args,'settings',None)
    if settings:
        settings = Path(settings).resolve();paths.append(settings)
        doc = read_toml(settings)
        for section,keys in [('renderer',('executable','track_executable','rom_directory')),('soundfont',('file',))]:
            for key in keys:
                if key in doc.get(section,{}):paths.append((settings.parent/doc[section][key]).resolve())
    return snapshot(args.kind,getattr(args,'profile',None),paths,root)


def snapshot(kind, profile, paths, root=ROOT):
    paths = sorted({str(Path(p).resolve()) for p in paths})
    return dict(kind=kind,profile=str(profile) if profile is not None else None,
                roots=paths,inputs=inputs(paths)['files'],compiler=compiler_files(root))


def atomic(path, value):
    path = Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


def begin(out, identity):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    previous=None
    # A samples-only rebuild must not adopt a leftover full-render WAV, either.
    # Keep previous output separately so edits and failure evidence survive.
    if any(p.name not in (RECEIPT,RECEIPT+'.tmp') for p in out.iterdir()):
        previous=out.with_name(out.name+'.previous-'+str(time.time_ns()))
        out.rename(previous)
        out.mkdir()
    atomic(out/RECEIPT,dict(format=1,status='building',**identity))
    return previous


def discard_generated(previous):
    """Remove a replaced, intact generated pack; retain edits and extra files."""
    if previous is None:return
    try:
        doc=json.loads((previous/RECEIPT).read_text())
        identity=doc.pop('identity')
        if doc.get('status')!='complete' or identity!=hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest():return
        files={p.relative_to(previous).as_posix():p for p in previous.rglob('*') if p.is_file() and p.name!=RECEIPT}
        if set(files)!=set(doc['outputs']):return
        if any(digest(files[name])!=expected for name,expected in doc['outputs'].items()):return
    except (OSError,ValueError,KeyError):return
    import shutil
    shutil.rmtree(previous)


def complete(out, identity, root=ROOT):
    out=Path(out)
    now=snapshot(identity['kind'],identity['profile'],identity['roots'],root)
    if now!=identity:raise ValueError('Audio inputs or compiler changed during compilation; no current output was published')
    files={p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file()
           and p.name not in (RECEIPT,RECEIPT+'.tmp','.stage.json')
           and '__pycache__' not in p.parts}
    if not files:raise ValueError('Audio build produced no files')
    result=dict(format=1,status='complete',**identity,outputs=files)
    result['identity']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    atomic(out/RECEIPT,result)
    return result


def failed(out, error):
    atomic(Path(out)/RECEIPT,dict(format=1,status='failed',error=str(error)))


def validate(path, root=ROOT):
    path=Path(path)
    if path.is_dir():path/=RECEIPT
    elif path.name!=RECEIPT:path=path.parent/RECEIPT
    if not path.is_file():raise ValueError('Audio has no current build receipt; rebuild with the public build command: '+str(path))
    doc=json.loads(path.read_text())
    if doc.get('format')!=1 or doc.get('status')!='complete':raise ValueError('Audio build is incomplete or failed: '+str(path))
    expected=doc.get('identity');copy=dict(doc);copy.pop('identity',None)
    if expected!=hashlib.sha256(json.dumps(copy,sort_keys=True).encode()).hexdigest():raise ValueError('Audio build receipt was changed: '+str(path))
    if doc['compiler']!=compiler_files(root):raise ValueError('Audio compiler changed; rebuild the audio: '+str(path))
    if inputs(doc['roots'])['files']!=doc['inputs']:raise ValueError('Audio recipe or input changed; rebuild the audio: '+str(path))
    for name,expected in doc['outputs'].items():
        item=(path.parent/name).resolve()
        if path.parent.resolve() not in item.parents or not item.is_file() or digest(item)!=expected:
            raise ValueError('Audio output missing or changed; rebuild the audio: '+str(item))
    return doc


def native_binding(native, compiled, root=ROOT):
    """Bind a completed native recording to this rebuilt bank and exact media."""
    native,compiled=Path(native),Path(compiled)
    audio=validate(compiled, root)
    identity=json.loads((native/'identity.json').read_text())
    profile=identity['profile'];pins=profile['sha256'];files=profile['files']
    for key,expected in pins.items():
        if digest(files[key])!=expected:raise ValueError('Native preview input changed: '+key)
    bank=compiled/'stored.bin'
    if pins['bank']!=digest(bank) or audio['outputs'].get('stored.bin')!=pins['bank']:
        raise ValueError('Native preview belongs to a different rebuilt music bank')
    checked=json.loads((native/'PASS.json').read_text())
    if not checked.get('repeatable'):raise ValueError('Native preview lacks verified repeatability')
    if digest(native/'mix/loaded-cold.bin')!=pins['bank']:
        raise ValueError('Native player loaded a different music bank')
    for key,run in checked['runs'].items():
        if digest(native/key/'music.wav')!=run['wav_sha256']:raise ValueError('Native preview WAV changed: '+key)
        if run.get('failed') or run.get('effect_volume_writes') or run.get('doc_access_violations'):
            raise ValueError('Native music preview failed validation: '+key)
    return dict(status='verified',renderer_type='native-mame',renderer_sha256=pins['emulator'],audio_build_identity=audio['identity'],bank_sha256=pins['bank'],
                engine_sha256=pins['elf'],disk_sha256=pins['disk'],disk2_sha256=pins.get('disk2'),
                audio_receipt_file=str((compiled/RECEIPT).resolve()),
                audio_receipt_sha256=digest(compiled/RECEIPT),
                native_identity_file=str((native/'identity.json').resolve()),
                native_identity_sha256=digest(native/'identity.json'))


def validate_binding(binding):
    """Recheck the source build before publishing a previously saved capture."""
    receipt=Path(binding['audio_receipt_file'])
    if digest(receipt)!=binding['audio_receipt_sha256']:
        raise ValueError('Preview audio build receipt changed; rebuild the preview')
    if binding.get('renderer_type')!='native-mame':
        raise ValueError('Unsupported preview renderer binding')
    native=Path(binding['native_identity_file']).parent
    if native_binding(native,receipt.parent)!=binding:
        raise ValueError('Preview build binding changed; rebuild the preview')
