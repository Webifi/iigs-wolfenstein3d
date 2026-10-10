"""Super Hi-Res page conversion after ii-pix's SHR method, and the measure that picks a result.

The method is Kris Kennaway's ii-pix (github.com/KrisKennaway/ii-pix, convert_shr.py and
dither_shr.pyx), ported without its packages: dither to the 4096 IIgs colors first; fit the 16
palettes on overlapping 35-line bands with random-start k-means that keeps each frequent color
(10% of a band's pixels) exact; choose each line's palette while dithering; keep a new palette set
only when the whole dithered error falls; give an unused palette the worst line.

Differences, each measured on the Spear and Wolf3D titles (bands, noise and tone of
measure_bands): OKLab instead of CAM16-UCS; black fixed in index 0; protected boxes weighted and
not dithered; flat source areas take their nearest color with chroma counted 3 times (a gray floor
stays pure gray) and pass on no error; error diffusion over the 2 colors nearest each source color
with 45% of the error passed on; a fixed number of steps, seeded, so a build repeats its bytes.

The search and dither loops run in tools/host_kernels.c when it compiles; the Python twins below
keep the same operation order.
"""
from collections import defaultdict

import numpy as np

import native_host
import wolfpics as wp

CHROMA = 1.0          # search and dither: chroma counted 3 times doubled the measured bands
FLAT_CHROMA = 3.0     # flat areas: a gray source keeps a pure gray
DITHER_AMOUNT = 0.45
CANDIDATES = 2
STEPS = 10
BAND_LINES = 35

M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
               [0.2119034982, 0.6806995451, 0.1073969566],
               [0.0883024619, 0.2817188376, 0.6299787005]])
M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
               [1.9779984951, -2.4285922050, 0.4505937099],
               [0.0259040371, 0.7827717662, -0.8086757660]])


def srgb_to_linear(v):
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v):
    v = np.clip(np.asarray(v, dtype=np.float64), 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055)


def oklab(linear, chroma):
    return (np.cbrt(np.asarray(linear) @ M1.T) @ M2.T) * np.array([1.0, chroma, chroma])


def oklab_to_linear(lab, chroma):
    lab = np.asarray(lab) / np.array([1.0, chroma, chroma])
    return (lab @ np.linalg.inv(M2).T) ** 3 @ np.linalg.inv(M1).T


WORDS = np.arange(4096)
RGB12 = (np.stack([(WORDS >> 8) & 15, (WORDS >> 4) & 15, WORDS & 15], 1) * 17).astype(np.uint8)
LIN12 = srgb_to_linear(RGB12 / 255.0)
LAB12 = oklab(LIN12, CHROMA)
FLAT12 = oklab(LIN12, FLAT_CHROMA)


def lab_to_word(lab):
    srgb = linear_to_srgb(oklab_to_linear(np.atleast_2d(lab), CHROMA))
    q = np.clip(np.round(srgb * 15), 0, 15).astype(int)
    return q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]


def kmeans_fixed(words, weights, centroids, n_fixed, iterations=1000):
    """ii-pix's k-means: 12-bit centroids, distances and means in OKLab; ends when the error stops falling."""
    labs = LAB12[words]
    cents = np.array(centroids)
    last = np.inf
    for _ in range(iterations):
        d = ((labs[:, None, :] - LAB12[cents][None, :, :]) ** 2).sum(2)
        near = d.argmin(1)
        total = float((d[np.arange(len(words)), near] * weights).sum())
        if total >= last:
            break
        last = total
        for c in range(n_fixed, len(cents)):
            m = near == c
            if m.any():
                cents[c] = lab_to_word((labs[m] * weights[m, None]).sum(0) / weights[m].sum())[0]
    return [int(c) for c in cents]


def _oklab1(px, chroma):
    r, g, b = px
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1.0 / 3.0)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1.0 / 3.0)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1.0 / 3.0)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            chroma * (1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s),
            chroma * (0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s))


def _d2(a, b):
    d0, d1, d2 = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return d0 * d0 + d1 * d1 + d2 * d2


def _rgb_dist(a, b):
    dr, dg, db = int(a[0]) - int(b[0]), int(a[1]) - int(b[1]), int(a[2]) - int(b[2])
    return 3 * dr * dr + 4 * dg * dg + 2 * db * db


def _nearest(colors, lab):
    best, bd = 0, np.inf
    for j, c in enumerate(colors):
        d = _d2(c, lab)
        if d < bd:
            bd, best = d, j
    return best


def _spread(img, h, w, y, x, err):
    for c in range(3):
        e = err[c]
        if x < w - 1:
            img[y][x + 1][c] = min(1.0, max(0.0, img[y][x + 1][c] + e * (7.0 / 16.0)))
        if y < h - 1:
            if x > 0:
                img[y + 1][x - 1][c] = min(1.0, max(0.0, img[y + 1][x - 1][c] + 0.5 * e * (3.0 / 16.0)))
            img[y + 1][x][c] = min(1.0, max(0.0, img[y + 1][x][c] + 0.5 * e * (5.0 / 16.0)))
            if x < w - 1:
                img[y + 1][x + 1][c] = min(1.0, max(0.0, img[y + 1][x + 1][c] + 0.5 * e * (1.0 / 16.0)))


class Page:
    def __init__(self, rgb, weight=None, clean=None, snap=700, seed=1):
        self.rng = np.random.default_rng(seed)
        self.src8 = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
        self.h, self.w = self.src8.shape[:2]
        self.linear = np.ascontiguousarray(srgb_to_linear(self.src8 / 255.0))
        self.src_lab = np.ascontiguousarray(oklab(self.linear, CHROMA))
        self.src_flat = np.ascontiguousarray(oklab(self.linear, FLAT_CHROMA))
        self.weight = np.ascontiguousarray(np.array(
            [[weight(x, y) if weight else 1.0 for x in range(self.w)] for y in range(self.h)], dtype=np.float64))
        flats = wp.flat([[tuple(int(v) for v in px) for px in row] for row in self.src8])
        self.flags = np.ascontiguousarray(np.array(
            [[(1 if clean and clean(x, y) else 0) | (2 if flats[y][x] else 0) for x in range(self.w)]
             for y in range(self.h)], dtype=np.uint8))
        self.snap = float(snap)
        self.lib = native_host.library()
        self.perfect = self.perfect_dither()
        self.fixed = [0x000]
        self.global_palette = self.fit_global()
        self.lines = self.init_lines()

    # -- the two loops (C, or the Python twin)

    def perfect_dither(self):
        img = self.linear.copy()
        out = np.zeros((self.h, self.w), dtype=np.int32)
        if self.lib:
            f = lambda a, t: a.ctypes.data_as(t)
            import ctypes
            P, U8, I = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_int)
            self.lib.shr_perfect(f(img, P), f(self.src_flat, P), f(self.src8, U8), f(self.flags, U8), self.h, self.w,
                                 f(LAB12, P), f(FLAT12, P), f(RGB12, U8), f(LIN12, P), CHROMA, DITHER_AMOUNT,
                                 self.snap, f(out, I))
            return out
        work = img.tolist()
        nearest = lambda table, lab: int(((table - np.array(lab)) ** 2).sum(1).argmin())
        for y in range(self.h):
            for x in range(self.w):
                flag = self.flags[y, x]
                if (flag & 1) or (self.snap > 0 and (flag & 2)):
                    word = nearest(FLAT12, self.src_flat[y, x])
                    if (flag & 1) or _rgb_dist(self.src8[y, x], RGB12[word]) <= self.snap:
                        out[y, x] = word
                        continue
                px = work[y][x]
                word = nearest(LAB12, _oklab1(px, CHROMA))
                out[y, x] = word
                err = [(px[c] - LIN12[word, c]) * DITHER_AMOUNT for c in range(3)]
                work[y][x] = [float(LIN12[word, c]) for c in range(3)]
                _spread(work, self.h, self.w, y, x, err)
        return out

    def dither(self, pals, keep=0.0):
        words = np.array(pals)
        pal_lab = np.ascontiguousarray(LAB12[words])
        pal_flat = np.ascontiguousarray(FLAT12[words])
        pal_lin = np.ascontiguousarray(LIN12[words])
        pal8 = np.ascontiguousarray(RGB12[words])
        img = self.linear.copy()
        out = np.zeros((self.h, self.w), dtype=np.int32)
        line_pal = np.zeros(self.h, dtype=np.int32)
        line_err = np.zeros(self.h, dtype=np.float64)
        if self.lib:
            import ctypes
            P, U8, I = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_int)
            f = lambda a, t: a.ctypes.data_as(t)
            total = ctypes.c_double()
            self.lib.shr_dither(f(img, P), f(self.src_lab, P), f(self.src_flat, P), f(self.src8, U8), f(self.flags, U8),
                                f(self.weight, P), self.h, self.w, f(pal_lab, P), f(pal_flat, P), f(pal_lin, P), f(pal8, U8),
                                CHROMA, DITHER_AMOUNT, CANDIDATES, self.snap, keep, f(out, I), f(line_pal, I),
                                f(line_err, P), ctypes.byref(total))
            return out, line_pal.tolist(), line_err.tolist(), total.value
        work = img.tolist()
        plab, pflat, plin = pal_lab.tolist(), pal_flat.tolist(), pal_lin.tolist()
        total = 0.0
        for y in range(self.h):
            line = np.array([_oklab1(px, CHROMA) for px in work[y]])
            near_d = ((line[:, None, None, :] - pal_lab[None]) ** 2).sum(3).min(2)
            cost = []
            for p in range(16):
                s = 0.0
                for x in range(self.w):
                    s += near_d[x, p] * self.weight[y, x]
                cost.append(s)
            p = min(range(16), key=lambda q: (cost[q], q))
            if y and keep > 0 and cost[line_pal[y - 1]] <= cost[p] * (1.0 + keep):
                p = int(line_pal[y - 1])
            line_pal[y], line_err[y] = p, cost[p]
            for x in range(self.w):
                sd = [_d2(self.src_lab[y, x], c) for c in plab[p]]
                order = sorted(range(16), key=lambda j: (sd[j], j))
                near = order[0]
                flat = self.snap > 0 and (self.flags[y, x] & 2)
                if flat:
                    near = _nearest(pflat[p], self.src_flat[y, x].tolist())
                if (self.flags[y, x] & 1) or (flat and _rgb_dist(self.src8[y, x], pal8[p, near]) <= self.snap):
                    out[y, x] = near
                    total += sd[near] * self.weight[y, x]
                    continue
                px = work[y][x]
                lab = _oklab1(px, CHROMA)
                best, bi = 1e9, near
                for j in (order[:CANDIDATES] if CANDIDATES else range(16)):
                    d = _d2(lab, plab[p][j])
                    if d < best:
                        best, bi = d, j
                out[y, x] = bi
                total += best * self.weight[y, x]
                err = [(px[c] - plin[p][bi][c]) * DITHER_AMOUNT for c in range(3)]
                work[y][x] = list(plin[p][bi])
                _spread(work, self.h, self.w, y, x, err)
        return out, line_pal.tolist(), line_err.tolist(), total

    # -- the palette search

    def samples(self, lines):
        px = self.perfect[lines].ravel()
        wt = self.weight[lines].ravel()
        words, inverse, counts = np.unique(px, return_inverse=True, return_counts=True)
        return words, np.bincount(inverse, weights=wt), counts, px, wt

    def fit_global(self):
        words, weights, _, _, _ = self.samples(list(range(self.h)))
        labs = LAB12[words]
        cents = [0x000]
        while len(cents) < 16:
            d = np.min([((labs - LAB12[c]) ** 2).sum(1) for c in cents], 0) * weights
            cents.append(int(words[d.argmax()]))
        return kmeans_fixed(words, weights, cents, 1)

    def init_lines(self):
        overlap = (16 * BAND_LINES - self.h) / 15
        return {p: list(range(int(round(p * (BAND_LINES - overlap))),
                              min(self.h, int(round(p * (BAND_LINES - overlap) + BAND_LINES))))) for p in range(16)}

    def fit_palettes(self):
        pals = []
        for p in range(16):
            words, weights, counts, px, wt = self.samples(self.lines.get(p) or [0])
            fixed = list(self.fixed)
            init = fixed + list(self.global_palette[len(fixed):])
            seen = set(fixed)
            for i in range(len(fixed), 16):
                pick = int(px[self.rng.choice(len(px), p=wt / wt.sum())])
                if pick not in seen:
                    seen.add(pick)
                    init[i] = pick
            n_fixed = len(fixed)
            for i in np.argsort(-counts, kind='stable'):
                if counts[i] < 0.1 * counts.sum() or n_fixed == 16:
                    break
                if int(words[i]) not in seen:
                    seen.add(int(words[i]))
                    init[n_fixed] = int(words[i])
                    n_fixed += 1
            pal = list(dict.fromkeys(kmeans_fixed(words, weights, init, n_fixed)))
            for i in np.argsort(-weights, kind='stable'):
                if len(pal) == 16:
                    break
                if int(words[i]) not in pal:
                    pal.append(int(words[i]))
            while len(pal) < 16:
                word = int(self.rng.integers(1, 4096))
                if word not in pal:
                    pal.append(word)
            pals.append(pal)
        return pals

    def iterate(self, steps=STEPS, max_inner=10):
        """ii-pix's loop with a fixed number of steps; returns the best (idx, line_pal, pals, error)."""
        best = None
        inner = 0
        self.lines = self.init_lines()
        for _ in range(steps):
            if inner >= max_inner:
                self.lines = self.init_lines()
                inner = 0
            pals = self.fit_palettes()
            out, line_pal, line_err, total = self.dither(pals)
            lines = defaultdict(list)
            for y, p in enumerate(line_pal):
                lines[p].append(y)
            worst = [y for _, y in sorted(zip(line_err, range(self.h)))]
            keys = set()
            for p in range(16):
                key = frozenset(pals[p])
                if p not in lines or key in keys:
                    lines[p] = [worst.pop()]
                keys.add(key)
            self.lines = dict(lines)
            if best is None or total < best[3]:
                best, inner = (out, line_pal, pals, total), 0
            else:
                inner += 1
        return best


def average_grays(pals, line_pal):
    """The best average grays of a first pass: for each loading-box role (shared_gray.BOX_GRAYS), every
    used palette's nearest color to the role's gray, their lightness averaged over the rows of each
    palette, as the nearest pure IIgs gray, kept in the role's range and darker than the role before.
    pals: 12-bit words."""
    from shared_gray import BOX_GRAYS
    rows = np.bincount(line_pal, minlength=len(pals))
    locked, below = {}, 16
    for slot, (target, low, high) in BOX_GRAYS.items():
        gray = target * 0x111
        total = weight = 0.0
        for p, pal in enumerate(pals):
            if rows[p]:
                near = min(pal, key=lambda c: (float(((LAB12[c] - LAB12[gray]) ** 2).sum()), c))
                total += LAB12[near][0] * rows[p]
                weight += rows[p]
        fits = [g for g in range(low, high + 1) if g < below]
        below = min(fits, key=lambda g: (abs(LAB12[g * 0x111][0] - total / weight), -g))
        locked[slot] = below * 0x111
    return locked


def locked_fixed(pals, line_pal):
    """Black and a first pass's best average grays (8-bit RGB), the fixed colors of its second pass."""
    locked = average_grays(pals, line_pal)
    return ((0, 0, 0),) + tuple(tuple(int(v) for v in RGB12[locked[s]]) for s in (1, 12, 13, 14))


def convert(rgb, weight=None, clean=None, snap=700):
    """Two full passes: the second fixes black and the first pass's best average grays in every
    palette. Returns (row_pal, pals of 8-bit RGB, idx rows, locked grays)."""
    page = Page(rgb, weight, clean, snap)
    _, line1, pals1, _ = page.iterate()
    locked = average_grays(pals1, line1)
    page.fixed = [0x000, locked[1], locked[12], locked[13], locked[14]]
    out, line2, pals2, _ = page.iterate()
    pals8 = [[tuple(int(v) for v in RGB12[w]) for w in pal] for pal in pals2]
    return line2, pals8, out.tolist(), locked


def measure_bands(src_rgb, out_rgb):
    """Lines the source lacks: after a 3x3 blur, the vertical OKLab change of the output beyond the
    source's (less 0.01), summed over the page."""
    def blur(a):
        pad = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode='edge')
        return sum(pad[dy:dy + a.shape[0], dx:dx + a.shape[1]] for dy in range(3) for dx in range(3)) / 9
    s = blur(oklab(srgb_to_linear(np.asarray(src_rgb, dtype=np.float64) / 255), 1.0))
    o = blur(oklab(srgb_to_linear(np.asarray(out_rgb, dtype=np.float64) / 255), 1.0))
    dv_s = np.linalg.norm(s[1:] - s[:-1], axis=2)
    dv_o = np.linalg.norm(o[1:] - o[:-1], axis=2)
    return float(np.clip(dv_o - dv_s - 0.01, 0, None).sum())
