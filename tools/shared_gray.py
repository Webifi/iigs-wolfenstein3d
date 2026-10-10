"""Group existing palette colors by role without changing the picture's colors."""
import json
import struct
from pathlib import Path

GRAYS = (0x444, 0x333, 0x222, 0x111)



def word(rgb):
    r, g, b = (round(c / 17) for c in rgb)
    return r * 256 + g * 16 + b


def rgb(c):
    return tuple((c >> s & 15) * 17 for s in (8, 4, 0))


def distance(a, b):
    return sum(w * ((a >> s & 15) - (b >> s & 15)) ** 2
               for s, w in ((8, 3), (4, 6), (0, 1)))


# Free slots go first to the roles that overlays draw with: the loading sign
# uses 13 and 14 for its edges and 1 for its letters; the menu grays use 12-15.
FREE_ROLES = (13, 14, 1, 12, 15)


def neutral(c):
    channels = [c >> s & 15 for s in (8, 4, 0)]
    return c and max(channels) <= 7 and max(channels) - min(channels) <= 2


def general_colors(pal, copies, fixed):
    """pal with each copied entry replaced by the general color of a role it lacks."""
    from gscolor import ALIGN_REF, assignment, lab_dist, oklab4
    targets = list(ALIGN_REF[:12]) + [tuple(c >> s & 15 for s in (8, 4, 0)) for c in GRAYS]
    general = [r * 256 + g * 16 + b for r, g, b in targets]
    out = list(pal)
    present = set(pal)
    free = list(copies)

    def take(slot):
        # The role's general color, or the nearest color the palette does not have yet.
        color = general[slot] if general[slot] not in present else min(
            (c for c in range(1, 4096) if c not in present),
            key=lambda c: lab_dist(oklab4((c >> 8, c >> 4 & 15, c & 15)), oklab4(targets[slot])))
        out[free.pop(0)] = color
        present.add(color)

    # Own dark neutrals cover their nearest gray roles; the other gray roles need a general gray.
    destinations = set(fixed.values())
    open_grays = [s for s in (12, 13, 14, 15) if s not in destinations]
    found = [pal[i] for i in range(16) if i not in fixed and i not in copies and neutral(pal[i])]
    size = max(len(found), len(open_grays))
    cost = [[distance(found[r], GRAYS[open_grays[c] - 12]) if r < len(found) and c < len(open_grays) else 0
             for c in range(size)] for r in range(size)]
    covered = {open_grays[c] for r, c in enumerate(assignment(cost) if size else ())
               if r < len(found) and c < len(open_grays)}
    for slot in FREE_ROLES:
        if free and slot not in destinations and (slot not in open_grays or slot not in covered):
            if slot != 1 or general[1] not in present:
                take(slot)
    # Then the roles that the picture's colors are farthest from.
    real = [tuple(c >> s & 15 for s in (8, 4, 0)) for c in present]
    for slot in sorted(range(2, 12), key=lambda s: -min(lab_dist(oklab4(c), oklab4(targets[s])) for c in real)):
        if free and slot not in destinations:
            take(slot)
    for slot in range(1, 16):
        if free:
            take(slot)
    return out


def align_palette(pal, keep=1, *, fixed_slots=None):
    """Permute existing colors; fixed_slots maps source indexes to shared destinations.

    A copy of a color that already has a slot is a free slot. It first gets the
    general color of a role the palette lacks (the grays and the light color
    that overlays draw with), then all colors are ordered as before. No color
    of the picture is removed or changed.
    """
    from gscolor import ALIGN_REF, assignment, lab_dist, oklab4
    check(pal, 'source palette')
    if not 1 <= keep <= 16:
        raise ValueError(f'invalid fixed prefix: {keep}')
    targets = list(ALIGN_REF[:12]) + [tuple(c >> s & 15 for s in (8, 4, 0)) for c in GRAYS]
    fixed = {i: i for i in range(keep)}
    for source, destination in (fixed_slots or {}).items():
        if not (0 <= source < 16 and 0 <= destination < 16):
            raise ValueError('fixed palette indexes must be 0..15')
        if source in fixed and fixed[source] != destination:
            raise ValueError('fixed slot moves the preserved prefix')
        fixed[source] = destination
    if len(set(fixed.values())) != len(fixed):
        raise ValueError('fixed palette destinations overlap')
    source = pal
    seen = {pal[i] for i in fixed}
    copies = []
    for i in range(16):
        if i not in fixed:
            if pal[i] in seen:
                copies.append(i)
            seen.add(pal[i])
    if copies:
        pal = general_colors(pal, copies, fixed)
    out = [0] * 16
    for source_index, destination in fixed.items():
        out[destination] = pal[source_index]
    chosen = set(fixed)
    occupied = set(fixed.values())
    gray_slots = set()
    found = [i for i in range(keep, 16) if i not in chosen and neutral(pal[i])]
    few = 0 < len(found) < 3 and not {13, 14} & occupied
    if few:
        # Too few for every gray role: the loading sign draws its edges with 13 and 14.
        cost = [[distance(pal[i], GRAYS[slot - 12]) + 0.1 * (i != slot) for slot in (13, 14)] for i in found]
        cost += [[0, 0]] * (2 - len(found))
        for row, column in enumerate(assignment(cost)[:len(found)]):
            chosen.add(found[row])
            gray_slots.add(13 + column)
            out[13 + column] = pal[found[row]]
    # Keep the available dark neutrals together. A palette can have fewer
    # than four; its other colors still get slots, never replacement RGB.
    for slot in (15, 14, 13, 12):
        if slot in occupied or few:
            continue
        candidates = [i for i in range(keep, 16) if i not in chosen and neutral(pal[i])]
        if candidates:
            i = min(candidates, key=lambda i: (distance(pal[i], GRAYS[slot - 12]), i != slot))
            chosen.add(i)
            gray_slots.add(slot)
            out[slot] = pal[i]
    rest = [pal[i] for i in range(keep, 16) if i not in chosen]
    slots = [i for i in range(16) if i not in occupied and i not in gray_slots]
    colors = [tuple(c >> shift & 15 for shift in (8, 4, 0)) for c in rest]
    cost = [[lab_dist(oklab4(c), oklab4(targets[i])) for i in slots] for c in colors]
    columns = assignment(cost)
    for color, column in zip(rest, columns):
        out[slots[column]] = color
    if not set(source) <= set(out):
        raise ValueError(f'alignment lost a color: {source} -> {out}')
    return out


def check(pal, where):
    if len(pal) != 16 or any(not 0 <= c <= 0xfff for c in pal):
        raise ValueError(f'{where}: expected sixteen 12-bit colors')


def remap(old, new):
    return [min((i for i in range(16) if new[i] == c), key=lambda i: i != n)
            for n, c in enumerate(old)]


def pairs(mapping):
    return bytes(mapping[b >> 4] * 16 + mapping[b & 15] for b in range(256))


def floor_record(path):
    path = Path(path)
    data = json.loads(path.read_text())
    old = [word(c) for c in data['palette']]
    new = align_palette(old)
    if old != new:
        table = pairs(remap(old, new))
        def convert(value):
            return [convert(v) for v in value] if isinstance(value, list) else table[value]
        for key in ('wall_ab', 'sprite_ab', 'wall_pair', 'sprite_pair', 'wall_lights', 'sprite_lights'):
            data[key] = convert(data[key])
        data['palette'] = [rgb(c) for c in new]
        path.write_text(json.dumps(data, separators=(',', ':')) + '\n')
    check(new, str(path))
    return data


# The loading box's gray roles (gray level 0-15, target, lowest, highest): letters and bar (slot 1), border
# (12) and letter edges (13, 14), as the floors and the menu show them; the edges run light to dark.
BOX_GRAYS = {1: (13, 11, 15), 12: (7, 4, 8), 13: (5, 3, 6), 14: (3, 2, 4)}


def sign_grays(raw, rows):
    """{color: slot} for a page whose second pass fixed the loading box's grays in every palette
    (shr_search.locked_fixed): for each BOX_GRAYS role, the pure gray in its range that every used palette
    holds, darker than the role before, nearest its target (the lighter one on a tie)."""
    used = {raw[32000 + y] & 15 for y in range(rows)}
    common = set.intersection(*(set(struct.unpack_from('<16H', raw, 32256 + p * 32)) for p in used))
    levels = sorted(c & 15 for c in common if c and c >> 8 == c >> 4 & 15 == c & 15)
    pins, below = {}, 16
    for slot, (target, low, high) in BOX_GRAYS.items():
        fits = [g for g in levels if low <= g <= high and g < below]
        if not fits:
            return {}
        below = min(fits, key=lambda g: (abs(g - target), -g))
        pins[below * 0x111] = slot
    return pins


def picture(raw, victory=False, boot=False):
    out = bytearray(raw)
    tables = []
    mappings = []
    pins = sign_grays(raw, 160 if victory else 200)
    for p in range(16):
        old = list(struct.unpack_from('<16H', raw, 32256 + p * 32))
        keep = 9 if boot and p == 15 else 1
        fixed = {old.index(c): slot for c, slot in pins.items() if c in old} if keep == 1 else None
        new = align_palette(old, keep, fixed_slots=fixed)
        mapping = remap(old, new)
        mappings.append(mapping)
        tables.append(pairs(mapping))
        struct.pack_into('<16H', out, 32256 + p * 32, *new)
    for y in range(160 if victory else 200):
        at = y * 160
        out[at:at + 160] = raw[at:at + 160].translate(tables[raw[32000 + y] & 15])
    if victory:
        for p, mapping in enumerate(mappings):
            for i in range(16):
                out[25600 + p * 16 + i] = mapping[raw[25600 + p * 16 + i]]
    if len(raw) >= 36864:
        for p, table in enumerate(tables):
            at = 32768 + p * 256
            out[at:at + 256] = raw[at:at + 256].translate(table)
    return bytes(out)


def preview(raw):
    from frontend.native_assets import unpack_block
    from frontend.build_words import block
    out = bytearray(raw[:130])
    mappings = []
    for p in range(2):
        old = list(struct.unpack_from('<16H', raw, 2 + p * 32))
        new = align_palette(old)
        mappings.append(remap(old, new))
        struct.pack_into('<16H', out, 2 + p * 32, *new)
    rows = unpack_block(raw, 130, 64)
    for y, row in enumerate(rows):
        m = mappings[raw[66 + y] - 13]
        rows[y] = [None if c is None else m[c] for c in row]
    return bytes(out) + block(rows, 0)


def tally(raw, const):
    from gscolor import ALIGN_REF, assignment, lab_dist, oklab4
    out = bytearray(raw)
    numbers = (0, 13, 14)
    palettes = {}
    original = [list(struct.unpack_from('<16H', raw, 160 + p * 32)) for p in range(3)]
    # The copied lettering must use the same slots in all three bands. Put
    # its existing teals in the cool-color area, leaving the neutral roles
    # available for each band's own colors. No RGB values are added/changed.
    cool_slots = (9, 10, 11)
    lettering = [tuple(c >> s & 15 for s in (8, 4, 0)) for c in original[0][1:4]]
    columns = assignment([[lab_dist(oklab4(c), oklab4(ALIGN_REF[i]))
                           for i in cool_slots] for c in lettering])
    fixed = {source: cool_slots[column] for source, column in enumerate(columns, 1)}
    assert all(pal[:4] == original[0][:4] for pal in original)
    for p, number in enumerate(numbers):
        old = original[p]
        new = align_palette(old, fixed_slots=fixed)
        palettes[number] = new
        struct.pack_into('<16H', out, 160 + p * 32, *new)
    pieces = (('TALLY_BJ1', 16, 52, 88),
              ('TALLY_BJ2', 16 + const['TALLY_BJ2_Y'], const['TALLY_BJ2_W'], const['TALLY_BJ2_H']))
    # Plain lettering rows do not need a portrait palette. Reuse an existing
    # neutral-rich palette wherever it represents both BJ poses and every
    # runtime glyph exactly. This keeps overlay ink neutral without reserving
    # colors, replacing RGB values or fitting ink separately at runtime.
    needed = [set(original[0][:4]) for _ in range(160)]
    for key, top, width, height in pieces:
        for row in range(height):
            pal = original[numbers.index(raw[top + row])]
            at = const[key] + row * width
            for b in raw[at:at + width]:
                needed[top + row].update((pal[b >> 4], pal[b & 15]))

    def neutral_roles(number):
        colors = {palettes[number][i] for i in OVERLAY_SLOTS if i}
        return sum(max(rgb(c)) - min(rgb(c)) <= 34 for c in colors)

    row_maps = []
    for y, colors in enumerate(needed):
        candidates = [n for n in numbers if colors <= set(palettes[n])]
        number = max(candidates, key=lambda n: (neutral_roles(n), n == raw[y]))
        out[y] = number
        old = original[numbers.index(raw[y])]
        # Unused source entries need no match in the chosen palette.
        mapping = [palettes[number].index(c) if c in colors else 0 for c in old]
        row_maps.append(pairs(mapping))
    for key, y, width, height in pieces:
        for row in range(height):
            at = const[key] + row * width
            out[at:at + width] = raw[at:at + width].translate(row_maps[y + row])
    glyph_map = pairs(remap(original[0], palettes[0]))
    at = const['TALLY_GLYPHS'] + 39 * 2
    out[at:const['TALLY_BYTES']] = raw[at:const['TALLY_BYTES']].translate(glyph_map)
    const['TALLY_FILL'] = glyph_map[const['TALLY_FILL']]
    return bytes(out)


def shade_table(bright):
    result = []
    for c in STEEL:
        value = c & 15
        target = min(15, value + 1) if bright and value >= 6 else value
        if not bright and value >= 2:
            target = max(4, min(8, value - 5))
        result.append(INK[target])
    # Backdrop shades and the transparent marker survive row highlighting.
    result[TRANSPARENT_INK] = TRANSPARENT_INK
    if bright:
        for i in (0, 13, 14, 15):
            result[i] = i
    return pairs(result)


# The font palette uses the same permutation as pictures. Its source shades
# are all distinct; transparency is a glyph-encoding marker, not a color slot
# that other palettes must leave unused.
STEEL = tuple(align_palette([shade * 0x111 for shade in range(16)]))
# Menu rows already own the complete steel palette. Preserve its fitted
# intermediate shades instead of quantizing every glyph to overlay roles.
INK = tuple(STEEL.index(shade * 0x111) for shade in range(16))
TRANSPARENT_INK = INK[1]

# Signs over artwork use one fixed projection into the aligned neutral
# roles. This does not inspect, replace, or reserve picture palette colors.
OVERLAY_SLOTS = (0, 1, 12, 13, 14, 15)
OVERLAY_INK = tuple(min(OVERLAY_SLOTS, key=lambda i: distance(STEEL[i], color))
                    for color in STEEL)
OVERLAY_PAIRS = pairs(OVERLAY_INK)
