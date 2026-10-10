"""Letters of the original Wolfenstein 3-D chrome lettering, cut from the heading pictures of VGAGRAPH.WL1.

Each source is a word picture; its letters are cut at the columns where the fewest letter pixels touch the next letter.
A glyph keeps the original VGA palette indexes of its pixels (index 0 is the black plate, which is transparent here)."""
import struct
import sys
from pathlib import Path

from assets import graphics, palette, picture_index

# picture chunk: (word, x0, x1 of the lettering, y0, y1 rows that can hold lettering)
SOURCES = {
    22: ('Options', 26, 134, 7, 46),
    38: ('Control', 24, 136, 7, 46),
    39: ('Customize', 8, 149, 9, 44),
    40: ('Load Game', 34, 206, 7, 46),
    41: ('Save Game', 38, 205, 7, 46),
    146: ('Get Psyched!', 9, 213, 3, 46),
    102: ('High Scores', 27, 200, 10, 52),
}
# the rivets of the plate that stand inside the lettering rectangle: (x0, x1, y0, y1)
RIVETS = {39: [(10, 12, 9, 11), (10, 12, 41, 42), (145, 147, 9, 11), (145, 147, 41, 43)]}
_cache = {}


def picture(n):
    if n not in _cache:
        chunks = graphics()
        source = picture_index(n)
        w, h = struct.unpack_from('<HH', chunks[0], (source-3)*4)
        plane = w*h//4
        rows = [[chunks[source][(x & 3)*plane+y*(w//4)+(x >> 2)] for x in range(w)] for y in range(h)]
        for x0, x1, y0, y1 in RIVETS.get(n, ()):
            for y in range(y0, y1+1):
                for x in range(x0, x1+1):
                    rows[y][x] = 0
        _cache[n] = (rows, w, h)
    return _cache[n]


def crossings(rows, x, y0, y1):
    """How many letter pixels of column x touch (8 neighbours) a letter pixel of column x+1."""
    n = 0
    for y in range(y0, y1):
        if rows[y][x] and any(rows[yy][x+1] for yy in (y-1, y, y+1)):
            n += 1
    return n


def _dp(rows, ink, lo, hi, k, y0, y1, prior):
    cost = {x: crossings(rows, x, y0, y1) if x+1 < len(rows[0]) else 0 for x in range(lo, hi+1)}
    best = {}
    for i in range(k):
        for x in range(lo, hi+1):
            if i == 0:
                width = x-lo+1
                if 6 <= width <= 40:
                    best[(0, x)] = (cost[x]*3*(k > 1)+(width-prior)**2/6, None)
            else:
                cands = []
                for px in range(lo, x-5):
                    if (i-1, px) in best:
                        width = x-px
                        if width <= 40:
                            cands.append((best[(i-1, px)][0]+cost[x]*3*(i < k-1)+(width-prior)**2/6, px))
                if cands:
                    best[(i, x)] = min(cands)
    spans, x = [], hi
    for i in range(k-1, -1, -1):
        prev = best[(i, x)][1]
        spans.append((prev+1 if prev is not None else lo, x))
        x = prev
    spans.reverse()
    return spans


def cuts(n, prior=16):
    """Column spans [(x0, x1)] of the letters (spaces dropped): the cut columns where the fewest letter pixels touch,
    with a preference for letters about `prior` columns wide. The words of a source are told apart by gaps of 6 empty columns.
    Fixed cuts of a source (CUTS) win."""
    rows, w, h = picture(n)
    word, xa, xb, y0, y1 = SOURCES[n]
    y1 = min(y1, h)
    parts = word.split(' ')
    letters = [c for c in word if c != ' ']
    ink = [any(rows[y][x] for y in range(y0, y1)) for x in range(w)]
    lo = next(x for x in range(xa, min(xb, w)) if ink[x])
    hi = max(x for x in range(xa, min(xb, w)) if ink[x])
    if n in CUTS:
        edges = [lo-1]+list(CUTS[n])+[hi]
        return letters, [(edges[i]+1, edges[i+1]) for i in range(len(letters))]
    runs, start, empty = [], lo, 0
    for x in range(lo, hi+1):
        if ink[x]:
            if empty >= 6 and len(runs) < len(parts)-1:
                runs.append((start, x-empty-1))
                start = x
            empty = 0
        else:
            empty += 1
    runs.append((start, hi))
    assert len(runs) == len(parts), (n, runs)
    spans = []
    for part, (a, b) in zip(parts, runs):
        spans += _dp(rows, ink, a, b, len(part), y0, y1, prior)
    return letters, spans


# fixed cut columns (the last column of each letter but the last), where the automatic cut is wrong
CUTS = {}


def glyphs_of(n):
    """{char: dict(rows=[[index]], x0, x1, y0)} with rows cut to the ink of the span; first occurrence of each char."""
    rows, w, h = picture(n)
    word, xa, xb, y0, y1 = SOURCES[n]
    letters, spans = cuts(n)
    out = []
    for c, (a, b) in zip(letters, spans):
        ys = [y for y in range(y0, y1) if any(rows[y][x] for x in range(a, b+1))]
        top, bottom = ys[0], ys[-1]
        # the pixels of the span; the first and last columns can hold a neighbor's edge pixels: keep them as the cut says
        g = [[rows[y][x] for x in range(a, b+1)] for y in range(top, bottom+1)]
        out.append(dict(char=c, rows=g, x0=a, x1=b, y0=top, y1=bottom, pic=n))
    return out


if __name__ == '__main__':
    for n in SOURCES:
        letters, spans = cuts(n)
        print(n, SOURCES[n][0], list(zip(letters, spans)))


# Row shift of each source picture so that the second dark band and the red reflection line up (rows of picture 38)
SHIFT = {22: 2, 38: 0, 39: 1, 40: -1, 41: -1, 146: 5, 102: -2}
# Order in which a letter is taken when several sources have it (the sources of one size first)
FAMILY = [38, 22, 40, 41, 39, 146, 102]
_glyphs = None


def library():
    """{char: [Glyph dict]}: every cut letter with its pixels as {(dx, dy): index}, rows in the coordinates of picture 38."""
    global _glyphs
    if _glyphs is not None:
        return _glyphs
    lib = {}
    for n in FAMILY:
        rows, w, h = picture(n)
        word, xa, xb, y0, y1 = SOURCES[n]
        y1 = min(y1, h)
        letters, spans = cuts(n)
        for c, (a, b) in zip(letters, spans):
            px = {(x-a, y+SHIFT[n]): rows[y][x] for y in range(y0, y1) for x in range(a, b+1) if rows[y][x]}
            lib.setdefault(c, []).append(dict(char=c, pic=n, x0=a, x1=b, width=b-a+1, px=px))
    _glyphs = lib
    return lib


SPACE = 9


def compose(text, gap=0):
    """Rows of VGA indexes (0 = transparent) of `text` in the original lettering and the row offset of rows[0]
    (picture 38 coordinates). A letter that the sources lack raises KeyError."""
    lib = library()
    x, placed = 0, []
    prev = None
    for ch in text:
        if ch == ' ':
            x += SPACE
            prev = None
            continue
        g = lib[ch][0]
        # letters that touch in the original are cut where they touched: they keep their distance; a letter that ends
        # on ink next to one that starts on ink gets one blank column
        if prev is not None and not (prev['pic'] == g['pic'] and prev['x1']+1 == g['x0']):
            last = any(dx == prev['width']-1 for dx, dy in prev['px'])
            first = any(dx == 0 for dx, dy in g['px'])
            if last and first:
                x += 1
        placed.append((x, g))
        x += g['width']
        prev = g
    width = x
    ys = [dy for _, g in placed for dx, dy in g['px']]
    top, bottom = min(ys), max(ys)
    rows = [[0]*width for _ in range(bottom-top+1)]
    for ox, g in placed:
        for (dx, dy), v in g['px'].items():
            rows[dy-top][ox+dx] = v
    return rows, top
