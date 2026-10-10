"""Keep the original brown wall ramp legible in every distance-light atlas."""
import math

import viewcolor as vc


def preserve_grain(lights, source, colors, metric, gains):
    # Independent nearest-color fits collapsed every color in wall page 23
    # to $77 at medium light. Fit this source ramp together: its grain must
    # remain distinct from its background, without reversing shade order.
    labs = [vc.lab12(c) for c in colors]
    brown = vc.oklab8(source[218])
    angle = math.atan2(brown[2], brown[1])
    slots = [i for i in range(len(colors))
             if math.hypot(*labs[i][1:]) > .02
             and abs((math.atan2(labs[i][2], labs[i][1]) - angle + math.pi)
                    % math.tau - math.pi) < math.radians(35)]
    slots = [0] + sorted(slots, key=lambda i: labs[i][0])
    # Alignment permutes fitted colors. Find browns by their color, including
    # the darkest fitted shade; slot numbers do not identify their contents.
    # Adjacent brown shades avoid isolated bright/black speckles.
    symbols = [(i,) * 4 for i in slots]
    symbols += [tuple([a] * (4 - n) + [b] * n)
                for a, b in zip(slots, slots[1:]) for n in (1, 2, 3)]
    candidates = sorted(
        [(vc.mean_lin([colors[i] for i in q], [1] * 4),
          max(metric.noise(labs[i], labs[j]) for i in q for j in q), q)
         for q in symbols], key=lambda e: e[0][0])
    count = len(candidates)
    def row_light(q):
        values = [sum(w * vc.LIN4[v] for w, v in zip((.2126, .7152, .0722), colors[i]))
                  for i in q]
        return values[0] + values[3], values[1] + values[2]
    rows = [row_light(q) for _, _, q in candidates]
    grain_min = [next((k for k in range(i + 1, count)
                      if all(a > b for a, b in zip(rows[k], rows[i]))), count)
                 for i in range(count)]
    upper = [count - 1] * 16
    for light in reversed(range(len(gains))):
        targets = [vc.oklab8(tuple(vc.to_srgb(vc.LIN[v] * gains[light])
                                  for v in source[c])) for c in range(223, 207, -1)]
        costs = [[metric.err(t, lab) + .05 * noise for lab, noise, _ in candidates]
                 for t in targets]
        best = None
        for base in range(upper[0] + 1):
            states = [None] * count
            states[base] = (costs[0][base], (base,))
            for n, c in enumerate(range(222, 207, -1), 1):
                following = [None] * count
                prefix = None
                # Page 23's grain is 218 on 223; page 22 reaches 213.
                # Preserve contrast in each A/B row, not only their average.
                minimum = (max(grain_min[base], base + (3 if c <= 213 else 2))
                           if c <= 218 else base)
                for k in range(upper[n] + 1):
                    if states[k] is not None and (prefix is None or states[k][0] < prefix[0]):
                        prefix = states[k]
                    if k >= minimum and prefix is not None:
                        following[k] = (prefix[0] + costs[n][k], prefix[1] + (k,))
                states = following
            for entry in states:
                if entry is not None and (best is None or entry[0] < best[0]):
                    best = entry
        if best is None:
            raise ValueError('floor palette cannot preserve the wood shade ramp')
        upper = best[1]  # Darker light must never brighten any source color.
        for c, k in zip(range(223, 207, -1), upper):
            a, b, c2, d = candidates[k][2]
            lights[light][c] = ((a << 4) | d, (c2 << 4) | b)
