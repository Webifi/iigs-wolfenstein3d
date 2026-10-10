"""Super Hi-Res palette fitting and pixel conversion for indexed source pictures.

The screen has 16 palettes of 16 colors, 4 bits a channel, and each row picks one palette.
A picture gets its own palettes. Each palette comes from a weighted k-means over the colors of
the rows that use it, then every row takes the palette with the least error for its pixels and
the palettes are fitted again from their assigned rows. Colors use 8-bit RGB;
METRIC selects weighted RGB or OKLab distance. Color 0 is black, and fixed
colors remain in every palette.

Three ways to turn a pixel into a palette color, per row palette:
  nearest  the nearest color, no dither
  fs       Floyd-Steinberg error diffusion; flat areas of the source stay flat (see flat())
   pairs    the nearest two-color mean as a checkerboard; swap the pair on odd rows
"""
import contextlib
import struct
import native_host

import gscolor
from wolfdata import CONVERSION, graphics, palette

to12 = gscolor.to12
from12 = gscolor.from12
word12 = gscolor.word12
rgb_dist = gscolor.dist            # 3 dr^2 + 4 dg^2 + 2 db^2 on 8-bit RGB

# Search and conversion share the metric. 'rgb' uses weighted RGB distance;
# 'oklab' is the squared OKLab distance with the chroma counted CHROMA times (viewcolor.py), which
# keeps a hue error, such as a pale lavender in a pale skin, from looking close.
METRIC = CONVERSION['artwork']['metric']
CHROMA = CONVERSION['artwork']['chroma_weight']
_lab_cache = {}


def set_metric(name):
    global METRIC
    assert name in ('rgb', 'oklab')
    METRIC = name


def is_teal(c):
    """A teal of the original frames and of the view: no red, green equal to blue (VGA 122-127, 225 and 226)."""
    return c[0] == 0 and c[1] == c[2] and c[1] > 0


@contextlib.contextmanager
def chroma(value):
    """Temporarily set OKLab chroma weight; clear cached distances on entry and exit."""
    global CHROMA
    old = CHROMA
    CHROMA = value
    _lab_cache.clear()
    try:
        yield
    finally:
        CHROMA = old
        _lab_cache.clear()


def _lin(v):
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def lab(c):
    """OKLab of an 8-bit RGB color (floats allowed)."""
    r, g, b = _lin(c[0]), _lin(c[1]), _lin(c[2])
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = l ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            CHROMA * (1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s),
            CHROMA * (0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s))


def lab_of(c):
    if c not in _lab_cache:
        _lab_cache[c] = lab(c)
    return _lab_cache[c]


def lab_to_rgb(v):
    """The inverse of lab(): 8-bit RGB floats, clipped."""
    L, a, b = v[0], v[1] / CHROMA, v[2] / CHROMA
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    out = []
    for lin in (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
                -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
                -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s):
        lin = max(0.0, min(1.0, lin))
        out.append(255 * (12.92 * lin if lin <= 0.0031308 else 1.055 * lin ** (1 / 2.4) - 0.055))
    return tuple(out)


def dist(a, b):
    """The distance of two 8-bit RGB colors in the metric."""
    if METRIC == 'rgb':
        return rgb_dist(a, b)
    la = lab_of(a) if a.__class__ is tuple and a[0].__class__ is int else lab(a)
    lb = lab_of(b) if b.__class__ is tuple and b[0].__class__ is int else lab(b)
    return 10000 * ((la[0] - lb[0]) ** 2 + (la[1] - lb[1]) ** 2 + (la[2] - lb[2]) ** 2)

_chunks = None
_vga = None


def vga():
    """The 256 colors of the original game, 8-bit RGB."""
    global _vga
    if _vga is None:
        _vga = palette()
    return _vga


def picture(n):
    """(width, height, VGA color indexes by row) of VGAGRAPH chunk n."""
    global _chunks
    if _chunks is None:
        _chunks = graphics()
    w, h = struct.unpack_from('<HH', _chunks[0], (n - 3) * 4)
    data = _chunks[n]
    plane = w * h // 4
    if len(data) != w * h:
        raise ValueError('chunk %d is not a picture' % n)
    return w, h, [[data[(x & 3) * plane + y * (w // 4) + (x >> 2)] for x in range(w)] for y in range(h)]


def rgb_rows(rows, pal=None):
    """Rows of VGA indexes as rows of RGB."""
    pal = pal or vga()
    return [[pal[i] for i in row] for row in rows]


# ---------------------------------------------------------------------------
# the palette search

def _is_int(c):
    return c[0].__class__ is int


def vec(c):
    """The color in the space of the metric."""
    if METRIC == 'rgb':
        return (float(c[0]), float(c[1]), float(c[2]))
    return lab_of(c) if _is_int(c) else lab(c)


def space_dist(a, b):
    """Squared distance of two vectors of the metric's space."""
    if METRIC == 'rgb':
        return rgb_dist(a, b)
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def kmeans(items, k=16, fixed=((0, 0, 0),), rounds=30, mode_share=0.5):
    """Weighted k-means of items [(rgb, weight)] in the space of the metric, like gscolor.kmeans, with one
    change: when a single color of the source is at least mode_share of the weight of its cluster (a flat
    area of the picture), the cluster takes that color and not the mean, so that a large flat area shows
    its own color. Returns k colors of 4 bits a channel; the fixed colors come first, and the free colors
    that no item needs repeat the last one."""
    items = [(c, w) for c, w in items if w > 0]
    if not items:
        return [from12(to12(c)) for c in fixed] + [(0, 0, 0)] * (k - len(fixed))
    back = (lambda v: v) if METRIC == 'rgb' else lab_to_rgb
    unit = 1.0 if METRIC == 'rgb' else 1e-6
    pts = [(vec(c), w, c) for c, w in items]
    native = native_host.library()
    vectors = [p[0] for p in pts]
    centers = [vec(c) for c in fixed]
    while len(centers) < k:
        if native:
            _, costs = native_host.nearest3(vectors, centers, METRIC == 'rgb')
            best = pts[max(range(len(pts)), key=lambda i: pts[i][1]*costs[i])]
        else:
            best = max(pts, key=lambda it: it[1] * min(space_dist(it[0], c) for c in centers))
        if best[1] * min(space_dist(best[0], c) for c in centers) == 0:
            centers.append(centers[-1])
        else:
            centers.append(best[0])
    nf = len(fixed)

    def assign():
        sums = [[0.0, 0.0, 0.0, 0.0, None, 0] for _ in range(k)]
        choices = native_host.nearest3(vectors, centers, METRIC == 'rgb')[0] if native else None
        for number, (v, w, c) in enumerate(pts):
            j = choices[number] if native else min(range(k), key=lambda i: space_dist(v, centers[i]))
            t = sums[j]
            t[0] += v[0] * w
            t[1] += v[1] * w
            t[2] += v[2] * w
            t[3] += w
            if w > t[5]:
                t[4], t[5] = v, w
        return sums
    for _ in range(rounds):
        sums = assign()
        new = list(centers[:nf])
        for j in range(nf, k):
            t = sums[j]
            new.append((t[0] / t[3], t[1] / t[3], t[2] / t[3]) if t[3] else centers[j])
        moved = max(space_dist(a, b) for a, b in zip(new, centers))
        centers = new
        if moved < unit:
            break
    if mode_share:
        sums = assign()
        for j in range(nf, k):
            t = sums[j]
            if t[3] and t[5] >= mode_share * t[3]:
                centers[j] = t[4]
    out = [from12(to12(c)) for c in fixed]
    for j in range(nf, k):
        out.append(from12(to12(back(centers[j]))))
    return out


def rowhist_of(rgb, weight=None, x0=0, y0=0, hists=None, factor=1):
    """Add the colors of rgb rows (placed at x0, y0) to the row histograms {rgb: weight}.
    weight(x, y) in the coordinates of the screen: a pixel counts that much."""
    hists = hists if hists is not None else {}
    for yy, row in enumerate(rgb):
        h = hists.setdefault(y0 + yy, {})
        for xx, c in enumerate(row):
            n = factor * (weight(x0 + xx, y0 + yy) if weight else 1)
            h[c] = h.get(c, 0) + n
    return hists


def search(rowhist, count, fixed=((0, 0, 0),), rounds=30, rows=None, slots=16, tail=(), mode_share=0.5,
           restarts=1, seed=1):
    """Palettes for the rows of rowhist ({row: {rgb: weight}}; rows lists the rows in order).
    Returns (row_pal, pals): the palette number of each row of rows, and count palettes of 16 colors. Free rows:
    each row takes the palette that shows its colors with the least weighted error, and each palette is made
    again from its rows (rounds times, until no row moves). The first start has bands of rows, the others
    a random split (restarts in all); the run with the least total error wins. slots: colors of the search (the
    rest of the 16 is the tail, fixed colors in the last slots)."""
    import random
    rows = list(rows if rows is not None else sorted(rowhist))
    n = len(rows)
    colors = sorted({c for y in rows for c in rowhist[y]})
    nf, nt = len(fixed), len(tail)

    def palette_for(members):
        hist = {}
        for i in members:
            for c, w in rowhist[rows[i]].items():
                hist[c] = hist.get(c, 0) + w
        pal = kmeans(list(hist.items()), k=slots, fixed=fixed + tuple(tail), mode_share=mode_share)
        return pal[:nf] + pal[nf + nt:] + pal[nf:nf + nt]

    def assign(pals):
        if native_host.library():
            vectors = [vec(c) for c in colors]
            costs = [native_host.nearest3(vectors, [vec(c) for c in pal], METRIC == 'rgb')[1] for pal in pals]
            scale = 1 if METRIC == 'rgb' else 10000
            nearest = {c: [scale*row[i] for row in costs] for i,c in enumerate(colors)}
        else:
            nearest = {c: [min(dist(c, q) for q in pal) for pal in pals] for c in colors}
        costs = [[sum(w * nearest[c][p] for c, w in rowhist[rows[i]].items()) for p in range(count)] for i in range(n)]
        band = [min(range(count), key=lambda p: costs[i][p]) for i in range(n)]
        return band, sum(costs[i][band[i]] for i in range(n))

    def run(band):
        pals = [palette_for([i for i in range(n) if band[i] == p]) for p in range(count)]
        for _ in range(rounds):
            nxt, _ = assign(pals)
            if nxt == band:
                break
            band = nxt
            pals = [palette_for([i for i in range(n) if band[i] == p]) if p in band else pals[p] for p in range(count)]
        band, total = assign(pals)
        return band, pals, total

    rng = random.Random(seed)
    best = None
    for r in range(max(1, restarts)):
        start = [min(count - 1, i * count // n) for i in range(n)] if r == 0 else [rng.randrange(count) for _ in range(n)]
        got = run(start)
        if best is None or got[2] < best[2]:
            best = got
    return best[0], best[1]


# ---------------------------------------------------------------------------
# turning pixels into palette colors

def flat(rgb):
    """Which pixels sit in a flat area: the pixel and its four neighbors have one color. A flat
    area of the source that the palette shows well stays flat; error diffusion would dot it."""
    h = len(rgb)
    w = len(rgb[0])
    out = [[False] * w for _ in range(h)]
    for y in range(1, h - 1):
        a, b, c = rgb[y - 1], rgb[y], rgb[y + 1]
        for x in range(1, w - 1):
            p = b[x]
            out[y][x] = a[x] == p and c[x] == p and b[x - 1] == p and b[x + 1] == p
    return out


def nearest_index(pal, c):
    """The index of the color of pal nearest to c in the metric."""
    best, bd = 0, 1 << 60
    if METRIC == 'rgb':
        for j in range(len(pal)):
            d = rgb_dist(c, pal[j])
            if d < bd:
                best, bd = j, d
        return best
    v = vec(c)
    for j in range(len(pal)):
        q = lab_of(pal[j])
        d = (v[0] - q[0]) ** 2 + (v[1] - q[1]) ** 2 + (v[2] - q[2]) ** 2
        if d < bd:
            best, bd = j, d
    return best


REACH, FLOOR = 4.0, 60.0


def candidates(pal, c, top, cache):
    """The indexes of the colors of pal that error diffusion may use for the source color c: the nearest, and up to
    top - 1 others whose distance to c is at most REACH times the nearest distance plus FLOOR (squared OKLab times
    10000), so that a gray never takes a teal. Equal colors count once. cache: a dict of this palette."""
    key = (c, top)
    got = cache.get(key)
    if got is None:
        order = sorted(((dist(c, pal[j]), j) for j in range(len(pal))))
        d0 = order[0][0]
        got = []
        for d, j in order:
            if got and d > REACH * d0 + FLOOR:
                break
            if not any(pal[j] == pal[i] for i in got):
                got.append(j)
            if len(got) == top:
                break
        cache[key] = got
    return got


def pair_table(pal):
    """All pairs of the palette: (mean, p, q, penalty), the penalty as in gscolor.best_pairs."""
    out = []
    for p in range(len(pal)):
        for q in range(p, len(pal)):
            m = tuple((pal[p][i] + pal[q][i]) / 2 for i in range(3))
            out.append((m, p, q, dist(pal[p], pal[q]) * gscolor.PAIR_PENALTY))
    return out


# Error diffusion kernels: (dx, dy, weight) and the sum of the weights. The IIgs pixel is 1.2 times as tall as it is
# wide, so a kernel that passes more error along the row than down the screen can suit it.
KERNELS = {
    'fs': (((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)), 16),
    'atkinson': (((1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)), 8),
    'sierra-lite': (((1, 0, 2), (-1, 1, 1), (0, 1, 1)), 4),
    'burkes': (((1, 0, 8), (2, 0, 4), (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2)), 32),
    'jarvis': (((1, 0, 7), (2, 0, 5), (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
                (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1)), 48),
    'wide': (((1, 0, 9), (-1, 1, 2), (0, 1, 4), (1, 1, 1)), 16),
}
BAYER = {2: ((0, 2), (3, 1)),
         4: ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5)),
         8: ((0, 32, 8, 40, 2, 34, 10, 42), (48, 16, 56, 24, 50, 18, 58, 26), (12, 44, 4, 36, 14, 46, 6, 38),
             (60, 28, 52, 20, 62, 30, 54, 22), (3, 35, 11, 43, 1, 33, 9, 41), (51, 19, 59, 27, 49, 17, 57, 25),
             (15, 47, 7, 39, 13, 45, 5, 37), (63, 31, 55, 23, 61, 29, 53, 21))}


def _lin_c(c):
    return (_lin(c[0]), _lin(c[1]), _lin(c[2]))


def lab_lin(r, g, b):
    """lab() of a linear-light color."""
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = l ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            CHROMA * (1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s),
            CHROMA * (0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s))


def best_mix(pal, c, levels, near, penalty, cache):
    """(p, q, k): the mix of palette colors p and q, q with the share k / levels, that the eye sees nearest to c
    (mixed in linear light, measured in OKLab). Only the near colors nearest to c are tried. penalty: the
    weight of the distance between p and q, so that far colors do not mix. cache: a dict of this palette."""
    key = (c, levels, near, penalty)
    got = cache.get(key)
    if got is not None:
        return got
    ids = candidates(pal, c, near, cache)
    lin = {j: _lin_c(pal[j]) for j in ids}
    target = vec(c)
    best = None
    for a in range(len(ids)):
        for b in range(a, len(ids)):
            p, q = ids[a], ids[b]
            lp, lq = lin[p], lin[q]
            span = dist(pal[p], pal[q])
            for k in (range(levels + 1) if p != q else (0,)):
                r = k / levels
                m = lab_lin(lp[0] + (lq[0] - lp[0]) * r, lp[1] + (lq[1] - lp[1]) * r, lp[2] + (lq[2] - lp[2]) * r)
                d = (target[0] - m[0]) ** 2 + (target[1] - m[1]) ** 2 + (target[2] - m[2]) ** 2
                d = d * 10000 + penalty * span * (4 * r * (1 - r))
                if best is None or d < best[0]:
                    best = (d, p, q, k)
    got = best[1:]
    cache[key] = got
    return got


def convert(rgb, row_pal, pals, mode='fs', snap=700, first_row=0, amount=1.0, top=3, clean=None,
            kernel='fs', serpentine=False, matrix=4, near=6, penalty=0.0):
    """Palette indexes (rows of 16-color indexes) of rgb rows. row_pal[i] is the palette of row i; first_row is
    the screen row of row 0 (patterns follow the screen row). Modes:
      nearest   the nearest color
      pairs     the best two-color mean, as a checkerboard
      ordered   a Bayer matrix (2, 4 or 8) and the best mix of 2 palette colors for each pixel (see best_mix)
      fs        error diffusion with a kernel of KERNELS, left to right or serpentine.
    fs options: snap: a flat pixel whose nearest color is within this distance takes it and passes on no error;
    amount: the part of the error that is passed on; top: a pixel may only take one of the top palette colors
    that are near its source color (see candidates), so that the error cannot pull in a color of another hue.
    clean(x, y): where it is true a pixel takes the nearest color and passes on no error (a face that must stay
    crisp)."""
    h = len(rgb)
    w = len(rgb[0])
    out = []
    if mode == 'nearest':
        for y in range(h):
            pal = pals[row_pal[y]]
            cache = {}
            row = []
            for c in rgb[y]:
                if c not in cache:
                    cache[c] = nearest_index(pal, c)
                row.append(cache[c])
            out.append(row)
        return out
    if mode == 'pairs':
        tables = {}
        caches = {}
        for y in range(h):
            p = row_pal[y]
            if p not in tables:
                tables[p] = pair_table(pals[p])
                caches[p] = {}
            cache = caches[p]
            row = []
            for x, c in enumerate(rgb[y]):
                if c not in cache:
                    best = min(tables[p], key=lambda e: dist(c, e[0]) + e[3])
                    cache[c] = (best[1], best[2])
                pq = cache[c]
                row.append(pq[0] if ((x + y + first_row) & 1) == 0 else pq[1])
            out.append(row)
        return out
    caches = {}
    if mode == 'ordered':
        m = BAYER[matrix]
        levels = matrix * matrix
        flats = flat(rgb) if snap else None
        for y in range(h):
            pal = pals[row_pal[y]]
            cache = caches.setdefault(row_pal[y], {})
            row = []
            for x, c in enumerate(rgb[y]):
                if clean is not None and clean(x, y):
                    row.append(nearest_index(pal, c))
                    continue
                if snap and flats[y][x]:
                    k = nearest_index(pal, c)
                    if rgb_dist(c, pal[k]) <= snap:
                        row.append(k)
                        continue
                p, q, k = best_mix(pal, c, levels, near, penalty, cache)
                t = m[(y + first_row) % matrix][x % matrix] + 0.5
                row.append(q if k > t else p)
            out.append(row)
        return out
    taps, total = KERNELS[kernel]
    flats = flat(rgb) if snap else None
    errs = [[[0.0, 0.0, 0.0] for _ in range(w)] for _ in range(3)]    # the error for this row, the next, and after
    for y in range(h):
        pal = pals[row_pal[y]]
        cache = caches.setdefault(row_pal[y], {})
        pal_lab = [lab_of(q) for q in pal]
        cur = errs[0]
        row = [0] * w
        sign = -1 if serpentine and y & 1 else 1
        for x in (range(w) if sign == 1 else range(w - 1, -1, -1)):
            c = rgb[y][x]
            if clean is not None and clean(x, y):
                row[x] = nearest_index(pal, c)
                continue
            if snap and flats[y][x]:
                k = nearest_index(pal, c)
                if rgb_dist(c, pal[k]) <= snap:
                    row[x] = k
                    continue
            e0 = cur[x]
            v = (max(0.0, min(255.0, c[0] + e0[0])), max(0.0, min(255.0, c[1] + e0[1])), max(0.0, min(255.0, c[2] + e0[2])))
            vl = lab(v)
            cands = candidates(pal, c, top, cache) if top else range(len(pal))
            k = min(cands, key=lambda j: (vl[0] - pal_lab[j][0]) ** 2 + (vl[1] - pal_lab[j][1]) ** 2 + (vl[2] - pal_lab[j][2]) ** 2)
            row[x] = k
            q = pal[k]
            e = ((v[0] - q[0]) * amount, (v[1] - q[1]) * amount, (v[2] - q[2]) * amount)
            for dx, dy, wt in taps:
                tx = x + dx * sign
                if 0 <= tx < w:
                    f = wt / total
                    r = errs[dy][tx]
                    r[0] += e[0] * f
                    r[1] += e[1] * f
                    r[2] += e[2] * f
        out.append(row)
        errs = [errs[1], errs[2], [[0.0, 0.0, 0.0] for _ in range(w)]]
    return out


def shown(idx, row_pal, pals):
    """The RGB rows that palette indexes show."""
    return [[pals[row_pal[y]][k] for k in row] for y, row in enumerate(idx)]


def pack(idx):
    """Two pixels a byte, the left one in the high nibble."""
    return bytes((a << 4) | b for row in idx for a, b in zip(row[::2], row[1::2]))


def palette_words(pal):
    return b''.join(struct.pack('<H', word12(c)) for c in pal)
