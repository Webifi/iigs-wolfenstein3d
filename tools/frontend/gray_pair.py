"""Menu gray pair tables. One table per loaded palette, built at build time.

Lightness is 3*R + 6*G + B on the 4-bit channels (0..150). The five menu
picture grays occupy slots 12-15 plus existing black. The curve darkens
the source while equal lightness always yields the same slot.
"""
import struct

# The title-band maps and preview records use this same ordered gray ramp.
from shared_gray import STEEL
MENU_GRAY = STEEL


def lightness(word):
    r = (word >> 8) & 15
    g = (word >> 4) & 15
    b = word & 15
    return 3 * r + 6 * g + b


def gray_slot(word):
    """Shared dark-gray slot for one $0RGB word."""
    light = lightness(word)
    if light == 0:
        return 0
    if light <= 60:
        return 15
    if light <= 120:
        return 14
    return 13


def gray_slots(colors):
    if len(colors) != 16:
        raise ValueError(len(colors))
    return [gray_slot(c) for c in colors]


def pair_table(colors):
    g = gray_slots(colors)
    return bytes((g[b >> 4] << 4) | g[b & 15] for b in range(256))


def preview_words(colors):
    """16 $0RGB words: entry i is the menu gray of color i."""
    return [MENU_GRAY[s] for s in gray_slots(colors)]


def preview_bytes(colors):
    return struct.pack('<16H', *preview_words(colors))


def words_of(raw):
    if len(raw) != 32:
        raise ValueError(len(raw))
    return list(struct.unpack('<16H', raw))
