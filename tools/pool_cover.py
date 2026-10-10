"""Build-time coverage for thin floor sprites.

Short heights keep the rows that overlap a floor mark. A parallel copy of
the short scalers lives at the same offsets in bank 4. Light rows preserve
their integrated contrast as a continuous central span in the available
floor/white pair. Nothing here runs per frame.
"""
import json
from wolfdata import palette, sprite, vswap
from wolf_source import sprite_ids
from viewgeometry import HEIGHTS

LIGHT_GRAYS = {21, 22, 23, 24}


def _e(h, tex):
    return max(0, min(160, 80 - h // 2 + (tex * h + 63) // 64))


def endpoint_bytes(h, starts):
    """Screen rows for each feature start. Tall heights use the point-sample ends."""
    out = {}
    if h >= 64:
        end = _e(h, 64)
        for start in starts:
            out[start] = (_e(h, start), end)
    else:
        origin = 80 - h // 2
        end = origin + h
        for start in starts:
            out[start] = (origin + (start * h) // 64, end)
    return out


def _weights(h, row):
    """Overlap of one screen row with each source texel, in units of 1/h."""
    origin = 80 - h // 2
    r = row - origin
    lo, hi = r * 64, (r + 1) * 64
    weights = [0] * 64
    for tex in range(64):
        weights[tex] = max(0, min(hi, (tex + 1) * h) - max(lo, tex * h))
    return weights


def _band(rows):
    """A bottom band of at most six rows, split from the body by an empty row."""
    if not rows or max(rows) < 32:
        return None
    hi = max(rows)
    lo = hi
    while lo > 0 and lo - 1 in rows:
        lo -= 1
    if hi - lo + 1 > 6 or lo == 0 or lo - 1 in rows:
        return None
    return lo, hi + 1


def _misses(art_rows, start, end):
    for h in HEIGHTS:
        if h >= 64:
            continue
        origin = 80 - h // 2
        hit = False
        for row in range(max(0, origin), min(160, origin + h)):
            tex = max(0, min(63, (row - origin) * 64 // h))
            if start <= tex < end:
                hit = True
                break
        if not hit:
            return True
    return False


def _body_rows(h, spans):
    covered = set()
    for start, end in spans:
        a, b = _e(h, start), _e(h, end)
        covered.update(range(a, b))
    return covered


def classify():
    """Page id -> (feature start, feature end, 'light' or 'color').

    A sprite is included when a thin bottom band disappears at some short
    height and its screen rows never share a scaler row with its own body
    or with a light already included. Shareware has no red-light sprite.
    """
    ids = sprite_ids()
    pages, base, _ = vswap()
    found = {}
    arts = {}
    for name, page in ids.items():
        if page >= len(pages) - base or not pages[base + page]:
            continue
        try:
            art = sprite(pages[base + page])
        except ValueError:
            continue
        rows = set()
        for col in art['columns']:
            for a, b, _raw in col:
                rows.update(range(a, b))
        band = _band(rows)
        if not band or not _misses(rows, *band):
            continue
        grays = set()
        for col in art['columns']:
            for a, b, raw in col:
                for tex, pix in enumerate(raw, a):
                    if band[0] <= tex < band[1]:
                        grays.add(pix)
        kind = 'light' if grays and grays <= LIGHT_GRAYS else 'color'
        found[page] = (band[0], band[1], kind, name)
        arts[page] = art
    # Lights first: their bodies define rows the shared scaler must not retarget.
    lights = [p for p, info in found.items() if info[2] == 'light']
    others = [p for p in found if p not in lights]
    kept = {}

    def bodies(page, feature):
        spans = []
        for col in arts[page]['columns']:
            for a, b, _raw in col:
                if b <= feature[0] or a >= feature[1]:
                    spans.append((a, b))
                else:
                    if a < feature[0]:
                        spans.append((a, feature[0]))
                    if b > feature[1]:
                        spans.append((feature[1], b))
        return spans

    # patch rows are retargeted in the shared scaler. A sprite's own body, and
    # any body already included, must not execute one of those rows.
    patch = {h: set() for h in HEIGHTS if h < 64}
    drawn = {h: set() for h in HEIGHTS if h < 64}
    short = [h for h in HEIGHTS if h < 64]
    for page in lights + others:
        start, end, kind, name = found[page]
        spans = bodies(page, (start, end))
        cov = {h: set(range(*endpoint_bytes(h, [start])[start])) for h in short}
        body = {h: _body_rows(h, spans) for h in short}
        if any(cov[h] & body[h] or cov[h] & drawn[h] or body[h] & patch[h] for h in short):
            continue
        for h in short:
            patch[h] |= cov[h]
            drawn[h] |= body[h]
        kept[page] = (start, end, kind, name)
    return kept


_PAGES = None


def pages():
    global _PAGES
    if _PAGES is None:
        _PAGES = classify()
    return _PAGES


def feature_starts():
    return sorted({info[0] for info in pages().values()})


def endpoint_pair():
    """Feature start -> (low endpoint index, high endpoint index)."""
    pairs = {}
    index = 200
    for start in feature_starts():
        pairs[start] = (index, index + 1)
        index += 2
    if index > 254:
        raise ValueError('pool endpoint indices collide with the page')
    return pairs


def page_endpoints():
    """Page id -> (endpoint low, endpoint high, kind)."""
    pairs = endpoint_pair()
    return {page: (pairs[start][0], pairs[start][1], kind)
            for page, (start, end, kind, _name) in pages().items()}


class Plan:
    def __init__(self):
        self.starts = feature_starts()
        self.pairs = endpoint_pair()
        self.by_page = page_endpoints()
        self.slot = {}
        self.weights = {}
        for h in HEIGHTS:
            if h >= 64:
                continue
            rows = sorted({r for start in self.starts
                           for r in range(*endpoint_bytes(h, [start])[start])})
            for row in rows:
                slot = 64 + len(self.weights)
                self.slot[h, row] = slot
                self.weights[slot] = tuple(_weights(h, row))
        self.strip_size = 64 + len(self.weights)

    def endpoints_for(self, h):
        """256-byte endpoint page additions: index -> screen row."""
        ends = endpoint_bytes(h, self.starts)
        out = {}
        for start, (low, high) in self.pairs.items():
            a, b = ends[start]
            out[low] = a
            out[high] = b
        return out

    def span(self, h, low):
        ends = self.endpoints_for(h)
        high = low + 1
        return ends[low], ends[high]


_PLAN = None


def plan():
    global _PLAN
    if _PLAN is None:
        _PLAN = Plan()
    return _PLAN


def used_indices():
    data, base, _ = vswap()
    used = set()
    for page in sprite_ids().values():
        if page >= len(data) - base or not data[base + page]:
            continue
        try:
            art = sprite(data[base + page])
        except ValueError:
            continue
        for col in art['columns']:
            for _a, _b, raw in col:
                used.update(raw)
    return used


class Colors:
    """Unused source indices encode floor-relative pairs in all stored light copies."""
    def __init__(self, sprite_lights, palette, floor):
        self.tables = sprite_lights
        self.palette = palette
        self.floor = floor
        used = used_indices()
        self.free = [i for i in range(255, -1, -1) if i not in used]
        self.pairs = {}
        self.gray = self.index(floor, floor)
        self.light = self.index(1, floor)
        self.mix_pairs = [(a,b) for a in range(16) for b in range(a,16)]
        self.averages = [tuple((x+y)/2 for x,y in zip(palette[a],palette[b])) for a,b in self.mix_pairs]
        self.noise = [sum((x-y)**2 for x,y in zip(palette[a],palette[b]))*.035 for a,b in self.mix_pairs]

    def index(self, a, b):
        pair = ((a << 4) | b, (b << 4) | a)
        if pair not in self.pairs:
            if not self.free:
                raise ValueError('floor marks exhausted unused sprite colors')
            i = self.free.pop(0)
            self.pairs[pair] = i
            for table in self.tables:
                table[i] = pair
        return self.pairs[pair]

    def nearest(self, rgb):
        return self.nearest_many([rgb])[0]

    def nearest_many(self, rgbs):
        import native_host
        if native_host.library():
            chosen = native_host.nearest3(rgbs, self.averages, False, self.noise)[0]
        else:
            chosen = [min(range(len(self.mix_pairs)), key=lambda i:
                          sum((x-y)**2 for x,y in zip(self.averages[i],rgb))+self.noise[i]) for rgb in rgbs]
        return [self.index(*self.mix_pairs[i]) for i in chosen]


def strips(columns, feature, colors):
    """One source strip per column; slots 64 and up hold filtered rows."""
    start, end, kind, _ = feature
    pixels = [{y: c for a,b,raw in col for y,c in enumerate(raw,a) if start<=y<end}
              for col in columns]
    raw = palette()
    floor = colors.palette[colors.floor]
    samples = dict(plan().weights)
    for row in range(58,64):
        samples[row] = tuple(64 if y == row else 0 for y in range(64))
    result = [bytearray([colors.gray]*plan().strip_size) for _ in range(64)]
    for slot, weights in samples.items():
        total = sum(weights)
        rgb = []
        for column in pixels:
            rgb.append(tuple(sum(weights[y] * (raw[column[y]][c] if y in column else floor[c])
                                 for y in range(64)) / total for c in range(3)))
        if kind != 'light':
            for x,value in enumerate(colors.nearest_many(rgb)):
                result[x][slot] = value
    if kind == 'light':
        pair_contrast = (255 - sum(floor)/3)/2
        for h in list(range(2,64,2)) + [64]:
            rows = list(range(*endpoint_bytes(h,[start])[start]))
            expected = []
            for row in rows:
                weights = _weights(h,row)
                contrast = sum(weights[y] * max(0, sum(raw[c])/3-sum(floor)/3)
                               for column in pixels for y,c in column.items())/64
                expected.append(contrast * h / 128 / pair_contrast)
            count = int(sum(expected)+.5)
            widths = [int(v) for v in expected]
            for i in sorted(range(len(rows)), key=lambda i: expected[i]-widths[i], reverse=True)[:count-sum(widths)]:
                widths[i] += 1
            for row,width in zip(rows,widths):
                first = (h//2-width)//2
                if h < 64:
                    slot = plan().slot[h,row]
                    for col in range(first, first+width):
                        x = min(63,round(32768/h)*col//256)
                        result[x][slot] = colors.light
                else:
                    tex = row-(80-h//2)
                    for x in range(first*2, (first+width)*2):
                        result[x][tex] = colors.light
    return [bytes(row) for row in result]


def split_runs(runs, feature):
    """Body runs, plus the source texels inside the feature."""
    start, end = feature
    body = []
    pixels = {}
    for a, b, raw in runs:
        for tex, pix in enumerate(raw, a):
            if start <= tex < end:
                pixels[tex] = pix
        if b <= start or a >= end:
            body.append((a, b, raw))
            continue
        if a < start:
            body.append((a, start, raw[:start - a]))
        if b > end:
            body.append((end, b, raw[end - a:]))
    return body, pixels


def scaler_patches(directory):
    """(bank offset of the LDA, old immediate, new immediate) for bank 3."""
    chosen = plan()
    patches = []
    for h, bank, addr, top, _bottom, offsets, texels, _bounds in directory:
        if bank != 3 or h >= 64:
            continue
        for local, row in enumerate(range(top, top + len(texels))):
            slot = chosen.slot.get((h, row))
            if slot is None:
                continue
            lda = addr + offsets[local]
            old = texels[local] * 2 + (row & 1)
            new = slot * 2 + (row & 1)
            patches.append((lda, old, new))
    return patches


def describe():
    return dict(sprites=pages(), slots=len(plan().weights),
                excluded='Cage feet share scaled rows with their body; solid floor objects retain point sampling.')


if __name__ == '__main__':
    print(json.dumps(describe(), indent=2))
