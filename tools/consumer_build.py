"""Consumer discovery and preflight; native conversion adapters are engine-owned."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from campaign_manifest import compile_manifest, native_support, require_supported
from campaign_profile import identity
from dos_data import DosData
from game_profile import PROFILES, fields, integer, profile, read_toml
from source_discovery import discover

# Populate only with integrated converters for an agreed current-engine ABI.
# The legacy native_build packing path cannot convert new DOS assets.
from native_bundle import ADAPTER_ID, CurrentEngineAdapter


def default_audio_jobs():
    import os
    return min(16, int(os.environ.get('WOLF_JOBS') or os.cpu_count() or 1))
ADAPTERS = {ADAPTER_ID: CurrentEngineAdapter()}
REQUIRED_BUNDLE_ROLES = {'engine', 'boot', 'loader', 'capabilities', 'bindings', 'allocation', 'media'}


def package_path(root, value):
    if not isinstance(value, str):
        raise ValueError('bundle path must be text')
    name = PurePosixPath(value)
    if not value or name.is_absolute() or '..' in name.parts or '\\' in value or ':' in value:
        raise ValueError('bundle path must stay inside its folder: ' + value)
    path = (root / value).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('bundle path escapes its folder: ' + value)
    return path


def check_bundle(path, manifest):
    path = Path(path)
    doc = read_toml(path)
    fields(doc, ('format', 'engine_id', 'save_abi', 'asset_abi', 'adapter', 'verified_profiles', 'files'), 'engine bundle')
    integer(doc['format'], 1, 1, 'engine bundle format')
    for key in ('engine_id', 'save_abi', 'asset_abi', 'adapter'):
        identity(doc[key], 'engine bundle ' + key)
    verified = doc['verified_profiles']
    if not isinstance(verified, list) or any(not isinstance(v, str) for v in verified) or len(verified) != len(set(verified)):
        raise ValueError('verified_profiles: expected distinct source-profile IDs')
    game = manifest['campaign']['profile_id']
    if game not in verified:
        raise ValueError('engine bundle is not verified for ' + game)
    if not isinstance(doc['files'], dict) or not REQUIRED_BUNDLE_ROLES <= doc['files'].keys():
        raise ValueError('engine bundle needs engine, boot, loader, capabilities, bindings, allocation and media files; an ELF alone cannot convert game data')
    files = {}
    for role, entry in doc['files'].items():
        fields(entry, ('path', 'sha256'), 'bundle file ' + role)
        if not isinstance(entry['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']):
            raise ValueError('invalid bundle SHA-256 for ' + role)
        file = package_path(path.parent, entry['path'])
        if hashlib.sha256(file.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('bundle file changed: ' + role)
        files[role] = file
    support = native_support(manifest, files['capabilities'])
    if support['engine_id'] != doc['engine_id'] or support['save_abi'] != doc['save_abi']:
        raise ValueError('bundle identity disagrees with its native capabilities')
    require_supported(dict(manifest, native_support=support))
    if doc['adapter'] not in ADAPTERS:
        raise ValueError('native asset bindings/converter are not implemented for adapter ' + doc['adapter'] + '; no game image was generated')
    # The ABI-specific adapter must validate bindings and allocation before
    # any compilation, patching or packing. No generic address patcher exists.
    adapter = ADAPTERS[doc['adapter']]
    adapter.check_bindings(doc, files, manifest)
    return doc, files, adapter


def select_candidates(discovery, games):
    """Select detected identities; folder labels never override source contents."""
    requested = list(dict.fromkeys(games or []))
    unknown = sorted(set(requested) - PROFILES.keys())
    if unknown:
        raise ValueError('unknown game selection: ' + ', '.join(unknown))
    selected, seen = [], {}
    for candidate in discovery['candidates']:
        if requested and candidate['profile'] not in requested:
            continue
        row = dict(candidate)
        key = (row['profile'], row['candidate_id'])
        if row['status'] == 'ready':
            if key in seen:
                seen[key].setdefault('duplicate_folders', []).append(row.get('folder', '.'))
                continue
            seen[key] = row
        selected.append(row)
    found = {row['profile'] for row in selected}
    diagnostics = []
    for key in requested:
        if key in found:
            continue
        game = PROFILES[key]
        filenames = ', '.join(game.files.values())
        shared = (' Shared .SOD graphics/audio may be in the spear folder.'
                  if key in ('spear-mission2', 'spear-mission3') else '')
        diagnostics.append(dict(kind='missing-selected-game', profile=key,
            message=f'No installed data set found for selected game {key}. '
                    f'Place its extracted DOS files in {key}/ under the input folder. '
                    f'Required filenames: {filenames}.{shared}'))
    return selected, diagnostics


def preflight(input_folder, out, bundle=None, audio_source=None, selected_profile=None,
              inspect_only=False, release_root=None, selected_games=None, build_options=None):
    root = Path(release_root or Path(__file__).resolve().parents[1])
    options = dict(build_options or {})
    from_source = bool(options.get('calypsi'))
    prepared_music = options.get('music_pack')
    source_root, out = Path(input_folder).resolve(), Path(out).resolve()
    if selected_profile and selected_games:
        raise ValueError('use either --game or the advanced --profile option')
    if selected_profile:
        game = profile(selected_profile)
        source = DosData(source_root, game)
        info = source.inspect()
        candidates = [dict(candidate_id=game.key, profile=game.key, status='ready', diagnostics=[],
                           files={s:dict(path=str(source.files[game.files[s].upper()]), sha256=info['files'][game.files[s]]['sha256']) for s in game.files})]
        discovery = dict(candidates=candidates, diagnostics=[])
    else:
        discovery = discover(source_root)
        candidates, missing = select_candidates(discovery, selected_games)
        if missing:
            discovery = dict(discovery, diagnostics=missing)
    out.mkdir(parents=True, exist_ok=True)
    report = dict(format=1, kind='consumer-build', discovery=discovery, campaigns=[], images=[],
                  input_folder=str(source_root), output_folder=str(out),
                  selection=dict(mode='profile' if selected_profile else 'games' if selected_games else 'all-available',
                                 requested_games=list(dict.fromkeys(selected_games or [])),
                                 not_supplied=sorted(PROFILES.keys() - {c['profile'] for c in discovery['candidates']})),
                  status='preflight-failed', native_build_verified=False)
    counts = Counter(c['profile'] for c in candidates)
    for candidate in candidates:
        row = dict(candidate_id=candidate['candidate_id'], profile=candidate['profile'],
                   source_folder=candidate.get('folder', '.'),
                   diagnostics=list(candidate['diagnostics']), status='source-invalid')
        if candidate.get('duplicate_folders'):
            row['duplicate_folders'] = candidate['duplicate_folders']
        report['campaigns'].append(row)
        if candidate['status'] != 'ready':
            continue
        game = profile(selected_profile or candidate['profile'])
        files = {s:source_root / v['path'] for s,v in candidate['files'].items()}
        if any(hashlib.sha256(files[s].read_bytes()).hexdigest() != v['sha256'] for s,v in candidate['files'].items()):
            raise ValueError('source files changed during discovery; rerun with stable inputs')
        data = DosData.from_files(game, files)
        try:
            manifest = compile_manifest(data)
            destination = out/candidate['profile']
            if counts[candidate['profile']] > 1:
                destination /= candidate['candidate_id']
            destination.mkdir(parents=True, exist_ok=True)
            manifest_path = destination/'campaign.json'
            manifest_path.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
            row.update(status='source-validated', campaign_manifest=manifest_path.relative_to(out).as_posix(),
                       output_folder=destination.relative_to(out).as_posix(),
                       save_content_sha256=manifest['save_content_sha256'])
            if inspect_only:
                continue
            bundle_path = Path(bundle) if bundle else root/'bundles'/game.key/'engine-bundle.toml'
            if bundle_path.is_dir():
                bundle_path /= 'engine-bundle.toml'
            if not from_source and not bundle_path.is_file():
                row['diagnostics'].append(dict(kind='missing-engine-bundle', message='Missing current-engine consumer bundle: '+str(bundle_path)+'. Use --from-source --calypsi PATH, or --bundle with a bundle exported by a source build.'))
            music = Path(audio_source) if audio_source else root/'audio-source'/('spear' if game.spear else game.key)
            if prepared_music:
                from music_pack import MusicPack
                from effect_sources import manifest as effect_manifest
                from audio_provenance import validate as validate_audio
                validate_audio(prepared_music, root)
                MusicPack(prepared_music, game)
                if not options.get('effect_samples'):
                    raise ValueError('--music-pack requires --effect-samples')
                effect_manifest(data, options['effect_samples'])
            elif not (music/'intermediate.toml').is_file():
                row['diagnostics'].append(dict(kind='missing-audio-source', message='Missing prepared sample/configuration package: '+str(music/'intermediate.toml')))
            else:
                from audio_package import validate_effects
                try:
                    validate_effects(music, game, source_root, source=data)
                except (ValueError, OSError, KeyError) as error:
                    row['diagnostics'].append(dict(kind='incompatible-audio-source', message=str(error)))
            if row['diagnostics']:
                continue
            if from_source:
                from native_pipeline import build_images
                images = build_images(root, manifest, data, None if prepared_music else music, destination, **options)
            else:
                doc, bundle_files, adapter = check_bundle(bundle_path, manifest)
                images = adapter.build(doc, bundle_files, manifest, data, None if prepared_music else music, destination, **options)
            if not images:
                raise ValueError('native converter produced no game images')
            row.update(status='built', images=images)
            report['images'].extend(images)
        except (OSError, ValueError, KeyError, IndexError) as error:
            row['diagnostics'].append(dict(kind='unsupported-build', message=str(error)))
    successful = bool(report['campaigns']) and not discovery['diagnostics'] and all(
        not r['diagnostics'] and r['status'] == ('source-validated' if inspect_only else 'built') for r in report['campaigns'])
    report['status'] = ('source-inspection-complete' if inspect_only else 'build-complete') if successful else 'preflight-failed'
    (out/'build-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description='Build Apple IIgs images from extracted Wolf/Spear DOS data files. By default, process every detected game.',
        epilog='Default folders are relative to the project, even when launched elsewhere. Explicit relative paths use your current directory.')
    parser.add_argument('input', nargs='?', type=Path, default=None,
                        help='input folder (default: project/game-data)')
    parser.add_argument('--data', type=Path, help='override the input folder (alternative to the positional argument)')
    parser.add_argument('--out', type=Path, default=root/'dist/output',
                        help='output folder (default: project/dist/output)')
    parser.add_argument('--inspect-only', action='store_true', help='check selected campaigns and write reports without attempting native conversion')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--all', action='store_true', help='process every detected game (the default); skip empty folders')
    selection.add_argument('--game', choices=sorted(PROFILES), action='append',
                           help='select a detected game; repeat to select several')
    selection.add_argument('--profile', help='advanced: explicit source profile ID or custom TOML for a single input set')
    parser.add_argument('--bundle', type=Path, help='advanced: engine bundle folder or manifest')
    parser.add_argument('--audio-source', type=Path, help='advanced: prepared samples/configuration folder')
    parser.add_argument('--from-source', action='store_true', help='compile the current engine with Calypsi and export a fresh bundle')
    parser.add_argument('--calypsi', type=Path, help='Calypsi bin directory for --from-source')
    parser.add_argument('--music-pack', type=Path, help='explicit existing converted music pack; requires --effect-samples')
    parser.add_argument('--effect-samples', type=Path, help='explicit preserved effects folder with samples.toml')
    parser.add_argument('--audio-only', action='store_true', help='rebuild audio from editable intermediaries without packaging game images')
    parser.add_argument('--audio-song', help='with --audio-only, rebuild one catalog song for a bounded test')
    parser.add_argument('--audio-preview-settings', type=Path,
                        help='local complete-audio TOML with synthesis.settings and adlib; defaults to WOLF_AUDIO_SETTINGS or project/complete.toml')
    parser.add_argument('--no-audio-preview', action='store_true', help='skip developer listening WAVs; still rebuild and verify game audio')
    parser.add_argument('--audio-jobs', type=int, default=default_audio_jobs(), choices=range(1,17), help='parallel offline music compiler and preview processes (1-16; default WOLF_JOBS or the CPU count)')
    parser.add_argument('--scsi', action='store_true', help='also emit SCSI wrappers for every hard-disk volume')
    args = parser.parse_args()
    import os
    preview_settings=args.audio_preview_settings or os.environ.get('WOLF_AUDIO_SETTINGS')
    if preview_settings is None and (root/'complete.toml').is_file():preview_settings=root/'complete.toml'
    if args.from_source != bool(args.calypsi):
        parser.error('--from-source and --calypsi PATH must be used together')
    if args.input is not None and args.data is not None:
        parser.error('use either the input-folder argument or --data')
    input_folder = args.data or args.input or root/'game-data'
    preview_targets=([args.out.resolve()/'comparisons/preview'] if args.audio_only else
        [args.out.resolve()/key/'comparisons/preview' for key in (args.game or ([args.profile] if args.profile in PROFILES else []))])
    preview_targets += [args.out.resolve()/key/'comparisons/preview' for key in PROFILES
                        if (args.out.resolve()/key/'comparisons/preview/index.html').exists()]
    def preview_status(message,status):
        if args.inspect_only:return
        from audio_compare import export_status
        for path in set(preview_targets):export_status(path,'DOC audio preview',message,status)
    preview_status('Preview skipped for this build.' if args.no_audio_preview else
                   'Rebuild in progress; recordings await verification.',
                   'unavailable' if args.no_audio_preview else 'pending')
    if args.audio_song and not args.audio_only:
        parser.error('--audio-song requires --audio-only; a partial song build is not a game release')
    if args.audio_only:
        if args.music_pack or args.inspect_only:
            parser.error('--audio-only rebuilds from intermediaries; it cannot import a music pack or inspect only')
        selected = args.profile or (args.game[0] if args.game and len(args.game)==1 else None)
        if not selected:parser.error('--audio-only requires one --game or --profile')
        import subprocess, sys
        try:
            game=profile(selected)
            if not args.no_audio_preview:
                from doc_preview import bundle_engine
                preview_engine=bundle_engine(root,game,args.bundle)
            package=(args.audio_source or root/'audio-source'/('spear' if game.spear else game.key)).resolve()
            target=args.out.resolve()/'audio'
            if args.audio_song:
                if args.audio_song not in game.required_music.values():raise ValueError('Song is not required by this profile: '+args.audio_song)
                target/=args.audio_song
                command=['music',str(package/'songs'/(args.audio_song+'.toml')),'--preserved-samples',str(package)]
            else:command=['music-pack',str(package)]
            subprocess.run([sys.executable,str(root/'tools/audio_compile.py')]+command+
                ['--profile',str(selected),'--data',str(input_folder.resolve()),'--out',str(target),
                 '--require-identical','--jobs',str(args.audio_jobs)],check=True)
            from audio_provenance import validate as validate_audio
            receipt=validate_audio(target,root)
            print('Rebuilt audio: '+str(target))
            print('Build identity: '+receipt['identity'])
            if not args.no_audio_preview:
                from doc_preview import generate
                page=generate(target,preview_engine,args.out.resolve()/'comparisons/preview',
                              game,song=args.audio_song,jobs=args.audio_jobs,
                              package=package,data=input_folder.resolve(),settings=preview_settings,
                              cache=args.out.resolve()/'comparisons')
                print('Audio listening page: '+str(page))
            return
        except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
            preview_status('Build failed: '+str(error),'failed')
            parser.exit(2,str(error)+'\n')
    try:
        report = preflight(input_folder, args.out, args.bundle, args.audio_source, args.profile,
                           args.inspect_only, selected_games=args.game, build_options=dict(calypsi=args.calypsi, music_pack=args.music_pack, effect_samples=args.effect_samples, jobs=args.audio_jobs, scsi=args.scsi))
        print('Input: '+str(input_folder.resolve()))
        for row in report['campaigns']:
            print(row['profile']+' ('+row['source_folder']+'): '+row['status'])
            for error in row['diagnostics']:
                print('  '+error['message'])
        for error in report['discovery']['diagnostics']:
            print(error['message'])
        if not args.game and not args.profile and report.get('selection', {}).get('not_supplied'):
            print('Not supplied (skipped): '+', '.join(report['selection']['not_supplied']))
        print('Report: '+str((args.out/'build-report.json').resolve()))
        if report['status'] == 'preflight-failed':
            preview_status('Build incomplete; see build-report.json.','failed')
            parser.exit(2, 'Build incomplete; see the specific requirements above.\n')
        if not args.inspect_only and not args.no_audio_preview:
            from doc_preview import generate
            for row in report['campaigns']:
                if row['status']!='built':continue
                media=args.out.resolve()/row['output_folder']
                native=json.loads((media/'native-build.json').read_text())
                compiled=Path(native['audio_receipt']).parent
                engine=Path(native['work_directory'])/'build/wolf.elf'
                game=profile(row['profile'])
                package=(args.audio_source or root/'audio-source'/('spear' if game.spear else game.key)).resolve()
                page=generate(compiled,engine,media/'comparisons/preview',game,
                              jobs=args.audio_jobs,media=media,package=package,
                              data=Path(native['work_directory'])/'licensed-data',settings=preview_settings,
                              cache=args.out.resolve()/'comparisons')
                row['audio_preview']=str(page)
                print('Audio listening page: '+str(page))
            (args.out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    except (OSError, ValueError, KeyError, IndexError) as error:
        preview_status('Build failed: '+str(error),'failed')
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    main()
