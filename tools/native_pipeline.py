"""Generate assets, assemble the selected engine recipe and pack disk images."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from game_profile import read_toml
from native_recipe import load as load_native_recipe


def native_recipe(root, game):
    return load_native_recipe(root, game.key)


def build_jobs():
    """Parallel build processes; WOLF_JOBS overrides the detected CPU count."""
    return int(os.environ.get('WOLF_JOBS') or os.cpu_count() or 1)

def text_hash(path):
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').replace('\r\n', '\n').encode()).hexdigest()


def stage_sources(root, destination):
    """Each build owns a fresh tree; developer checkouts are never regenerated."""
    destination.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.build-', dir=destination))
    for folder in ('tools', 'src', 'profiles', 'data'):
        shutil.copytree(root/folder, stage/folder, ignore=shutil.ignore_patterns('__pycache__', 'build'))
    shutil.copy2(root/'Makefile', stage/'Makefile')
    for folder in ('build/gen', 'build/obj', 'build/boot', 'licensed-data'):
        (stage/folder).mkdir(parents=True, exist_ok=True)
    return stage


def stage_profile(stage, game):
    """Copy the selected profile and resources with paths relative to the stage."""
    from copy import deepcopy
    from audio_package import write_toml
    selected = stage/'profiles/selected'
    selected.mkdir(parents=True, exist_ok=True)
    doc = deepcopy(game.document)
    write_toml(selected/'conversion.toml', game.conversion)
    doc['conversion'] = 'conversion.toml'
    for key in ('campaign', 'map_semantics'):
        source = game.resource(key)
        if source is None:
            raise ValueError('Native source profile requires '+key)
        resource = read_toml(source)
        if key == 'map_semantics' and 'sprite_catalog' in resource:
            sprite_source = source.parent/resource['sprite_catalog']
            shutil.copy2(sprite_source, selected/'sprites.toml')
            resource['sprite_catalog'] = 'sprites.toml'
        filename = key+'.toml'
        write_toml(selected/filename, resource)
        doc[key] = filename
    write_toml(selected/'profile.toml', doc)
    return selected/'profile.toml'


def write_if_changed(path, data):
    """Keep an unchanged file untouched (its cached hash stays valid)."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode()
    try:
        if path.read_bytes() == data:
            return
    except FileNotFoundError:
        pass
    path.write_bytes(data)


def source_assets(steps, execute, music=None, sprite_groups=None):
    """Source dependencies, including on the first build with no trace records.

    Names are the recipe's tool stems. Unknown recipes retain their declared
    serial order. build_loads is a barrier because it inventories the assets.
    The dependencies cover reads, overwritten files and directory inventories.
    """
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    deps = {
        'prepare_profile': [], 'build_campaign': [], 'prepare_audio': [],
        'gen_tics': [], 'gen_config': [], 'build_colors': [],
        'build_assets': ['gen_config', 'build_colors'],
        'build_world': ['build_assets'], 'build_logic': ['build_world'],
        'build_demos': [], 'gen_scalers': ['gen_config'], 'build_sound': ['prepare_audio'],
        'share_effects': ['build_sound'],
        'build_sprites': ['build_logic', 'gen_scalers', 'share_effects', 'build_sound'],
        'check_art_coverage': ['build_sprites'], 'build_ui': [],
        'gen_views': ['gen_config'], 'gen_shading': ['build_assets'],
        'gen_tints': ['gen_config', 'build_colors', 'build_ui'],
        'build_menu': ['build_campaign', 'gen_tints'],
        'build_menu_cache': ['build_sound', 'build_menu'],
        'build_words': ['build_menu_cache'],
        'build_weapon_masks': ['gen_scalers', 'build_sprites'],
        'build_weapon_drawers': ['build_menu', 'build_weapon_masks'],
        'gen_ray_tables': [], 'gen_ray_height': ['gen_ray_tables'],
        'gen_controls': [], 'gen_mouse': [], 'gen_death': [],
        'gen_ray_programs': ['gen_config'], 'build_loads': [],
    }
    names = [Path(s['arguments'][0]).stem for s in steps]
    if len(set(names)) != len(names) or set(names) - set(deps):
        if music:
            music()
        for step in steps:
            if sprite_groups and Path(step['arguments'][0]).stem == 'build_sprites':
                sprite_groups()
            execute(step)
        return
    jobs = {name: (lambda step=step: execute(step)) for name, step in zip(names, steps)}
    waits = {name: set(deps[name]) & set(names) for name in names}
    for name in names:
        if name != 'prepare_profile':
            waits[name].add('prepare_profile')
    if 'build_loads' in waits:
        waits['build_loads'] = set(names) - {'build_loads'}
    if music:
        jobs['music'] = music
        waits['music'] = set()
        waits['prepare_audio'].add('music')
    if sprite_groups:
        jobs['sprite_groups'] = sprite_groups
        # Pool-strip sizes used by grouping read the fitted floor palettes.
        waits['sprite_groups'] = {'prepare_profile', 'build_colors'} & set(names)
        waits['build_sprites'].add('sprite_groups')
    pending, done, running = dict(jobs), set(), {}
    with ThreadPoolExecutor(max_workers=build_jobs()) as pool:
        while pending or running:
            for name in list(pending):
                if waits[name] <= done:
                    running[pool.submit(pending.pop(name))] = name
            if not running:
                raise ValueError('Cycle in source asset dependencies')
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                future.result()
                done.add(running.pop(future))


def engine_jobs(recipe, game):
    """(boot units, objects) as (source, object, defines), in the recipe's order."""
    boot = [('src/iigs/'+name+'.s', 'build/boot/'+name+'.o', []) for name in ('boot', 'loader')]
    boot += [('src/iigs/'+name+'.s', 'build/boot/'+name+'.o', []) for name in ('fixed_gen', 'weapon_comp', 'sight_gen')]
    objects = []
    for obj in recipe['objects']:
        stem = Path(obj).stem
        assembly = ('build/gen/' if stem in ('scalers', 'ray_programs') else 'src/iigs/')+stem+'.s'
        defines = ['-D', 'UI_SOUND=1', '-D', 'UI_DEMOS=1', '-D', 'UI_LOGIC=1'] if stem in ('ui_sound', 'ui_hooks', 'ui_demo', 'ui_save') else []
        objects.append((assembly, obj, defines))
    return boot, objects


def post_command(step, game):
    command = [sys.executable]+step['arguments']
    if step['arguments'][0]=='tools/build_episode.py':
        command += ['--groups','build/sprite-groups.json']
    return command


def cached_build(cache, stage, game, recipe, env, log, destination, commands, assembler, linker, disk, bundle=None,
                 cold=False, audio_command=None, audio_env=None):
    """The build with tools/step_cache.py: the same commands as the plain
    build, each skipped when nothing it read changed, independent ones side
    by side. The whole order is known first, so a step that runs sees the
    stage as a build from an empty stage shows it (step_cache.set_plan)."""
    from palette_cache import fit_floors, command as fit_command
    python = sys.executable
    flags = ['--code-model=large', '--data-model=medium', '-I', 'build/gen', '-I', 'src/iigs']
    segments = [('run', [python, 'tools/memmap.py', 'build/gen'])]
    if audio_command is not None:
        segments.insert(0, ('run', audio_command))
    host = [python, 'tools/native_host.py']
    if host not in commands:
        segments.append(('run', host))
    pending = []
    for step in recipe['asset_step']:
        if step.get('always', False):
            segments += [('steps', pending), ('fresh', [python]+step['arguments'])]
            pending = []
            continue
        if step['arguments'] == ['tools/build_colors.py']:
            # One fit per floor, in parallel, each only when what it read changed
            # (tools/palette_cache.py); the fits travel in data/palette-cache.
            segments += [('steps', pending), ('palettes', [fit_command(n) for n in range(game.floors)])]
            pending = []
        elif step['arguments'] == ['tools/build_sprites.py']:
            # The work of build_sprites.py: the shared sprite groups, one step per
            # floor in parallel, then the shared outputs (build_registered_sprites.py).
            groups = 'build/sprite-groups.json'
            segments += [('steps', pending),
                         ('run', [python, 'tools/build_registered_sprites.py', '--save-groups', groups]),
                         ('floors', [[python, 'tools/build_registered_sprites.py', '--floor', str(n), '--groups', groups]
                                     for n in reversed(range(game.floors))]),
                         ('run', [python, 'tools/build_registered_sprites.py', '--finish'])]
            pending = []
        else:
            pending.append([python]+step['arguments'])
    segments.append(('steps', pending))
    asset_end = len(segments)
    if assembler is None:
        # A consumer build: the engine comes from the bundle.
        from native_bundle import install_engine, verify_generated_bindings
        segments += [('call', lambda: install_engine(stage, bundle)),
                     ('run', [python, 'tools/gen_loader_api.py']),
                     ('call', lambda: verify_generated_bindings(stage, bundle))]
    else:
        boot, objects = engine_jobs(recipe, game)
        # The boot and loader first: gen_loader_api.py reads the loader's symbols.
        segments.append(('assemble', boot[:2]))
        for source, obj, _ in boot[:2]:
            name = Path(obj).stem
            segments.append(('link', ('src/iigs/'+name+'.scm', [obj],
                                      ['-o', 'build/boot/'+name+'.elf', 'src/iigs/'+name+'.scm', obj, '--output-format', 'raw'])))
        segments.append(('run', [python, 'tools/gen_loader_api.py']))
        # Everything else assembles in parallel; unchanged objects are kept.
        segments.append(('assemble', boot[2:] + objects))
        for source, obj, _ in boot[2:]:
            name = Path(obj).stem
            segments.append(('link', ('src/iigs/'+name+'.scm', [obj],
                                      ['-o', 'build/boot/'+name+'.raw', 'src/iigs/'+name+'.scm', obj, '--output-format', 'raw'])))
        segments.append(('link', (recipe['settings']['linker'], recipe['objects'],
                                  ['-o', 'build/wolf.elf', recipe['settings']['linker']]+recipe['objects']+
                                  ['--hosted', '--list-file', 'build/wolf.lst'])))
    # The checks and the disk build run side by side where they share no file.
    segments.append(('steps', [post_command(step,game) for step in recipe['post_link']] + [disk]))

    def to_commands(kind, payload):
        if kind in ('run', 'fresh'):
            return [payload]
        if kind in ('steps', 'palettes', 'floors'):
            return payload
        if kind == 'assemble':
            return [[assembler]+flags+extra+['-o', obj, source] for source, obj, extra in payload]
        if kind == 'link':
            return [[linker]+payload[2]]
        return []
    plan = [[str(v) for v in c] for kind, payload in segments for c in to_commands(kind, payload)]
    cache.set_plan(commands + plan)
    # Music and its host helper ran before this plan was installed. Their
    # products are already present, including when an earlier step is skipped.
    for command in commands:
        cache.mark(command)
    commands += plan
    if cold:
        (stage/'build/assets').mkdir(exist_ok=True)
        def execute(command, reason=None, step_env=env):
            with log.open('a', encoding='utf-8') as output:
                if command == audio_command:
                    # Songs own their records and locks; the pack only validates
                    # the catalog and publishes current provenance.
                    subprocess.run(command,cwd=stage,env=step_env,stdout=output,
                                   stderr=subprocess.STDOUT,check=True)
                    cache.completed_outputs((stage/'build/audio/music').rglob('*'))
                else:
                    cache.python(command, step_env, output, reason)
        execute([python, 'tools/memmap.py', 'build/gen'])
        groups = 'build/sprite-groups.json'
        def asset(step):
            if step.get('always',False):
                execute([python]+step['arguments'], 'required every build')
            elif step['arguments'] == ['tools/build_colors.py']:
                fit_floors(cache, stage, game, env, log, destination/'palette-cache')
            elif step['arguments'] == ['tools/build_sprites.py']:
                cache.parallel([[python, 'tools/build_registered_sprites.py', '--floor', str(n), '--groups', groups]
                                for n in reversed(range(game.floors))], env, log, 'floor art layouts')
                execute([python, 'tools/build_registered_sprites.py', '--finish'])
            else:
                execute([python]+step['arguments'], 'required every build' if step.get('always',False) else None)
        source_assets(recipe['asset_step'], asset,
                      (lambda: execute(audio_command, step_env=audio_env)) if audio_command else None,
                      lambda: execute([python,'tools/build_registered_sprites.py','--save-groups',groups]))
        segments = segments[asset_end:]
    for kind, payload in segments:
        if kind in ('run', 'fresh'):
            with log.open('a', encoding='utf-8') as output:
                cache.python(payload, env, output, 'required every build' if kind == 'fresh' else None)
        elif kind == 'steps' and payload:
            cache.run_steps(payload, env, log)
        elif kind == 'palettes':
            fit_floors(cache, stage, game, env, log, destination/'palette-cache')
        elif kind == 'floors':
            cache.parallel(payload, env, log, 'floor art layouts')
        elif kind == 'assemble':
            cache.assemble(assembler, flags, ['build/gen', 'src/iigs'], payload, log)
        elif kind == 'link':
            cache.link(linker, *payload, log)
        elif kind == 'call':
            # In-process work outside the cache: the files of the steps after it
            # are put back or made again by those steps.
            payload()
    cache.drop_old_steps()


def build_images(root, manifest, source, audio_source, destination, *, bundle=None,
                 calypsi=None, music_pack=None, effect_samples=None, jobs=1, scsi=False):
    began = time.monotonic()
    jobs = min(jobs, build_jobs())
    (destination/'native-build.json').unlink(missing_ok=True)
    (destination/'media-audio.json').unlink(missing_ok=True)
    game = source.profile
    recipe = load_native_recipe(root, game.key)
    if recipe['format'] != 2 or recipe['game'] != game.key or len(recipe['objects']) != 90:
        raise ValueError('Expected the current 90-object format-2 engine recipe')
    assembler = linker = None
    if calypsi:
        suffix = '.exe' if os.name == 'nt' else ''
        assembler = Path(calypsi).resolve()/('as65816'+suffix)
        linker = Path(calypsi).resolve()/('ln65816'+suffix)
        if not assembler.is_file() or not linker.is_file():
            raise ValueError('--calypsi must contain as65816 and ln65816')
    stage = stage_sources(root, destination)
    commands = []
    generated_audio = music_pack is None
    env = dict(os.environ, WOLF_PROFILE=str(stage_profile(stage, game)), WOLF_DOS_DATA=str(stage/'licensed-data'),
               WOLF_REFERENCE_SOURCE=str(stage/'data/reference'), WOLF_FRONTEND_ROOT=str(stage))
    # Clear inherited choices so one game build cannot accidentally use another's inputs.
    for key in ('WOLF_SHARED_DATA', 'WOLF_MUSIC_PACK', 'WOLF_EFFECT_SAMPLES', 'WOLF_YM_DATA', 'WOLF_STEP_CACHE'):
        env.pop(key, None)
    for stem in game.files:
        write_if_changed(stage/'licensed-data'/source.filename(stem), source.read(stem))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # Reproducible steps: with random str hashing, set order changes some outputs
    # between two runs of the same step (registered-art.json key order).
    env['PYTHONHASHSEED'] = '0'
    log = destination/'build.log'
    # Steps whose recorded inputs did not change are skipped (tools/step_cache.py);
    # WOLF_STEP_CACHE=0 runs every step, as a build from an empty stage does.
    cache = None
    if os.environ.get('WOLF_STEP_CACHE', '1') != '0':
        from step_cache import StepCache
        cache = StepCache(stage, log=lambda line: print(line, flush=True), source_root=root)
    cold_cache = cache is not None and not any((cache.folder/'steps').glob('*.json'))

    def run(command):
        command = [str(v) for v in command]
        commands.append(command)
        print('Build: '+ ' '.join(command), flush=True)
        with log.open('a', encoding='utf-8') as output:
            song_pack=len(command)>2 and command[1:3]==['tools/audio_compile.py','music-pack']
            if cache is not None and not song_pack:
                cache.python(command, env, output)
            else:
                step_env=dict(env,WOLF_STEP_CACHE='0') if song_pack and cache is None else env
                subprocess.run(command, cwd=stage, env=step_env, stdout=output, stderr=subprocess.STDOUT, check=True)
                if song_pack and cache is not None:
                    cache.completed_outputs((stage/'build/audio/music').rglob('*'))

    def parallel(batch):
        """Independent commands also use every core when the step cache is off."""
        from concurrent.futures import ThreadPoolExecutor
        batch = [[str(v) for v in command] for command in batch]
        commands.extend(batch)
        def execute(command):
            return subprocess.run(command, cwd=stage, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        with ThreadPoolExecutor(max_workers=build_jobs()) as pool:
            results = list(pool.map(execute, batch))
        with log.open('ab') as output:
            for command, result in zip(batch, results):
                output.write(result.stdout)
                result.check_returncode()

    try:
        audio_command = None
        audio_env = dict(env)
        if cache is not None:
            # Compile once before traced song workers start. They only read
            # the helper; an external compiler does not make every song opaque.
            run([sys.executable, 'tools/native_host.py'])
        if music_pack is None:
            if audio_source is None:
                raise ValueError('A prepared sample/configuration package is required')
            from audio_package import validate_effects
            effect_samples = validate_effects(audio_source, game, None, source=source)
            music_pack = stage/'build/audio/music'
            audio_command = [sys.executable, 'tools/audio_compile.py', 'music-pack', audio_source,
                 '--profile', env['WOLF_PROFILE'], '--data', stage/'licensed-data', '--require-identical',
                 '--jobs', str(jobs), '--out', music_pack]
            if cache is not None and not cold_cache:
                run(audio_command)
        else:
            from music_pack import MusicPack
            MusicPack(music_pack, game)
            if effect_samples is None:
                raise ValueError('--music-pack requires --effect-samples; source effects must be explicit')
        from effect_sources import manifest as effects_manifest
        effects_manifest(source, effect_samples)
        env['WOLF_MUSIC_PACK'] = str(Path(music_pack).resolve())
        env['WOLF_EFFECT_SAMPLES'] = str(Path(effect_samples).resolve())
        stride = recipe['settings']['ray_stride']
        if stride not in (4, 8, 16):
            raise ValueError('Invalid native ray stride')
        write_if_changed(stage/'build/gen/ray_mode.inc', '#define WOLF_EXACT_RAYS 0\n#define WOLF_QUARTER_RAYS 1\n#define WOLF_RAY_STRIDE '+str(stride)+'\n')
        if not calypsi and bundle is None:
            raise ValueError('A matching engine bundle or --calypsi is required')
        media = recipe['media']
        images = stage/'build/media'
        images.mkdir(exist_ok=cache is not None)
        disk = [sys.executable, 'tools/mkdisk.py', '--entry', str(recipe['settings']['entry']),
                '--compress', '--no-readme', '--b1cache', 'build/b1cache', '--out', images/'disk', '--hd', images/'wolf-hd.po']
        if media['hd_only']:
            disk.append('--hd-only')
        else:
            disk += ['--disk-units', 'build/assets/episode-disk.json', '--campaign', 'build/gen/campaign.json']
        if media['menu']:
            disk += ['--menu', media['menu']]
        if scsi:
            disk += ['--scsi', images/'wolf-scsi.hdv']
        for key in ('boot', 'loader', 'elf', 'store', 'picture_reuse', 'picture_file'):
            if key in media:
                disk += ['--'+key.replace('_', '-'), media[key]]
        for key, option in (('data_lists', '--data-list'), ('data', '--data')):
            for value in media[key]:
                disk += [option, value]
        if cache is not None:
            cached_build(cache, stage, game, recipe, env, log, destination, commands, assembler, linker,
                         [str(v) for v in disk], bundle, cold=cold_cache,
                         audio_command=audio_command if cold_cache else None, audio_env=audio_env)
        else:
            run([sys.executable, 'tools/memmap.py', 'build/gen'])
            run([sys.executable, 'tools/native_host.py'])
            (stage/'build/assets').mkdir(exist_ok=True)
            def asset(step):
                if step['arguments'] == ['tools/build_colors.py']:
                    # Every floor fitted again, one process per core (tools/palette_cache.py).
                    from palette_cache import fit_all, fit_commands
                    commands.extend(fit_commands(game.floors,build_jobs()))
                    fit_all(stage, game, env, log, build_jobs())
                elif step['arguments'] == ['tools/build_sprites.py']:
                    groups = 'build/sprite-groups.json'
                    parallel([[sys.executable, 'tools/build_registered_sprites.py', '--floor', str(n), '--groups', groups]
                              for n in reversed(range(game.floors))])
                    run([sys.executable, 'tools/build_registered_sprites.py', '--finish'])
                else:
                    run([sys.executable]+step['arguments'])
            source_assets(recipe['asset_step'], asset,
                          (lambda: run(audio_command)) if audio_command else None,
                          lambda: run([sys.executable,'tools/build_registered_sprites.py',
                                        '--save-groups','build/sprite-groups.json']))
            if calypsi:
                flags = ['--code-model=large', '--data-model=medium', '-I', 'build/gen', '-I', 'src/iigs']
                boot, objects = engine_jobs(recipe, game)
                for source_file, obj, _ in boot[:2]:
                    name = Path(obj).stem
                    run([assembler]+flags+['-o', obj, source_file])
                    run([linker, '-o', 'build/boot/'+name+'.elf', 'src/iigs/'+name+'.scm', obj, '--output-format', 'raw'])
                run([sys.executable, 'tools/gen_loader_api.py'])
                parallel([[assembler]+flags+defines+['-o', obj, source_file]
                          for source_file, obj, defines in boot[2:]+objects])
                for source_file, obj, _ in boot[2:]:
                    name = Path(obj).stem
                    run([linker, '-o', 'build/boot/'+name+'.raw', 'src/iigs/'+name+'.scm', obj, '--output-format', 'raw'])
                run([linker, '-o', 'build/wolf.elf', recipe['settings']['linker']]+recipe['objects']+
                    ['--hosted', '--list-file', 'build/wolf.lst'])
            else:
                from native_bundle import install_engine, verify_generated_bindings
                install_engine(stage, bundle)
                run([sys.executable, 'tools/gen_loader_api.py'])
                verify_generated_bindings(stage, bundle)
            checks = []
            for step in recipe['post_link']:
                if Path(step['arguments'][0]).name.startswith('check_'):
                    checks.append(post_command(step,game))
                else:
                    if checks:
                        parallel(checks)
                        checks = []
                    run(post_command(step,game))
            parallel(checks + [disk])
        from audio_provenance import validate as validate_audio
        audio_receipt = validate_audio(music_pack, root=root)
        audio_receipt_path = Path(music_pack)
        if not audio_receipt_path.is_dir():
            audio_receipt_path = audio_receipt_path.parent
        audio_receipt_path /= 'audio-build.json'
        audio_receipt_sha = hashlib.sha256(audio_receipt_path.read_bytes()).hexdigest()
        missing = [name for name in media['hard_disks'] if not (images/name).is_file()]
        if missing:
            raise ValueError('Required output volumes missing: '+', '.join(missing))
        from check_media_audio import check as check_media_audio
        audio_input = json.loads((stage/'build/gen/audio-input.json').read_text())
        packed_audio = check_media_audio(images/'wolf-hd.po', audio_input)
        packed_audio['audio_receipt_sha256'] = audio_receipt_sha
        packed_audio['audio_identity'] = audio_receipt['identity']
        audio_check = destination/'media-audio.json'
        audio_check.write_text(json.dumps(packed_audio, indent=2)+'\n')
        from check_attract_assets import check as check_attract_assets
        attract_check = check_attract_assets(source, stage/'build/assets', stage/'build/gen')
        (destination/'asset-check.json').write_text(json.dumps(attract_check, indent=2)+'\n')
        receipts = []
        for path in sorted(images.iterdir()):
            if path.suffix not in ('.po', '.hdv'):
                continue
            raw = path.read_bytes()
            header = raw[512:1024] if path.suffix == '.po' else raw[65*512:66*512]
            if header[:6] != b'WOLFGS':
                raise ValueError('Invalid packed game header: '+path.name)
            target = destination/path.name
            target.write_bytes(raw)
            receipts.append(dict(file=target.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                 disk_number=header[6], disks=header[7], resident_boot_disks=header[438],
                                 store_banks=header[439]))
        sources = {name: json.loads((stage/'build/assets'/name).read_text())
                   for name in ('frontend-source.json', 'demo-source.json')}
        (destination/'asset-sources.json').write_text(json.dumps(sources, indent=2)+'\n')
        if calypsi:
            from native_bundle import export_bundle
            export_bundle(stage, game, manifest, destination/'engine-bundle')
        report = dict(profile=game.key, source_build=bool(calypsi), work_directory=str(stage),
                      regenerated_music=generated_audio,
                      audio_receipt=str(audio_receipt_path), audio_receipt_sha256=audio_receipt_sha,
                      audio_identity=audio_receipt['identity'],
                      packed_audio=dict(file=audio_check.name, sha256=hashlib.sha256(audio_check.read_bytes()).hexdigest()),
                      commands=commands, images=receipts, native_runtime_verified=False,
                      minimum_profile='ROM 00/01 plus 4 MiB expansion card (4352 KiB total)')
        if cache is not None:
            report['step_cache'] = cache.summary(time.monotonic() - began)
        (destination/'native-build.json').write_text(json.dumps(report, indent=2)+'\n')
        return receipts
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        (destination/'native-failure.json').write_text(json.dumps(dict(error=str(error), work_directory=str(stage),
            commands=commands), indent=2)+'\n')
        raise ValueError(str(error)+'; build log: '+str(log)+'; work files: '+str(stage)) from error
    finally:
        if cache is not None:
            cache.finish()
