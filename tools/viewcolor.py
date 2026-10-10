"""Offline OKLab palette fitting and four-color symbol selection.
"""
import math
import functools
import native_host
CHROMA=2.0
LAMBDA=0.08

def _lin(v):
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


LIN = [_lin(i) for i in range(256)]
LIN4 = [LIN[v * 17] for v in range(16)]


def oklab_lin(r, g, b):
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab8(c):
    return oklab_lin(LIN[c[0]], LIN[c[1]], LIN[c[2]])


def lab12(c):
    return _lab12(tuple(c))


@functools.lru_cache(maxsize=4096)
def _lab12(c):
    return oklab_lin(LIN4[c[0]], LIN4[c[1]], LIN4[c[2]])


def dist(a, b):
    return 100 * math.sqrt((a[0] - b[0]) ** 2 + CHROMA * CHROMA * ((a[1] - b[1]) ** 2 +
                                                                  (a[2] - b[2]) ** 2))


def mean_lin(cols, ws):
    t = sum(ws)
    return oklab_lin(*(sum(LIN4[c[i]] * w for c, w in zip(cols, ws)) / t for i in range(3)))


def to_srgb(v):
    v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return max(0, min(255, int(round(255 * v))))


class Metric:
    """The error of a color against a target and the noise of two colors
    side by side (see above)."""

    def __init__(self, cfg):
        self.ekc, self.ekh, self.d0 = cfg['err_kc'], cfg['err_kh'], cfg['err_d0']
        self.nkc, self.hk = cfg['noise_kc'], cfg['hue_k']

    @staticmethod
    def parts(a, b):
        dl = a[0] - b[0]
        dc = math.hypot(a[1], a[2]) - math.hypot(b[1], b[2])
        dab2 = (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
        return dl * dl, dc * dc, max(0.0, dab2 - dc * dc)

    def noise(self, a, b):
        l2, c2, h2 = self.parts(a, b)
        return 100 * math.sqrt(l2 + self.nkc * self.nkc * c2 + self.hk * self.hk * h2)

    def err(self, t, m):
        """The error in the table: plain."""
        l2, c2, h2 = self.parts(t, m)
        return 100 * math.sqrt(l2 + self.ekc * self.ekc * c2 + self.ekh * self.ekh * h2)

    def err_search(self, t, m):
        """The error in the palette search: a large miss counts more."""
        d = self.err(t, m)
        return d + d * d / self.d0 if self.d0 else d


FIXED = ((0, 0, 0), (13, 13, 13))  # black and a white
_GRID = []


def grid():
    if not _GRID:
        _GRID.extend(((r, g, b), lab12((r, g, b))) for r in range(16) for g in range(16) for b in range(16))
    return _GRID


@functools.lru_cache(maxsize=4096)
def nearest(lab):
    if native_host.library():
        picked = native_host.nearest3([lab], [g[1] for g in grid()], 2, chroma=CHROMA)[0][0]
        return grid()[picked][0]
    return min(grid(), key=lambda g: dist(g[1], lab))[0]


def kmeans(items, k=16, rounds=30, fixed=FIXED):
    nf = len(fixed)
    native = native_host.library()
    points = [item[0] for item in items]
    centers = [lab12(c) for c in fixed]
    while len(centers) < k:
        if native:
            costs = native_host.nearest3(points, centers, 2, chroma=CHROMA)[1]
            centers.append(items[max(range(len(items)), key=lambda i: items[i][1]*costs[i]**2)][0])
        else:
            centers.append(max(items, key=lambda it: it[1] * min(dist(it[0], c) ** 2 for c in centers))[0])
    for _ in range(rounds):
        sums = [[0.0, 0.0, 0.0, 0.0] for _ in range(k)]
        choices = native_host.nearest3(points, centers, 2, chroma=CHROMA)[0] if native else None
        for number, (lab, w) in enumerate(items):
            j = choices[number] if native else min(range(k), key=lambda i: dist(lab, centers[i]))
            s = sums[j]
            for i in range(3):
                s[i] += lab[i] * w
            s[3] += w
        centers = centers[:nf] + [(s[0] / s[3], s[1] / s[3], s[2] / s[3]) if s[3] else centers[j]
                                  for j, s in enumerate(sums) if j >= nf]
    return list(fixed) + [nearest(c) for c in centers[nf:]]


class Search:
    """The palette search over the clean mixes (one color, two colors 50/50
    or 75/25)."""

    def __init__(self, targets, metric, solid_targets=None):
        tw = sum(w for _, w, _ in targets)
        self.targets = [(t, w / tw, lam) for t, w, lam in targets]
        self.mt = metric
        self.solid = [False] * len(targets) if solid_targets is None else list(solid_targets)
        if len(self.solid) != len(targets):
            raise ValueError('solid target flags must match palette targets')
        self.cache = {}
        self.allowed = lambda k, c: True
        self.native_targets = native_host.targets(self.targets, self.solid) if native_host.library() else None
        self.native_costs = {}

    def mixes_of(self, P, k, others):
        labs = [lab12(c) for c in P]
        out = [(labs[k], 0.0)]
        for j in others:
            if j == k:
                continue
            key = (P[k], P[j])
            if key not in self.cache:
                s = self.mt.noise(labs[k], labs[j])
                self.cache[key] = (mean_lin([P[k], P[j]], [1, 1]), mean_lin([P[k], P[j]], [3, 1]),
                                   mean_lin([P[k], P[j]], [1, 3]), s)
            m50, m75, m25, s = self.cache[key]
            out += [(m50, s), (m75, s), (m25, s)]
        return out

    def all_mixes(self, P, idx):
        out = []
        for a in idx:
            out += self.mixes_of(P, a, [b for b in idx if b > a])
        return out

    def best(self, mixes, solids):
        if self.native_targets is not None:
            return native_host.best_reusing(self.native_targets, mixes, solids, self.mt, self.native_costs)
        e = self.mt.err_search
        return [min(e(t, m) + lam * s for m, s in (solids if solid else mixes))
                for (t, w, lam), solid in zip(self.targets, self.solid)]

    def run(self, P, rounds=30):
        P = list(P)
        n, nf = len(P), len(FIXED)
        cur = sum(t[1] * c for t, c in zip(self.targets,
                  self.best(self.all_mixes(P, range(n)), [(lab12(c), 0) for c in P])))
        e = self.mt.err_search
        for _ in range(rounds):
            improved = False
            for k in range(nf, n):
                others = [j for j in range(n) if j != k]
                base = self.best(self.all_mixes(P, others), [(lab12(P[j]), 0) for j in others])
                cands = []
                for ch in range(3):
                    for step in (-2, -1, 1, 2):
                        v = P[k][ch] + step
                        if 0 <= v <= 15:
                            c = list(P[k])
                            c[ch] = v
                            cands.append(tuple(c))
                # jumps: to the targets served worst without k
                worst = sorted(range(len(self.targets)), key=lambda i: (-self.targets[i][1] * base[i], i))[:3]
                for i in worst:
                    c = nearest(self.targets[i][0])
                    if c not in P and c not in cands:
                        cands.append(c)
                best_c, best_v = None, cur
                for c in cands:
                    if not self.allowed(k, c):
                        continue
                    Q = P[:k] + [c] + P[k + 1:]
                    mine = self.mixes_of(Q, k, others)
                    if self.native_targets is not None:
                        v = native_host.score_reusing(self.native_targets,mine,mine[:1],self.mt,self.native_costs,base)
                    else:
                        v = 0.0
                        for (t, w, lam), b, solid in zip(self.targets, base, self.solid):
                            x = min(e(t, m) + lam * s for m, s in (mine[:1] if solid else mine))
                            v += w * (x if x < b else b)
                    if v < best_v - 1e-9:
                        best_c, best_v = c, v
                if best_c is not None:
                    P[k] = best_c
                    cur = best_v
                    improved = True
            if not improved:
                break
        return P


# ---- mixes of 4

class Mixes:
    def __init__(self, P, metric):
        self.P = P
        self.mt = metric
        labs = [lab12(c) for c in P]
        n = len(P)
        self.mixes = []
        noises = [[metric.noise(a,b) for b in labs] for a in labs]
        for a in range(n):
            for b in range(a, n):
                for c in range(b, n):
                    for d in range(c, n):
                        q = (a, b, c, d)
                        spread = max(noises[i][j] for i in q for j in q)
                        self.mixes.append((mean_lin([P[i] for i in q], [1, 1, 1, 1]), spread, q))
        self.lightness = [l[0] for l in labs]
        self.pairs = [e for e in self.mixes if e[2][0] == e[2][1] and e[2][2] == e[2][3]]
        self.pair_cache = {}
        self.byte_cache = {}
        self.native_mixes = native_host.mixes([(lab, noise) for lab, noise, _ in self.mixes]) if native_host.library() else None

    def pair_for(self, rgb):
        """The best mix with a = b and c = d, as a pair byte p << 4 | q."""
        rgb = tuple(rgb)
        if rgb in self.pair_cache:
            return self.pair_cache[rgb]
        t = oklab8(rgb)
        _, _, q = min(self.pairs, key=lambda e: dist(t, e[0]) + LAMBDA * e[1])
        result = (q[0] << 4) | q[2]
        self.pair_cache[rgb] = result
        return result

    def bytes_for(self, rgb, lam):
        key = (tuple(rgb), lam)
        if key in self.byte_cache:
            return self.byte_cache[key]
        t = oklab8(rgb)
        err = self.mt.err
        if self.native_mixes is not None:
            _, _, q = self.mixes[native_host.pick(self.native_mixes, len(self.mixes), t, lam, self.mt)]
        else:
            _, _, q = min(self.mixes, key=lambda e: err(t, e[0]) + lam * e[1])
        a, b, c, d = sorted(q, key=lambda i: self.lightness[i])
        result = (a << 4) | d, (c << 4) | b
        self.byte_cache[key] = result
        return result
