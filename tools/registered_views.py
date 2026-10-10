"""Build cold view-specific data with the same native hot-path formats.

The selected perspective weights and literal weapon routines are loaded when
the view or floor changes. Unselected copies occupy disk space only.
"""
import memmap
from collections import defaultdict
import json
import math
import struct

from wolfdata import ROOT, PROFILE
from viewgeometry import SIZES

ASSETS = ROOT / 'build/assets'
WEIGHTS = memmap.WEIGHTS
WEIGHTS_END = memmap.WEIGHTS_SPARE
WEIGHT_DIRECTORY = memmap.WEIGHT_DIRECTORY
WEAPON_ENTRIES = memmap.WEAPON_ENTRIES
WEAPON_REGIONS = ((memmap.WEAPON_DRAWERS_1, memmap.HORIZONTAL), (memmap.WEAPON_DRAWERS_2, memmap.WALL_LIGHT_POINTERS))


def write_segment(folder, name, address, data):
    path = folder / name
    path.write_bytes(data)
    return dict(file=str(path.relative_to(ROOT)), address=address, bytes=len(data))


def weights():
    """Identical byte weights and indexed directories, packed independently."""
    manifest = []
    all_values = []
    for vi, view in enumerate(SIZES):
        raw = bytearray()
        cache = {}
        offsets = [round(math.atan(((view - 1) / 2 - col) / (view / 2) *
                                   (65536 / (2 * (0x5700 + 0x5800)))) * 1024 / math.tau)
                   for col in range(view)]

        def allocate(data):
            data = bytes(data)
            if data not in cache:
                raw.extend(bytes(-len(raw) % 512))
                cache[data] = (WEIGHTS + len(raw)) >> 8
                raw.extend(data)
            return cache[data]

        directories = []
        for mode, length in enumerate((0, 4, 8)):
            values = []
            for col in range(view):
                step = col & -col
                left, right = (((col - step, col + step) if 0 < step <= 8 else (-1, -1))
                               if not length else ((col // length) * length, (col // length + 1) * length))
                if left < 0 or right >= view or col == left:
                    values.append(0)
                    continue
                data = bytearray()
                if length:
                    center = (left + right) // 2
                    pattern = tuple(v - offsets[center] for v in offsets[left:right + 1])
                    for angle in range(0, 512, 4):
                        slopes = [-math.tan((angle + d) * math.tau / 1024) for d in pattern]
                        denominator = slopes[-1] - slopes[0]
                        data.append(0)
                        for j in range(length - 1, 0, -1):
                            w = round(256 * (slopes[j] - slopes[0]) / denominator) if denominator else 128
                            data.append(max(1, min(255, w)))
                else:
                    pair = offsets[left] - offsets[col], offsets[col] - offsets[right]
                    for angle in range(512):
                        slopes = [-math.tan((angle + d) * math.tau / 1024) for d in (pair[0], 0, -pair[1])]
                        denominator = slopes[2] - slopes[0]
                        w = round(256 * (slopes[1] - slopes[0]) / denominator) if denominator else 128
                        data.append(max(1, min(255, w)))
                values.append(allocate(data))
            directories.append(values)
        raw.append(0)  # native word lookup of the final byte
        if WEIGHTS + len(raw) > WEIGHTS_END:
            raise ValueError(f'view {vi} weights require {len(raw)} bytes')
        # The original four-view directory uses three groups of four pointers.
        # All four now name the active view's three resident arrays.
        pointers = [WEIGHT_DIRECTORY + 24 + mode * view * 2 for mode in range(3) for _ in SIZES]
        directory = struct.pack('<12H', *[v & 65535 for v in pointers])
        directory += b''.join(struct.pack('<%dH' % view, *v) for v in directories)
        folder = ASSETS / 'views' / str(vi)
        folder.mkdir(parents=True, exist_ok=True)
        rows = [write_segment(folder, 'weights.bin', WEIGHTS, raw),
                write_segment(folder, 'directory.bin', WEIGHT_DIRECTORY, directory)]
        manifest.append(rows)
        all_values.append(dict(view=view, bytes=len(raw), rows=len(cache)))
    (ASSETS / 'view-weight-loads.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # gen_ray_height includes an initial directory; startup loads replace it
    # together with the chosen view before casting.
    (ASSETS / 'ray-weight-views.bin').write_bytes((ASSETS / 'views/1/directory.bin').read_bytes())
    print('active-view weights:', all_values)


def literal_weapon(pixels, colors):
    words, singles = defaultdict(list), defaultdict(list)
    pixels = dict(pixels)
    while pixels:
        address = min(pixels)
        first = pixels.pop(address)
        if address % 160 != 159 and address + 1 in pixels:
            second = pixels.pop(address + 1)
            words[colors[first] | colors[second] << 8].append(address)
        else:
            singles[colors[first]].append(address)
    code = bytearray()
    for groups, byte in ((words, False), (singles, True)):
        if byte and groups:
            code.extend((0xe2, 0x20))
        for value, addresses in sorted(groups.items()):
            code.append(0xa9)
            code.extend(struct.pack('<H', value)[:1 if byte else 2])
            for address in addresses:
                code.extend((0x8d,))
                code.extend(struct.pack('<H', 0x2000 + address))
        if byte and groups:
            code.extend((0xc2, 0x20))
    code.append(0x6b)
    return bytes(code)


def weapons():
    """Weapon drawers compiled at load (weapon_units.py, src/iigs/weapon_comp.s).

    view-weapon-loads.json keeps the resident result for the checks: the
    compiler model's code and entry table for each floor and view.
    view-weapon-units.json lists what a view group loads: the shared index
    image, the floor's light table, the compiler and the view's mask unit
    (the compiler builds the 20 pose lists from it).
    """
    import weapon_units
    units_folder = weapon_units.write_units()
    image = (units_folder / 'widx.bin').read_bytes()
    rel = lambda path: str(path.relative_to(ROOT))
    report = []
    for floor in range(PROFILE.floors):
        table_path = ROOT / f'build/levels/{floor}/weapon-table.bin'
        colors = weapon_units.colors_of(image, table_path.read_bytes())
        views, groups = [], []
        for vi in range(4):
            poses = [units_folder / f'pose-{vi}-{pose:02}.bin' for pose in range(20)]
            code, entries = weapon_units.compile_view([p.read_bytes() for p in poses], colors)
            folder = ROOT / f'build/levels/{floor}/views/{vi}'
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob('weapon-*.bin'):
                old.unlink()
            rows = [write_segment(folder, 'weapon-entries.bin', WEAPON_ENTRIES, entries)]
            for start, end in WEAPON_REGIONS:
                blob = bytearray()
                for address in sorted(a for a in code if start <= a < end):
                    assert start + len(blob) == address
                    blob += code[address]
                if blob:
                    rows.append(write_segment(folder, f'weapon-{start:06x}.bin', start, bytes(blob)))
            views.append(rows)
            order = [dict(file=rel(units_folder / 'widx.bin'), address=weapon_units.WIDX),
                     dict(file=rel(table_path), address=weapon_units.WTAB),
                     dict(file='build/boot/weapon_comp.raw', address=weapon_units.WCOMP)]
            order.append(dict(file=rel(units_folder / f'mask-{vi}.bin'), address=weapon_units.WMASK))
            groups.append([dict(row, sequence=n, raw=True) for n, row in enumerate(order)])
            report.append(dict(floor=floor, view=vi, code_bytes=sum(map(len, code.values())), programs=20))
        (ROOT / f'build/levels/{floor}/view-weapon-loads.json').write_text(json.dumps(views, indent=2) + '\n')
        (ROOT / f'build/levels/{floor}/view-weapon-units.json').write_text(json.dumps(groups, indent=2) + '\n')
    (ASSETS / 'weapon-drawer-loads.json').write_text('[]\n')
    (ASSETS / 'registered-weapons.json').write_text(json.dumps(report, indent=2) + '\n')
    (ROOT / 'build/gen/weapon_drawers.inc').write_text(
        f'weaponDrawerEntries .equ 0x{WEAPON_ENTRIES:06x}\n'
        ' .section paintsetup, text, root\npatchWeaponPalette: rtl\n')
    print('registered literal weapons:', max(r['code_bytes'] for r in report), 'peak selected-view bytes')
