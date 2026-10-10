#!/usr/bin/env python3
"""Prepare full-duration effects and comparison audio without changing game assets."""
import argparse
import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import wave

from audio_package import checked, contained, write_toml
from dos_data import DosData
from effect_sources import manifest as source_manifest, source_effects
from game_profile import fields, integer, number, read_toml

ROOT = Path(__file__).resolve().parents[1]
DOC_RATE = 894886 / 34
# Fixed stock-mono emulator output coefficient, maximum system volume.
# Both centred effect oscillators contribute. No per-file playback gain is fitted.
PAIR_SCALE = 2 * 17 / (4 * 32768 * 34)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def table_bytes(length):
    return 1 << max(8, length.bit_length())  # one zero terminator after length samples


def frequency(rate, size):
    code = size.bit_length() - 9
    # Same integer rounding as the current player, resolution 7.
    raw = round(rate * 65536 / DOC_RATE)
    result = (raw + ((1 << code) >> 1)) >> code
    if not 1 <= result <= 65535:
        raise ValueError('source rate cannot use the selected DOC buffer/resolution')
    return result


def descriptor(raw, sid):
    return dict(zip(('address', 'bytes', 'fc', 'priority', 'size', 'pages', 'level', 'pad', 'zero'),
                    struct.unpack_from('<IHHHBBBBH', raw, sid * 16)))


def load_recipe(path):
    doc = read_toml(path)
    fields(doc, ('format', 'digitized', 'opl', 'doc', 'stream_analysis'), 'effects recipe', ('opl_override',))
    integer(doc['format'], 1, 1, 'recipe format')
    if doc['digitized'] != dict(rate='source', duration='full'):
        raise ValueError('digitized recordings require source rate and full duration')
    fields(doc['opl'], ('input', 'sample_rate', 'duration'), 'OPL settings')
    if doc['opl']['input'] != 'preserved' or doc['opl']['duration'] != 'full':
        raise ValueError('OPL defaults require an explicit preserved input and full duration')
    number(doc['opl']['sample_rate'], 1000, 192000, 'OPL sample rate')
    if doc['doc'] != dict(zero_bytes='replace-with-one', levels='current'):
        raise ValueError('this preparation retains current levels and only substitutes zero bytes')
    stream = doc['stream_analysis']
    fields(stream, ('buffer_bytes', 'buffers_per_voice', 'voices', 'effects_doc_bytes'), 'stream analysis')
    integer(stream['buffer_bytes'], 256, 4096, 'buffer bytes')
    if stream['buffer_bytes'] & (stream['buffer_bytes'] - 1):
        raise ValueError('stream buffer must be a power of two')
    if (stream['buffers_per_voice'], stream['voices'], stream['effects_doc_bytes']) != (2, 2, 16384):
        raise ValueError('analysis must retain two effect voices and the existing 16 KiB DOC partition')
    overrides = {}
    for row in doc.get('opl_override', []):
        fields(row, ('name', 'file', 'sha256', 'sample_rate', 'note'), 'OPL override')
        number(row['sample_rate'], 1000, 192000, 'override sample rate')
        if row['name'] in overrides or not row['note'].strip():
            raise ValueError('OPL overrides require unique names and an explanation')
        overrides[row['name']] = row
    return doc, overrides


def source_pcm(raw):
    if not raw:
        raise ValueError('empty effect input')
    return bytes(max(1, b) for b in raw)


def write_pcm_wav(path, raw, rate):
    # WAV has an integer sample-rate field. PCM payload is copied byte for byte.
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 1, round(rate), 0, 'NONE', 'not compressed'))
        wav.writeframes(raw)


def render_doc_model(payload, fc, size, level, *, continuous=False):
    """Resolution-7 address/hold model on one fixed stock-mono output scale.

    continuous models an ideal seamless refill of consecutive source bytes.
    It does not claim that the existing game implements such a refill.
    The initial phase convention matches audio_preview.render_parts.
    """
    code = size.bit_length() - 9
    shift = 16 - code
    step = fc / (1 << shift)
    if fc < 1 or not payload or payload[-1] != 0 or 0 in payload[:-1]:
        raise ValueError('DOC preview requires nonempty zero-terminated, zero-free PCM')
    samples = array.array('f')
    phase = 0
    for _ in range(math.ceil(len(payload) / step) + 2):
        phase += fc
        at = phase >> shift
        if at >= len(payload) or (not continuous and at >= size) or payload[at] == 0:
            break
        samples.append((payload[at] - 128) * level * PAIR_SCALE)
    return samples


def write_float_wav(path, values):
    # IEEE float preserves fixed amplitudes; neither normalize nor clip previews.
    values = array.array('f', values)
    if sys.byteorder != 'little':
        values.byteswap()
    data = values.tobytes()
    rate = round(DOC_RATE)
    path.write_bytes(struct.pack('<4sI4s4sIHHIIHH4sII4sI', b'RIFF', 48+len(data), b'WAVE',
        b'fmt ', 16, 3, 1, rate, rate*4, 4, 32, b'fact', 4, len(values), b'data', len(data)) + data)


def demand(rows, floor, regions, stream):
    """Byte counts and conservative transfer demands, never measured CPU time."""
    selected = [rows[i] for i in floor['effects']]
    unique = {r['sample_sha256']:r['bytes_with_terminator'] for r in selected}
    sizes = [r['end']-r['start'] for r in regions]
    used = [87*16 + 64] + [0] * (len(sizes)-1)
    failed = []
    seen = set()
    for row in selected:
        if row['sample_sha256'] in seen:
            continue
        seen.add(row['sample_sha256'])
        region = next((i for i in range(len(sizes)) if used[i]+row['bytes_with_terminator'] <= sizes[i]), None)
        if region is None:
            failed.append(row['id'])
        else:
            used[region] += row['bytes_with_terminator']
    buffers = stream['buffer_bytes'] * stream['buffers_per_voice'] * stream['voices']
    payload = stream['buffer_bytes'] - 1
    maxrate = max(r['source_rate'] for r in selected)
    pinned = floor.get('pinned', [])
    return dict(floor=floor['floor'], effect_ids=floor['effects'],
        current_ram_bytes=floor['resident_bytes'], proposed_ram_bytes=87*16+64+sum(unique.values()),
        reserved_ram_bytes=sum(sizes), existing_region_used=used, existing_region_unplaced=failed,
        distinct_sample_bytes=sum(unique.values()),
        all_one_shot_pages=sum(r['one_shot_table_bytes']//256 for r in selected),
        old_pins_proposed_pages=sum(rows[sid]['one_shot_table_bytes']//256 for sid in pinned),
        exceeds_current_pool=[r['id'] for r in selected if r['one_shot_table_bytes'] > 4096],
        exceeds_entire_effect_partition=[r['id'] for r in selected if r['one_shot_table_bytes'] > 16384],
        exceeds_hardware_table=[r['id'] for r in selected if r['one_shot_table_bytes'] > 32768],
        exceeds_current_length_field=[r['id'] for r in selected if r['bytes_with_terminator'] > 65535],
        two_voice_stream_buffer_bytes=buffers,
        pages_left_for_pins=(stream['effects_doc_bytes']-buffers)//256,
        worst_two_voice_upload_bytes_per_second=stream['voices']*maxrate*stream['buffer_bytes']/payload,
        worst_two_voice_refills_per_second=stream['voices']*maxrate/payload,
        shortest_refill_deadline_ms=payload/maxrate*1000,
        max_current_cache_miss_bytes=max(r['current_bytes'] for r in selected),
        max_proposed_whole_sample_upload_bytes=max(r['bytes_with_terminator'] for r in selected),
        runtime_feasibility_verified=False)


def prepare(args):
    recipe, overrides = load_recipe(args.recipe)
    out = args.out.resolve()
    for source in (args.data, args.preserved, args.current_sound):
        root = source.resolve()
        if out == root or root in out.parents:
            raise ValueError('output must be outside the source and current-build folders')
    if out.exists() and any(out.iterdir()):
        raise ValueError('use a new empty output directory; comparison evidence is never overwritten')
    game = DosData(args.data, args.profile)
    current = args.current_sound.resolve()
    current_manifest = json.loads((current/'manifest.json').read_text())
    floors = json.loads((current/'effects-floors.json').read_text())
    if len(floors['floors']) != game.profile.floors:
        raise ValueError('current floor inventory differs from the source profile')
    for key, digest in current_manifest['source_hashes'].items():
        stem = next(stem for stem in game.profile.files if game.filename(stem) == key)
        if sha(game.read(stem)) != digest:
            raise ValueError('licensed source differs from the current build: '+key)
    provenance = source_manifest(game, args.preserved)
    sources = source_effects(game)
    names = {r['name']:r for r in sources}
    for name in overrides:
        if name not in names or names[name]['pcm'] is not None:
            raise ValueError('only named OPL effects may have OPL overrides: '+name)
    levels = json.loads(args.levels.read_text())
    descriptors = {}
    for floor in floors['floors']:
        for load in floor['loads']:
            checked(current/load['file'], load['sha256'])
        bank = (current/floor['file']).read_bytes()
        for sid in floor['effects']:
            entry = descriptor(bank, sid)
            if entry['level'] != levels['levels'][str(sid)]['level']:
                raise ValueError('selected levels do not match current floor descriptors')
            if sid in descriptors and any(entry[k] != descriptors[sid][k] for k in ('bytes','fc','size','pages','level')):
                raise ValueError('effect playback differs between floor descriptors')
            descriptors[sid] = entry
    out.mkdir(parents=True, exist_ok=True)
    (out/'samples').mkdir()
    (out/'comparisons').mkdir()
    rows = []
    for original, identity, existing in zip(sources, provenance['effects'], current_manifest['effects']):
        sid, name = original['id'], original['name']
        assert sid == identity['id'] == existing['id']
        if original['pcm'] is not None:
            raw, rate, origin = original['pcm'], original['source_rate'], 'licensed-digitized'
        else:
            raw = checked(contained(args.preserved, identity['file']), identity['payload_sha256'])
            rate, origin = recipe['opl']['sample_rate'], 'retained-opl'
            if name in overrides:
                spec = overrides[name]
                raw = checked(contained(args.recipe.parent, spec['file']), spec['sha256'])
                rate, origin = spec['sample_rate'], 'explicit-opl-override'
        proposed = source_pcm(raw)
        payload = proposed+b'\0'
        stored = checked(current/f'effect-{sid:02}.pcm', existing['sha256'])
        old = descriptors.get(sid, dict(fc=existing['fc'], pages=existing['pages'],
                                       level=levels['levels'][str(sid)]['level']))
        if len(stored) != existing['bytes']:
            raise ValueError('current sample size differs from manifest')
        filename = f'samples/{sid:02}-{name}.u8'
        (out/filename).write_bytes(proposed)  # un-terminated, complete source duration
        size = table_bytes(len(proposed))
        stream_size = recipe['stream_analysis']['buffer_bytes']
        fc = frequency(rate, stream_size)
        model_rate = fc*DOC_RATE*stream_size/16777216
        folder = out/'comparisons'/f'{sid:02}-{name}'
        folder.mkdir()
        write_pcm_wav(folder/'raw-source.wav', raw, rate)
        write_pcm_wav(folder/'current-stored-pcm.wav', stored[:-1], existing['rate'])
        write_pcm_wav(folder/'proposed-source.wav', proposed, rate)
        write_float_wav(folder/'current-doc-model.wav', render_doc_model(stored, old['fc'], old['pages']*256, old['level']))
        write_float_wav(folder/'proposed-doc-model.wav', render_doc_model(payload, fc, stream_size, old['level'], continuous=True))
        rows.append(dict(id=sid, name=name, origin=origin, file=filename, source_rate=rate,
            selection_note=(overrides[name]['note'] if name in overrides else
                'Original digitized recording from licensed data.' if original['pcm'] is not None else
                'Complete supplied OPL input; this does not undo any earlier trimming or quantization.'),
            source_bytes=len(raw), source_sha256=sha(raw), original_adlib_sha256=identity['adlib_sha256'],
            sample_sha256=sha(proposed), bytes_with_terminator=len(payload), zero_bytes_replaced=raw.count(0),
            source_seconds=len(raw)/rate, duration_samples_preserved=len(raw)==len(proposed),
            one_shot_table_bytes=size, descriptor_level=old['level'], priority=existing['priority'],
            current_bytes=len(stored), current_sha256=sha(stored),
            current_in_floor_inventory=sid in descriptors,
            proposed_stream_frequency=fc, proposed_doc_rate=model_rate,
            proposed_doc_read_step=model_rate/DOC_RATE,
            rate_error_percent=100*(model_rate/rate-1),
            comparison_wavs={p.name:sha(p.read_bytes()) for p in sorted(folder.glob('*.wav'))}))
    demands = [demand(rows, floor, floors['ranges'], recipe['stream_analysis']) for floor in floors['floors']]
    report = dict(format=1, kind='source-preserving-effects-preparation', profile=game.profile.key,
        tool_sources={name:sha((ROOT/'tools'/name).read_bytes()) for name in
                      ('prepare_effects.py','effect_sources.py','dos_data.py','game_profile.py','audio_package.py')},
        recipe_sha256=sha(args.recipe.read_bytes()), input_levels_sha256=sha(args.levels.read_bytes()),
        current_manifest_sha256=sha((current/'manifest.json').read_bytes()),
        current_floor_manifest_sha256=sha((current/'effects-floors.json').read_bytes()),
        current_levels_policy=levels['policy'],
        source_files=current_manifest['source_hashes'], effects=rows, floors=demands,
        summary=dict(effects=len(rows), origins=dict(Counter(r['origin'] for r in rows)),
            sample_bytes=sum(r['source_bytes'] for r in rows),
            largest_sample_bytes=max(r['source_bytes'] for r in rows),
            max_floor_ram_bytes=max(f['proposed_ram_bytes'] for f in demands),
            floors_exceeding_existing_ram=sum(bool(f['existing_region_unplaced']) for f in demands),
            effects_exceeding_doc_partition=sum(r['one_shot_table_bytes']>16384 for r in rows),
            max_two_voice_stream_bytes_per_second=max(f['worst_two_voice_upload_bytes_per_second'] for f in demands)),
        preview=dict(kind='host DOC address/hold model; NOT native capture',
            proposed_playback='ideal continuous stream; refill behavior is not implemented',
            effect_oscillators=4, effect_voices=2, system_volume=15, sound_volume=15,
            current_levels='unchanged descriptors', pair_scale=PAIR_SCALE, normalization=False,
            fitted_playback_gain=False, wav_rates_rounded_to_integer=True,
            analog_filter_modeled=False, native_effects_model_validated=False),
        engine_changes_required=['Full-length storage and per-floor RAM/art layout',
            'Streaming/chunk descriptors for samples beyond one-shot and 16-bit length limits',
            'DOC cache/pin plan retaining music partition and oscillator ownership',
            'Seamless refill, priorities, preemption and stereo handling under actual IRQ load',
            'Updated checks that currently enforce peak normalization and 4096-byte effects'],
        images_created=False, music_or_engine_changed=False, native_performance_verified=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    write_toml(out/'effects-prepared.toml', dict(format=1, kind='effects-preparation-only',
        profile=game.profile.key, effects=[{k:r[k] for k in ('id','name','file','sample_sha256','source_rate',
            'source_bytes','original_adlib_sha256','descriptor_level','priority','selection_note')} for r in rows]),
        '# Complete sample inputs. This is not an engine-compatible effects pack.')
    (out/'recipe.toml').write_bytes(args.recipe.read_bytes())
    (out/'comparison-notes.txt').write_text(
        'raw-source.wav: original unsigned PCM, no normalization.\n'
        'proposed-source.wav: same bytes except DOC-reserved zero becomes one.\n'
        'current-stored-pcm.wav: current converted sample, without terminator; not native playback.\n'
        'current-doc-model.wav: current frequency/size/level through the host DOC model.\n'
        'proposed-doc-model.wav: full candidate at the same fixed output scale and descriptor level; ideal seamless streaming.\n'
        'Models retain their fixed output amplitudes. They are not recordings from the game and omit its analog filter.\n'
        'Native capture and performance acceptance are required before any engine integration.\n')
    return report['summary']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, default=ROOT/'profiles/audio/effects-source-preserving.toml')
    parser.add_argument('--profile', default='wolf3d')
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--preserved', type=Path, required=True, help='complete hash-pinned OPL source folder with samples.toml')
    parser.add_argument('--current-sound', type=Path, required=True, help='frozen current build/sound folder')
    parser.add_argument('--levels', type=Path, required=True, help='that build\'s data/sound/levels.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args),indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2,str(error)+'\n')


if __name__ == '__main__':
    main()
