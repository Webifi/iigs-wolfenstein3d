"""Source wall flags and the current native byte-plane representation.

Map setup preserves source values below AREATILE. Wall hits check the
door-side flag in bit 6, then remove it for material lookup. Door and ambush
values have separate meanings.
"""


def wall_material(value):
    """Return the wall material, retaining door-side flags in the source map."""
    if 1 <= value < 64 or 65 <= value < 90 or 102 <= value < 106:
        return value & 63
    return None


def native_plane_bytes(values, *, floor, plane, extended_info=False):
    """Reject source words the byte-plane ABI cannot represent; never discard them."""
    if len(values) != 64 * 64:
        raise ValueError(f'floor {floor}, plane {plane}: expected 4096 source words')
    if extended_info and plane == 1:
        # Source Wolf has no info objects 1..4. These native-only bytes retain
        # all four hard mutant patrol directions without widening hot map reads.
        if any(1 <= value <= 4 for value in values):
            raise ValueError(f'floor {floor}, plane 1: source codes 1..4 conflict with the native mutant encoding')
        values = [value - 255 if 256 <= value <= 259 else value for value in values]
    unsupported = [(i, value) for i, value in enumerate(values) if not 0 <= value <= 255]
    if unsupported:
        cells = ', '.join(f'{value} at ({i % 64},{i // 64})' for i, value in unsupported[:8])
        suffix = f'; {len(unsupported)} cells in total' if len(unsupported) > 8 else ''
        raise ValueError(f'floor {floor}, plane {plane}: native byte-plane format cannot represent '
                         f'{cells}{suffix}. The source words are preserved; explicit native '
                         'object encoding and behavior support are required.')
    return bytes(values)


def potentially_reachable(planes, semantics, blocked=()):
    """Conservative ray/movement reach: all doors and pushwalls open.

    Seed every player and actor placement, at every difficulty. An unvisited
    cell cannot become reachable through an actor, pickup or pushwall change.
    Rays cross cell edges; touching solid corners do not connect open regions.
    """
    geometry, info = planes[:2]
    pending = [i for i, code in enumerate(info)
               if i not in blocked and semantics.lookup.get((1, code), {}).get('kind') in ('player', 'actor')]
    seen = set(pending)
    while pending:
        i = pending.pop(); x, y = i % 64, i // 64
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            xx, yy = x + dx, y + dy
            if not (0 <= xx < 64 and 0 <= yy < 64):
                continue
            cell = yy * 64 + xx
            if cell not in seen and cell not in blocked and (wall_material(geometry[cell]) is None or info[cell] == 98):
                seen.add(cell); pending.append(cell)
    return seen


def pushwall_protected_borders(planes, semantics, holes):
    """Prove border holes stay sealed at every possible pushwall stop.

    All other pushwalls are treated as open. The candidate must have only one
    possible push direction. Its initial cell and each possible stopping
    cell must isolate the border hole. A state exactly at 256 can claim a
    third cell; include that case and the native column-major edge wrap.
    No source tile is changed.
    """
    geometry, info = planes[:2]
    protected = set()
    for start, code in enumerate(info):
        if code != 98:
            continue
        before = potentially_reachable(planes, semantics, {start})
        candidates = set(holes) - before - protected
        if not candidates:
            continue
        x, y = start % 64, start // 64
        directions = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            bx, by, nx, ny = x-dx, y-dy, x+dx, y+dy
            if (0 <= bx < 64 and 0 <= by < 64 and 0 <= nx < 64 and 0 <= ny < 64
                    and by*64+bx in before and wall_material(geometry[ny*64+nx]) is None):
                directions.append((dx, dy))
        if len(directions) != 1:
            continue
        dx, dy = directions[0]
        for distance in (1, 2, 3):
            xx, yy = x+dx*distance, y+dy*distance
            cell = xx*64+yy
            if not 0 <= cell < 4096:
                candidates.clear()
                break
            native_x, native_y = divmod(cell, 64)
            at = native_y*64+native_x
            if wall_material(geometry[at]) is not None and info[at] != 98:
                break
            if not (0 <= xx < 64 and 0 <= yy < 64):
                candidates.clear()
                break
            candidates -= potentially_reachable(planes, semantics, {at})
        protected.update(candidates)
    return protected
