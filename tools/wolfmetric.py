"""Picture error for art comparisons: mean CIELAB dE after a Gaussian blur
in linear light (sigma 1.0 pixels horizontally, 0.83 vertically). Blurring
reduces the penalty for fine dithering. Requires numpy at build time.
"""
import math

import numpy as np


def _lin(a):
    a = a / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _kernel(sigma):
    r = max(1, int(math.ceil(3 * sigma)))
    k = np.exp(-(np.arange(-r, r + 1) ** 2) / (2 * sigma * sigma))
    return k / k.sum(), r


def _blur(img, sx=1.0, sy=0.83):
    kx, rx = _kernel(sx)
    ky, ry = _kernel(sy)
    p = np.pad(img, ((0, 0), (rx, rx), (0, 0)), mode='edge')
    t = sum(kx[i] * p[:, i:i + img.shape[1], :] for i in range(len(kx)))
    p = np.pad(t, ((ry, ry), (0, 0), (0, 0)), mode='edge')
    return sum(ky[i] * p[i:i + img.shape[0], :, :] for i in range(len(ky)))


def _lab(rgb_lin):
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = rgb_lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def error_map(a_rows, b_rows):
    """dE of every pixel; a_rows and b_rows are rows of (r, g, b) of the same size."""
    a = np.asarray(a_rows, dtype=float)
    b = np.asarray(b_rows, dtype=float)
    la = _lab(_blur(_lin(a)))
    lb = _lab(_blur(_lin(b)))
    return np.sqrt(((la - lb) ** 2).sum(-1))


def _sharp(rows):
    """Mean CIELAB distance between each pixel and the same picture blurred a little more (sigma 1.5): how much
    local contrast the picture has."""
    a = np.asarray(rows, dtype=float)
    lin = _lin(a)
    return float(np.sqrt(((_lab(lin) - _lab(_blur(lin, 1.5, 1.25))) ** 2).sum(-1)).mean())


def added_noise(orig_rows, rows):
    """The local contrast that the conversion adds to the original: positive means a dither pattern or noise."""
    return _sharp(rows) - _sharp(orig_rows)
