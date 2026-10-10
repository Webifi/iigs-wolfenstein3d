"""Complete floor-specific wall coverage for the offline color fitter."""
from collections import Counter

from native_map_format import wall_material


def wall_faces(tiles, sprite_start, width=64):
    """Weight source texture pages by exposed faces and actual door types.

    View sampling remains the main source of screen-area weights. This census
    supplies the art it can miss, including opposite wall sides, switched
    elevators, locked doors and door jambs. A material hidden by a pushwall or
    enclosed room still contributes one face per side, rather than vanishing.
    """
    pages = Counter()
    materials = {m for t in tiles if (m := wall_material(t)) is not None}
    for i, tile in enumerate(tiles):
        material = wall_material(tile)
        if material is not None:
            x, y = i % width, i // width
            for dx, dy, side in ((-1, 0, 1), (1, 0, 1), (0, -1, 0), (0, 1, 0)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < len(tiles) // width):
                    continue
                adjacent = tiles[ny * width + nx]
                if adjacent >= 106 or 90 <= adjacent <= 101:
                    pages[2 * (material - 1) + side] += 1
        elif 90 <= tile <= 101:
            # Ordinary, keyed, and elevator doors use different source art.
            offset = 4 if tile >= 100 else 6 if tile >= 92 else 0
            pages[sprite_start - 8 + offset + int(tile % 2 == 0)] += 2
            pages[sprite_start - 6] += 1
            pages[sprite_start - 5] += 1
    if 21 in materials:
        materials.add(22)
        for side in (0, 1):
            pages[42 + side] = max(1, pages[40 + side])
    for material in materials:
        for side in (0, 1):
            page = 2 * (material - 1) + side
            pages[page] = max(1, pages[page])
    return pages


def wall_histogram(tiles, pages, sprite_start):
    faces = wall_faces(tiles, sprite_start)
    counts = Counter()
    for page, weight in sorted(faces.items()):
        pixels = pages[page]
        if len(pixels) != 4096:
            raise ValueError(f'wall texture {page} is not 64 by 64')
        for color, count in Counter(pixels).items():
            counts[color] += count * weight
    return counts, faces


def distribution(counts):
    total = sum(counts.values())
    return {color: count / total for color, count in counts.items()} if total else {}


def world_distribution(views, walls, coverage_share):
    """Preserve view-area priorities while giving all floor wall art a vote."""
    if not 0 <= coverage_share <= 1:
        raise ValueError('wall coverage share must be between zero and one')
    if not walls:
        return distribution(views)
    if not views:
        return distribution(walls)
    result = Counter()
    for counts, share in ((views, 1 - coverage_share), (walls, coverage_share)):
        for color, fraction in distribution(counts).items():
            result[color] += fraction * share
    return result


def solid_index(rgb, colors, world):
    """Choose a flat surface's one actual RGB, independently of dither cells."""
    import viewcolor as vc
    metric = vc.Metric(dict(err_kc=world['error_chroma_weight'],
                            err_kh=world['error_hue_weight'],
                            err_d0=world['large_error_scale'],
                            noise_kc=world['noise_chroma_weight'],
                            hue_k=world['noise_hue_weight']))
    target = vc.oklab8(rgb)
    return min(range(len(colors)), key=lambda i: metric.err(target, vc.oklab8(colors[i])))


def conversion_scores(source, colors, walls, sprites, gains, domains, metric):
    """Measure the generated A/B cells, including constrained wood mappings.

    A theoretical four-color mixture is not necessarily the cell the converter
    emits. Score its actual mean and visible contrast before retaining a fit.
    Keep separate scores for sampled views, complete wall art, sprites and
    full-bright weapons so improving one cannot silently degrade another.
    """
    import viewcolor as vc
    labs = [vc.lab12(c) for c in colors]
    scores = {}
    for name, counts, kind, alpha in domains:
        weights = distribution({c: v ** alpha for c, v in counts.items()})
        for li in ([len(gains) - 1] if kind in ('weapon', 'flat') else range(len(gains))):
            table = walls[li] if kind == 'wall' else sprites[li]
            lam = .20 if kind == 'wall' else .35
            cost = 0.0
            color_error = 0.0
            for c, weight in weights.items():
                if kind == 'flat':
                    cost += weight * min(metric.err_search(vc.oklab8(source[c]), lab) for lab in labs)
                    color_error += weight * min(metric.err(vc.oklab8(source[c]), lab) for lab in labs)
                    continue
                indexes = [i for byte in table[c] for i in (byte >> 4, byte & 15)]
                mean = vc.mean_lin([colors[i] for i in indexes], [1] * 4)
                target = vc.oklab8(tuple(vc.to_srgb(vc.LIN[v] * gains[li]) for v in source[c]))
                noise = max(metric.noise(labs[i], labs[j]) for i in indexes for j in indexes)
                cost += weight * (metric.err_search(target, mean) + lam * noise)
                color_error += weight * metric.err(target, mean)
            scores[f'{name}/{li}'] = cost
            scores[f'{name}/{li}/color'] = color_error
    return scores


def no_regression(before, after):
    return before.keys() == after.keys() and all(after[k] <= before[k] + 1e-9 for k in before)
