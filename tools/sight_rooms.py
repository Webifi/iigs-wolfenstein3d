"""Room-pair sight proofs: the compact replacement for whole-bank line proofs.

The engine's tables keep their format (line_proofs.inc): at META_BANK:0000 a
4096-entry row-address table, then byte offsets and bit masks per cell. Here a
"number" is a room, not a cell: neighbouring cells with similar proof rows are
merged into at most DEFAULT_ROOMS rooms (grow_rooms.py; a floor with fewer open
cells keeps one room per cell, so its proofs are exact). Room bit (i, j) is set
only when every cell pair across rooms i and j is proven blocked by
line_proofs.blocked_rows, so every set bit is still a valid proof.

Per floor files in build/levels/N/:
  sight-rooms.bin   u16 room number per cell (0: not an open cell)   -> generator
  sight-matrix.bin  (rooms + 1) rows of stride bytes, plus one spare byte (expected RAM)
  sight-lower.bin   the same with only bits j <= i of row i: the stored unit. The matrix is
                    symmetric; the generator (fixed_gen.s stepMatrix) copies the rest.
  sight-meta.bin    the 32 KB tables (expected RAM, for checks and the boot floor)
"""
import hashlib
import json
import struct

from line_proofs import geometry, blocked_rows, SIGNATURE, DESCRIPTOR
from line_regions import partition

META_BANK = 0x32
META_BYTES = 32768
VERSION = 3
DEFAULT_ROOMS = 700                     # a 700-room matrix (61.7 KB) fits one bank
NEAR = 12


def rooms(raw, target, proofs=None):
    saved = proofs.get(raw) if proofs is not None else None
    if saved is None:
        cells, bars = geometry(raw)
        matrix = [int.from_bytes(r, 'little') for r in blocked_rows(cells, bars)] if bars else []
        if proofs is not None:
            proofs[raw] = cells, bars, matrix
    else:
        cells, bars, matrix = saved
    if not bars:
        return None
    from grow_rooms import cluster_many
    num = {x * 64 + y: i + 1 for i, (x, y) in enumerate(cells)}
    key = ('rooms', raw)
    choices = proofs.get(key, {}) if proofs is not None else {}
    if target not in choices:
        caps = {target}
        if proofs is not None:
            caps.update((700, 500, 350, 250))
        choices.update(cluster_many(cells, num, matrix, caps, near=NEAR))
        if proofs is not None:
            proofs[key] = choices
    room = choices[target]
    room = space_order(room)
    members = {}
    for cell, k in room.items():
        members.setdefault(k, []).append(cell)
    n = len(members)
    assert sorted(members) == list(range(1, n + 1))
    masks = {k: sum(1 << num[c] for c in cs) for k, cs in members.items()}
    both = {}
    for k, cs in members.items():
        acc = -1
        for c in cs:
            acc &= matrix[num[c]]
        both[k] = acc
    stride = (n + 8) // 8                     # bits 0..n; bit 0 is unused
    rows = [bytes(stride)]
    for i in range(1, n + 1):
        bits = 0
        for j in range(1, n + 1):
            if both[i] & masks[j] == masks[j]:
                bits |= 1 << j
        rows.append(bits.to_bytes(stride, 'little'))
    ids = bytearray(8192)
    for cell, k in room.items():
        struct.pack_into('<H', ids, 2 * cell, k)
    return dict(rooms=n, stride=stride, ids=bytes(ids), matrix=b''.join(rows) + b'\0')


def hilbert(x, y, n=64):
    """The distance of tile (x, y) along a Hilbert curve over the 64 x 64 map."""
    d, s = 0, n // 2
    while s:
        rx, ry = int(bool(x & s)), int(bool(y & s))
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        s //= 2
    return d


def space_order(room):
    """Number the rooms along a Hilbert curve through their centres: rooms near each
    other get near numbers, so the matrix rows pack 23% smaller (measured on all 60
    floors). The proofs do not change."""
    groups = {}
    for cell, k in room.items():
        groups.setdefault(k, []).append(cell)
    def centre(cs):
        return sum(c // 64 for c in cs) // len(cs), sum(c % 64 for c in cs) // len(cs)
    order = sorted(groups, key=lambda k: (hilbert(*centre(groups[k])), k))
    number = {k: i + 1 for i, k in enumerate(order)}
    return {cell: number[k] for cell, k in room.items()}


def prepare(root, floor, cap=DEFAULT_ROOMS, proofs=None):
    """Room data for a floor, cached by the map planes."""
    folder = root / f'build/levels/{floor}'
    raw = (folder / 'source-planes.bin').read_bytes()
    identity = hashlib.sha256(bytes([VERSION]) + cap.to_bytes(2, 'little') + raw).hexdigest()
    manifest = folder / 'sight.json'
    old = json.loads(manifest.read_text()) if manifest.is_file() else {}
    if old.get('identity') == identity:
        write_lower(folder, old)
        return old
    data = rooms(raw, cap, proofs)
    report = dict(identity=identity, cap=cap, enabled=data is not None)
    if data:
        (folder / 'sight-rooms.bin').write_bytes(data['ids'])
        (folder / 'sight-matrix.bin').write_bytes(data['matrix'])
        report.update(rooms=data['rooms'], stride=data['stride'], matrix_bytes=len(data['matrix']))
    manifest.write_text(json.dumps(report, indent=2) + '\n')
    write_lower(folder, report)
    return report


def write_lower(folder, report):
    """sight-lower.bin from sight-matrix.bin; the matrix must be symmetric."""
    if not report['enabled']:
        return
    target = folder / 'sight-lower.bin'
    if target.is_file() and target.stat().st_mtime >= (folder / 'sight-matrix.bin').stat().st_mtime:
        return
    matrix = (folder / 'sight-matrix.bin').read_bytes()
    n, stride = report['rooms'], report['stride']
    full = [int.from_bytes(matrix[i * stride:(i + 1) * stride], 'little') for i in range(n + 1)]
    lower = [v & ((2 << i) - 1) for i, v in enumerate(full)]
    column = [0] * (n + 1)
    for i, v in enumerate(lower):
        while v:
            j = (v & -v).bit_length() - 1
            column[j] |= 1 << i
            v &= v - 1
    assert all(full[i] == lower[i] | column[i] for i in range(n + 1)), f'{folder.name}: sight matrix is not symmetric'
    target.write_bytes(b''.join(v.to_bytes(stride, 'little') for v in lower) + matrix[(n + 1) * stride:])


def meta(ids, rows_at, stride):
    """The engine tables for rooms whose rows start at rows_at (24-bit)."""
    directory, offsets, masks = [rows_at] * 4096, [0] * 4096, [0] * 4096
    for cell in range(4096):
        k = struct.unpack_from('<H', ids, 2 * cell)[0]
        if k:
            directory[cell] = rows_at + k * stride
            offsets[cell] = k // 8
            masks[cell] = 1 << (k & 7)
    data = struct.pack('<4096I8192H', *(directory + offsets + masks))
    assert len(data) == META_BYTES
    return data


def enable(folder, enabled):
    """Write the sight descriptor into the floor's logic image."""
    image = bytearray((folder / 'logic.bin').read_bytes())
    struct.pack_into('<HH', image, DESCRIPTOR, META_BANK if enabled else 0, SIGNATURE if enabled else 0)
    (folder / 'logic.bin').write_bytes(image)


def prepare_all(root, floors, initial_floor):
    """Enable room sight on floors whose fixed layout placed it (fixed.json)."""
    reports = []
    for floor in range(floors):
        folder = root / f'build/levels/{floor}'
        fixed = folder / 'fixed.json'
        enabled = fixed.is_file() and json.loads(fixed.read_text()).get('sight_rows') is not None
        enable(folder, enabled)
        reports.append(dict(floor=floor, enabled=enabled))
    # The initial floor also has a directly loaded logic image.
    image = bytearray((root / 'build/assets/logic.bin').read_bytes())
    descriptor = (root / f'build/levels/{initial_floor}/logic.bin').read_bytes()[DESCRIPTOR:DESCRIPTOR + 4]
    image[DESCRIPTOR:DESCRIPTOR + 4] = descriptor
    (root / 'build/assets/logic.bin').write_bytes(image)
    (root / 'build/sight.json').write_text(json.dumps(reports, indent=2) + '\n')
    return reports
