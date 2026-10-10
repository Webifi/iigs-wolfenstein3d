"""Measure exact substring/overlap sharing before changing the native atlas.

This is an unbanked storage estimate, not a bank-safe native packer. It reads source
frames named by an existing palette receipt, preserves every source index,
and never rewrites palettes or build assets. Sprite bank ownership, row bias,
command storage and bank padding still need a separate allocation proof.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from dos_data import DosData, sprite
from game_profile import profile


def aligned_offsets(blob, pieces, alignment):
    """First aligned occurrence of each string; equal widths share one scan."""
    pieces = set(pieces)
    if len(pieces) > 16 and len({len(raw) for raw in pieces}) == 1:
        size = len(next(iter(pieces)))
        result = {}
        for at in range(0, len(blob)-size+1, alignment):
            raw = blob[at:at+size]
            if raw in pieces:
                result[raw] = at
                pieces.remove(raw)
                if not pieces:
                    return result
        raise AssertionError('lost source string')
    result = {}
    for raw in pieces:
        at = blob.find(raw)
        while at >= 0 and at % alignment:
            at = blob.find(raw, at + 1)
        if at < 0:
            raise AssertionError('lost source string')
        result[raw] = at
    return result


def overlap_strings(pieces, alignment=1):
    """Return deterministic strings containing every input byte string exactly.

    Remove contained strings, then join disjoint paths by decreasing exact
    suffix/prefix length. The caller must still place each required window
    without crossing a native source bank.
    """
    unique = set(pieces) - {b''}
    assert alignment > 0 and all(len(raw) % alignment == 0 for raw in unique)
    lengths = sorted({len(s) for s in unique})
    contained = set()
    for raw in sorted(unique, key=lambda s: (-len(s), s)):
        if raw in contained:
            continue
        for size in lengths:
            if size >= len(raw):
                break
            for offset in range(0, len(raw) - size + 1, alignment):
                part = raw[offset:offset + size]
                if part in unique:
                    contained.add(part)
    strings = sorted(unique - contained)
    count = len(strings)
    before = [-1] * count
    after = [-1] * count
    shared = [0] * count
    parent = list(range(count))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for size in range(max(lengths, default=alignment) - alignment, 0, -alignment):
        prefixes = defaultdict(list)
        for i, raw in enumerate(strings):
            if before[i] == -1 and len(raw) > size:
                prefixes[raw[:size]].append(i)
        for i, raw in enumerate(strings):
            if after[i] != -1 or len(raw) <= size:
                continue
            options = prefixes.get(raw[-size:], ())
            for j in options:
                if before[j] == -1 and root(i) != root(j):
                    after[i], before[j], shared[i] = j, i, size
                    parent[root(i)] = root(j)
                    break
    paths = []
    for i in range(count):
        if before[i] != -1:
            continue
        value = bytearray(strings[i])
        while after[i] != -1:
            j = after[i]
            value.extend(strings[j][shared[i]:])
            i = j
        paths.append(bytes(value))
    packed = b''.join(paths)
    aligned_offsets(packed, unique, alignment)
    return packed, dict(unique_strings=len(unique), contained_strings=len(contained),
                       paths=len(paths), unique_bytes=sum(map(len, unique)),
                       packed_bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest())


def floor_parts(data, floor, receipt):
    pages, first_sprite, _ = data.vswap()
    level = data.maps()[floor]
    tiles = {t for t in level['planes'][0] if 0 < t < 64}
    if 21 in tiles:
        tiles.add(22)
    wall_pages = {p for t in tiles for p in (2 * (t - 1), 2 * (t - 1) + 1)}
    wall_pages.update(range(first_sprite - 8, first_sprite))
    walls = {bytes(pages[p][u:u + 64]) for p in wall_pages
             if len(pages[p]) == 4096 for u in range(0, 4096, 64)}
    groups = receipt['source_shapes']
    world = set(groups[0]) | set(groups[1])
    runs = {bytes(raw) for shape in world
            for column in sprite(pages[first_sprite + shape])['columns']
            for _, _, raw in column}
    return walls, runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--profile', default='wolf3d')
    parser.add_argument('--palettes', type=Path, required=True)
    parser.add_argument('--floors', type=int, nargs='+', required=True,
                        help='zero-based source floor indices')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mapped-lights', action='store_true',
                        help='also measure a different format sharing exact A/B byte strings across four lights')
    args = parser.parse_args()
    data = DosData(args.source, profile(args.profile))
    rows = []
    for floor in args.floors:
        receipt_path = args.palettes / f'{floor}.json'
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        walls, runs = floor_parts(data, floor, receipt)
        _, wall = overlap_strings(walls)
        _, sprites = overlap_strings(runs)
        row = dict(source_floor_index=floor,
                   palette_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                   walls=wall, sprites=sprites,
                   original_payload_per_light=2 * (wall['unique_bytes'] + sprites['unique_bytes']),
                   overlapping_payload_per_light=2 * (wall['packed_bytes'] + sprites['packed_bytes']))
        if args.mapped_lights:
            from build_colors import light_maps, CFG
            from wolfdata import palette
            from viewcolor import Metric
            wall_maps, sprite_maps = receipt['wall_lights'], receipt['sprite_lights']
            if len(wall_maps) == len(sprite_maps) == 3:
                intermediate = light_maps(palette(), [tuple(v // 17 for v in c) for c in receipt['palette']], Metric(CFG))
                wall_maps = [wall_maps[0], intermediate[0][1], *wall_maps[1:]]
                sprite_maps = [sprite_maps[0], intermediate[1][1], *sprite_maps[1:]]
            assert len(wall_maps) == len(sprite_maps) == 4
            lit = {b''.join(bytes(mapping[c]) for c in raw)
                   for raw in walls for mapping in wall_maps}
            lit.update(b''.join(bytes(mapping[c]) for c in raw)
                       for raw in runs for mapping in sprite_maps)
            _, row['mapped_all_lights'] = overlap_strings(lit, alignment=2)
        rows.append(row)
        print(json.dumps(row), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(
        method=__doc__, profile=args.profile, floors=rows,
        scope='Exact greedy overlap estimate; no optimality, bank, row-bias, pool, command or directory allocation proof.'), indent=2) + '\n')


if __name__ == '__main__':
    main()
