"""Colors of the large title lettering: the measured chrome of the original headings, row by row, in palette bands.

Measured in GETPSYCHEDPIC rows 7 to 33 (the dominant color of each row of lettering): a steel rise from (100,100,100) to
(220,220,220) over 17 rows, a sharp horizon, then a red reflection from (100,0,0) to (252,92,92) over 10 rows, a gray shadow
below. White (252,252,252) lights the top and left edges of the letters in the steel half and a pink (252,124,124) in the red half.
A title picks one palette for each band of rows. Every band palette shares only the three gray-copy colors with the background
($000 $111 $222); its other 13 slots hold the colors of the rows of that band.
"""
STEEL = [100, 100, 112, 124, 140, 140, 152, 168, 168, 168, 180, 192, 192, 208, 220, 220, 220]
RED = [(100, 0, 0), (112, 0, 0), (124, 0, 0), (152, 0, 0), (168, 0, 0), (200, 0, 0), (224, 0, 0), (252, 64, 64), (252, 84, 84), (252, 92, 92)]
SHADOW = [(72, 72, 72), (44, 44, 44)]
RIM_STEEL = (252, 252, 252)
RIM_RED = (252, 124, 124)
GRAY_COPY = [0x000, 0x111, 0x222]
BAND_ROWS = 4
SHADE = 0.55              # the dark inner edge (bottom and right of a stroke) is the face color at this brightness
HORIZON = 17/27           # the share of the cap rows above the horizon in the original (17 of 27 rows)


def rgb12(rgb):
    return (round(rgb[0]/17) << 8) | (round(rgb[1]/17) << 4) | round(rgb[2]/17)


def shade_of(rgb):
    return tuple(round(v*SHADE) for v in rgb)


def row_colors(height, baseline):
    """[(face 12-bit, rim 12-bit, shade 12-bit)] for the glyph rows 0..height-1: steel above the horizon, red below it, shadow under the baseline."""
    horizon = max(1, round(HORIZON*(baseline+1)))
    out = []
    for y in range(height):
        if y < horizon:
            v = STEEL[round(y*(len(STEEL)-1)/max(1, horizon-1))]
            out.append((rgb12((v, v, v)), rgb12(RIM_STEEL), rgb12(shade_of((v, v, v)))))
        elif y <= baseline:
            k = round((y-horizon)*(len(RED)-1)/max(1, baseline-horizon))
            out.append((rgb12(RED[k]), rgb12(RIM_RED), rgb12(shade_of(RED[k]))))
        else:
            s = SHADOW[min(len(SHADOW)-1, y-baseline-1)]
            out.append((rgb12(s), rgb12(s), rgb12(shade_of(s))))
    return out


def assign(height, baseline, band_rows=BAND_ROWS):
    """bands: [(row_start, row_end, palette words)] over the glyph rows 0..height-1 (the title has no outline: no margin rows);
    face_slot[y], rim_slot[y], shade_slot[y]: slots of the glyph row y inside the palette of its band."""
    colors = row_colors(height, baseline)
    bands, face_slot, rim_slot, shade_slot = [], [0]*height, [0]*height, [0]*height
    box = height
    for r0 in range(0, box, band_rows):
        r1 = min(box, r0+band_rows)
        used = []
        for y in range(r0, r1):
            for c in colors[y]:
                if c not in used:
                    used.append(c)
        assert len(used) <= 13, (r0, len(used))
        words = GRAY_COPY+used+[0]*(13-len(used))
        for y in range(r0, r1):
            face_slot[y] = 3+used.index(colors[y][0])
            rim_slot[y] = 3+used.index(colors[y][1])
            shade_slot[y] = 3+used.index(colors[y][2])
        bands.append((r0, r1, words))
    return dict(bands=bands, face_slot=face_slot, rim_slot=rim_slot, shade_slot=shade_slot, colors=colors)


if __name__ == '__main__':
    a = assign(21, 16)
    print(len(a['bands']), [sum(1 for w in b[2][3:] if w) for b in a['bands']])


def convert_original(rows, bands=3):
    """Fit original RGB12 lettering with the native menu band quantizer.

    The aligned gray copy and the loading frame must retain their existing
    colors beside the lettering. They occupy five shared palette entries.
    """
    from frontend.lettering.bands import convert
    return convert(rows, limit=bands, shared=(0x000, 0x111, 0x222, 0x333, 0x444))
