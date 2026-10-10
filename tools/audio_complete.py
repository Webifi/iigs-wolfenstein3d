"""Complete music producer: synthesis, intermediaries, game images and comparisons."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from audio_package import write_toml
from game_profile import profile, read_toml
from audio_build_cache import digest
from audio_build_cache import inputs, stage

TOOLS = Path(__file__).resolve().parent


def recipe_inputs(recipe):
    found = set()
    def visit(path):
        path = Path(path).resolve()
        if path in found:
            return
        if not path.is_file():
            raise ValueError('Missing recipe dependency: '+str(path))
        found.add(path)
        if path.suffix != '.toml':
            return
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('file','wav','sampling_policy') and isinstance(item,str):
                        visit(path.parent/item)
                    else:
                        walk(item)
            elif isinstance(value,list):
                for item in value:
                    walk(item)
        walk(read_toml(path))
    visit(recipe)
    return sorted(found)


def compile_music(out, recipes, settings, game, data, jobs):
    """Regenerate a song only when its inputs or any checked output changed."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from audio_compare import copy_wav
    synthesis = Path(settings['synthesis']['settings'])
    cfg = read_toml(synthesis)
    common = [synthesis,TOOLS/'doccompiler',TOOLS.parent/'profiles/audio',
              TOOLS/'music_score.py',TOOLS/'instrument_defaults.py']+[
                  p for p in TOOLS.glob('audio_*.py') if p.stem not in
                  ('audio_complete','audio_build_cache','audio_compare','audio_bench')]
    for section, keys in [('renderer',('executable','track_executable','rom_directory')), ('soundfont',('file',))]:
        for key in keys:
            if key in cfg.get(section, {}):
                common.append((synthesis.parent/cfg[section][key]).resolve())
    base = inputs(common, exclude_dirs=('build',), python=sys.version)
    recipes_by_name = {read_toml(p)['name']:p for p in (recipes/'songs').glob('*.toml')}
    def compile_one(pair):
        song_id, name = pair
        recipe = recipes_by_name[name]
        dep = inputs(recipe_inputs(recipe), compiler=base)
        def action(folder):
            command = [sys.executable,str(TOOLS/'audio_compile.py'),'music',str(recipe),
                       '--settings',str(synthesis),'--out',str(folder/'details'),
                       '--preserve-samples',str(folder/'intermediate')]
            with (folder/'build.log').open('w') as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        built,_ = stage(out,'music-'+name,dep,action)
        return song_id,name,built
    songs, failures, completed = [], [], []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {pool.submit(compile_one, pair):pair for pair in sorted(game.required_music.items())}
        for future in as_completed(pending):
            song_id, name = pending[future]
            try:
                result = future.result()
                songs.append(result)
                completed.append(dict(song_id=song_id, song=name, directory=str(result[2])))
            except Exception as error:
                failures.append(dict(song_id=song_id, song=name, error=str(error)))
            out.mkdir(parents=True, exist_ok=True)
            (out/'music-stage-status.json').write_text(json.dumps(dict(
                required=len(pending), completed=sorted(completed,key=lambda r:r['song_id']),
                failures=sorted(failures,key=lambda r:r['song_id'])),indent=2)+'\n')
    if failures:
        raise ValueError('Music synthesis failed for '+', '.join(r['song'] for r in failures)+
                         '; all other songs were attempted. See '+str(out/'music-stage-status.json'))
    songs.sort()
    deps = inputs([p/'.stage.json' for _,_,p in songs]+[Path(settings['build']['effect_samples']),data],profile=game.key)
    def assemble(folder):
        from audio_intermediate import finish_package
        music, intermediary = folder/'music', folder/'intermediate'
        music.mkdir();intermediary.mkdir()
        from audio_provenance import validate, snapshot, begin, complete
        for _,_,source in songs:validate(source/'details')
        identity=snapshot('music-pack',game.key,[source for _,_,source in songs]+[Path(settings['build']['effect_samples']),data])
        begin(music,identity)
        lines = ['format = 1', 'catalog = '+json.dumps(game.document['engine']), 'player = "wdm2"']
        for song_id,name,source in songs:
            shutil.copytree(source/'details',music/'details'/name,copy_function=copy_wav)
            shutil.copytree(source/'intermediate',intermediary,dirs_exist_ok=True,copy_function=copy_wav)
            bank = music/f'song-{song_id:02}.bin'
            shutil.copy2(source/'details/stored.bin',bank)
            lines += ['', '[[songs]]', 'name = '+json.dumps(name), 'file = '+json.dumps(bank.name), 'sha256 = '+json.dumps(digest(bank))]
        (music/'pack.toml').write_text('\n'.join(lines)+'\n')
        finish_package(intermediary,game)
        from audio_intermediate import export_effects
        export_effects(intermediary,Path(settings['build']['effect_samples']),game,data)
        from music_pack import MusicPack
        MusicPack(music/'pack.toml',game)
        complete(music,identity)
    assembled,_ = stage(out,'music-pack',deps,assemble)
    return assembled/'music',assembled/'intermediate'


def settings_file(path):
    doc = read_toml(path)
    if doc.get('format') != 1:
        raise ValueError('Expected format = 1 complete-audio settings')
    def resolve(section, key, directory=False):
        try:
            value = (path.parent/doc[section][key]).resolve()
        except KeyError as error:
            raise ValueError(f'Missing [{section}].{key} in {path}') from error
        if not (value.is_dir() if directory else value.is_file()):
            raise ValueError(f'Missing [{section}].{key}: {value}')
        doc[section][key] = str(value)
    resolve('synthesis', 'settings')
    resolve('adlib', 'executable')
    resolve('build', 'calypsi', True)
    suffix = '.exe' if os.name == 'nt' else ''
    for name in ('as65816', 'ln65816'):
        if not (Path(doc['build']['calypsi'])/(name+suffix)).is_file():
            raise ValueError('Calypsi bin directory needs '+name+suffix)
    pinned = doc['adlib'].get('sha256')
    if not pinned or digest(doc['adlib']['executable']) != pinned:
        raise ValueError('Pin the checked [adlib].sha256 for '+doc['adlib']['executable'])
    comparison = doc.setdefault('comparison', {})
    jobs = comparison.get('jobs', 1)
    if type(jobs) is not int or not 1 <= jobs <= 16:
        raise ValueError('[comparison].jobs must be an integer from 1 to 16')
    if 'output' in comparison:
        comparison['output'] = str((path.parent/comparison['output']).resolve())
    return doc


def compare_music(compiled, recipes, media, settings, selected_profile, out):
    """Render compiled DOC banks and compare locally generated source references."""
    from audio_compare import export
    game = profile(selected_profile)
    from audio_provenance import validate
    from doc_preview import render_bank, media_binding, MIDI_CATALOG
    validate(compiled)
    build = json.loads((media/'native-build.json').read_text())
    engine_work = Path(build['work_directory'])
    media_binding(media,compiled,engine_work/'build/wolf.elf')
    recipe_paths = {read_toml(p)['name']:p for p in (recipes/'songs').glob('*.toml')}
    hand_picked = {entry['name'] for entry in read_toml(MIDI_CATALOG)['song']}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    preview = Path(settings.get('comparison', {}).get('output', out/'preview'))
    pending = {sid:[dict(section='Music', song=name, song_id=sid, part='Full mix',
        channel=None, label=name+' · full mix', status='pending',
        note='Generation pending for this build.', versions=[])]
        for sid,name in sorted(game.required_music.items())}
    out.mkdir(parents=True, exist_ok=True)
    def publish():
        items = [row for sid in sorted(pending) for row in pending[sid]]
        return export(preview, game.key+' audio comparisons', items)
    publish()
    def compare_song(song_id, name):
        rows = []
        work = compiled/'details'/name
        recipe = recipe_paths[name]
        doc = read_toml(recipe)
        info = json.loads((work/'info.json').read_text())
        source = (recipe.parent/doc['original']['file']).resolve()
        from sb_reference import render as render_sb
        sb_dependencies = inputs([source,settings['adlib']['executable'],TOOLS/'sb_reference.py',
                                  TOOLS/'sb_imf_player.com',TOOLS/'sb_imf_player.s',TOOLS/'audio_build_cache.py'])
        sb,_ = stage(out,'soundblaster-'+name,sb_dependencies,
                     lambda folder: render_sb(source,settings['adlib']['executable'],folder,doc['original']['sha256']))
        adlib = sb/'soundblaster.wav'
        bank = compiled/f'song-{song_id:02}.bin'
        if digest(work/'stored.bin') != digest(bank):
            raise ValueError('Pack and compiled bank differ for '+name)
        versions_doc = render_bank(compiled,bank,engine_work/'build/wolf.elf',out,name,
                                   parts=work,media=media)
        selected = {r['channel']:r['name'] for r in info['selected_instruments']}
        note = 'Developer comparison. DOC comes from this Roland conversion; AdLib is the original Sound Blaster baseline. Recorded levels are unchanged.'
        if name not in hand_picked:
            note += ' No hand-picked MIDI arrangement in midi-sources.toml.'
        def version(label, kind, wav, identity=None, **provenance):
            return dict(label=label, kind=kind, source=wav, sha256=identity, provenance=provenance)
        for key, doc_version in versions_doc.items():
            reference = work/'reference'/('full.wav' if key=='mix' else 'channel-'+key[2:]+'.wav')
            reference_info = json.loads(reference.with_suffix('.json').read_text())
            versions = [version('Roland reference', 'Full instrument-track emulator render', reference,
                                reference_info['wav_sha256'], render=reference_info), doc_version]
            if key=='mix':
                opl = json.loads(adlib.with_suffix('.json').read_text())
                versions.insert(0,version('Original AdLib', 'Sound Blaster 16 · DOSBox-X capture', adlib, opl['wav_sha256'], render=opl))
            label = name+' · '+('full mix' if key=='mix' else selected[int(key[2:])]+' · CH'+key[2:])
            rows.append(dict(section='Music', song=name, song_id=song_id, part='Full mix' if key=='mix' else selected[int(key[2:])]+' · CH'+key[2:], channel=None if key=='mix' else int(key[2:]), label=label, note=note, versions=versions, default_version=len(versions)-1))
        return rows
    failures = []
    collected = set()
    with ThreadPoolExecutor(max_workers=settings.get('comparison',{}).get('jobs',1)) as pool:
        work = {pool.submit(compare_song, sid, name):(sid,name) for sid,name in sorted(game.required_music.items())}
        for future in as_completed(work):
            sid,name = work[future]
            try:
                pending[sid] = future.result()
            except Exception as error:
                pending[sid][0].update(status='failed', note=str(error))
                failures.append(name+': '+str(error))
            collected.add(future)
            # Export the ready batch together; exporting a growing table for
            # every already-completed song repeats all recording checks.
            if not any(f.done() and f not in collected for f in work):
                publish()
    if failures:
        raise ValueError('Comparison render failures: '+'; '.join(failures))
    return preview/'index.html'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='shareware')
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--recipes', type=Path, help='existing edited recipes; otherwise restore the shipped arrangements')
    parser.add_argument('--midi-dir', action='append', default=[], type=Path)
    parser.add_argument('--settings', required=True, type=Path, help='complete-audio settings TOML')
    parser.add_argument('--out', required=True, type=Path, help='developer build target; verified current stages are reused')
    parser.add_argument('--jobs', type=int, default=1, choices=range(1,17))
    args = parser.parse_args()
    out = args.out.resolve()
    try:
        game = profile(args.profile)
        settings = settings_file(args.settings.resolve())
        from audio_compare import export_status
        preview=Path(settings.get('comparison',{}).get('output',out/'comparisons/preview'))
        export_status(preview,game.key+' audio comparisons','Audio build in progress; prior recordings are not verified for this build.','pending')
        out.mkdir(parents=True,exist_ok=True)
        (out/'complete.json').write_text(json.dumps(dict(status='building',listening_accepted=False))+'\n')
        recipes = args.recipes.resolve() if args.recipes else out/'recipes'
        if not args.recipes:
            if args.midi_dir:
                command = [sys.executable,str(TOOLS/'audio_recipes.py'),'generate','--profile',args.profile,
                           '--data',str(args.data.resolve()),'--out',str(recipes)]
                for folder in args.midi_dir:
                    command += ['--midi-dir',str(folder.resolve())]
                subprocess.run(command,check=True)
            else:
                from audio_recipes import restore
                package=TOOLS.parent/'audio-source'/('spear' if game.spear else game.key)
                restore(package,args.data,game,recipes)
        from dos_data import DosData
        original = DosData(args.data.resolve(),game).audio()
        by_name={read_toml(p)['name']:read_toml(p) for p in (recipes/'songs').glob('*.toml')}
        import hashlib
        for sid,name in game.required_music.items():
            expected=hashlib.sha256(original[game.sounds*3+sid]).hexdigest()
            if by_name[name]['original']['sha256'] != expected:
                raise ValueError(name+' recipe belongs to different licensed AdLib source data')
        from audio_effects import regenerate
        settings['build']['effect_samples']=str(regenerate(out,args.data,game))
        compiled, intermediate = compile_music(out,recipes,settings,game,args.data.resolve(),args.jobs)
        from consumer_build import preflight
        suffix='.exe' if os.name=='nt' else ''
        engine_dependencies=inputs([TOOLS.parent/f for f in ('src','tools','profiles','data')]+
            [args.data.resolve(),compiled/'pack.toml',Path(settings['build']['effect_samples'])]+
            list(compiled.glob('song-*.bin'))+
            [Path(settings['build']['calypsi'])/(n+suffix) for n in ('as65816','ln65816')],profile=game.key)
        def build_images(folder):
            report = preflight(args.data.resolve(),folder,selected_profile=args.profile,
                               build_options=dict(calypsi=Path(settings['build']['calypsi']),music_pack=compiled/'pack.toml',
                                                  effect_samples=Path(settings['build']['effect_samples']),jobs=args.jobs))
            if report['status'] != 'build-complete':
                raise ValueError('Native build incomplete; see '+str(folder/'build-report.json'))
        media,_=stage(out,'images',engine_dependencies,build_images)
        html = compare_music(compiled,recipes,media/game.key,settings,args.profile,out/'comparisons')
        (out/'complete.json').write_text(json.dumps(dict(status='complete',profile=game.key,comparison_page=str(html),images=str(media/game.key),
            intermediary=str(intermediate),doc_renderer='compiled-doc-python',doc_previews_verified=True,listening_accepted=False),indent=2)+'\n')
        print('Complete producer output: '+str(html))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        if 'preview' in locals():
            export_status(preview,game.key+' audio comparisons','Build failed: '+str(error),'failed')
        if out.is_dir():
            (out/'complete.json').write_text(json.dumps(dict(status='failed',error=str(error),listening_accepted=False),indent=2)+'\n')
        parser.exit(2,str(error)+'\n')


if __name__ == '__main__':
    main()
