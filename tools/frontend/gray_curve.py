"""Native menu background levels. Slots 0-3 are the picture grays.
The top clamps at $333. A power below 1 holds the middle off black.
Ink still uses the brighter steel slots above these."""
LEVELS = (0, 1, 2, 3, 3, 3)
COLORS = tuple(v * 0x111 for v in LEVELS)


def index_light(light):
    if not light:
        return 0
    return min(3, max(1, round(3 * (light / 150) ** 0.40)))


def index(color):
    light = 3 * (color >> 8 & 15) + 6 * (color >> 4 & 15) + (color & 15)
    return index_light(light)
