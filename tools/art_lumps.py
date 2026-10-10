"""The pages of the game as lumps of the menu file (tools/build_menu.py).

victory, end1, end2: a record of the screen memory like the title (32,768 bytes: 160 or 200 rows of pixels, the
palette of each row, 16 palettes). The victory page keeps the status bar: the game copies only its 160 rows and
its palettes 0, 13, 14 and 15. Blocks 50-52 of the victory record, where the rows of the status bar would be, hold what
the game needs to draw the digits at run time: for each palette the slot of each of the 6 teals of the lettering (a
table of 16 bytes), then the 10 digit pictures, 16 rows of 8 bytes, as indexes of those teals.

tally: row palette selections for 160 rows, three palettes (0, 13, 14),
BJ's first picture, the changed part of the second picture, and large glyphs.
Page and lettering colors occupy fixed slots in every palette.
"""
import struct

import art_pages as ap
import wolfpics as wp

BLOCK = 512
LETTERS = [ap.APIC + n for n in range(26)]
CANON = {127: 0, 126: 1, 125: 2, 124: 3, 123: 4, 122: 5}   # the teals of the lettering, in the order of the digit tables
TALLY_NUMBERS = (0, 13, 14)
VICTORY_DIGIT_AT = 25600                                    # byte of the record where the digit data starts (block 50)

# the glyph of a character in the table of the tally: 0-9 the digits, 10-35 the letters, then : % !
GLYPH_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:%!'


def victory_lump():
    """The record of the victory page with the digit data in blocks 50-52."""
    row_pal, pals, idx = ap.new_victory()
    rec = bytearray(ap.record(row_pal, pals, idx, numbers=ap.VICTORY_NUMBERS))
    vga = wp.vga()
    tables = bytearray(16 * 16)
    for n, pal in zip(ap.VICTORY_NUMBERS, pals):
        for v, canon in CANON.items():
            tables[n * 16 + canon] = wp.nearest_index(pal, vga[v])
    glyphs = bytearray()
    for d in range(10):
        w, h, rows = wp.picture(ap.NUM0 + d)
        assert (w, h) == (16, 16)
        for row in rows:
            canon = [CANON[v] for v in row]
            glyphs += bytes((a << 4) | b for a, b in zip(canon[::2], canon[1::2]))
    extra = bytes(tables) + bytes(glyphs)
    assert all(b == 0 for b in rec[VICTORY_DIGIT_AT:VICTORY_DIGIT_AT + len(extra)])
    rec[VICTORY_DIGIT_AT:VICTORY_DIGIT_AT + len(extra)] = extra
    return bytes(rec), dict(VICTORY_DIGITS_BLOCK=VICTORY_DIGIT_AT // BLOCK, VICTORY_DIGITS_BLOCKS=-(-len(extra) // BLOCK),
                            VICTORY_DIGITS=len(tables))


def end_lumps(font, chunk=None, protect_first_face=True):
    """Ending-page records; font is the result of build_menu.Art.font(1)."""
    out = []
    for i, rgb in enumerate(ap.end_pages(font, chunk)):
        out.append(ap.record(*ap.new_end(rgb, ap.end_face() if i == 0 and protect_first_face else None)))
    return out


def tally_lump(page, ink):
    """(bytes, constants) of the tally pieces for a page color and a color of the letters."""
    row_pal, pals, idx, second = ap.new_tally(page=page, ink=ink)
    colors = ap.lettering(page, ink)
    fixed = tuple(dict.fromkeys(((0, 0, 0),) + colors))
    slot = {c: wp.nearest_index(pals[0], c) for c in fixed}
    assert all(pal[slot[c]] == pals[0][slot[c]] for pal in pals for c in fixed)
    scb = bytes(TALLY_NUMBERS[p] for p in row_pal)
    palettes = b''.join(wp.palette_words(pal) for pal in pals)
    bj = lambda rows: [row[:104] for row in rows[16:104]]
    bj1 = wp.pack(bj(idx))
    a, b = bj(idx), bj(second)
    diff = [(y, x) for y in range(88) for x in range(104) if a[y][x] != b[y][x]]
    if diff:
        y0, y1 = min(y for y, _ in diff), max(y for y, _ in diff)
        x0, x1 = min(x for _, x in diff) // 2, max(x for _, x in diff) // 2
    else:
        # Some source frames quantize identically. Repainting one unchanged
        # byte keeps the native animation record valid without inventing pixels.
        y0 = y1 = x0 = x1 = 0
    bj2 = wp.pack([row[2 * x0:2 * x1 + 2] for row in b[y0:y1 + 1]])
    # the letters: a table of one word for each character of GLYPH_CHARS (the offset in the lump, 0 for none)
    glyph_data = bytearray()
    table = []
    base = 256 + len(bj1) + len(bj2)
    base += len(GLYPH_CHARS) * 2
    for ch in GLYPH_CHARS:
        g = ap.glyph(ch)
        rows = ap.recolor(ap.pic_rgb(g), colors)
        table.append(base + len(glyph_data))
        glyph_data += wp.pack([[slot[c] for c in row] for row in rows])
    lump = bytearray(scb) + bytearray(palettes) + bj1 + bj2
    assert len(lump) == 256 + len(bj1) + len(bj2)
    lump += b''.join(struct.pack('<H', t) for t in table) + glyph_data
    fill = slot[page] * 17
    consts = dict(TALLY_SCB=0, TALLY_PALS=len(scb), TALLY_BJ1=256, TALLY_BJ2=256 + len(bj1), TALLY_BJ2_X=x0, TALLY_BJ2_Y=y0,
                  TALLY_BJ2_W=x1 - x0 + 1, TALLY_BJ2_H=y1 - y0 + 1, TALLY_GLYPHS=256 + len(bj1) + len(bj2), TALLY_FILL=fill,
                  TALLY_BYTES=len(lump))
    lump += bytes(-len(lump) % BLOCK)
    return bytes(lump), consts


def nibble(rec, x, y):
    b = rec[y * 160 + x // 2]
    return b >> 4 if x % 2 == 0 else b & 15


def checks(victory, ends):
    """Points of the pages for tools/check_floor_flow.py: [x, y, the palette slot on the screen], and the palette of each
    row. The digit is a pixel of the 2, the second digit of the minutes of the test (the averages come to 2 minutes)."""
    face = ap.face_box(ap.pic_rgb(ap.BJWIN), 8, 4)
    bj = ((face[0] + face[2]) // 2, (face[1] + face[3]) // 2)
    w, h, rows = wp.picture(ap.NUM0 + 2)
    dy, dx = next((y, x) for y, row in enumerate(rows) for x, v in enumerate(row) if CANON[v] != 0)
    at = (ap.VICTORY_DIGITS[1][0] + dx, ap.VICTORY_DIGITS[1][1] + dy)
    slot = victory[VICTORY_DIGIT_AT + victory[32000 + at[1]] * 16 + CANON[rows[dy][dx]]]
    out = dict(victory=[[bj[0], bj[1], nibble(victory, *bj)], [at[0], at[1], slot]])
    rows = dict(victory=160, ending0=200, ending1=200)
    from wolfdata import PROFILE
    face = (96,48,224,144) if PROFILE.spear else ap.end_face()
    point = ((face[0] + face[2]) // 2, (face[1] + face[3]) // 2)
    out['ending0'] = [[point[0], point[1], nibble(ends[0], *point)]]
    # the first pixel of the second page that is not the page color, in reading order
    page = nibble(ends[1], 0, 0)
    y, x = next((y, x) for y in range(200) for x in range(320) if nibble(ends[1], x, y) != page)
    out['ending1'] = [[x, y, nibble(ends[1], x, y)]]
    pages = dict(victory=victory, ending0=ends[0], ending1=ends[1])
    return {k: dict(points=v, scb=list(pages[k][32000:32000 + rows[k]])) for k, v in out.items()}
