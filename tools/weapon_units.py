"""Weapon drawers compiled at load (src/iigs/weapon_comp.s) from shared units.

Today's weapon code (registered_views.literal_weapon) depends on the floor's
colours, so it was stored per floor and view (3 MB). Its inputs are:
- which screen bytes each pose writes and from which weapon-pixel offset, and
  how they pair into word stores: the same on every floor;
- the colour of weapon-pixel offset o: the floor's last sprite light table
  applied to the weapon's source index at o (registered_sprites.weapon_oracle).

Units (loaded raw into bank $1D, which the paused interface already uses;
raw loads need no stage, so the rest of the bank is the compiler's scratch):
  $1D:0000-$1D:3FFF  two sort buffers; $1D:4000 count table (scratch)
  WIDX   $1D:8000  11038 bytes: source index of every weapon-pixel offset (shared)
  WTAB   $1D:AC00  512 bytes: the floor's last sprite light table, A/B per index
  WPOSE  $1D:B000  one per pose, in order (shared per view):
                   u16 words, u16 singles, words x (u16 address, u16 o1, u16 o2),
                   singles x (u16 address, u16 o); addresses ascending
  WCOMP  $1D:F800  the compiler (shared); it loads before the first pose
The compiler writes each pose's code at the next free place in the two weapon
regions (pose order, first fit) and its entry in the 20-entry table.
"""
import memmap
import struct
import tempfile
from pathlib import Path

from wolfdata import ROOT

WIDX, WTAB, WPOSE, WCOMP = memmap.WEAPON_INDEX, memmap.WEAPON_LIGHTS, memmap.WEAPON_POSE, memmap.WEAPON_COMP
POSE_LIMIT = WCOMP - WPOSE
WMASK, MASK_LIMIT = memmap.WEAPON_MASK_UNIT, 0x1C00     # the view's compact mask, to $1D:7FFF
PIXELS_LIMIT = 0x2AA8                    # pixel records (4 bytes) per pose: $1D:0000 and $1D:2B00
ENTRIES = memmap.WEAPON_ENTRIES
REGIONS = ((memmap.WEAPON_DRAWERS_1, memmap.HORIZONTAL), (memmap.WEAPON_DRAWERS_2, memmap.WALL_LIGHT_POINTERS))


def index_image():
    """weapon_oracle with an identity colour table: byte o holds the source index."""
    from build_registered_sprites import weapon_oracle
    identity = [[c, c] for c in range(256)]
    with tempfile.TemporaryDirectory() as folder:
        weapon_oracle(Path(folder), dict(sprite_lights=[identity] * 4))
        return (Path(folder) / 'weapon-pixels-00.bin').read_bytes()


def pose_unit(pixels):
    words, singles = [], []
    pixels = dict(pixels)
    while pixels:
        address = min(pixels)
        first = pixels.pop(address)
        if address % 160 != 159 and address + 1 in pixels:
            words.append((address, first, pixels.pop(address + 1)))
        else:
            singles.append((address, first))
    data = struct.pack('<HH', len(words), len(singles))
    data += b''.join(struct.pack('<HHH', *w) for w in words)
    data += b''.join(struct.pack('<HH', *s) for s in singles)
    assert len(data) <= POSE_LIMIT, len(data)
    return data


def mask_unit(full, vi):
    """The view's runs from weapon-mask-full.bin (build_weapon_masks.source_pixels):
    u16 screen column of the first weapon column, then 200 u16 2*texel[y] + (y & 1),
    then 20 u16 pose offsets; a pose is u8 columns, then per column u8 runs, runs x
    (u8 y0, u8 y1, u16 source - $C800)."""
    from viewgeometry import SIZES, weapon_height
    view = SIZES[vi]
    height = weapon_height(view)
    width = height // 2
    left, screen_left = (view - width) // 2, (160 - view) // 2
    top = 80 - height // 2
    texel = [(y - top) * 64 // height if top <= y < top + height else 0 for y in range(200)]
    head = struct.pack('<H', screen_left + left) + struct.pack('<200H', *(2 * texel[y] + (y & 1) for y in range(200)))
    poses = []
    for pose in range(20):
        directory = struct.unpack_from('<H', full, 2 * (pose * 4 + vi))[0]
        body = bytearray([width])
        for col in range(left, left + width):
            pointer = struct.unpack_from('<H', full, directory + 2 * col)[0]
            body.append(full[pointer])
            for run in range(full[pointer]):
                bounds, _, source, _, _ = struct.unpack_from('<5H', full, pointer + 2 + run * 10)
                body += struct.pack('<BBH', bounds & 255, bounds >> 8, (source - 0xC800) & 0xFFFF)
        poses.append(bytes(body))
    at = len(head) + 40
    offsets = []
    for body in poses:
        offsets.append(at)
        at += len(body)
    unit = head + struct.pack('<20H', *offsets) + b''.join(poses)
    assert len(unit) <= MASK_LIMIT, (vi, len(unit))
    return unit


def build_pose(unit, pose):
    """Host model of WeaponComp's pose builder: the pose unit (pose_unit format) from
    the mask unit. Pixels in column order, a stable bucket pass by row, then pairs."""
    first = struct.unpack_from('<H', unit)[0]
    step = struct.unpack_from('<200H', unit, 2)
    at = struct.unpack_from('<H', unit, 402 + 2 * pose)[0]
    columns = unit[at]
    at += 1
    pixels = []
    for col in range(columns):
        runs = unit[at]
        at += 1
        for _ in range(runs):
            y0, y1, source = struct.unpack_from('<BBH', unit, at)
            at += 4
            for y in range(y0, y1):
                pixels.append((y * 160 + first + col, (source + step[y]) & 0xFFFF))
    assert len(pixels) * 4 <= PIXELS_LIMIT
    rows = [[] for _ in range(200)]
    for address, offset in pixels:
        rows[address // 160].append((address, offset))
    order = [p for row in rows for p in row]
    words, singles, i = [], [], 0
    while i < len(order):
        address, offset = order[i]
        assert address % 160 != 159
        if i + 1 < len(order) and order[i + 1][0] == address + 1:
            words.append((address, offset, order[i + 1][1]))
            i += 2
        else:
            singles.append((address, offset))
            i += 1
    data = struct.pack('<HH', len(words), len(singles))
    data += b''.join(struct.pack('<HHH', *w) for w in words)
    data += b''.join(struct.pack('<HH', *s) for s in singles)
    return data


def floor_table(floor):
    import json
    lights = json.loads((ROOT / f'build/levels/{floor}/pool-colors.json').read_text())
    return b''.join(bytes(lights[-1][c]) for c in range(256))


def compile_pose(unit, colors):
    """Host model of the native compiler: the same bytes as literal_weapon."""
    nw, ns = struct.unpack_from('<HH', unit)
    words, singles = {}, {}
    for k in range(nw):
        a, o1, o2 = struct.unpack_from('<HHH', unit, 4 + 6 * k)
        words.setdefault(colors[o1] | colors[o2] << 8, []).append(a)
    at = 4 + 6 * nw
    for k in range(ns):
        a, o = struct.unpack_from('<HH', unit, at + 4 * k)
        singles.setdefault(colors[o], []).append(a)
    code = bytearray()
    for value in sorted(words):
        code += bytes((0xa9,)) + struct.pack('<H', value)
        for a in words[value]:
            code += bytes((0x8d,)) + struct.pack('<H', 0x2000 + a)
    if singles:
        code += bytes((0xe2, 0x20))
        for value in sorted(singles):
            code += bytes((0xa9, value))
            for a in singles[value]:
                code += bytes((0x8d,)) + struct.pack('<H', 0x2000 + a)
        code += bytes((0xc2, 0x20))
    code.append(0x6b)
    return bytes(code)


def compile_view(units, colors):
    """Placement in pose order, first fit; returns {address: bytes} and the entry table."""
    free = [list(r) for r in REGIONS]
    out, entries = {}, bytearray()
    for unit in units:
        code = compile_pose(unit, colors)
        for r in free:
            if r[0] + len(code) <= r[1]:
                out[r[0]] = code
                entries += struct.pack('<HH', r[0] & 0xffff, r[0] >> 16)
                r[0] += len(code)
                break
        else:
            raise ValueError('weapon code exceeds its regions')
    return out, bytes(entries)


def colors_of(image, table):
    return bytes(table[2 * image[o] + (o & 1)] for o in range(len(image)))


def write_units():
    """Shared units into build/fixed/weapons, plus a check on every floor."""
    from build_weapon_masks import source_pixels
    from registered_views import literal_weapon
    from wolfdata import PROFILE
    folder = ROOT / 'build/fixed/weapons'
    folder.mkdir(parents=True, exist_ok=True)
    image = index_image()
    (folder / 'widx.bin').write_bytes(image)
    full = (ROOT / 'build/assets/weapon-mask-full.bin').read_bytes()
    pixels = [[source_pixels(full, pose, vi) for pose in range(20)] for vi in range(4)]
    for vi in range(4):
        mask = mask_unit(full, vi)
        (folder / f'mask-{vi}.bin').write_bytes(mask)
        for pose in range(20):
            unit = pose_unit(pixels[vi][pose])
            assert build_pose(mask, pose) == unit, (vi, pose)
            (folder / f'pose-{vi}-{pose:02}.bin').write_bytes(unit)
    for floor in range(PROFILE.floors):
        table = floor_table(floor)
        (ROOT / f'build/levels/{floor}/weapon-table.bin').write_bytes(table)
        colors = colors_of(image, table)
        expected = (ROOT / f'build/levels/{floor}/weapon-pixels-00.bin').read_bytes()
        assert colors == expected, f'floor {floor + 1}: weapon colours differ from the index image'
        for vi in (0, 3):
            for pose in (0, 7, 19):
                unit = (folder / f'pose-{vi}-{pose:02}.bin').read_bytes()
                assert compile_pose(unit, colors) == literal_weapon(pixels[vi][pose], colors)
    return folder
