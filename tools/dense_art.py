"""Exact floor-local packing when the shared sprite groups exceed available RAM.

The renderer still reads ordinary lit runs and bank-local column commands.
Only floor loading changes: these exceptional floors store their packed bytes.
"""
import functools
import hashlib
import json
from pathlib import Path
import struct

import memmap
from probe_art_overlap import aligned_offsets, overlap_strings
from registered_art import Bank
from shared_cache import atomic, folder, locked


def counter(length):
    """Population count, including the Python 3.9 source-build host."""
    if hasattr(int, 'bit_count'):
        return int.bit_count
    size = (length + 31) // 32 * 4
    one = int.from_bytes(b'\x55' * size, 'little')
    two = int.from_bytes(b'\x33' * size, 'little')
    four = int.from_bytes(b'\x0f' * size, 'little')
    words = int.from_bytes(b'\xff\0\0\0' * (size // 4), 'little')
    def count(value):
        value -= (value >> 1) & one
        value = (value & two) + ((value >> 2) & two)
        value = (value + (value >> 4)) & four
        return (((value * 0x01010101) >> 24) & words) % 0xffffffff
    return count


def build_banks(groups):
    """Cluster related frame/light runs, then verify each exact packed bank.

    Shared byte windows guide the clustering. Its relaxed estimate allows
    for overlaps recovered by the final pack; oversized banks shed their
    last frame until all its reads fit with the scaler's 128-byte bias.
    """
    pieces = set().union(*groups.values())
    blob, _ = overlap_strings(pieces, alignment=2)
    where = aligned_offsets(blob, pieces, 2)
    flags = {raw: ((1 << len(raw)) - 1) << at for raw, at in where.items()}
    bits = {key: functools.reduce(int.__or__, (flags[raw] for raw in values), 0)
            for key, values in groups.items()}
    count = counter(len(blob))
    sizes = {key: count(value) for key, value in bits.items()}
    remaining, banks = set(groups), []
    while remaining:
        key = max(remaining, key=lambda k: (sizes[k], k))
        remaining.remove(key)
        used, size, members = bits[key], sizes[key], [key]
        while remaining:
            choices = []
            for key in remaining:
                combined = used | bits[key]
                cost = count(combined) - size
                if size + cost <= 74000:
                    choices.append((cost / max(1, sizes[key]), cost, key, combined))
            if not choices:
                break
            _, cost, key, used = min(choices)
            members.append(key)
            remaining.remove(key)
            size += cost
        bank = Bank()
        while True:
            bank.groups = list(members)
            bank.pieces = set().union(*(groups[key] for key in members))
            bank.compact()
            if bank.size <= bank.capacity:
                break
            if len(members) == 1:
                raise ValueError(f'frame {members[0]} exceeds a sprite source bank')
            remaining.add(members.pop())
        banks.append(bank)
    return banks


def frame_banks(groups):
    """Cache the expensive, palette-dependent clustering by all source bytes."""
    from wolfdata import ROOT
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(Path(__file__).with_name('probe_art_overlap.py').read_bytes())
    for key, values in sorted(groups.items()):
        digest.update(struct.pack('<2I', *key))
        for raw in sorted(values):
            digest.update(struct.pack('<I', len(raw)) + raw)
    cache = (folder() or ROOT/'build/cache')/'v1/dense-art'
    path = cache/(digest.hexdigest() + '.json')
    with locked(path.with_suffix('.lock')):
        if path.exists():
            banks = []
            for keys, encoded in json.loads(path.read_text()):
                bank = Bank(groups=[tuple(key) for key in keys], blob=bytes.fromhex(encoded))
                bank.size = len(bank.blob)
                banks.append(bank)
        else:
            banks = build_banks(groups)
            atomic(path, json.dumps([[b.groups, b.blob.hex()] for b in banks]).encode())
    assert sorted(key for bank in banks for key in bank.groups) == sorted(groups)
    for bank in banks:
        assert len(bank.blob) <= bank.capacity
        assert all(bank.blob.find(raw) >= 0 for key in bank.groups for raw in groups[key])
    return banks


def extra_ranges(floor):
    """Unused table tails and effect-bank bytes, after the art generator ends."""
    from fixed_art import split
    from wolfdata import ROOT
    import os
    sound = Path(os.environ.get('WOLF_FLOOR_EFFECTS', ROOT/'build/sound'))
    effects = json.loads((sound/f'effects-floor-{floor:02}-loads.json').read_text())
    # Keep sector padding as well as every sample and descriptor. A load at
    # FIXED_GEN itself would be mistaken for a new generator by GenHook.
    occupied = [(r['address'], r['address'] + ((r['bytes'] + 511) & ~511)) for r in effects]
    occupied.append((memmap.FIXED_GEN, memmap.FIXED_GEN + 2))
    free = split([(memmap.SFX_BASE, memmap.GRAY_CODE)], occupied)[0]
    return memmap.compact_art_tails() + memmap.midpoint_art_ranges() + free


def load_records(records):
    """Coalesce scattered midpoint padding without changing any used entry.

    The table is immutable after boot. Loading its exact existing entries
    beside the new commands avoids hundreds of tiny floor-load records.
    The art manifest retains only the padding, for the live-span checker.
    """
    from wolfdata import ROOT
    begin, end = memmap.RAY_MIDPOINT, memmap.RAY_MIDPOINT_END
    padding = [(a, raw) for a, raw in records if begin <= a < end]
    if not padding:
        return records
    from viewgeometry import midpoint_table
    table = bytearray(midpoint_table())
    assert len(table) == end - begin
    holes = memmap.midpoint_art_ranges()
    for address, raw in padding:
        assert any(lo <= address and address + len(raw) <= hi for lo, hi in holes)
        table[address-begin:address-begin+len(raw)] = raw
    result = [(a, raw) for a, raw in records if not begin <= a < end]
    for offset in range(0, len(table), 65536):
        result.append((begin + offset, bytes(table[offset:offset+65536])))
    return result
