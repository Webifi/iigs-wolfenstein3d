"""Reduce fragmented world-sprite opacity without recoloring surviving texels."""
from functools import lru_cache
from hashlib import sha256

RUN_COST = 10
FILL_COST = 2
REMOVE_COST = 3
STRUCTURE_WIDTH = 6
TABLE_SOURCE = '598799bb1c49811f5d60fa26f9cf0549c8719b91395b62a2aa4aa4c611b5c2c8'
IVY_SOURCE = 'ddfcfac1df88de9cf041eb24bc9a51e14ce4f70e4d8f15fe35e72adbb1edd2a2'


def source_pixels(art):
    pixels = [[None] * 64 for _ in range(64)]
    for x, column in enumerate(art['columns'], art['left']):
        for top, bottom, colors in column:
            pixels[x][top:bottom] = colors
    return pixels


def source_key(pixels):
    return sha256(bytes(255 if c is None else c for col in pixels for c in col)).hexdigest()


def hanging_ivy(source):
    """Narrow three source vines and smooth their sideways travel.

    Each output row samples the corresponding original row. Source identity
    guards this geometry so unrelated mission art keeps the general filter.
    """
    pending = {(x, y) for x, col in enumerate(source) for y, c in enumerate(col) if c is not None}
    components = []
    while pending:
        first = pending.pop()
        cells, stack = {first}, [first]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cell = x + dx, y + dy
                    if cell in pending:
                        pending.remove(cell)
                        cells.add(cell)
                        stack.append(cell)
        components.append(cells)
    components.sort(key=lambda cells: min(x for x, y in cells))
    assert len(components) == 3
    result = [[None] * 64 for _ in range(64)]
    for cells, center in zip(components, (12, 33, 53)):
        spans = []
        for y in range(64):
            runs = []
            for x in sorted(x for x, row in cells if row == y):
                if not runs or x != runs[-1][-1] + 1:
                    runs.append([])
                runs[-1].append(x)
            spans.append(max(runs, key=len))
        centers = [(xs[0] + xs[-1]) / 2 for xs in spans]
        widths = [len(xs) for xs in spans]
        mean = sum(centers) / 64
        for y in range(64):
            lo, hi = max(0, y - 4), min(64, y + 5)
            cx = center + (sum(centers[lo:hi]) / (hi - lo) - mean) * .5
            width = max(2, round(sum(widths[lo:hi]) / (hi - lo) * .85))
            left = round(cx - (width - 1) / 2)
            for dx in range(width):
                sx = spans[y][round(dx * (len(spans[y]) - 1) / (width - 1))]
                result[left + dx][y] = source[sx][y]
    # Remove isolated edge texels that require additional column runs.
    for x, top, bottom in (
        (8, 1, 2), (10, 24, 25), (10, 56, 57), (11, 32, 34),
        (14, 57, 58), (15, 0, 1), (15, 7, 8), (15, 13, 14), (15, 52, 53),
        (33, 61, 62), (48, 32, 33), (50, 52, 53), (50, 58, 59),
        (50, 61, 62), (51, 62, 64), (52, 63, 64),
    ):
        result[x][top:bottom] = [None] * (bottom - top)
    return result


@lru_cache(maxsize=1)
def mirror_shape():
    """Only the matching source ivy receives a companion header."""
    from wolfdata import vswap, sprite
    from wolf_source import sprite_ids
    shape = sprite_ids()['SPR_STAT_47']
    pages, base, _ = vswap()
    return shape if source_key(source_pixels(sprite(pages[base + shape]))) == IVY_SOURCE else None


def column_mask(column, protected):
    """Minimize changed opacity plus a fixed cost per opaque run.

    A wide horizontal feature must survive even when it is only one row
    high. Smaller features may be removed or joined. Ties prefer transparent
    rows; surviving colors are never changed.
    """
    states = {0: (0, [])}
    for y, color in enumerate(column):
        next_states = {}
        for bit in (0, 1):
            mismatch = 0
            if bit != int(color is not None):
                mismatch = (RUN_COST + 1 if protected[y] else REMOVE_COST) if color is not None else FILL_COST
            choices = [(cost + mismatch + (RUN_COST if bit and not previous else 0),
                        path + [bit]) for previous, (cost, path) in states.items()]
            next_states[bit] = min(choices)
        states = next_states
    return min(states.values())[1]


def simplify(art):
    counts = [len(column) for column in art['columns']]
    if max(counts, default=0) < 6 and sum(n >= 4 for n in counts) < 12:
        return art

    source = source_pixels(art)
    key = source_key(source)
    protected = [[False] * 64 for _ in range(64)]
    for y in range(64):
        x = 0
        while x < 64:
            if source[x][y] is None:
                x += 1
                continue
            start = x
            while x < 64 and source[x][y] is not None:
                x += 1
            if x - start >= STRUCTURE_WIDTH:
                for at in range(start, x):
                    protected[at][y] = True
    result = []
    for x, column in enumerate(source):
        bits = column_mask(column, protected[x])
        opaque = [y for y, color in enumerate(column) if color is not None]
        # A filled gap borrows the nearest opaque color in its own column.
        # Surviving opaque texels keep their original palette indices.
        result.append([None if not bit else column[y] if column[y] is not None else
                       column[min(opaque, key=lambda row: abs(row - y))]
                       for y, bit in enumerate(bits)])

    if key == TABLE_SOURCE:
        # Keep the seat and leg openings; close the left back with wood.
        for x in (10, 11):
            for y in range(37, 43):
                assert result[x][y] is None
                result[x][y] = 63
        # The narrow recess below the left seat uses the lower rail's gray.
        for y in range(51, 56):
            assert result[16][y] is None
            result[16][y] = source[19][58]
    elif key == IVY_SOURCE:
        result = hanging_ivy(source)

    columns = []
    for column in result:
        runs = []
        y = 0
        while y < 64:
            if column[y] is None:
                y += 1
                continue
            top = y
            while y < 64 and column[y] is not None:
                y += 1
            runs.append((top, y, bytes(column[top:y])))
        columns.append(runs)
    used = [x for x, column in enumerate(columns) if column]
    if not used:
        return art
    left, right = min(used), max(used)
    return dict(art, left=left, right=right, columns=columns[left:right + 1])


@lru_cache(maxsize=None)
def world_sprite(page):
    from wolfdata import sprite
    return simplify(sprite(page))
