"""Describe complete source effects without choosing native addresses or packing."""
import argparse
import json
import os
from pathlib import Path
import struct

from audio_package import checked, contained, sha
from game_profile import PROFILE_DIR, fields, integer, read_toml


def selected_samples(game):
    edition = 'spear' if game.spear else game.key
    return Path(os.environ.get('WOLF_EFFECT_SAMPLES') or
                Path(__file__).resolve().parents[1] / 'audio-source' / edition / 'effects/ym3812')


def source_effects(source, catalog_path=None):
    """Return original AdLib contours and optional digitized replacements by ID."""
    game = source.profile
    catalog_path = catalog_path or PROFILE_DIR/'audio'/('effects-spear.toml' if game.spear else 'effects-wolf3d.toml')
    catalog = read_toml(catalog_path)
    fields(catalog, ('format', 'source_rate', 'effect'), 'effect catalog')
    integer(catalog['format'], 1, 1, 'effect catalog format')
    integer(catalog['source_rate'], 1, 192000, 'digitized source rate')
    rows = catalog['effect']
    for row in rows:
        integer(row['id'], 0, game.sounds-1, 'effect ID')
        if not isinstance(row.get('digitized_only', False), bool):
            raise ValueError('digitized_only must be boolean')
    if sorted(r['id'] for r in rows) != list(range(game.sounds)):
        raise ValueError('effect catalog must cover each source sound ID exactly once')
    chunks = source.audio()
    pages, _, start = source.vswap()
    if len(pages[-1]) % 4:
        raise ValueError('invalid digitized sound directory')
    directory = list(struct.iter_unpack('<HH', pages[-1]))
    result = []
    key = 'digitized_shareware' if game.public_game_data else 'digitized'
    for row in sorted(rows, key=lambda r:r['id']):
        ident, name = row['id'], row['name']
        raw = chunks[game.sounds+ident]
        if len(raw) < 23:
            raise ValueError('truncated AdLib effect: '+name)
        length, priority = struct.unpack_from('<IH', raw)
        if 23+length > len(raw):
            raise ValueError('truncated AdLib contour: '+name)
        digi = row[key]
        integer(digi, -1, 65535, 'digitized replacement')
        pcm = None
        if digi >= 0:
            if digi >= len(directory):
                raise ValueError('missing digitized directory entry: '+name)
            first, size = directory[digi]
            stop = start+first+(size+4095)//4096
            # The final page is directory data, never sample audio.
            if not size or stop > len(pages)-1:
                raise ValueError('digitized effect extends outside sample pages: '+name)
            span = pages[start+first:stop]
            pcm = b''.join(span)
            if any(not p for p in span) or len(pcm) < size:
                raise ValueError('missing digitized sample bytes: '+name)
            pcm = pcm[:size]
        result.append(dict(id=ident, name=name, priority=priority, adlib=raw,
                           digitized=digi, pcm=pcm, source_rate=catalog['source_rate']))
    return result


def manifest(source, preserved=None, catalog_path=None):
    """Verify every source ID and optionally every preserved AdLib sample.

    Digitized bytes remain in the supplied VSWAP. Their DOC-safe identity applies
    the existing zero-to-one substitution; it does not trim or resample them.
    This describes inputs only: build_sound subsequently invokes the legacy
    reducer, which trims, resamples, caps duration and peak-normalizes samples.
    """
    effects = source_effects(source, catalog_path)
    samples = {}
    if preserved is not None:
        preserved = Path(preserved)
        doc = read_toml(preserved/'samples.toml')
        integer(doc['format'], 1, 1, 'preserved effects format')
        for row in doc['samples']:
            ident = row['id']
            integer(ident, 0, source.profile.sounds-1, 'preserved effect ID')
            if ident in samples:
                raise ValueError('duplicate preserved effect ID: '+str(ident))
            samples[ident] = row
        required = {e['id'] for e in effects if e['pcm'] is None}
        if set(samples) != required:
            raise ValueError('preserved AdLib coverage differs: missing %s; unexpected %s' %
                             (sorted(required-set(samples)), sorted(set(samples)-required)))
    rows = []
    for effect in effects:
        ident, pcm = effect['id'], effect['pcm']
        row = dict(id=ident, name=effect['name'], priority=effect['priority'],
                   adlib_sha256=sha(effect['adlib']), digitized_id=effect['digitized'])
        if pcm is not None:
            payload = bytes(max(1, v) for v in pcm)
            row.update(kind='dos-digitized', source_sha256=sha(pcm),
                       payload_sha256=sha(payload), payload_bytes=len(payload),
                       source_rate=effect['source_rate'], zero_bytes_replaced=pcm.count(0))
        else:
            row.update(kind='preserved-ym3812', source_rate=7042.65625)
            if preserved is not None:
                sample = samples[ident]
                if sample['original_sha256'] != row['adlib_sha256']:
                    raise ValueError('preserved AdLib source differs: '+effect['name'])
                payload = checked(contained(preserved, sample['file']), sample['sha256'])
                if not payload or 0 in payload:
                    raise ValueError('preserved effect must have nonempty, zero-free PCM: '+effect['name'])
                row.update(file=sample['file'], payload_sha256=sha(payload), payload_bytes=len(payload))
        rows.append(row)
    return dict(format=1, profile=source.profile.key, effects=rows,
                source_effects_verified=True, preserved_effects_verified=preserved is not None,
                native_bank_assembled=False, native_allocation_verified=False,
                note='Source samples before native layout, termination, layering or fitting. No sound RAM or oscillator allocation is assigned.')


def main():
    from dos_data import DosData
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='shareware')
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--shared-data', type=Path)
    parser.add_argument('--catalog', type=Path, help='editable effect names and digitized replacements')
    package = parser.add_mutually_exclusive_group()
    package.add_argument('--preserved', type=Path, help='effects/ym3812 folder from the intermediate package')
    package.add_argument('--package', type=Path, help='complete music intermediate to validate and extend with effects')
    parser.add_argument('--export-samples', type=Path, help='rendered AdLib .u8 files to preserve in --package')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    source = DosData(args.data, args.profile, args.shared_data)
    if args.export_samples and not args.package:
        parser.error('--export-samples requires --package')
    if args.package:
        from audio_package import validate_dos
        validate_dos(args.package, source.profile, args.data, args.shared_data, source=source)
        if args.export_samples:
            from audio_intermediate import export_effects
            export_effects(args.package, args.export_samples, source.profile, args.data, args.shared_data)
        args.preserved = args.package/'effects/ym3812'
    report = manifest(source, args.preserved, args.catalog)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('%s: %d effect sources verified; preserved samples %s' %
          (report['profile'], len(report['effects']), report['preserved_effects_verified']))


if __name__ == '__main__':
    main()
