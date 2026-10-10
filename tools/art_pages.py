"""Compose full-screen pages from VGAGRAPH pictures and text, then fit SHR palettes.

A page is rows of RGB. convert_page() gives each row one of a few palettes (wolfpics.search). Only black is
fixed in every palette. The digits that the game draws over a page at run time count in the histogram of
their rows (digit_overlay) and take the nearest color of the palette of their row.
"""
import re
import struct

import page_text
import wolfpics as wp
from wolfdata import CONVERSION, graphics, source_data

W, H = 320, 200
PAGE_CONVERSION = CONVERSION['page']
DITHER = dict(mode=PAGE_CONVERSION['dither_mode'], serpentine=PAGE_CONVERSION['serpentine'],
              top=PAGE_CONVERSION['dither_candidates'], amount=PAGE_CONVERSION['dither_amount'],
              snap=PAGE_CONVERSION['flat_snap'])

# VGAGRAPH.WL1 (v1.4): the original victory and tally glyphs, the chunk numbers of the v1.4 archive
_source = source_data()
_source.graphics()
_ROLES = _source.graphics_layout['roles']
COLON, NUM0, PERCENT, APIC, EXCLAIM, APOSTROPHE = (_ROLES[k] for k in
    ('tally_colon','tally_digit_first','tally_percent','tally_letter_first','tally_exclamation','tally_apostrophe'))
GUY, GUY2, BJWIN = (_ROLES[k] for k in ('tally_guy','tally_guy_alt','victory_bj'))
ENDART = _ROLES['ending_first']
VIEWCOLOR = 127
BACKCOLOR = 0x11
PG13_BACK = 0x82


def blank(rgb, w=W, h=H):
    return [[rgb] * w for _ in range(h)]


def put(canvas, rows, x, y):
    """Opaque picture rows at x, y."""
    for j, row in enumerate(rows):
        if 0 <= y + j < len(canvas):
            canvas[y + j][x:x + len(row)] = row[:max(0, len(canvas[0]) - x)]


def pic_rgb(n):
    return wp.rgb_rows(wp.picture(n)[2])


# -- full screen pictures

def picture_page(n):
    return pic_rgb(n)


def pg13_page():
    pal = wp.vga()
    page = blank(pal[PG13_BACK])
    put(page, pic_rgb(_ROLES['rating']), 216, 110)
    return page


# -- the original victory and tally screens (Write of WL_INTER.C)

# The big letters are VGA 122 on the page color 127, with four steps between (123-126). The new tally keeps the page, the ink
# and two steps (the dark pair and the light pair of the steps), so that the digits that the game draws find their slots.
INK = 122
STEPS = (0.31, 0.69)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def lettering(page, ink):
    """(page, dark step, light step, ink): the four colors of the letters of the tally."""
    return page, mix(page, ink, STEPS[0]), mix(page, ink, STEPS[1]), ink


def recolor(rows, colors):
    """Rows of a letter picture of the original with its teals in the colors of `lettering`."""
    pal = wp.vga()
    page, dark, light, ink = colors
    m = {pal[127]: page, pal[126]: dark, pal[125]: dark, pal[124]: light, pal[123]: light, pal[INK]: ink}
    return [[m.get(c, c) for c in row] for row in rows]


def repage(rows, page):
    """Rows of a picture with every teal (the margin and the shaded edge of the pictures of BJ) in the page color."""
    return [[page if wp.is_teal(c) else c for c in row] for row in rows]


def glyph(ch):
    ch = ch.upper()
    if ch == '!':
        return EXCLAIM
    if ch == "'":
        return APOSTROPHE
    if ch == ':':
        return COLON
    if ch == '%':
        return PERCENT
    if ch == ' ':
        return None
    if 'A' <= ch <= 'Z':
        return APIC + ord(ch) - ord('A')
    if '0' <= ch <= '9':
        return NUM0 + ord(ch) - ord('0')
    raise ValueError(ch)


def glyph_rgb(g, colors=None):
    rows = pic_rgb(g)
    return rows if colors is None else recolor(rows, colors)


def write(canvas, x, y, text, colors=None):
    """WL_INTER.C Write(): x and y in character cells; 16 pixels for a letter, 8 for ! : ' and a new line
    goes 16 pixels down. colors: the `lettering` of the page, or None for the original teals."""
    ox = nx = x * 8
    ny = y * 8
    for ch in text:
        if ch == '\n':
            nx = ox
            ny += 16
            continue
        g = glyph(ch)
        if g is not None:
            put(canvas, glyph_rgb(g, colors), nx, ny)
        nx += 8 if ch in "!:'" else 16


def digits(canvas, x, y, text, colors=None):
    """Digit pictures only: 16 pixels each, the colon 8."""
    for ch in text:
        g = glyph(ch)
        if g is not None:
            put(canvas, glyph_rgb(g, colors), x, y)
        x += 8 if ch == ':' else 16


def victory_page(minutes=12, seconds=34, ratios=(88, 100, 67), numbers=True):
    """Rows 0-159 of Victory() (WL_INTER.C): BJ and the totals on the teal of the view. numbers=False leaves the
    cells of the digits empty: the game draws them."""
    pal = wp.vga()
    page = blank(pal[VIEWCOLOR], W, 160)
    put(page, pic_rgb(BJWIN), 8, 4)
    write(page, 18, 2, 'you win!')
    write(page, 14, 6, 'total time')
    write(page, 12, 12, 'averages')
    write(page, 14, 14, 'kill    %')
    write(page, 10, 16, 'secret    %')
    write(page, 6, 18, 'treasure    %')
    digits(page, 144, 64, ':')
    if numbers:
        digits(page, 112, 64, '%02d' % minutes)
        digits(page, 152, 64, '%02d' % seconds)
        for y, v in zip((112, 128, 144), ratios):
            text = str(v)
            digits(page, 240 - 16 * len(text), y, text)
    return page


def tally_page(floor=1, minutes=1, seconds=23, par='03:30', bonus=0, ratios=(100, 67, 50), breathe=0, colors=None):
    """Rows 0-159 of LevelCompleted() (WL_INTER.C), with BJ as the original draws him. colors: the `lettering`
    of another page color and ink (BJ's margin takes the page color), or None for the teal of the view."""
    pal = wp.vga()
    page = blank(pal[VIEWCOLOR] if colors is None else colors[0], W, 160)
    guy = pic_rgb(GUY2 if breathe else GUY)
    put(page, guy if colors is None else repage(guy, colors[0]), 0, 16)
    write(page, 14, 2, 'floor\ncompleted', colors)
    write(page, 14, 7, 'bonus     0', colors)
    write(page, 16, 10, 'time', colors)
    write(page, 16, 12, ' par', colors)
    write(page, 9, 14, 'kill ratio    %', colors)
    write(page, 5, 16, 'secret ratio    %', colors)
    write(page, 1, 18, 'treasure ratio    %', colors)
    write(page, 26, 2, str(floor), colors)
    write(page, 26, 12, par, colors)
    digits(page, 208, 80, '%02d' % minutes, colors)
    digits(page, 240, 80, ':', colors)
    digits(page, 248, 80, '%02d' % seconds, colors)
    for y, v in zip((112, 128, 144), ratios):
        text = str(v)
        write(page, 37 - 2 * len(text), y // 8, text, colors)
    return page


# -- the ending pages: ENDART of the shareware archive

def end_pages(font, chunk=None):
    """RGB rows (320 x 200) of each page of ENDART (chunk 155) as WL_TEXT.C lays it out, in the original
    colors. font: (height, widths, glyph bitmaps) of VGAGRAPH chunk 1 (build_menu.Art.font)."""
    pal = wp.vga()
    chunks = graphics()
    text = chunks[ENDART if chunk is None else chunk].decode('latin1').replace('\r', '')
    parts = re.split(r'\^P(?:AGE)?[^\n]*\n', text)
    bodies = []
    for part in parts[1:]:
        part = re.sub(r'\n?\^E\s*$', '', part)
        if part.strip():
            bodies.append(part)
    ids = sorted({int(m) for body in bodies for m in re.findall(r'\^[GT]\d+,\d+,(\d+)', body)})
    sizes = {n: tuple(struct.unpack_from('<HH', chunks[0], (n - 3) * 4)) for n in ids}
    layout = page_text.Layout(font, sizes)
    out = []
    for body in bodies:
        runs, pictures = layout.page(body)
        page = blank(pal[BACKCOLOR])
        for x, y, n in pictures:
            put(page, pic_rgb(n), x, y)
        for run in runs:
            draw_text(page, font, run['x'], run['y'], run['text'], pal[run['color']])
        out.append(page)
    return out


def draw_text(canvas, font, x, y, text, rgb):
    height, widths, glyphs = font
    for ch in text:
        if ch == '\x01':
            x += 7
            continue
        k = ord(ch) - 32
        if not 0 <= k < 95:
            continue
        w = widths[k]
        stride = (w + 7) // 8
        g = glyphs[k]
        for j in range(height):
            for i in range(w):
                if g[j * stride + i // 8] & (0x80 >> (i % 8)) and 0 <= y + j < len(canvas) and 0 <= x + i < len(canvas[0]):
                    canvas[y + j][x + i] = rgb
        x += w


# -- conversion of a page

def is_skin(c):
    """An orange skin or hair color of the original palette."""
    return c[0] > 110 and c[0] > c[1] * 1.2 and c[1] >= c[2] and c[2] < c[0] * 0.7


def face_box(rows, x0=0, y0=0, pad=3, upper=1.0):
    """(x0, y0, x1, y1) around BJ's face in page coordinates: the largest connected area of skin and
    hair colors of the picture; upper: the part of the height that is searched (a floor of skin colors
    below BJ is left out)."""
    h, w = int(len(rows) * upper), len(rows[0])
    seen = [[False] * w for _ in range(h)]
    best = None
    for sy in range(h):
        for sx in range(w):
            if seen[sy][sx] or not is_skin(rows[sy][sx]):
                continue
            stack, cells = [(sx, sy)], []
            seen[sy][sx] = True
            while stack:
                x, y = stack.pop()
                cells.append((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and is_skin(rows[ny][nx]):
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if best is None or len(cells) > len(best):
                best = cells
    xs = [c[0] for c in best]
    ys = [c[1] for c in best]
    return (x0 + min(xs) - pad, y0 + min(ys) - pad, x0 + max(xs) + 1 + pad, y0 + max(ys) + 1 + pad)


def page_weight(boxes):
    """weight(x, y) for boxes ((x0, y0, x1, y1, factor), ...): important areas count more."""
    def weight(x, y):
        for x0, y0, x1, y1, f in boxes:
            if x0 <= x < x1 and y0 <= y < y1:
                return f
        return 1
    return weight


def convert_page(rgb, palettes, fixed=((0, 0, 0),), weight=None, clean=None, restarts=None, rounds=None, overlay=None, **conv):
    """(row_pal, pals, idx) of rows of RGB: palettes palettes of 16 colors, free rows, the fixed colors
    in the first slots of every palette. conv: the options of wolfpics.convert; the default is DITHER."""
    restarts = PAGE_CONVERSION['restarts'] if restarts is None else restarts
    rounds = PAGE_CONVERSION['rounds'] if rounds is None else rounds
    hist = {}
    for y, row in enumerate(rgb):
        h = hist.setdefault(y, {})
        for x, c in enumerate(row):
            h[c] = h.get(c, 0) + (weight(x, y) if weight else 1)
    if overlay:
        merge_hist(hist, overlay)
    row_pal, pals = wp.search(hist, palettes, fixed=fixed, rounds=rounds, restarts=restarts)
    idx = wp.convert(rgb, row_pal, pals, clean=clean, **dict(DITHER, **conv))
    return row_pal, pals, idx


def record(row_pal, pals, idx, numbers=None):
    """The record of tools/gscolor.py picture() that the front end streams, as far as the screen
    needs it: 32,000 bytes of pixels, 200 row palettes, zeros to 32,256, 16 palettes of words. numbers: the
    hardware palette of each palette of pals (the default is 0, 1, 2 ...)."""
    numbers = numbers or range(len(pals))
    pixels = bytearray(wp.pack(idx))
    pixels += bytes(160 * (200 - len(idx)))
    scb = bytes(numbers[p] for p in row_pal)
    scb += bytes(200 - len(scb))
    rec = bytes(pixels) + scb
    rec += bytes(32256 - len(rec))
    allp = [[(0, 0, 0)] * 16 for _ in range(16)]
    for n, pal in zip(numbers, pals):
        allp[n] = pal
    for pal in allp:
        rec += wp.palette_words(pal)
    assert len(rec) == 32768
    return rec


# -- the conversions the art sheets propose

TITLE_BOXES = tuple(tuple(box) for box in CONVERSION['hallway_title']['protected_boxes'])


def digit_overlay(positions):
    """Row histograms of every digit picture at every position (x, y): the digits that the game draws at run
    time over a page get their colors in the palettes of those rows, and the game draws them through the
    palette of each row (the nearest color, a table of 16 nibbles for each row palette)."""
    hist = {}
    for n in range(10):
        rows = pic_rgb(NUM0 + n)
        for x, y in positions:
            wp.rowhist_of(rows, None, x, y, hist, 1)
    return hist


VICTORY_DIGITS = [(112, 64), (128, 64), (152, 64), (168, 64)] + [(240 - 16 * k, y) for y in (112, 128, 144) for k in (1, 2, 3)]


def merge_hist(a, b):
    for y, h in b.items():
        t = a.setdefault(y, {})
        for c, w in h.items():
            t[c] = t.get(c, 0) + w
    return a


def rare_weight(rgb, share=0.03, factor=4):
    """weight(x, y): a color that covers less than `share` of the page counts factor + 1 times, so the
    thin lettering of a page keeps its colors."""
    count = {}
    for row in rgb:
        for c in row:
            count[c] = count.get(c, 0) + 1
    total = sum(count.values())
    return lambda x, y: 1 + factor * (count[rgb[y][x]] / total < share)


def title_page(n):
    """Compose the split Spear title with its source palette (WL_MAIN)."""
    if n != _ROLES.get('title_top'):
        return pic_rgb(n)
    raw = graphics()[_ROLES['title_palette']]
    if len(raw) != 768 or max(raw) > 63:
        raise ValueError('Spear title needs a 256-color VGA palette')
    pal = [tuple(c * 4 for c in raw[i:i+3]) for i in range(0, 768, 3)]
    top = wp.picture(n)
    bottom = wp.picture(_ROLES['title_bottom'])
    if top[:2] != (320, 80) or bottom[:2] != (320, 120):
        raise ValueError('Spear title pictures must cover rows 0-79 and 80-199')
    return wp.rgb_rows(top[2] + bottom[2], pal)


def new_title(n):
    """The title in two full passes; the second fixes black and the first pass's best average grays
    (the loading box's letters, bar, border and letter edges) in every palette. Both this converter's search and
    shr_search's (after ii-pix) run; the one with fewer lines that the source lacks is kept: ii-pix's
    wins on painted pictures (Spear's castle), this one on flat pixel art (the Wolf3D hallway)."""
    import shr_search
    rgb = title_page(n)
    hallway = n == _ROLES.get('title') and n != _ROLES.get('title_top')
    boxes = TITLE_BOXES if hallway else ()
    clean = (lambda x, y: any(b[0] <= x < b[2] and b[1] <= y < b[3] for b in boxes)) if boxes else None
    weight = page_weight(boxes) if boxes else None
    # Preserve the face-weighted palette search. Restrict diffusion on the
    # hallway title so fine shading does not acquire unrelated bright specks.
    settings = CONVERSION['hallway_title' if hallway else 'other_title']
    dither = dict(amount=settings['dither_amount'], top=settings['dither_candidates'])
    row_pal, pals, _ = convert_page(rgb, settings['palettes'], weight=weight, clean=clean,
                                    restarts=settings['restarts'], **dither)
    fixed = shr_search.locked_fixed([[wp.word12(c) for c in pal] for pal in pals], row_pal)
    own = convert_page(rgb, settings['palettes'], fixed=fixed, weight=weight, clean=clean,
                       restarts=settings['restarts'], **dither)
    line, pals8, idx, _ = shr_search.convert(rgb, weight, clean, snap=DITHER['snap'])
    return min((own, (line, pals8, idx)), key=lambda r: shr_search.measure_bands(rgb, wp.shown(r[2], r[0], r[1])))


def new_pg13():
    """Two full passes, as new_title: the loading box can open over this page."""
    import shr_search
    rgb = pg13_page()
    row_pal, pals, _ = convert_page(rgb, 2, weight=rare_weight(rgb))
    fixed = shr_search.locked_fixed([[wp.word12(c) for c in pal] for pal in pals], row_pal)
    return convert_page(rgb, 2, fixed=fixed, weight=rare_weight(rgb))


VICTORY_NUMBERS = (0, 13, 14, 15)


def new_victory(**kw):
    """Rows 0-159 of the victory page. The status bar keeps palettes 1-12, so the page has palettes 0, 13, 14, 15.
    Only black is fixed. The digits are drawn at run time through the palette of their row, so they count in
    the histogram and take the nearest color."""
    rgb = victory_page(numbers=False, **kw)
    face = face_box(pic_rgb(BJWIN), 8, 4)
    digit_area = lambda x, y: any(dx <= x < dx + 16 and dy <= y < dy + 16 for dx, dy in VICTORY_DIGITS)
    inside = lambda x, y: face[0] <= x < face[2] and face[1] <= y < face[3]
    return convert_page(rgb, 4, weight=lambda x, y: 20 if inside(x, y) else 1, clean=lambda x, y: inside(x, y) or digit_area(x, y),
                        overlay=digit_overlay(VICTORY_DIGITS), restarts=4)


TEAL_INK = (0, 180, 180)
STEEL_INK = (204, 204, 204)

# Tally background and lettering colors, fixed across its row palettes.
TALLY_PAGE, TALLY_COLOR = (0, 0, 0), TEAL_INK


def new_tally(page=(0, 0, 0), ink=TEAL_INK, **kw):
    """Rows 0-159 of the tally with 3 palettes (0, 13, 14): (row_pal, pals, idx), and the indexes of the page with the
    second picture of BJ. The page color, the ink and the two steps between them are in every palette (the letters and the
    digits use only those colors). Weight the face tenfold and disable dithering
    inside it; chroma weight 2.0 keeps the tally conversion independent of
    the artwork profile's default chroma weight."""
    colors = lettering(page, ink)
    rgb = tally_page(colors=colors, **kw)
    face = face_box(pic_rgb(GUY), 0, 16)
    inside = lambda x, y: face[0] <= x < face[2] and face[1] <= y < face[3]
    fixed = tuple(dict.fromkeys(((0, 0, 0),) + colors))
    with wp.chroma(2.0):
        row_pal, pals, idx = convert_page(rgb, 3, fixed=fixed, weight=lambda x, y: 10 if inside(x, y) else 1, clean=inside, rounds=6,
                                          serpentine=False)
        second = wp.convert(tally_page(colors=colors, breathe=1, **kw), row_pal, pals, clean=inside, **dict(DITHER, serpentine=False))
    return row_pal, pals, idx, second


def new_end(rgb, face=None):
    """face: (x0, y0, x1, y1) of BJ's face on the page, or None."""
    rare = rare_weight(rgb)
    if face:
        inside = lambda x, y: face[0] <= x < face[2] and face[1] <= y < face[3]
        return convert_page(rgb, 2, weight=lambda x, y: rare(x, y) * (20 if inside(x, y) else 1), clean=inside, restarts=3)
    return convert_page(rgb, 2, weight=rare)


def end_face():
    """BJ's face on page 1 of the ending (chunk 11 at 16, 16)."""
    return face_box(pic_rgb(_ROLES['ending_face']), 16, 16)
