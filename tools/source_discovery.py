"""Find and validate DOS campaigns without running installers or renaming files."""
from collections import defaultdict
import hashlib
import re
from pathlib import Path

from campaign_profile import digest, identity
from dos_data import DosData
from game_profile import PROFILE_DIR, PROFILES, REQUIRED, fields, integer, read_toml

MAP_FILES = ('MAPHEAD', 'GAMEMAPS', 'VSWAP')


def catalogs(directory=None):
    directory = Path(directory or PROFILE_DIR/'detection')
    doc = read_toml(directory/'layouts.toml')
    fields(doc, ('format', 'layouts'), 'source layouts')
    integer(doc['format'], 1, 1, 'source layouts format')
    extensions = set()
    for row in doc['layouts']:
        fields(row, ('extension', 'shared_extension', 'profile'), 'source layout')
        for key in ('extension', 'shared_extension'):
            if not isinstance(row[key], str) or not re.fullmatch('[A-Z0-9]+', row[key]):
                raise ValueError('source extension: expected uppercase letters and digits')
        if row['extension'] in extensions or row['profile'] not in PROFILES:
            raise ValueError('duplicate source extension or unknown profile')
        extensions.add(row['extension'])
    editions = read_toml(directory/'editions.toml')
    fields(editions, ('format', 'editions'), 'source editions')
    integer(editions['format'], 1, 1, 'source editions format')
    identities = set()
    for row in editions['editions']:
        fields(row, ('edition_id', 'profile', 'description', 'map_files'), 'source edition')
        identity(row['edition_id'], 'edition_id')
        if row['edition_id'] in identities or row['profile'] not in PROFILES:
            raise ValueError('duplicate edition_id or unknown profile')
        identities.add(row['edition_id'])
        fields(row['map_files'], MAP_FILES, 'edition map files')
        for value in row['map_files'].values():
            if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
                raise ValueError('edition source fingerprint must be a SHA-256 hash')
    return doc['layouts'], editions['editions']


def discover(directory, catalog_directory=None):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError('source input must be a folder: ' + str(directory))
    layouts, editions = catalogs(catalog_directory)
    by_folder, by_name = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    packages, hashes, diagnostics = [], {}, []
    def sha(path):
        if path not in hashes:
            hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes[path]
    def relative(path):
        return path.relative_to(directory).as_posix()
    extensions = {row['extension'] for row in layouts} | {row['shared_extension'] for row in layouts}
    wanted = {stem+'.'+ext for stem in REQUIRED for ext in extensions}
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        name = path.name.upper()
        if name in wanted:
            by_folder[path.parent][name].append(path)
            by_name[name].append(path)
        elif path.suffix.lower() in ('.zip', '.7z', '.rar', '.img', '.ima', '.iso', '.cue', '.bin', '.exe'):
            packages.append(relative(path))
    def choose(paths, name, folder):
        # Two differently-cased names in one directory are ambiguous even
        # when equal: they behave differently on case-sensitive hosts.
        grouped = defaultdict(list)
        for p in paths:
            grouped[p.parent].append(p)
        if any(len(v) > 1 for v in grouped.values()):
            return None, dict(kind='ambiguous', file=name, paths=[relative(p) for p in paths],
                              message='Multiple case-insensitive copies of '+name)
        if not paths:
            return None, dict(kind='missing', file=name, folder=relative(folder), message='Missing '+name)
        if len({sha(p) for p in paths}) != 1:
            return None, dict(kind='ambiguous', file=name, paths=[relative(p) for p in paths],
                              message='Different shared copies of '+name+'; keep the intended game in its own input folder.')
        return sorted(paths)[0], None
    # Prefer shared files from an identified base installation. A mission
    # installed with .SOD names may carry different local graphics/audio;
    # those belong to that mission and must not make another mission ambiguous.
    shared_bases = defaultdict(set)
    for layout in layouts:
        for folder, local in by_folder.items():
            names = {stem:stem+'.'+layout['extension'] for stem in MAP_FILES}
            if not all(len(local.get(name, [])) == 1 for name in names.values()):
                continue
            signature = {stem:sha(local[name][0]) for stem,name in names.items()}
            if any(e['profile'] == layout['profile'] and e['map_files'] == signature for e in editions):
                shared_bases[layout['profile']].add(folder)
    shared_profiles = {row['extension']:row['profile'] for row in layouts
                       if row['extension'] == row['shared_extension']}
    shared_extensions = {row['shared_extension'] for row in layouts
                         if row['extension'] != row['shared_extension']}
    map_names = {stem+'.'+row['extension'] for row in layouts for stem in MAP_FILES}
    common_folders = {folder for folder,local in by_folder.items() if not map_names.intersection(local)}
    candidates = []
    for folder, local in sorted(by_folder.items()):
        for layout in layouts:
            ext = layout['extension']
            has_maps = any(stem+'.'+ext in local for stem in MAP_FILES)
            # A standalone set with only audio/graphics is incomplete. A
            # shared-only folder used by map files elsewhere is not another game.
            shared_only = (ext == layout['shared_extension'] and
                           any(stem+'.'+ext in local for stem in REQUIRED if stem not in MAP_FILES) and
                           not any(stem+'.'+other['extension'] in by_name
                                   for other in layouts if other['shared_extension'] == ext
                                   for stem in MAP_FILES))
            if not (has_maps or shared_only):
                continue
            # The combined CD has an extra MAPHEAD.SD1 beside a complete .SOD
            # base set; it is not a separate incomplete fourth campaign.
            if (ext == 'SD1' and 'GAMEMAPS.SD1' not in local and 'VSWAP.SD1' not in local
                    and 'GAMEMAPS.SOD' in local and len(local.get('MAPHEAD.SD1', [])) == 1
                    and len(local.get('MAPHEAD.SOD', [])) == 1
                    and sha(local['MAPHEAD.SD1'][0]) == sha(local['MAPHEAD.SOD'][0])):
                continue
            row = dict(folder=relative(folder), source_extension=ext, profile=layout['profile'],
                       status='incomplete', diagnostics=[], files={})
            resolved = {}
            for stem in MAP_FILES:
                name = stem+'.'+ext
                path, error = choose(local.get(name, []), name, folder)
                if error:
                    row['diagnostics'].append(error)
                else:
                    resolved[stem] = path
            if len(resolved) == 3:
                signature = {stem:sha(resolved[stem]) for stem in MAP_FILES}
                matches = [e for e in editions if e['map_files'] == signature]
                ids = {e['profile'] for e in matches}
                if len(ids) > 1:
                    raise ValueError('conflicting campaign identities in the edition catalog')
                row['recognized_campaign'] = bool(matches)
                row['editions'] = [e['edition_id'] for e in matches]
                if matches:
                    row['profile'] = matches[0]['profile']
                row['map_fingerprint'] = digest(signature)
            for stem in REQUIRED:
                if stem in MAP_FILES:
                    continue
                name = stem+'.'+layout['shared_extension']
                primary = shared_profiles.get(layout['shared_extension'])
                preferred, common = [], []
                if layout['shared_extension'] in shared_extensions:
                    preferred = [p for base in sorted(shared_bases.get(primary, ()))
                                 for p in by_folder[base].get(name, [])]
                    common = [p for base in sorted(common_folders) for p in by_folder[base].get(name, [])]
                path, error = choose(local.get(name) or preferred or common, name, folder)
                if error:
                    row['diagnostics'].append(error)
                else:
                    resolved[stem] = path
            row['files'] = {stem:dict(path=relative(p), bytes=p.stat().st_size, sha256=sha(p)) for stem,p in resolved.items()}
            if not row['diagnostics']:
                try:
                    info = DosData.from_files(row['profile'], resolved).inspect()
                    row.update(status='ready' if row['recognized_campaign'] else 'unrecognized-variant',
                               floors=info['floors'], episodes=info['episodes'], graphics_layout=info['graphics_layout'])
                    if not row['recognized_campaign']:
                        row['diagnostics'].append(dict(kind='unrecognized', message='Containers decode, but campaign routing is not identified. Supply an explicit custom source/campaign profile.'))
                except (ValueError, IndexError) as error:
                    row.update(status='incompatible')
                    row['diagnostics'].append(dict(kind='incompatible', message=str(error)))
            row['candidate_id'] = digest(dict(profile=row['profile'], files={s:v['sha256'] for s,v in row['files'].items()}))[:16]
            row['native_build_verified'] = False
            candidates.append(row)
    if not candidates:
        message = 'No extracted Wolf/Spear DOS data files found. Put the installed game data in the named input folders; see game-data/README.md.'
        if packages:
            message += ' Extract or install these packages yourself first: ' + ', '.join(packages) + '.'
        diagnostics.append(dict(kind='missing', message=message))
    return dict(format=1, kind='source-discovery', candidates=candidates, packages=packages,
                diagnostics=diagnostics, native_build_verified=False)
