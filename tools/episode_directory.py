"""Disk directory layouts, both using 1024 bytes of resident loader scratch.

EP02 stores ten floors' records together. EP03 stores a root entry per floor
and one 512-byte record page per floor. Music keeps its directory at block 2.
All offsets and counts below are disk blocks, except EP02's byte offsets.
"""
import struct

import memmap

BLOCK = 512
MAX_FLOORS = 60
AUX_AT = 400
# Compact EP08 (AX03): the first ROOT_BLOCKS blocks are the root, which the boot
# also loads into RAM at $00:6E00 (src/iigs/leveldirectory.s rootLookup): the
# header and the floor index (block 0), the music directory (block 2) and the
# auxiliary index (AUX_TABLE: 3 bytes per group: the block of its list, then the
# list's byte offset in that block / 4, bit 7 set when the list continues into
# the next block). A floor's records and an auxiliary list (u16 count, u16 0,
# records) sit anywhere in the store, next to the units they load.
ROOT_BLOCKS = memmap.STORE_ROOT_BLOCKS
AUX_TABLE = 1536


def create(floors, auxiliary=0, record_pages=1, wide_blocks=False, fast_codecs=False, compact=False):
    if compact:
        if not (wide_blocks and record_pages == 2 and fast_codecs == 3) or not 1 <= auxiliary <= (ROOT_BLOCKS * BLOCK - AUX_TABLE) // 3:
            raise ValueError('compact directory: EP08 with wide blocks and at most 341 groups')
        data = bytearray(BLOCK * ROOT_BLOCKS)
        data[:8] = b'WOLFEP08'
        struct.pack_into('<4sHH', data, AUX_AT, b'AX03', AUX_TABLE, auxiliary)
        return data
    if not 1 <= floors <= MAX_FLOORS:
        raise ValueError('episode directory supports 1 through 60 floors')
    if not 0 <= auxiliary <= 4096:
        raise ValueError('auxiliary segment group count exceeds native index')
    if record_pages not in (1, 2):raise ValueError("directory records use one or two pages")
    indexed = floors != 10 or bool(auxiliary) or record_pages == 2
    data = bytearray(BLOCK * (3 + (floors + auxiliary) * record_pages if indexed else 3))
    if wide_blocks and record_pages != 2:
        raise ValueError('EP05 uses two record pages')
    if fast_codecs and not wide_blocks:raise ValueError('EP06 requires wide blocks')
    data[:8] = b'WOLFEP08' if fast_codecs == 3 else b'WOLFEP07' if fast_codecs == 2 else b'WOLFEP06' if fast_codecs else b'WOLFEP05' if wide_blocks else b'WOLFEP04' if record_pages == 2 else b'WOLFEP03' if indexed else b'WOLFEP02'
    if auxiliary:
        struct.pack_into('<4sHH', data, AUX_AT, b'AX02' if record_pages == 2 else b'AX01', 3 + floors * record_pages, auxiliary)
    return data


def finish_auxiliary(data, groups):
    """Independent load groups for selected-view and paused-interface data."""
    magic, first, count = struct.unpack_from('<4sHH', data, AUX_AT)
    pages = 2 if data[:8] in (b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') else 1
    if data[:8] not in (b'WOLFEP03', b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') or magic != (b'AX02' if pages == 2 else b'AX01') or count != len(groups):
        raise ValueError('auxiliary directory header differs from groups')
    if first < 3 or (first + count * pages) * BLOCK > len(data):
        raise ValueError('auxiliary directory outside store')
    for i, records in enumerate(groups):
        if not 1 <= len(records) <= pages * 64 - 1:
            raise ValueError('auxiliary group needs 1 through 63 load records')
        offset = (first + i * pages) * BLOCK
        struct.pack_into('<2H', data, offset, len(records), 0)
        for n, record in enumerate(records):
            struct.pack_into('<4H', data, offset + 4 + n * 8, *record)


def finish_compact(data, floors, groups, records_total):
    """floors: (block, count) of each floor's records; groups: (block, offset, pages)."""
    struct.pack_into('<HH', data, 8, len(floors), records_total)
    for floor, (block, count) in enumerate(floors):
        if not 1 <= count <= 128 or block < ROOT_BLOCKS:
            raise ValueError('invalid compact floor list')
        struct.pack_into('<3H', data, 12 + floor * 6, block, count, 0)
    magic, table, count = struct.unpack_from('<4sHH', data, AUX_AT)
    if magic != b'AX03' or count != len(groups):
        raise ValueError('compact auxiliary header differs from groups')
    for group, (block, offset, pages) in enumerate(groups):
        if block < ROOT_BLOCKS or offset % 4 or not 0 <= offset < BLOCK or pages not in (1, 2):
            raise ValueError('invalid compact auxiliary list')
        struct.pack_into('<HB', data, table + group * 3, block, offset // 4 | (0x80 if pages == 2 else 0))


def auxiliary_records(data, group, *, title=False):
    magic, first, count = struct.unpack_from('<4sHH', data, AUX_AT)
    if magic == b'AX03':
        if not 0 <= group < count:
            raise ValueError('invalid auxiliary group')
        block, place = struct.unpack_from('<HB', data, first + group * 3)
        offset = block * BLOCK + (place & 0x7f) * 4
        records, prefix = struct.unpack_from('<2H', data, offset)
        if not 1 <= records <= 127 or not 0 <= prefix < records or (place & 0x7f) * 4 + 4 + records * 8 > BLOCK * (2 if place & 0x80 else 1):
            raise ValueError('invalid auxiliary record count')
        return [struct.unpack_from('<4H', data, offset + 4 + n * 8) for n in range(0 if title else prefix,records)]
    pages = 2 if data[:8] in (b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') else 1
    if data[:8] not in (b'WOLFEP03', b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') or magic != (b'AX02' if pages == 2 else b'AX01') or not 0 <= group < count:
        raise ValueError('invalid auxiliary group')
    offset = (first + group * pages) * BLOCK
    if offset + BLOCK * pages > len(data):
        raise ValueError('auxiliary record page outside store')
    records, reserved = struct.unpack_from('<2H', data, offset)
    if not 1 <= records <= pages * 64 - 1 or reserved:
        raise ValueError('invalid auxiliary record count')
    return [struct.unpack_from('<4H', data, offset + 4 + n * 8) for n in range(records)]


def finish(data, offsets, counts, art_steps, records):
    floors = len(counts)
    if not (floors == len(offsets) == len(art_steps)):
        raise ValueError('floor directory column lengths differ')
    if any(not 0 <= step <= 255 for step in art_steps):
        raise ValueError('floor art step count exceeds a byte')
    pages = 2 if data[:8] in (b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') else 1
    if any(not 1 <= count <= pages * 64 for count in counts):
        raise ValueError('floor records exceed a directory page')
    if sum(counts) != len(records):
        raise ValueError('floor record total differs from directory')
    struct.pack_into('<HH', data, 8, floors, len(records))
    if data[:8] == b'WOLFEP02':
        if floors != 10 or 64 + len(records) * 8 > 1024:
            raise ValueError('episode directory exceeds two blocks')
        struct.pack_into('<20H', data, 12, *(offsets + counts))
        data[52:62] = bytes(art_steps)
        for n, row in enumerate(records):
            struct.pack_into('<4H', data, 64 + n * 8, *row)
    elif data[:8] in (b'WOLFEP03', b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08'):
        if not 1 <= floors <= MAX_FLOORS or len(data) < BLOCK * (3 + floors * pages):
            raise ValueError('invalid indexed floor directory')
        for floor, (offset, count, steps) in enumerate(zip(offsets, counts, art_steps)):
            if offset < 0 or offset % 8 or offset // 8 + count > len(records):
                raise ValueError('invalid floor record offset')
            page = 3 + floor * pages
            struct.pack_into('<3H', data, 12 + floor * 6, page, count, steps)
            for n in range(count):
                struct.pack_into('<4H', data, page * BLOCK + n * 8, *records[offset // 8 + n])
    else:
        raise ValueError('unknown episode directory')


def floor_records(data, floor):
    """Read one floor's directory, independently of payload decompression."""
    if len(data) < 1536 or data[:8] not in (b'WOLFEP02', b'WOLFEP03', b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08'):
        raise ValueError('invalid episode directory header')
    pages = 2 if data[:8] in (b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') else 1
    floors = struct.unpack_from('<H', data, 8)[0]
    if not 1 <= floors <= MAX_FLOORS or not 0 <= floor < floors:
        raise ValueError('floor outside episode directory')
    if data[:8] == b'WOLFEP02':
        if floors != 10:
            raise ValueError('invalid EP02 floor count')
        offset = 64 + struct.unpack_from('<H', data, 12 + floor * 2)[0]
        if offset % 8:
            raise ValueError('unaligned floor record offset')
        count = struct.unpack_from('<H', data, 32 + floor * 2)[0]
        steps = data[52 + floor]
        limit = 1024
    elif struct.unpack_from('<4s', data, AUX_AT)[0] == b'AX03':
        page, count, steps = struct.unpack_from('<3H', data, 12 + floor * 6)
        steps &= 255        # high byte counts the episode-disk records in a two-part floor load
        offset, limit = page * BLOCK, (page + pages) * BLOCK
    else:
        page, count, steps = struct.unpack_from('<3H', data, 12 + floor * 6)
        if not 3 <= page < 3 + floors * pages or (page - 3) % pages:
            raise ValueError('floor record page outside directory')
        offset, limit = page * BLOCK, (page + pages) * BLOCK
    if not count or count > pages * 64 or steps > 255 or offset + count * 8 > min(limit, len(data)):
        raise ValueError('floor records outside directory')
    return [struct.unpack_from('<4H', data, offset + n * 8) for n in range(count)], steps
