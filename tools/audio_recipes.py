#!/usr/bin/env python3
"""Generate editable audio recipes, compare paired scores, and render debug WAVs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import urllib.request
import wave
import array
import sys
import copy
import math
import zipfile

from dos_data import DosData
from game_profile import read_toml, integer, number, fields
from music_score import Event, imf_notes, midi_notes, midi_read, midi_write
from music_mapping import aggregate, held_out, MAPPING_FIELDS
from music_context import evaluate, features, ranked, label, validate_settings, REFERENCE_AUTHORITIES
from instrument_defaults import validate_defaults, default_song, midi_defaults, imf_defaults

DEFAULTS = Path(__file__).resolve().parents[1] / 'profiles' / 'audio'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def checked(path, expected):
    data = Path(path).read_bytes()
    if sha(data) != expected:
        raise ValueError(str(path)+': SHA-256 differs from the recipe')
    return data


def program_map(data, changes):
    """Edit only program bytes; keep score, controller context and SMF layout."""
    _, events = midi_read(data)
    result, used = bytearray(data), set()
    rules = {}
    for index, change in enumerate(changes):
        fields(change, ('channel', 'from_program', 'to_program'), 'program change')
        integer(change['channel'], 1, 16, 'channel')
        integer(change['from_program'], 1, 128, 'from_program')
        integer(change['to_program'], 1, 128, 'to_program')
        key = change['channel'], change['from_program']
        if key in rules:
            raise ValueError('duplicate program mapping')
        rules[key] = index, change['to_program']
    for event in events:
        if event.raw[0] & 0xf0 == 0xc0:
            key = (event.raw[0] & 15)+1, event.raw[1]+1
            if key in rules:
                index, program = rules[key]
                result[event.offset] = program-1
                used.add(index)
    if used != set(range(len(changes))):
        raise ValueError('a program mapping did not match its MIDI source')
    return bytes(result)


def midi_catalog(directories):
    by_hash = {}
    for directory in directories:
        for path in sorted(Path(directory).rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.mid', '.midi'):
                by_hash.setdefault(sha(path.read_bytes()), path)
    return by_hash


def collect_midi(args):
    catalog = midi_catalog(args.cache)
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    for source in read_toml(args.sources)['song']:
        if source.get('source_authority', source['authority']) != 'composer-original':
            continue
        name = Path(source['source_file']).name
        if name != source['source_file']:
            raise ValueError('composer MIDI source_file must be a plain filename')
        output = args.out/name
        if output.exists():
            data = checked(output, source['source_sha256'])
        elif source['source_sha256'] in catalog:
            data = checked(catalog[source['source_sha256']], source['source_sha256'])
        else:
            url = source.get('source_url', '')
            if not url.startswith('https://'):
                raise ValueError(source['name']+': provide a cache or an HTTPS source_url')
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(4*1024*1024+1)
            if len(data) > 4*1024*1024 or sha(data) != source['source_sha256']:
                raise ValueError(source['name']+': downloaded MIDI differs from the pinned source')
        midi_read(data)
        if not output.exists():
            output.write_bytes(data)
        report.append(dict(song=source['name'], file=name, sha256=sha(data), source_url=source.get('source_url')))
    (args.out/'sources.json').write_text(json.dumps(report, indent=2)+'\n')
    return dict(composer_midis=len(report), output=str(args.out))


def collect_standins(args):
    catalog = read_toml(args.sources)
    checked(args.archive, catalog['archive_sha256'])
    payloads = {}
    with zipfile.ZipFile(args.archive) as archive:
        members = archive.infolist()
        if sum(m.file_size for m in members) > 64*1024*1024:
            raise ValueError('stand-in archive exceeds the extraction limit')
        for member in members:
            if member.file_size > 2*1024*1024:
                raise ValueError('stand-in archive member exceeds the extraction limit')
            data = archive.read(member)
            if data.startswith(b'MThd'):
                payloads[sha(data)] = data
    planned, filenames = [], set()
    for source in catalog['song']:
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.mid', source['source_file']):
            raise ValueError('stand-in source_file must be a safe MIDI filename')
        if source['source_file'].casefold() in filenames:
            raise ValueError('duplicate stand-in output filename')
        filenames.add(source['source_file'].casefold())
        if source['source_sha256'] not in payloads:
            raise ValueError(source['name']+': expected MIDI absent from archive')
        data = payloads[source['source_sha256']]
        midi_read(data)
        output = args.out/source['source_file']
        if output.exists():
            checked(output, source['source_sha256'])
        planned.append((output, data))
    args.out.mkdir(parents=True, exist_ok=True)
    for output, data in planned:
        if not output.exists():
            output.write_bytes(data)
    (args.out/'sources.toml').write_bytes(args.sources.read_bytes())
    return dict(standin_midis=len(planned), output=str(args.out))


def selected_midi(spec, catalog):
    if not spec:
        return None
    if spec['selected_sha256'] in catalog:
        data = checked(catalog[spec['selected_sha256']], spec['selected_sha256'])
    elif spec['source_sha256'] in catalog:
        data = program_map(checked(catalog[spec['source_sha256']], spec['source_sha256']), spec.get('change', []))
        if sha(data) != spec['selected_sha256']:
            raise ValueError(spec['name']+': default mapping does not reproduce the selected MIDI')
    else:
        return None
    midi_read(data)
    return data


def editable_selection(spec, catalog, selected):
    """Keep the source and the established program decisions visible separately."""
    if spec['source_sha256'] in catalog:
        source = checked(catalog[spec['source_sha256']], spec['source_sha256'])
        changes = spec.get('change', [])
        if program_map(source, changes) != selected:
            raise ValueError(spec['name']+': source and mappings differ from the selected arrangement')
        return source, changes
    return selected, []


def save_source(out, name, data, suffix):
    filename = name+'-'+sha(data)[:16]+suffix
    path = out/'sources'/filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    elif path.read_bytes() != data:
        raise ValueError('source filename hash collision')
    return '../sources/'+filename


def generate_effects(dos, chunks, out, catalog_path=None):
    catalog = read_toml(catalog_path or DEFAULTS/('effects-spear.toml' if dos.profile.spear else 'effects-wolf3d.toml'))
    rows = catalog['effect']
    if sorted(e['id'] for e in rows) != list(range(dos.profile.sounds)):
        raise ValueError('effect catalog must name each source sound ID exactly once')
    pages, _, sound_start = dos.vswap()
    directory = list(struct.iter_unpack('<HH', pages[-1]))
    (out/'effects').mkdir(exist_ok=True)
    (out/'generated-effects').mkdir(exist_ok=True)
    defaults_path = out/'effect-instrument-defaults.toml'
    if not defaults_path.exists():
        defaults_path.write_bytes((DEFAULTS/'effect-instrument-defaults.toml').read_bytes())
    defaults = read_toml(defaults_path)
    if defaults.get('format') != 1:
        raise ValueError('expected format-1 effect instrument defaults')
    selected = {}
    for row in defaults.get('effect', []):
        key = row['name'], row['contour_sha256']
        if key in selected:
            raise ValueError('duplicate effect instrument default: '+row['name'])
        selected[key] = row
    counts = Counter()
    for effect in rows:
        sid, name = effect['id'], effect['name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('invalid effect filename')
        raw = chunks[dos.profile.sounds+sid]
        if len(raw) < 23:
            raise ValueError('truncated original synthetic effect '+name)
        length, priority = struct.unpack_from('<IH', raw)
        if 23+length > len(raw):
            raise ValueError('truncated original effect contour '+name)
        digi = effect['digitized_shareware'] if dos.profile.public_game_data else effect['digitized']
        if digi >= 0:
            if digi >= len(directory):
                raise ValueError('effect PCM directory index outside VSWAP: '+name)
            first, size = directory[digi]
            span = pages[sound_start+first:sound_start+first+(size+4095)//4096]
            data = b''.join(span)
            if not size or len(data) < size or any(not p for p in span):
                raise ValueError('missing original PCM for '+name)
            data = data[:size]
            kind, suffix = 'pcm-u8', '.u8'
        else:
            data, kind, suffix = raw, 'adlib-effect-contour', '.adlib'
        source = save_source(out, name, data, suffix)
        lines = ['# Editable effect recipe. Regeneration preserves effects/ and refreshes generated-effects/.',
            'format = 1', 'kind = "effect"', 'name = '+quote(name), f'priority = {priority}',
            '', '[source]', 'kind = '+quote(kind), 'file = '+quote(source), 'sha256 = '+quote(sha(data)),
            f'rate = {catalog["source_rate"] if digi >= 0 else 140}']
        if digi < 0:
            selection = selected.get((name, sha(raw)))
            lines += ['', '# The original FM bytes provide timing/pitch contours, not reference timbre.',
                      '# Programs are 1-based. Each layer runs in the shared Roland performance.']
            if selection:
                lines += ['# Recovered defaults from effect-instrument-defaults.toml; editable below.']
                for layer in selection['layer']:
                    values = dict(layer, expression_shape=selection['expression_shape'])
                    lines += ['', '[[layer]]']+[key+' = '+quote(value) for key,value in values.items()]
                counts['selected_layered_defaults'] += 1
            else:
                lines += ['# No matching recorded default. Choose at least two layers; zero is unresolved.']
                for role in ('body', 'attack-or-texture'):
                    lines += ['', '[[layer]]', 'role = '+quote(role), 'program = 0',
                              'bank_msb = 0', 'bank_lsb = 0', 'transpose = 0', 'velocity = 100']
                counts['unresolved_layered_effects'] += 1
        lines += ['', '[doc]', 'auto_fit = true', 'tail_db = 60.0', 'volume = 255',
                  '# Add rate = 12000 to pin a rate; omit it for automatic fitting.']
        text = '\n'.join(lines)+'\n'
        filename = f'{sid:02d}-{name}.toml'
        (out/'generated-effects'/filename).write_text(text, encoding='utf-8')
        editable = out/'effects'/filename
        if not editable.exists():
            editable.write_text(text, encoding='utf-8')
        counts[kind] += 1
    return dict(counts)


def generate(args):
    dos = DosData(args.data, args.profile, args.shared_data)
    chunks = dos.audio()
    catalog = midi_catalog(args.midi_dir)
    sources = {s['name']: s for s in read_toml(args.sources)['song']}
    fallback_sources = [{s['name']: s for s in read_toml(path)['song']}
                        for path in args.fallback_sources]
    mappings = {p['id']: p for p in read_toml(args.mapping).get('patch', [])} if args.mapping else {}
    out = args.out.resolve()
    programs = read_toml(DEFAULTS/'gm-programs.toml')['program']
    (out/'songs').mkdir(parents=True, exist_ok=True)
    (out/'generated').mkdir(exist_ok=True)
    defaults_path = out/'instrument-defaults.toml'
    if not defaults_path.exists():
        defaults_path.write_bytes(args.instrument_defaults.read_bytes())
    defaults = validate_defaults(read_toml(defaults_path))
    conversion_path = out/'conversion-defaults.toml'
    if not conversion_path.exists():
        conversion_path.write_bytes((DEFAULTS/'conversion-defaults.toml').read_bytes())
    report = dict(profile=dos.profile.key, songs=[], recipes_created=0, recipes_preserved=0,
                  report_scope='freshly generated recipes; existing editable recipes are preserved')
    for sid, name in dos.profile.required_music.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('song name must be safe as a filename: '+name)
        raw = chunks[dos.profile.sounds*3+sid]
        notes, ticks, warnings = imf_notes(raw)
        original = save_source(out, name, raw, '.imf')
        spec = sources.get(name)
        midi = selected_midi(spec, catalog)
        if midi is None:
            for fallback in fallback_sources:
                candidate = fallback.get(name)
                midi = selected_midi(candidate, catalog)
                if midi is not None:
                    spec = candidate
                    break
        midi_source, changes = editable_selection(spec, catalog, midi) if midi else (None, [])
        default_name = None
        selected_parts = {}
        if midi:
            mapped, default_name = midi_defaults(midi, defaults, name)
            if default_name:
                # A source catalog chooses the score, not a new orchestration.
                # Preserve its performance while applying the selected defaults.
                midi = midi_source = mapped
                changes = []
        else:
            selected_parts, default_name = imf_defaults(raw, defaults)
        source = save_source(out, name, midi_source, '.mid') if midi else original
        lines = ['# Editable audio recipe. Regeneration updates generated/ and preserves this file.',
            '# All instruments/channels are 1-based. program = 0 means unresolved, never piano.',
            '# Established instrument defaults: '+(default_name or 'no matching reference'),
            'format = 1', 'kind = "music"', 'name = '+quote(name), '', '[source]',
            'kind = '+quote('midi' if midi else 'imf'), 'file = '+quote(source),
            'sha256 = '+quote(sha(midi_source if midi else raw)),
            'authority = '+quote(spec['authority'] if midi else 'inferred-from-imf'), '',
            '[original]', 'file = '+quote(original), 'sha256 = '+quote(sha(raw)),
            '', '[render]', 'reset = "gs"', 'end = "release"',
            '', '[capture]', 'lead_seconds = 0.05', 'tail_seconds = 2.0',
            '', '[reconstruction]', '# Changing FM patches during held notes needs a richer decoder.',
            'allow_unsupported = false', '# IMF has no recoverable GM velocity/controller stream.',
            '# Each instrument below states the audition velocity and articulation explicitly.']
        if midi and default_name:
            lines += ['', '[defaults]', '# Editable part assignments, applied before [[change]] overrides.',
                      'file = "../instrument-defaults.toml"']
        for change in changes:
            before = 'Drum kit' if change['channel'] == 10 else programs[str(change['from_program'])]
            after = 'Drum kit' if change['channel'] == 10 else programs[str(change['to_program'])]
            lines += ['', '# Established project instrument choice; notes and controls stay in the source.',
                      '[[change]]', f'channel = {change["channel"]}',
                      f'from_program = {change["from_program"]} # {before}',
                      f'to_program = {change["to_program"]} # {after}']
        unresolved = 0
        if not midi:
            for patch, channel in sorted({(n['patch'], n['channel']) for n in notes}):
                mapping = mappings.get(patch, {})
                suggestions = mapping.get('candidates', [])
                selected = selected_parts.get((patch, channel))
                choice = selected or dict(program=0, bank_msb=0, bank_lsb=0, drum_key=-1, transpose=0)
                instrument_name = ('Standard/selected drum kit' if choice['drum_key'] >= 0 else
                                   programs[str(choice['program'])] if choice['program'] else 'Unresolved')
                lines += ['', '[[instrument]]', 'patch = '+quote(patch), f'opl_channel = {channel}',
                    f'program = {choice["program"]} # {instrument_name}',
                    f'bank_msb = {choice["bank_msb"]}', f'bank_lsb = {choice["bank_lsb"]}',
                    f'drum_key = {choice["drum_key"]}', f'transpose = {choice["transpose"]}',
                    'velocity = 100', 'note_length_scale = 1.0',
                    'minimum_note_seconds = 0.0', 'reverb = 40', 'chorus = 0', 'pan = 64',
                    '# Selected defaults take precedence over candidates from other songs.',
                    'candidates = '+quote(suggestions)]
                unresolved += selected is None
        from audio_defaults import conversion_default
        conversion = conversion_default(midi,name,conversion_path) if midi else None
        lines += ['', '[doc]', 'auto_fit = true',
                  'level_mode = "source"',
                  'capture_policy = "calibrated-sf2-and-captures"',
                  'fallback_reason = "Modeled samples and selected full-track captures, using the established conversion method"',
                  'auto_captures = true',
                  'capture_selection = '+quote('listed' if conversion else 'automatic'),
                  'auto_balance = true',
                  'capture_source = "instrument-track"',
                  '# Per-sample edits: see profiles/audio/doc.example.toml and docs/AUDIO_BUILD.md.']
        if conversion:
            lines += ['# Established conversion inputs for this selected performance.',
                      '# Level values are starting estimates; synthesis fits the unchanged Roland source.']
            if 'song_gain_steps' in conversion:
                lines += ['song_gain_steps = '+str(conversion['song_gain_steps'])]
            lines += ['loop_layout = '+quote(conversion['loop_layout'])]
            for kind in ('quality','levels','pan'):
                if conversion.get(kind):
                    lines += ['', '[doc.'+kind+']']
                    lines += [key+' = '+quote(value) for key,value in conversion[kind].items()]
            for capture in conversion.get('capture',[]):
                lines += ['', '[[doc.capture]]']
                lines += [key+' = '+quote(value) for key,value in capture.items()]
        text = '\n'.join(lines)+'\n'
        (out/'generated'/(name+'.toml')).write_text(text, encoding='utf-8')
        editable = out/'songs'/(name+'.toml')
        if editable.exists():
            report['recipes_preserved'] += 1
        else:
            editable.write_text(text, encoding='utf-8')
            report['recipes_created'] += 1
        report['songs'].append(dict(name=name, source='midi' if midi else 'imf',
            authority=spec['authority'] if midi else 'inferred-from-imf',
            source_sha256=sha(midi if midi else raw), imf_notes=len(notes),
            input_sha256=sha(midi_source if midi else raw), program_changes=changes,
            instrument_defaults=default_name, defaulted_imf_parts=len(selected_parts),
            conversion_defaults=name if conversion else None,
            unresolved_instruments=unresolved, decoder_warnings=warnings,
            editable_matches_generated=editable.read_text(encoding='utf-8') == text))
    settings = out/'renderer.toml'
    if not settings.exists():
        settings.write_bytes((DEFAULTS/'renderer.example.toml').read_bytes())
    report['effects'] = generate_effects(dos, chunks, out, args.effects_catalog)
    (out/'generation-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def restore(package, data, game, out, shared=None):
    """Restore shipped arrangements for synthesis, without retained sample audio."""
    from audio_package import validate_dos, write_toml
    from audio_defaults import performance_identity
    original = validate_dos(package, game, data, shared)
    out = Path(out).resolve()
    for name, raw in original.items():
        recipe = package/'songs'/(name+'.toml')
        midi, doc = recipe_midi(recipe, licensed_imf=raw)
        meta = read_toml(package/'inputs'/name/'inputs.toml')
        if performance_identity(midi) != meta['performance_sha256']:
            raise ValueError('Restored arrangement differs from shipped performance: '+name)
        target = out/'songs'/(name+'.toml')
        if target.exists():
            continue  # The developer owns existing editable recipes.
        source = out/'source'/name
        source.mkdir(parents=True, exist_ok=True)
        (source/'score.mid').write_bytes(midi)
        (source/'original.imf').write_bytes(raw)
        doc['source'].update(kind='midi',file='../source/'+name+'/score.mid',sha256=sha(midi))
        doc['original']['file']='../source/'+name+'/original.imf'
        policy = recipe.parent/doc['doc']['sampling_policy']
        (source/'sampling.toml').write_bytes(policy.read_bytes())
        doc['doc']['sampling_policy']='../source/'+name+'/sampling.toml'
        if any('wav' in spec for spec in doc['doc'].get('capture',[])):
            raise ValueError('Explicit WAV overrides need an editable synthesis recipe: '+name)
        write_toml(target,doc,'# Restored arrangement and calibration; samples are freshly synthesized.')
    return out


def load_recipe(path):
    doc = read_toml(path)
    if type(doc.get('format')) is not int or doc.get('format') != 1 or doc.get('kind') != 'music':
        raise ValueError('expected a format-1 music recipe')
    expected = {'format', 'kind', 'name', 'source', 'original', 'render', 'capture', 'reconstruction', 'instrument', 'change', 'doc', 'defaults'}
    if doc.keys()-expected:
        raise ValueError('unknown recipe fields: '+', '.join(sorted(doc.keys()-expected)))
    for key in ('source', 'original', 'render', 'capture', 'reconstruction'):
        if not isinstance(doc.get(key), dict):
            raise ValueError('recipe is missing ['+key+']')
    for key, names in dict(source=('kind', 'file', 'sha256', 'authority'), original=('file', 'sha256'),
        render=('reset', 'end'), capture=('lead_seconds', 'tail_seconds'),
        reconstruction=('allow_unsupported',)).items():
        fields(doc[key], names, key)
    if type(doc['reconstruction']['allow_unsupported']) is not bool:
        raise ValueError('reconstruction.allow_unsupported must be true or false')
    if 'defaults' in doc:
        fields(doc['defaults'], ('file',), 'defaults')
    return doc


def suggest(args):
    doc = load_recipe(args.recipe)
    raw = checked(args.recipe.parent/doc['original']['file'], doc['original']['sha256'])
    notes, _, warnings = imf_notes(raw)
    reports = json.loads(args.evidence.read_text(encoding='utf-8'))['reports']
    examples = [e for r in reports if r['authority'] in REFERENCE_AUTHORITIES
                for e in r.get('examples', []) if e['song'] != doc['name']]
    settings = read_toml(args.heuristics)
    validate_settings(settings)
    lines = ['# Ranked audition candidates, not selected instruments or recovered composer intent.',
        '# Lower distance means more similar score context. It is not a probability.',
        '# The target song is excluded from its own reference set.', 'format = 1',
        'song = '+quote(doc['name'])]
    covered, total = 0, 0
    for patch, channel in sorted({(n['patch'], n['channel']) for n in notes}):
        part = [n for n in notes if (n['patch'], n['channel']) == (patch, channel)]
        context = features(notes, part)
        candidates = ranked(examples, patch, context, settings)
        lines += ['', '[[part]]', f'opl_channel = {channel}', 'patch = '+quote(patch),
                  f'notes = {len(part)}']
        seen = set()
        for candidate in candidates:
            example = candidate['example']
            if label(example['mapping']) in seen:
                continue
            seen.add(label(example['mapping']))
            lines += ['', '[[part.candidate]]', 'reference_song = '+quote(example['song']),
                f'reference_opl_channel = {example["opl_channel"]}', f'distance = {candidate["distance"]:.6f}']
            lines += [f'{key} = {example["mapping"][key]}' for key in MAPPING_FIELDS]
            if len(seen) == 3:
                break
        covered += bool(seen)
        total += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.resolve() == args.recipe.resolve():
        raise ValueError('suggestions must not overwrite the editable recipe')
    args.out.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return dict(parts=total, parts_with_candidates=covered, decoder_warnings=warnings)


def learn(args):
    recipes = {}
    for directory in args.recipes:
        for path in sorted((directory/'songs').glob('*.toml')):
            doc = load_recipe(path)
            if doc['source']['kind'] == 'midi':
                selected, _ = recipe_midi(path)
                recipes[doc['name'], doc['original']['sha256'], sha(selected)] = path, doc
    reports, skipped, default_songs = [], [], []
    for pair in read_toml(args.pairs)['song']:
        key = pair['name'], pair['imf_sha256'], pair['midi_sha256']
        if key not in recipes:
            skipped.append(pair['name'])
            continue
        path, doc = recipes[key]
        raw = checked(path.parent/doc['original']['file'], pair['imf_sha256'])
        fm, _, warnings = imf_notes(raw)
        selected, _ = recipe_midi(path)
        if sha(selected) != pair['midi_sha256']:
            raise ValueError(pair['name']+': selected arrangement changed during learning')
        default, report = default_song(pair, raw, selected, fm)
        default_songs.append(default)
        report.update(imf_sha256=pair['imf_sha256'], midi_sha256=pair['midi_sha256'], decoder_warnings=warnings)
        reports.append(report)
    if not reports:
        raise ValueError('no recipes matched the paired source hashes')
    patches = aggregate(reports)
    names = read_toml(DEFAULTS/'gm-programs.toml')['program']
    lines = ['# Observed OPL-to-Roland choices. These are suggestions for new arrangements.',
        '# Same patch does not imply same orchestration or register in another song.',
        '# Edit song recipes to select programs; unresolved choices never become piano.',
        'format = 1']
    for patch in patches:
        lines += ['', '[[patch]]', 'id = '+quote(patch['patch']),
            'authority = '+quote(patch['authority']), 'candidates = [']
        for c in patch['candidates']:
            instrument_name = 'Drum kit' if c['drum_key'] >= 0 else names[str(c['program'])]
            description = f"program {c['program']} {instrument_name}, bank {c['bank_msb']}/{c['bank_lsb']}, transpose {c['transpose']}, drum {c['drum_key']}"
            lines.append('    '+quote(description)+',')
        lines += [']', 'evidence = [']
        for o in patch['observations']:
            labels = ', '.join(f"{c['program']} ({c['matched']} notes)" for c in o['candidates'])
            lines.append('    '+quote(f"{o['song']} OPL {o['opl_channel']} -> MIDI {o['midi_channel']}: {labels}; {o['authority']}")+',')
        lines += [']']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    context_test = evaluate(reports, read_toml(args.heuristics))
    result = dict(reports=reports, patches=patches, held_out=held_out(reports),
                  context_test=context_test, skipped=skipped)
    args.out.with_suffix('.json').write_text(json.dumps(result, indent=2)+'\n')
    if args.defaults_out:
        write_defaults(args.defaults_out, default_songs)
    return dict(paired_songs=len(reports), patches=len(patches), held_out=result['held_out'],
                context_test=context_test['methods'], skipped=skipped)


def write_defaults(path, songs):
    validate_defaults(dict(format=1, song=songs))
    names = read_toml(DEFAULTS/'gm-programs.toml')['program']
    lines = ['# Functional defaults, extracted from the selected instrument arrangements.',
             '# generate applies these automatically before optional recipe edits.',
             '# MIDI matches the timed score; IMF matches source hash, OPL part and patch.',
             '# first_note counts note-ons on that MIDI channel, starting at 1.',
             '# A drum part uses a kit program; other programs name melodic instruments.',
             'format = 1']
    for song in songs:
        lines += ['', '[[song]]']
        lines += [key+' = '+quote(song[key]) for key in
                  ('name', 'authority', 'imf_sha256', 'midi_sha256', 'midi_score_sha256')]
        # Empty arrays must be explicit so an incomplete correspondence stays visible.
        if not song['imf']:
            lines += ['imf = []']
        for part in song['midi']:
            name = 'Drum kit' if part['channel'] == 10 else names[str(part['program'])]
            lines += ['', '[[song.midi]]', '# '+name]
            lines += [f'{key} = {value}' for key, value in part.items()]
        for part in song['imf']:
            name = 'Drum kit' if part['drum_key'] >= 0 else names[str(part['program'])]
            lines += ['', '[[song.imf]]', '# '+name]
            lines += [key+' = '+quote(value) for key, value in part.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def imf_midi(raw, doc):
    notes, end, warnings = imf_notes(raw)
    if warnings and not doc['reconstruction'].get('allow_unsupported', False):
        raise ValueError('; '.join(warnings))
    mappings = {}
    for inst in doc.get('instrument', []):
        fields(inst, ('patch', 'opl_channel', 'program', 'bank_msb', 'bank_lsb', 'drum_key',
            'transpose', 'velocity', 'note_length_scale', 'minimum_note_seconds', 'reverb', 'chorus', 'pan')
            + (('candidates',) if 'candidates' in inst else ()), 'instrument')
        key = inst['patch'], inst['opl_channel']
        if inst.get('program') == 0:
            raise ValueError('unmapped instrument '+str(key)+': select a program before MIDI/WAV export')
        if key in mappings:
            raise ValueError('duplicate instrument entry')
        for field, lo, hi in [('program', 1, 128), ('bank_msb', 0, 127), ('bank_lsb', 0, 127),
                             ('drum_key', -1, 127), ('transpose', -48, 48), ('velocity', 1, 127),
                             ('reverb', 0, 127), ('chorus', 0, 127), ('pan', 0, 127)]:
            integer(inst.get(field), lo, hi, field+' for '+str(key))
        number(inst.get('note_length_scale'), 0.1, 10, 'note_length_scale')
        number(inst.get('minimum_note_seconds'), 0, 10, 'minimum_note_seconds')
        mappings[key] = inst
    required = {(n['patch'], n['channel']) for n in notes}
    if set(mappings) != required:
        raise ValueError('instrument entries must cover every source patch/voice exactly once')
    events = [Event(0, 0, b'\xff\x51\x03\x07\xa1\x20')]
    kits, last = set(), {}
    for n in notes:
        inst = mappings[n['patch'], n['channel']]
        channel = 9 if inst['drum_key'] >= 0 else n['channel']-1
        key = inst['drum_key'] if channel == 9 else n['key']+inst['transpose']
        integer(key, 0, 127, 'reconstructed MIDI key')
        signature = tuple(inst[k] for k in ('program', 'bank_msb', 'bank_lsb', 'pan', 'reverb', 'chorus'))
        if channel == 9:
            kits.add(signature)
            if len(kits) > 1:
                raise ValueError('simultaneous drum parts require one shared kit/controller context')
        tick = n['tick']
        if last.get(channel) != signature:
            for cc, value in ((0, inst['bank_msb']), (32, inst['bank_lsb']), (7, 100), (11, 127),
                              (10, inst['pan']), (91, inst['reverb']), (93, inst['chorus']),
                              (101, 0), (100, 0), (6, 24), (38, 0), (101, 127), (100, 127)):
                events.append(Event(tick, 0, bytes([0xb0+channel, cc, value])))
            events.append(Event(tick, 0, bytes([0xc0+channel, inst['program']-1])))
            last[channel] = signature
        # Key-on FNUM rounding is corrected by pitch bend; later bends retain their times.
        if channel != 9:
            for bt, pitch in [(tick, n['pitch'])]+n['bends']:
                bend = round(8192+(pitch-n['key'])*8192/24)
                if not 0 <= bend <= 16383:
                    raise ValueError('IMF pitch bend exceeds the explicit 24-semitone range')
                events.append(Event(bt, 0, bytes([0xe0+channel, bend & 127, bend >> 7])))
        events.append(Event(tick, 0, bytes([0x90+channel, key, inst['velocity']])))
        length = max(round((n['end_tick']-tick)*inst['note_length_scale']), round(inst['minimum_note_seconds']*700), 1)
        events.append(Event(tick+length, 0, bytes([0x80+channel, key, 0])))
    events.append(Event(max(end, max(e.tick for e in events)), 0, b'\xff\x2f\x00'))
    return midi_write(350, events)


def recipe_midi(path, licensed_imf=None):
    doc = load_recipe(path)
    source = doc['source']
    data = checked(path.parent/source['file'], source['sha256'])
    if source['kind'] == 'midi':
        midi_read(data)
        if 'defaults' in doc:
            defaults = validate_defaults(read_toml(path.parent/doc['defaults']['file']))
            data, _ = midi_defaults(data, defaults, doc['name'])
        data = program_map(data, doc.get('change', []))
    elif source['kind'] == 'imf':
        data = imf_midi(data, doc)
    elif source['kind'] == 'imf-delta':
        if licensed_imf is None:raise ValueError('source-relative music requires the licensed AdLib input')
        from audio_score_delta import reconstruct
        data=reconstruct(licensed_imf,read_toml(path.parent/source['file']))
    else:
        raise ValueError('unknown music source kind')
    return data, doc


def debug_midi(data, doc, part=None, capture=None, steady=False, hold_seconds=None, probe_key=None, neutral_bend=False):
    division, events = midi_read(data)
    if capture:
        channel, key, occurrence = capture
        integer(channel, 1, 16, 'capture channel')
        integer(key, 0, 127, 'capture key')
        matches = [n for n in midi_notes(data) if (n['channel'], n['key']) == (channel, key)]
        integer(occurrence, 1, len(matches), 'capture occurrence')
        note = matches[occurrence-1]
        attacks = [i for i, e in enumerate(events) if e.raw[0] == 0x90+channel-1
                   and e.raw[1] == key and e.raw[2]]
        selected_index = attacks[occurrence-1]
        lead, tail = doc['capture']['lead_seconds'], doc['capture']['tail_seconds']
        number(lead, 0.01, 10, 'capture lead_seconds')
        number(tail, 0, 30, 'capture tail_seconds')
        # Preserve setup order, including parameter selections and SysEx, but
        # let the MIDI port consume it before the quiet lead and note attack.
        # Collapsing a long controller history onto time zero delays the note
        # inside the emulator and makes that queue delay look like its envelope.
        setup_ticks = {}
        setup_bytes = 0
        for index, e in enumerate(events[:selected_index]):
            status = e.raw[0] & 0xf0
            if status in (0x80, 0x90) or e.raw[:2] in (b'\xff\x51', b'\xff\x2f'):
                continue
            if status < 0xf0 and (e.raw[0] & 15) != channel-1:
                continue
            setup_ticks[index] = math.ceil(setup_bytes * 10 * 1000 / 31250)
            if e.raw[0] != 0xff:
                # Counting the SMF SysEx length prefix too is conservative.
                setup_bytes += len(e.raw)
        lead += math.ceil(setup_bytes * 10 * 1000 / 31250) / 1000
        output = [Event(0, 0, b'\xff\x51\x03\x0f\x42\x40')]
        on = round(lead*1000)
        held = note['end']-note['start']
        if hold_seconds is not None:
            if not steady:
                raise ValueError('a probe hold requires static note-on controls')
            number(hold_seconds, held, 120, 'capture probe hold_seconds')
            held = hold_seconds
        if probe_key is not None:
            if not steady or channel == 10:
                raise ValueError('a common probe key requires a static melodic capture')
            integer(probe_key, 0, 127, 'capture probe_key')
        if neutral_bend and (not steady or channel == 10):
            raise ValueError('a neutral probe bend requires a static melodic capture')
        off = round((lead+held)*1000)
        released, sustain = False, 0
        for index, e in enumerate(events):
            status = e.raw[0] & 0xf0
            if e.seconds > note['end']+tail:
                break
            if index == selected_index:
                if neutral_bend:
                    output.append(Event(on, 0, bytes([0xe0+channel-1,0,64])))
                output.append(Event(on, 0, e.raw if probe_key is None else bytes([e.raw[0], probe_key, e.raw[2]])))
            if (not released and index > selected_index and e.tick == note['end_tick']
                    and (e.raw[0] & 15) == channel-1 and len(e.raw) == 3 and e.raw[1] == key
                    and (status == 0x80 or (status == 0x90 and e.raw[2] == 0))):
                output.append(Event(off, 0, e.raw if probe_key is None else bytes([e.raw[0], probe_key, e.raw[2]])))
                released = True
            if status in (0x80, 0x90) or e.raw[:2] in (b'\xff\x51', b'\xff\x2f'):
                continue
            if status < 0xf0 and (e.raw[0] & 15) != channel-1:
                continue
            if steady and index > selected_index and status in (0xa0, 0xb0, 0xc0, 0xd0, 0xe0, 0xf0):
                continue
            if status == 0xb0 and e.raw[1] in (64, 121):
                sustain = e.raw[2] if e.raw[1] == 64 else 0
            t = setup_ticks[index] if index < selected_index else round((lead+e.seconds-note['start'])*1000)
            output.append(Event(t, 0, e.raw))
        if not released:
            raise ValueError('capture could not find the selected note release')
        if steady:
            output.append(Event(off, 0, bytes([0xb0+channel-1, 64, 0])))
            sustain = 0
        if sustain >= 64:
            raise ValueError('capture ends with sustain held; increase capture.tail_seconds to include its release')
        output.append(Event(off+round(tail*1000), 0, b'\xff\x2f\x00'))
        return midi_write(1000, output)
    if part is not None:
        integer(part, 1, 16, 'part')
        if not any(n['channel'] == part for n in midi_notes(data)):
            raise ValueError('selected MIDI part has no notes')
        return midi_write(division, [e for e in events if e.raw[0] & 0xf0 not in (0x80, 0x90)
                                    or (e.raw[0] & 15) == part-1])
    return data


def release_window(data, seconds):
    """Leave the complete score unchanged and extend only its end marker."""
    division,events=midi_read(data)
    tempo=500000
    for e in events:
        if e.raw[:2]==b'\xff\x51':tempo=int.from_bytes(e.raw[3:6],'big')
    end=events[-1].tick+math.ceil(seconds*division*1000000/tempo)
    return midi_write(division,events+[Event(end,0,b'\xff\x2f\x00')])


def reference_tail_quiet(path):
    """Check audible tail energy independently of the emulator's idle DC."""
    with wave.open(str(path),'rb') as wav:
        values=array.array('h',wav.readframes(wav.getnframes()))
        if sys.byteorder!='little':values.byteswap()
        rate,channels=wav.getframerate(),wav.getnchannels()
    for channel in range(channels):
        side=values[channel::channels]
        tail=side[-round(.1*rate):]
        dc=sum(tail)/max(1,len(tail))
        peak=max((abs(v-dc) for v in side),default=0)
        if math.sqrt(sum((v-dc)**2 for v in tail)/max(1,len(tail)))>max(2.,peak*.001):
            return False
    return True


def render(args):
    initial = read_toml(args.recipe)
    if initial.get('kind') == 'effect':
        source = initial['source']
        if args.command != 'wav' or source['kind'] != 'pcm-u8' or args.part or args.capture:
            raise ValueError('use audio_compile.py effect for synthetic layers and their debug WAVs')
        data = checked(args.recipe.parent/source['file'], source['sha256'])
        integer(source['rate'], 1000, 192000, 'PCM sample rate')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(args.out), 'wb') as wav:
            wav.setparams((1, 1, source['rate'], len(data), 'NONE', 'not compressed'))
            wav.writeframes(data)
        return dict(wav=str(args.out), source_sha256=sha(data), frames=len(data), rate=source['rate'])
    data, doc = recipe_midi(args.recipe)
    steady = getattr(args, 'capture_static', False)
    probe_hold = getattr(args, 'capture_hold_seconds', None)
    probe_key = getattr(args, 'capture_probe_key', None)
    neutral_bend = getattr(args, 'capture_neutral_bend', False)
    data = debug_midi(data, doc, args.part, args.capture, steady=steady, hold_seconds=probe_hold, probe_key=probe_key, neutral_bend=neutral_bend)
    if args.command == 'midi':
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(data)
        return dict(midi=str(args.out), sha256=sha(data))
    if args.settings is None:
        raise ValueError('music WAV rendering requires --settings renderer.toml')
    settings = read_toml(args.settings)['renderer']
    executable = (args.settings.parent/Path(settings['executable'])).resolve()
    roms = (args.settings.parent/Path(settings['rom_directory'])).resolve()
    if not executable.is_file() or not roms.is_dir():
        raise ValueError('set renderer.executable and renderer.rom_directory in renderer.toml')
    if settings.get('executable_sha256') and sha(executable.read_bytes()) != settings['executable_sha256']:
        raise ValueError('renderer executable hash differs from settings')
    if doc['render']['reset'] not in ('gs', 'gm', 'none') or doc['render']['end'] not in ('release', 'cut'):
        raise ValueError('invalid renderer reset or end policy')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    midi_path = args.out.with_suffix('.mid').resolve()
    requested_midi_sha = sha(data)
    reference_data=data
    reference_tail=2. if not args.capture and doc['render']['end']=='release' else None
    if reference_tail is not None:data=release_window(reference_data,reference_tail)
    midi_path.write_bytes(data)
    command = [str(executable), '-d', str(roms), '--romset', settings['romset'],
               '-r', doc['render']['reset'], '--end', 'cut' if args.capture or reference_tail is not None else doc['render']['end'], '-f', 's16',
               '--quiet', '-o', str(args.out.resolve()), str(midi_path)]
    while True:
        try:
            duration = midi_read(data)[1][-1].seconds
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=max(60,duration*10+30))
        except subprocess.TimeoutExpired as error:
            raise ValueError('Roland renderer did not reach silence within its bounded render time') from error
        except subprocess.CalledProcessError as error:
            raise ValueError('Roland renderer failed: '+error.stderr.decode('utf-8', 'replace')[-3000:]) from error
        if not args.capture:
            if reference_tail is None or reference_tail_quiet(args.out):break
            if reference_tail>=30:
                raise ValueError('reference remains audible after 30 seconds; inspect the score controls')
            reference_tail=min(30,reference_tail*2)
            data=release_window(reference_data,reference_tail)
            midi_path.write_bytes(data)
            continue
        # Some ROM voices leave a tiny nonzero idle signal forever. Render a
        # bounded post-release window and verify audible silence ourselves.
        if reference_tail_quiet(args.out):
            break
        tail_seconds=doc['capture']['tail_seconds']
        if tail_seconds>=30:
            raise ValueError('captured instrument remains audible after 30 seconds; inspect the score controls')
        doc=copy.deepcopy(doc)
        doc['capture']['tail_seconds']=min(30,max(2,tail_seconds*2))
        original,_=recipe_midi(args.recipe)
        data=debug_midi(original,doc,args.part,args.capture,steady=steady,hold_seconds=probe_hold,probe_key=probe_key,neutral_bend=neutral_bend)
        midi_path.write_bytes(data)
    with wave.open(str(args.out), 'rb') as wav:
        rate, channels, width, frames = wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
        if (rate, channels, width) != (64000, 2, 2) or not frames:
            raise ValueError('expected nonempty 64 kHz stereo 16-bit renderer WAV')
    receipt = dict(recipe_sha256=sha(args.recipe.read_bytes()), midi_sha256=sha(data),
        render_requested_midi_sha256=requested_midi_sha,
        render_policy=doc['render'],
        wav_sha256=sha(args.out.read_bytes()), renderer_sha256=sha(executable.read_bytes()),
        romset=settings['romset'], command=command, rate=rate, channels=channels, frames=frames,
        seconds=frames/rate, doc_bank_built=False, listening_accepted=False)
    if reference_tail is not None:
        receipt.update(release_window_seconds=reference_tail,tail_silence_verified=True)
    if args.capture:
        note = midi_notes(data)[0]
        receipt.update(lead=note['start'], hold_seconds=note['end']-note['start'],
                       quiet_lead_seconds=doc['capture']['lead_seconds'],
                       capture_requested_midi_sha256=requested_midi_sha,
                       tail_seconds=doc['capture']['tail_seconds'], tail_silence_verified=True)
        receipt['capture_controls'] = 'held at note-on state' if steady else 'original score automation'
    receipt['rom_inputs'] = {p.relative_to(roms).as_posix(): sha(p.read_bytes())
                            for p in sorted(roms.rglob('*')) if p.is_file()}
    args.out.with_suffix('.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    collect = commands.add_parser('collect-midi', help='collect hash-verified composer MIDIs from cache or archived source URLs')
    collect.add_argument('--sources', type=Path, default=DEFAULTS/'midi-sources.toml')
    collect.add_argument('--cache', action='append', default=[], type=Path)
    collect.add_argument('--out', required=True, type=Path)
    standins = commands.add_parser('collect-standins', help='extract a pinned optional MIDI set by hash, without executing archive contents')
    standins.add_argument('--sources', required=True, type=Path)
    standins.add_argument('--archive', required=True, type=Path)
    standins.add_argument('--out', required=True, type=Path)
    g = commands.add_parser('generate', help='create editable per-song recipes without overwriting edits')
    g.add_argument('--profile', default='shareware')
    g.add_argument('--data', required=True, type=Path)
    g.add_argument('--shared-data', type=Path)
    g.add_argument('--midi-dir', action='append', default=[], type=Path)
    g.add_argument('--sources', type=Path, default=DEFAULTS/'midi-sources.toml')
    g.add_argument('--fallback-sources', action='append', default=[], type=Path,
                   help='explicit optional MIDI source catalog, tried only when the primary source is absent')
    g.add_argument('--mapping', type=Path, default=DEFAULTS/'adlib-observations.toml')
    g.add_argument('--instrument-defaults', type=Path, default=DEFAULTS/'instrument-defaults.toml',
                   help='established instrument choices, applied automatically to matching scores')
    g.add_argument('--effects-catalog', type=Path, help='custom readable effect names and PCM replacements')
    g.add_argument('--out', required=True, type=Path)
    learn_parser = commands.add_parser('learn', help='compare explicitly paired IMF and MIDI parts')
    learn_parser.add_argument('--recipes', action='append', required=True, type=Path)
    learn_parser.add_argument('--pairs', type=Path, default=DEFAULTS/'reference-pairs.toml')
    learn_parser.add_argument('--heuristics', type=Path, default=DEFAULTS/'heuristics.toml')
    learn_parser.add_argument('--out', required=True, type=Path)
    learn_parser.add_argument('--defaults-out', type=Path,
                              help='extract executable defaults from the selected paired arrangements')
    suggestions = commands.add_parser('suggest', help='rank candidates using the notes and their accompaniment')
    suggestions.add_argument('recipe', type=Path)
    suggestions.add_argument('--evidence', required=True, type=Path)
    suggestions.add_argument('--heuristics', type=Path, default=DEFAULTS/'heuristics.toml')
    suggestions.add_argument('--out', required=True, type=Path)
    for command in ('midi', 'wav'):
        r = commands.add_parser(command, help='write a score or render a debug audition')
        r.add_argument('recipe', type=Path)
        r.add_argument('--out', required=True, type=Path)
        selected = r.add_mutually_exclusive_group()
        selected.add_argument('--part', type=int)
        selected.add_argument('--capture', nargs=3, type=int, metavar=('CHANNEL', 'KEY', 'OCCURRENCE'))
        if command == 'wav':
            r.add_argument('--settings', type=Path)
    args = p.parse_args()
    try:
        if args.command == 'collect-midi':
            result = collect_midi(args)
        elif args.command == 'collect-standins':
            result = collect_standins(args)
        elif args.command == 'generate':
            result = generate(args)
        elif args.command == 'learn':
            result = learn(args)
        elif args.command == 'suggest':
            result = suggest(args)
        else:
            result = render(args)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        p.exit(2, str(error)+'\n')


if __name__ == '__main__':
    main()
