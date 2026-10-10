"""Build conservative blocked-sight lookups in otherwise unused floor banks.

An entry is set only when a continuous, permanent wall separates every pair
of points in the two tile boxes. Doors and pushwall source tiles never prove
occlusion. The half-tile margin also covers the native line walk's fixed-point
rounding. Unknown pairs retain the normal CheckLine walk and its live doors.

Only wholly unused art banks are candidates. Every weapon view and the floor's
effect loads participate in allocation; a floor without room uses the original
walk. These files share the art's menu restore lifetime, not the music cache.
"""
import hashlib
import json
import struct
from pathlib import Path

SIGNATURE = 0xAB04
DESCRIPTOR = 0xFFFC
META_BYTES = 32768
BANKS = tuple(b for b in range(0x10, 0x30) if b != 0x1D) + (0x32,)
VERSION = 1


def geometry(raw):
    assert len(raw) == 8192
    solid = {(x, y) for x in range(64) for y in range(64)
             if 0 < raw[y*64+x] < 64 and raw[4096+y*64+x] != 98}
    cells = [(x, y) for x in range(64) for y in range(64) if (x, y) not in solid]
    bars = []
    for swap in (False, True):
        for wall in range(1, 63):
            start = None
            for v in range(65):
                occupied = ((v, wall) if swap else (wall, v)) in solid
                if occupied and start is None:
                    start = v
                if not occupied and start is not None:
                    if v-start >= 2:
                        bars.append((swap, wall, start, v))
                    start = None
    return cells, bars


def blocked_rows(cells, bars):
    import native_host
    if native_host.library():
        return native_host.blocked_rows(cells, bars)
    return blocked_rows_python(cells, bars)


def blocked_rows_python(cells, bars):
    """Integer interval version of the tile-box corner proof; no host packages."""
    masks = [0] * (len(cells)+1)
    for swap in (False, True):
        points = [(y, x) if swap else (x, y) for x, y in cells]
        columns = [[0]*65 for _ in range(64)]
        for number, (x, y) in enumerate(points, 1):
            columns[x][y+1] = 1 << number
        for prefix in columns:
            for y in range(1, 65):
                prefix[y] |= prefix[y-1]
        for orientation, wall, lo, hi in bars:
            if orientation != swap:
                continue
            right = [x for x in range(wall+1, 64) if columns[x][64]]
            for number, (ax, ay) in enumerate(points, 1):
                if ax >= wall:
                    continue
                near = (wall-ax)*256-255
                far = (wall+1-ax)*256
                lower = lo*256+128-ay*256
                upper = hi*256-128-ay*256-255
                result = masks[number]
                for bx in right:
                    dx = bx-ax
                    for low_den, high_den, minimum, maximum in (
                            (far, near, -ay, -1), (near, far, 0, 63-ay)):
                        first = max(minimum, -((-lower*dx)//low_den))
                        last = min(maximum, (upper*dx-1)//high_den)
                        if first <= last:
                            result |= columns[bx][ay+last+1] ^ columns[bx][ay+first]
                masks[number] = result
    # Each sweep proves left-to-right pairs. Visibility is symmetric, but keep
    # the native forward/reverse arithmetic checks as a separate acceptance test.
    forward = tuple(masks)
    for a, bits in enumerate(forward):
        while bits:
            low = bits & -bits
            masks[low.bit_length()-1] |= 1 << a
            bits ^= low
    stride = (len(masks)+7)//8
    return [mask.to_bytes(stride, 'little') for mask in masks]


def prepare(root, floor):
    folder = root/f'build/levels/{floor}'
    occupied = []
    sources = [folder/'source-planes.bin']
    for name, relative in ((folder/'registered-art-loads.json', folder),
                           (folder/'view-weapon-loads.json', root),
                           (root/f'build/sound/effects-floor-{floor:02}-loads.json', root/'build/sound')):
        sources.append(name)
        rows = json.loads(name.read_text())
        if rows and isinstance(rows[0], list):
            rows = sum(rows, [])
        for row in rows:
            path = Path(row['file'])
            path = path if path.is_absolute() else relative/path
            occupied.append((row['address'], row['address']+path.stat().st_size))
    free = [bank for bank in BANKS
            if not any(a < (bank+1)*65536 and bank*65536 < b for a, b in occupied)]
    raw = sources[0].read_bytes()
    cells, bars = geometry(raw)
    stride = (len(cells)+8)//8
    per_bank = 65535//stride  # spare byte for the native word load at the last bit byte
    required = (len(cells)+1+per_bank-1)//per_bank+1
    identity = hashlib.sha256(bytes([VERSION])+raw+json.dumps(occupied).encode()).hexdigest()
    manifest = folder/'line-proofs.json'
    previous = json.loads(manifest.read_text()) if manifest.is_file() else {}
    if previous.get('identity') == identity and all(
            (root/r['file']).is_file() and (root/r['file']).stat().st_size == r['bytes']
            for r in previous['loads']):
        report = previous
    else:
        report = dict(identity=identity, cells=len(cells), stride=stride, free_banks=free,
                      required_banks=required, enabled=False, loads=[], metadata_bank=0)
        if bars and len(free) >= required:
            matrix = blocked_rows(cells, bars)
            meta_bank = free[-1]
            locations = []
            loads = []
            for group, start in enumerate(range(0, len(matrix), per_bank)):
                bank = free[group]
                chunk = matrix[start:start+per_bank]
                locations.extend(bank*65536+i*stride for i in range(len(chunk)))
                path = folder/f'line-proofs-{group}.bin'
                data = b''.join(chunk)+b'\0'
                path.write_bytes(data)
                loads.append(dict(file=str(path.relative_to(root)), address=bank*65536, bytes=len(data)))
            directory = [locations[0]]*4096
            offsets = [0]*4096
            masks = [0]*4096
            for number, (x, y) in enumerate(cells, 1):
                cell = x*64+y
                directory[cell] = locations[number]
                offsets[cell] = number//8
                masks[cell] = 1 << (number & 7)
            data = struct.pack('<4096I8192H', *(directory+offsets+masks))
            assert len(data) == META_BYTES
            path = folder/'line-proofs-directory.bin'
            path.write_bytes(data)
            loads.append(dict(file=str(path.relative_to(root)), address=meta_bank*65536, bytes=len(data)))
            report.update(enabled=True, loads=loads, metadata_bank=meta_bank,
                          matrix_bytes=sum(len(row) for row in matrix),
                          proven_pairs=sum(sum(bin(byte).count('1') for byte in row) for row in matrix)//2)
        manifest.write_text(json.dumps(report, indent=2)+'\n')
    image = bytearray((folder/'logic.bin').read_bytes())
    struct.pack_into('<HH', image, DESCRIPTOR, report['metadata_bank'], SIGNATURE if report['enabled'] else 0)
    (folder/'logic.bin').write_bytes(image)
    return report


def prepare_all(root, floors, initial_floor):
    reports = [prepare(root, floor) for floor in range(floors)]
    # The initial floor also has a directly loaded logic image.
    image = bytearray((root/'build/assets/logic.bin').read_bytes())
    descriptor = (root/f'build/levels/{initial_floor}/logic.bin').read_bytes()[DESCRIPTOR:DESCRIPTOR+4]
    image[DESCRIPTOR:DESCRIPTOR+4] = descriptor
    (root/'build/assets/logic.bin').write_bytes(image)
    (root/'build/line-proofs.json').write_text(json.dumps(reports, indent=2)+'\n')
    return reports
