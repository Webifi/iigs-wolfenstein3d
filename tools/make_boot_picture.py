#!/usr/bin/env python3
"""Full-color PNG to SHR: linear area reduction, RGB12 OKLab fitting and diffusion.

Usage: make_boot_picture.py PICTURE.png [OUT.shr [PREVIEW.png]]
Fifteen palettes share the art rows; palette 15 and rows 191-199 are the loader.
There is no intermediate indexed image. Requires numpy and Pillow.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path
from source_identity import source_bytes
import numpy as np
from PIL import Image
import gscolor
import memmap

HEIGHT = memmap.SHR_SCB_SIZE
WIDTH = memmap.SHR_SIZE * 2 // HEIGHT
ART_ROWS = gscolor.STRIP_ROW0
SCB = memmap.SHR_SCB - memmap.SHR
PAL = memmap.SHR_PAL - memmap.SHR
RECORD_BYTES = memmap.SHR_PAL_END - memmap.SHR
PALETTES = gscolor.STRIP_PAL


def read_png(path):
    with Image.open(path) as image:
        if image.format != 'PNG':
            raise ValueError('boot artwork must be a PNG')
        image = image.convert('RGB')
        w, h = image.size
        return w, h, 3, np.asarray(image).reshape(h, w*3)


def write_png(path, w, h, rows):
    Image.frombytes('RGB', (w, h), b''.join(bytes(row) for row in rows)).save(path)


def linear(rgb):
    return np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)


def oklab(rgb):
    r, g, b = np.moveaxis(rgb, -1, 0)
    l = np.cbrt(.4122214708*r + .5363325363*g + .0514459929*b)
    m = np.cbrt(.2119034982*r + .6806995451*g + .1073969566*b)
    s = np.cbrt(.0883024619*r + .2817188376*g + .6299787005*b)
    # Chroma weighting is included in the coordinates used by every search.
    return np.stack((.2104542553*l + .7936177850*m - .0040720468*s,
                     1.5*(1.9779984951*l - 2.4285922050*m + .4505937099*s),
                     1.5*(.0259040371*l + .7827717662*m - .8086757660*s)), axis=-1)


GRID_RGB = np.indices((16, 16, 16)).reshape(3, -1).T.astype(np.float32)/15
GRID_LAB = oklab(linear(GRID_RGB))


def screen_shape(w, h, bpp, rows):
    rows = np.asarray(rows, dtype=np.uint8).reshape(h, w, bpp)
    if w*HEIGHT > h*WIDTH:
        target = h*WIDTH//HEIGHT
        rows = rows[:, (w-target)//2:(w-target)//2+target]
    elif w*HEIGHT < h*WIDTH:
        target = w*HEIGHT//WIDTH
        rows = rows[(h-target)//2:(h-target)//2+target]
    h, w = rows.shape[:2]
    return w, h, bpp, rows.reshape(h, w*bpp)


def shrink_linear(w, h, bpp, rows, tw=WIDTH, th=HEIGHT):
    """Area filtering retains floating-point linear RGB through palette fitting."""
    rgb = np.asarray(rows, dtype=np.uint8).reshape(h, w, bpp)[..., :3]
    rgb = linear(rgb.astype(np.float32)/255)
    if h % th == 0 and w % tw == 0:
        return rgb.reshape(th, h//th, tw, w//tw, 3).mean(axis=(1, 3))
    def weights(source, target):
        edges = np.arange(target+1, dtype=np.float32)*source/target
        pixel = np.arange(source, dtype=np.float32)
        return np.maximum(0, np.minimum(edges[1:, None], pixel+1) -
                          np.maximum(edges[:-1, None], pixel))*target/source
    vertical = np.einsum('yh,hxc->yxc', weights(h, th), rgb, optimize=True)
    return np.einsum('xw,ywc->yxc', weights(w, tw), vertical, optimize=True)


def distance(a, b):
    return ((a[:, None, 0]-b[None, :, 0])**2 +
            (a[:, None, 1]-b[None, :, 1])**2 +
            (a[:, None, 2]-b[None, :, 2])**2)


def fit_palette(points, centers=None, rounds=8):
    """Fit full-precision centroids, then choose their nearest actual RGB12 colors."""
    if centers is None:
        centers = np.zeros((16, 3), dtype=np.float32)
        error = (points*points).sum(axis=1)
        for k in range(1, 16):
            centers[k] = points[error.argmax()]
            error = np.minimum(error, ((points-centers[k])**2).sum(axis=1))
    for _ in range(rounds):
        costs = distance(points, centers)
        labels = costs.argmin(axis=1)
        counts = np.bincount(labels, minlength=16)
        means = centers.copy()
        for channel in range(3):
            sums = np.bincount(labels, weights=points[:, channel], minlength=16)
            np.divide(sums, counts, out=means[:, channel], where=counts > 0)
        means[0] = 0
        next_centers = means
        if np.array_equal(next_centers, centers):
            break
        centers = next_centers
    indices = distance(centers, GRID_LAB).argmin(axis=1)
    # A lattice collision must not waste a palette entry. Split the largest
    # remaining error using an unused hardware color.
    used = set()
    for i, index in enumerate(indices):
        if index in used:
            cost = distance(points, GRID_LAB[list(used)]).min(axis=1)
            order = distance(points[cost.argmax():cost.argmax()+1], GRID_LAB)[0].argsort()
            index = next(int(v) for v in order if v not in used)
            indices[i] = index
        used.add(int(index))
    return GRID_LAB[indices]


def row_costs(lab, palettes):
    points = lab[:, ::2].reshape(-1, 3)
    return np.stack([distance(points, pal).min(axis=1).reshape(len(lab), -1).mean(axis=1)
                     for pal in palettes], axis=1)


def fit_rows(lab):
    groups = np.arange(len(lab))*PALETTES//len(lab)
    palettes = np.stack([fit_palette(lab[groups == p, ::2].reshape(-1, 3)) for p in range(PALETTES)])
    for _ in range(5):
        chosen = row_costs(lab, palettes).argmin(axis=1)
        if np.array_equal(chosen, groups):
            break
        groups = chosen
        for p in range(PALETTES):
            rows = lab[groups == p, ::2]
            if len(rows):
                palettes[p] = fit_palette(rows.reshape(-1, 3), palettes[p])
    # Every source pixel participates in the final fit; the alternating search
    # samples columns only to keep repeated row-assignment passes small.
    for p in range(PALETTES):
        rows = lab[groups == p]
        if len(rows):
            palettes[p] = fit_palette(rows.reshape(-1, 3), palettes[p])
    groups = row_costs(lab, palettes).argmin(axis=1)
    words = distance(palettes.reshape(-1, 3), GRID_LAB).argmin(axis=1).reshape(PALETTES, 16)
    return words, groups


def diffuse(rgb, words, groups):
    """Serpentine Floyd-Steinberg in display RGB, against exact RGB12 colors."""
    height, width = rgb.shape[:2]
    errors = np.zeros((height+1, width+2, 3), dtype=np.float32)
    pixels = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    display_palettes = GRID_RGB[words]
    for y in range(height):
        step = 1 if y % 2 == 0 else -1
        columns = range(width) if step == 1 else range(width-1, -1, -1)
        output_rgb = display_palettes[groups[y]]
        for x in columns:
            value = np.clip(rgb[y, x] + errors[y, x+1], 0, 1)
            difference = output_rgb - value
            index = (difference* difference * (3, 6, 1)).sum(axis=1).argmin()
            pixels[y, x] = index
            error = value - output_rgb[index]
            errors[y, x+1+step] += error*(7/16)
            errors[y+1, x+1-step] += error*(3/16)
            errors[y+1, x+1] += error*(5/16)
            errors[y+1, x+1+step] += error*(1/16)
    return pixels


def picture_record(cover):
    small = shrink_linear(*screen_shape(*cover))[:ART_ROWS]
    lab = oklab(small)
    words, groups = fit_rows(lab)
    display = np.where(small <= .0031308, 12.92*small, 1.055*small**(1/2.4)-.055)
    pixels = diffuse(display, words, groups)
    record = bytearray(RECORD_BYTES)
    record[:memmap.SHR_SIZE] = ((pixels[:, ::2] << 4) | pixels[:, 1::2]).tobytes()
    record[SCB:SCB+ART_ROWS] = groups.astype(np.uint8).tobytes()
    record[SCB+ART_ROWS:SCB+HEIGHT] = bytes([gscolor.STRIP_PAL])*(HEIGHT-ART_ROWS)
    for p in range(PALETTES):
        struct.pack_into('<16H', record, PAL+p*32, *words[p])
    strip = [gscolor.word12(c) for c in gscolor.STRIP_COLORS]
    struct.pack_into('<16H', record, PAL+gscolor.STRIP_PAL*32, *(strip+[0]*(16-len(strip))))
    return bytes(record)


def preview(record, path, scale=2):
    pixels = np.frombuffer(record[:memmap.SHR_SIZE], dtype=np.uint8).reshape(HEIGHT, WIDTH//2)
    indices = np.stack((pixels >> 4, pixels & 15), axis=-1).reshape(HEIGHT, WIDTH)
    rows = np.frombuffer(record[SCB:SCB+HEIGHT], dtype=np.uint8) & 15
    palette = np.frombuffer(record[PAL:PAL+memmap.SHR_PAL_SIZE], dtype='<u2').reshape(16, 16)
    colors = palette[rows[:, None], indices]
    rgb = np.stack(((colors >> 8) & 15, (colors >> 4) & 15, colors & 15), axis=-1).astype(np.uint8)*17
    image = Image.fromarray(rgb)
    if scale != 1:
        image = image.resize((WIDTH*scale, HEIGHT*scale), Image.Resampling.NEAREST)
    image.save(path)


def source_path(root, key):
    from game_profile import read_toml
    recipe = read_toml(root/'profiles/native'/f'{key}.toml')
    source = recipe.get('boot_picture', {}).get('source', 'data/boot-picture.png')
    path = (root/source).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix.lower() != '.png':
        raise ValueError('boot_picture.source must name a PNG inside the project')
    return path


def build(root, key):
    """Generate the raw and slot-aligned records from the selected PNG."""
    from shared_gray import picture
    source = source_path(root, key)
    raw = picture_record(read_png(source))
    out = root/'build/assets'
    out.mkdir(parents=True, exist_ok=True)
    (out/'boot-picture.shr').write_bytes(raw)
    aligned = picture(raw, boot=True)
    (out/'boot-shared.shr').write_bytes(aligned)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    receipt = dict(source=str(source.relative_to(root.resolve())), source_sha256=digest(source.read_bytes()),
                   converter_sha256=digest(source_bytes(Path(__file__))),
                   shr_sha256=digest(raw), aligned_sha256=digest(aligned))
    (out/'boot-picture.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def main():
    source = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1]/'build/assets/boot-picture.shr'
    record = picture_record(read_png(source))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(record)
    print('wrote', out, len(record), 'bytes')
    if len(sys.argv) > 3:
        preview(record, sys.argv[3])


if __name__ == '__main__':
    main()
