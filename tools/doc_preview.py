"""Build authenticated DOC previews and optional, cached synthesis references."""
import json
import os
from pathlib import Path
import subprocess
import sys

from audio_build_cache import digest, inputs, stage, outputs, verify_inputs
from audio_compare import export, export_status
from audio_provenance import validate

TOOLS = Path(__file__).resolve().parent
MIDI_CATALOG = TOOLS.parent/'profiles/audio/midi-sources.toml'


def render_stage(root, name, dependencies, action, *, doc=False):
    """Reuse identical render inputs even when the build stage has a new path."""
    def signature(value, key='', top=False):
        if not isinstance(value,dict):return value
        result={}
        for field,item in value.items():
            if field in ('files','renderer') and isinstance(item,dict):
                files=[(Path(path).name,identity) for path,identity in item.items()
                       if Path(path).name!='doc_preview.py']
                # The bank and ELF move together into each fresh native stage.
                result[field]=sorted(identity for _,identity in files) if doc and top and field=='files' else sorted(files)
            else:result[field]=signature(item,field)
        return result
    expected=signature(dependencies,top=True)
    for marker in sorted((Path(root)/'.audio-cache'/name).glob('*/.stage.json')):
        if '.stale-' in marker.parent.name:continue
        try:
            saved=json.loads(marker.read_text())
            if signature(saved['inputs'],top=True)!=expected:continue
            if saved['outputs']!=outputs(marker.parent):continue
        except (OSError,ValueError,KeyError):
            continue
        verify_inputs(dependencies)
        print('Validated cached inputs and outputs: '+name,flush=True)
        return marker.parent,False
    return stage(root,name,dependencies,action)


def bundle_engine(root, game, bundle=None):
    from audio_package import checked, contained
    from game_profile import read_toml
    path=Path(bundle) if bundle else Path(root)/'bundles'/game.key/'engine-bundle.toml'
    if path.is_dir():path/='engine-bundle.toml'
    doc=read_toml(path)
    if game.key not in doc['verified_profiles']:
        raise ValueError('Engine bundle does not support '+game.key)
    entry=doc['files']['engine']
    engine=contained(path.parent,entry['path'])
    checked(engine,entry['sha256'])
    return engine


def media_binding(media, compiled, engine):
    """Inspect packed bytes; a file name or a prior build report is insufficient."""
    from check_media_audio import check
    media=Path(media)
    build=json.loads((media/'native-build.json').read_text())
    receipt=Path(compiled)/'audio-build.json'
    if build['audio_receipt_sha256']!=digest(receipt):
        raise ValueError('Packaged game was built with a different audio receipt')
    work=Path(build['work_directory'])
    if digest(engine)!=digest(work/'build/wolf.elf'):
        raise ValueError('Preview engine differs from the packaged build')
    source=work/'build/gen/audio-input.json'
    selected=json.loads(source.read_text())
    audio=validate(compiled)
    for song in selected['songs']:
        bank=f'song-{song["id"]:02}.bin'
        if audio['outputs'].get(bank)!=song['sha256']:
            raise ValueError('Packaged audio selection differs from rebuilt bank: '+song['name'])
    checked=check(media/'wolf-hd.po',selected)
    if checked['status']!='verified':raise ValueError('Packaged audio verification failed')
    return dict(directory=str(media.resolve()),build_sha256=digest(media/'native-build.json'),
                source_sha256=digest(source),images=checked['images'])


class BindingChecks:
    """Authenticate shared packages once per render/export, then check again."""
    def __init__(self):
        self.audio = {}
        self.media = {}

    def package(self, receipt):
        key = str(receipt)
        if key not in self.audio:
            self.audio[key] = validate(receipt)
        return self.audio[key]

    def packaged(self, directory, compiled, engine):
        key = tuple(map(str, (directory, compiled, engine)))
        if key not in self.media:
            self.media[key] = media_binding(*key)
        return self.media[key]

    def verify(self):
        # Changes during a table export must fail before it is published.
        for receipt, expected in self.audio.items():
            if validate(receipt) != expected:
                raise ValueError('Audio changed while preparing comparison: '+receipt)
        for key, expected in self.media.items():
            if media_binding(*key) != expected:
                raise ValueError('Packaged game changed while preparing comparison: '+key[0])


def validate_binding(binding, checks=None):
    checks = checks or BindingChecks()
    receipt=Path(binding['audio_receipt_file'])
    if digest(receipt)!=binding['audio_receipt_sha256']:
        raise ValueError('Preview audio receipt changed; regenerate the preview')
    audio=checks.package(receipt)
    bank=Path(binding['bank_file'])
    relative=bank.resolve().relative_to(receipt.parent.resolve()).as_posix()
    if audio['outputs'].get(relative)!=binding['bank_sha256'] or digest(bank)!=binding['bank_sha256']:
        raise ValueError('Preview belongs to a different compiled bank')
    engine=Path(binding['engine_file'])
    if digest(engine)!=binding['engine_sha256']:
        raise ValueError('Preview engine changed; regenerate the preview')
    for path,expected in binding['renderer_inputs'].items():
        if digest(path)!=expected:raise ValueError('Preview renderer changed; regenerate the preview')
    rendered=json.loads(Path(binding['render_receipt_file']).read_text())
    if digest(binding['render_receipt_file'])!=binding['render_receipt_sha256']:
        raise ValueError('DOC render receipt changed')
    for key in ('bank_sha256','engine_sha256'):
        if rendered[key]!=binding[key]:raise ValueError('DOC render identity differs: '+key)
    if rendered['output']['sha256']!=digest(binding['wav_file']):
        raise ValueError('DOC preview WAV changed; regenerate the preview')
    for path,expected in rendered.get('part_inputs',{}).items():
        relative=Path(path).resolve().relative_to(receipt.parent.resolve()).as_posix()
        if digest(path)!=expected or audio['outputs'].get(relative)!=expected:
            raise ValueError('DOC instrument metadata changed; regenerate the preview')
    if rendered['gain']!=1 or rendered['normalization']:
        raise ValueError('DOC preview must retain the renderer output level')
    if binding.get('media'):
        if checks.packaged(binding['media']['directory'],receipt.parent,engine)!=binding['media']:
            raise ValueError('Packaged game changed; regenerate the preview')


def render_bank(compiled, bank, engine, out, name, *, parts=None, media=None):
    """One authenticated DOC-to-WAV path for easy and complete builds."""
    compiled,bank,engine,out=map(lambda p:Path(p).resolve(),(compiled,bank,engine,out))
    audio=validate(compiled)
    receipt=compiled/'audio-build.json'
    relative=bank.relative_to(compiled).as_posix()
    if audio['outputs'].get(relative)!=digest(bank):
        raise ValueError('Preview bank was not produced by this audio build: '+name)
    renderer_files=[TOOLS/file for file in
        ('doc_render.py','doc_output.py','emu816.py','elf.py','music_pack.py')]
    import memmap
    renderer_files.append(Path(memmap.__file__).resolve())
    part_files=[]
    if parts is not None:
        parts=Path(parts).resolve()
        part_files=[parts/file for file in ('unit.bin','notes.json','stereo.txt')]
        for path in part_files:
            if audio['outputs'].get(path.relative_to(compiled).as_posix())!=digest(path):
                raise ValueError('Instrument metadata was not produced by this audio build: '+str(path))
        renderer_files += [TOOLS/'doc_parts.py',TOOLS/'doccompiler']
    renderer_inputs=inputs(renderer_files,exclude_dirs=('build',))['files']
    dependencies=inputs([bank,engine]+part_files,renderer=renderer_inputs,
                        music_volume=15,system_volume=15)
    def render(folder):
        command=[sys.executable,str(TOOLS/'doc_render.py'),str(bank),
                 '--engine',str(engine),'--out',str(folder/'doc.wav')]
        if parts is not None:command += ['--parts',str(parts)]
        with (folder/'render.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    if parts is None:
        folder,_=render_stage(out,'doc-'+name,dependencies,render,doc=True)
    else:
        folder,_=stage(out,'doc-'+name+'-parts',dependencies,render)
    mixed=json.loads((folder/'doc.json').read_text())
    if parts is not None and not mixed.get('channels'):
        raise ValueError('Instrument renderer produced no channel metadata')
    packed=media_binding(media,compiled,engine) if media else None
    checks=BindingChecks()
    checks.audio[str(receipt)]=audio
    if media:
        checks.media[tuple(map(str,(media,compiled,engine)))]=packed
    versions={}
    for key in ['mix']+[f'ch{channel:02}' for channel in mixed.get('channels',[])]:
        stem='doc' if key=='mix' else key
        wav=folder/(stem+'.wav');render_receipt=folder/(stem+'.json')
        rendered=json.loads(render_receipt.read_text())
        binding=dict(status='verified',renderer_type='compiled-doc-python',
            audio_build_identity=audio['identity'],audio_receipt_file=str(receipt),
            audio_receipt_sha256=digest(receipt),bank_file=str(bank),bank_sha256=digest(bank),
            engine_file=str(engine),engine_sha256=digest(engine),renderer_inputs=renderer_inputs,
            render_receipt_file=str(render_receipt),render_receipt_sha256=digest(render_receipt),
            wav_file=str(wav),media=packed)
        validate_binding(binding,checks)
        versions[key]=dict(label='Generated DOC',kind='Compiled-bank Python renderer',
            source=wav,sha256=rendered['output']['sha256'],
            provenance=dict(build_binding=binding,render=rendered))
    checks.verify()
    return versions


def reference_settings(path):
    """Read the same local renderer settings as the complete synthesis workflow."""
    from game_profile import read_toml
    if path is None:return None
    path=Path(path).resolve()
    config=read_toml(path)
    if config.get('format')!=1:raise ValueError('Expected format-1 complete-audio settings')
    settings=(path.parent/config['synthesis']['settings']).resolve()
    renderer=read_toml(settings)['renderer']
    executable=(settings.parent/renderer['executable']).resolve()
    roms=(settings.parent/renderer['rom_directory']).resolve()
    adlib=(path.parent/config['adlib']['executable']).resolve()
    if not executable.is_file() or not roms.is_dir() or not adlib.is_file():
        raise ValueError('Configured preview renderer or ROM directory is missing')
    for tool,expected in ((executable,renderer.get('executable_sha256')),
                          (adlib,config['adlib']['sha256'])):
        if expected and digest(tool)!=expected:raise ValueError('Preview renderer hash differs: '+str(tool))
    jobs=config.get('comparison',{}).get('jobs',os.cpu_count() or 1)
    if type(jobs) is not int or jobs<1:raise ValueError('comparison.jobs must be a positive integer')
    return dict(settings=settings,executable=executable,roms=roms,adlib=adlib,jobs=jobs)


def reference_plan(package, data, game, settings, names):
    from audio_package import validate_dos
    from audio_recipes import recipe_midi, sha
    from music_score import midi_read
    config=reference_settings(settings)
    if config is None:return None
    if package is None or data is None:
        raise ValueError('Synthesis previews require the prepared audio source and licensed DOS files')
    package=Path(package).resolve()
    licensed=validate_dos(package,game,data)
    common=inputs([config['settings'],config['executable'],config['roms'],
        TOOLS/'audio_recipes.py',TOOLS/'music_score.py',TOOLS/'audio_build_cache.py'])
    sb=inputs([config['adlib'],TOOLS/'sb_reference.py',TOOLS/'sb_imf_player.com',
               TOOLS/'sb_imf_player.s',TOOLS/'audio_build_cache.py'])
    songs={}
    for name in names:
        recipe=package/'songs'/(name+'.toml')
        midi,doc=recipe_midi(recipe,licensed_imf=licensed[name])
        if sha(licensed[name])!=doc['original']['sha256']:
            raise ValueError('Original AdLib input differs from recipe: '+name)
        songs[name]=dict(midi=midi,recipe=doc,original=licensed[name],
            seconds=midi_read(midi)[1][-1].seconds,
            roland=dict(common=common,midi_sha256=sha(midi),policy=doc['render']),
            adlib=dict(common=sb,imf_sha256=sha(licensed[name])))
    return dict(config=config,songs=songs)


def render_reference(plan, name, kind, out):
    from audio_package import write_toml
    from audio_recipes import sha
    from sb_reference import render as render_sb
    import tempfile
    row=plan['songs'][name];config=plan['config']
    def render(folder):
        # Licensed scores are scratch inputs, never part of the prepared package.
        with tempfile.TemporaryDirectory(prefix='reference-',dir=folder) as temporary:
            work=Path(temporary)
            if kind=='adlib':
                original=work/'original.imf';original.write_bytes(row['original'])
                render_sb(original,config['adlib'],folder,sha(row['original']))
            else:
                midi=work/'score.mid';midi.write_bytes(row['midi'])
                doc={key:row['recipe'][key] for key in
                     ('format','kind','name','original','render','capture','reconstruction')}
                # recipe_midi has already applied the score edits and program choices.
                doc['source']=dict(kind='midi',file='score.mid',sha256=sha(row['midi']),
                                   authority=row['recipe']['source']['authority'])
                recipe=work/'reference.toml';write_toml(recipe,doc)
                with (folder/'render.log').open('w') as log:
                    subprocess.run([sys.executable,str(TOOLS/'audio_recipes.py'),'wav',str(recipe),
                        '--settings',str(config['settings']),'--out',str(folder/'full.wav')],
                        stdout=log,stderr=subprocess.STDOUT,check=True)
    folder,_=render_stage(out,kind+'-'+name,row[kind],render)
    stem='soundblaster' if kind=='adlib' else 'full'
    receipt=json.loads((folder/(stem+'.json')).read_text())
    return dict(label='Original AdLib' if kind=='adlib' else 'Roland reference',
        kind='Sound Blaster 16 · DOSBox-X capture' if kind=='adlib' else 'SC-55 · complete arranged score',
        source=folder/(stem+'.wav'),sha256=receipt['wav_sha256'],
        provenance=dict(render=receipt,dependencies=row[kind],gain=1,normalization=False))


def generate(compiled, engine, out, game, song=None, jobs=1, media=None,
             package=None, data=None, settings=None, cache=None):
    """Render only changed songs; all comparisons retain recorded output levels."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from game_profile import read_toml
    compiled,engine,out=Path(compiled).resolve(),Path(engine).resolve(),Path(out).resolve()
    cache=Path(cache).resolve() if cache is not None else out
    title=game.key+' audio comparison'
    export_status(out,title,'Generating previews for this build.','pending')
    try:
        validate(compiled)
        required={sid:name for sid,name in game.required_music.items() if song is None or name==song}
        if not required:raise ValueError('No required songs selected for preview')
        references=reference_plan(package,data,game,settings,required.values())
        selected={entry['name'] for entry in read_toml(MIDI_CATALOG)['song']}
        def render_one(pair):
            sid,name=pair
            bank=compiled/('stored.bin' if song else f'song-{sid:02}.bin')
            rendered=render_bank(compiled,bank,engine,cache,name,media=media)['mix']
            if references:
                versions=[render_reference(references,name,kind,cache) for kind in ('roland','adlib')]
            else:
                versions=[dict(label=label,kind=kind,status='unavailable',
                    reason='Configure --audio-preview-settings or WOLF_AUDIO_SETTINGS to render this reference.')
                    for label,kind in [('Roland reference','SC-55'),('Original AdLib','Sound Blaster 16')]]
            versions.append(rendered)
            note='Full song; recorded levels unchanged. DOC model at nominal stock timing; music only.'
            if name not in selected:note+=' No hand-picked MIDI arrangement in midi-sources.toml; score reconstructed from AdLib.'
            return dict(section='Music',song=name,song_id=sid,part='Full mix',channel=None,
                label=name+' · full mix',note=note,versions=versions,default_version=2)
        pending={sid:dict(section='Music',song=name,song_id=sid,part='Full mix',label=name+' · full mix',
                         note='Preview pending for this build.',status='pending',versions=[])
                 for sid,name in required.items()}
        failures=[];published=False
        with ThreadPoolExecutor(max_workers=references['config']['jobs'] if references else jobs) as pool:
            pairs=sorted(required.items(),key=lambda pair:references['songs'][pair[1]]['seconds']) if references else required.items()
            work={pool.submit(render_one,pair):pair for pair in pairs}
            for future in as_completed(work):
                sid,name=work[future]
                try:
                    pending[sid]=future.result()
                    print('Preview ready: '+name,flush=True)
                except Exception as error:
                    pending[sid].update(status='failed',note=str(error));failures.append(name+': '+str(error))
                    print('Preview failed: '+name+': '+str(error),flush=True)
                # Publish the first result promptly; avoid re-auditing every PCM file
                # after every song. Rendering continues while the page is exported.
                if not published:
                    export(out,title,[pending[sid] for sid in sorted(pending)])
                    published=True
        export(out,title,[pending[sid] for sid in sorted(pending)])
        if failures:raise ValueError('Audio previews incomplete: '+'; '.join(failures))
        return out/'index.html'
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        export_status(out,title,'Audio preview failed: '+str(error),'failed')
        raise
