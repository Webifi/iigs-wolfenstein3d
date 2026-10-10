"""Menu art for the front end: original pictures and fonts in palette slots.

The pictures keep their 16-slot meaning (black, white, red, dark red, yellow,
grays) so they show in whichever floor palette is loaded. Fonts are 1 bit per
pixel and stay resident; menu.bin is packed by build_menu_cache.py, and pictures
decode into bank $3F when a screen opens. Screens are display lists that tools/build_menu.py also
draws to PNG for a layout check.
"""
import json
import struct
import sys
import zlib
from pathlib import Path
from wolfdata import ROOT, PROFILE, graphics, palette, source_data
import viewcolor as vc
import art_lumps
import art_pages
import gscolor
import bench_route
from fade_palette import fade_table

BLOCK = 512
CHUNK = 4096                    # the unit of the cache (tools/build_menu_cache.py)
STAGE_SIZE = 0x3800           # bytes of bank $3F staging for pictures (UI_PICSIZE of frontend.inc)

# slot names used by the layouts below
BLACK, WHITE, RED, DKRED, YELLOW, SKIN, GREEN, BROWN = range(8)
TEAL, BLUE, DKBLUE, CYAN, GRAY, DKGRAY, DARKER, NAVY = range(8, 16)


def slot_palette():
    """The median color of each slot over the ten floor palettes."""
    files = sorted((ROOT / 'build/palettes').glob('*.json'))
    cols = [json.loads(f.read_text())['palette'] for f in files]
    if not cols:
        raise SystemExit('build/palettes is empty: run make first')
    return [tuple(sorted(c[s][i] for c in cols)[len(cols) // 2] for i in range(3)) for s in range(16)]


class Art:
    def __init__(self):
        self.chunks = graphics()
        self.pal = palette()
        self.slots = slot_palette()
        self.labs = [vc.oklab8(c) for c in self.slots]
        self.cache = {}

    def slot(self, rgb):
        if rgb not in self.cache:
            lab = vc.oklab8(rgb)
            self.cache[rgb] = min(range(16), key=lambda k: vc.dist(lab, self.labs[k]))
        return self.cache[rgb]

    def picture(self, n, clear=None):
        """Pixels as slots; clear: a slot that becomes black (the panel color)."""
        w, h, rows = self._picture(n)
        if clear is not None:
            rows = [[BLACK if v == clear else v for v in row] for row in rows]
        return w, h, rows

    def _picture(self, n):
        w, h = struct.unpack_from('<HH', self.chunks[0], (n - 3) * 4)
        data = self.chunks[n]
        plane = w * h // 4
        rows = [[data[(x & 3) * plane + y * (w // 4) + (x >> 2)] for x in range(w)] for y in range(h)]
        return w, h, [[self.slot(self.pal[p]) for p in row] for row in rows]

    def font(self, n):
        """(height, widths, bitmaps) of ASCII 32..126; row-major, MSB first."""
        f = self.chunks[n]
        height = struct.unpack_from('<H', f, 0)[0]
        loc = struct.unpack_from('<256H', f, 2)
        wid = f[2 + 512:2 + 512 + 256]
        widths, glyphs = [], []
        for c in range(32, 127):
            w = wid[c]
            if c == 32 and w == 0:
                w = 4
            widths.append(w)
            bits = bytearray()
            for y in range(height):
                row = [(f[loc[c] + y * w + x] != 0) if wid[c] else False for x in range(w)]
                for b in range(0, w, 8):
                    v = 0
                    for i in range(8):
                        v = (v << 1) | (1 if b + i < w and row[b + i] else 0)
                    bits.append(v)
            glyphs.append(bytes(bits))
        return height, widths, glyphs


def pack_pic(rows):
    return bytes((a << 4) | b for row in rows for a, b in zip(row[::2], row[1::2]))


def png(path, w, h, rgb_rows):
    raw = b''.join(b'\0' + bytes(r) for r in rgb_rows)

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


# ---------------------------------------------------------------------------
# lumps: pictures grouped by the screen that needs them

LUMPS = [
    ('common', 0x0000, [('cursor1', 23), ('cursor2', 24), ('hint', 30), ('notsel', 25), ('sel', 26)]),
    ('main', 0x0800, [('options', 22)]),
    ('newgame', 0x1800, [('face0', 31), ('face1', 32), ('face2', 33), ('face3', 34)]),
    ('load', 0x1800, [('loadgame', 40), ('disk', 35)]),
    ('save', 0x1800, [('savegame', 41), ('disk', 35)]),
    ('options', 0x1800, [('fxtitle', 27), ('musictitle', 29)]),
    ('controls', 0x1800, [('control', 38), ('customize', 39)]),
    ('scores', 0x1800, [('highscores', 102)]),
]
FONT_NAMES = ('font1', 'font2')
PANEL_PICS = ('cursor1', 'cursor2', 'notsel', 'sel', 'face0', 'face1', 'face2', 'face3')   # drawn on the black panel


PAGE_CONSTS = {}                # the layout of the page lumps (tools/art_lumps.py), for the assembly


def credits_picture(raw, playpal):
    """Two full passes, as art_pages.new_title: the loading box can open over the credits."""
    import shr_search
    first = gscolor.picture(raw, playpal)
    rows = list(first[32000:32200])
    pals = [list(struct.unpack_from('<16H', first, 32256 + p * 32)) for p in range(16)]
    return gscolor.picture(raw, playpal, fixed=shr_search.locked_fixed(pals, rows))


def build_lumps(art, fonts):
    """Return (blob, directory, picture table). Picture table maps a name to
    (staging offset, width in bytes, height) for each lump."""
    blob = bytearray(BLOCK)               # block 0: directory, filled in below
    directory, pics = [], {}
    # the title, the credits and PG-13: an image of the screen memory (pixels, row palettes, palettes)
    source = source_data(); source.graphics()
    roles = source.graphics_layout['roles']
    chunk = roles['credits']
    w, h = struct.unpack_from('<HH', art.chunks[0], (chunk - 3) * 4)
    plane = w * h // 4
    raw = bytes(art.chunks[chunk][(x & 3) * plane + y * (w // 4) + (x >> 2)] for y in range(h) for x in range(w))
    victory, consts = art_lumps.victory_lump()
    PAGE_CONSTS.update(consts)
    tally, consts = art_lumps.tally_lump(art_pages.TALLY_PAGE, art_pages.TALLY_COLOR)
    PAGE_CONSTS.update(consts)
    endings = []
    for key in PROFILE.campaign.document['episode_menu_order']:
        ending = PROFILE.campaign.endings[PROFILE.campaign.episodes[key]['ending_id']]
        chunk = roles[ending['picture_role']]+ending.get('picture_offset',0)
        if PROFILE.spear:
            from spear_pages import pages
            endings.extend(pages(art.font(1)))
        else:
            endings.extend(art_lumps.end_lumps(art.font(1), chunk, protect_first_face=not endings))
    end1, end2 = endings[:2]
    (ROOT / 'build/assets/pages-check.json').write_text(json.dumps(art_lumps.checks(victory, [end1, end2])) + '\n')
    resident = None
    for name, image in (('title', art_pages.record(*art_pages.new_title(roles.get('title', roles.get('title_top'))))),
                        ('credits', credits_picture(raw, art.pal)[:64 * BLOCK]),
                        ('pg13', art_pages.record(*art_pages.new_pg13())),
                        ('tally', tally), ('victory', victory)) + tuple((f'end{i+1}', page) for i,page in enumerate(endings)):
        if name == 'victory':
            blob += bytes(-len(blob) % CHUNK)       # whole chunks, so that these three can live in the logic bank
            resident = len(blob) // CHUNK
        directory.append((name, len(blob) // BLOCK, len(image) // BLOCK, 0, len(image)))
        blob += image
    (ROOT / 'build/assets/menu-resident.json').write_text(json.dumps(dict(first_chunk=resident)) + '\n')
    d = bytearray(BLOCK)
    d[0:4] = b'WMNU'
    d[4] = 1
    d[5] = len(directory)
    for i, (name, first, count, stage, size) in enumerate(directory):
        struct.pack_into('<HHHH', d, 8 + 8 * i, first, count, stage, size)
    blob[0:BLOCK] = d
    return bytes(blob), directory, pics


# ---------------------------------------------------------------------------
# display lists

class DL:
    """A display list: the same commands the front end interprets."""

    def __init__(self):
        self.cmds = []

    def fill(self, x, y, w, h, c):
        assert x % 2 == 0 and w % 2 == 0, (x, w)
        self.cmds.append(('fill', x, y, w, h, c))

    def pic(self, lump, name, x, y):
        assert x % 2 == 0
        self.cmds.append(('pic', lump, name, x, y))

    def text(self, font, c, x, y, s):
        self.cmds.append(('text', font, c, x, y, s))

    def window(self, x, y, w, h, bg, hi, lo):
        """Black or colored panel with a two-pixel bevel."""
        self.fill(x, y, w, h, bg)
        self.fill(x, y, w, 2, lo)
        self.fill(x, y, 2, h, lo)
        self.fill(x, y + h - 2, w, 2, hi)
        self.fill(x + w - 2, y, 2, h, hi)

    def asm(self, label, pics):
        """Assembly text of the list (words; text strings follow their command)."""
        out = [label + ':']
        for c in self.cmds:
            if c[0] == 'fill':
                _, x, y, w, h, col = c
                out.append(f'              .word 1, {x}, {y}, {w}, {h}, {col}')
            elif c[0] == 'pic':
                _, lump, name, x, y = c
                off, wb, h = pics[(lump, name)]
                out.append(f'              .word 2, {x}, {y}, {off}, {wb}, {h}')
            elif c[0] == 'text':
                _, font, col, x, y, s = c
                out.append(f'              .word 3, {x}, {y}, {font - 1}, {col}')
                out.append('              .asciz "' + s.replace('\\', '\\\\').replace('"', '\"') + '"')
        out.append('              .word 0')
        return out


class Screen:
    """Indexed 320x200 bitmap for the preview and the layout check."""

    def __init__(self):
        self.px = [[0] * 320 for _ in range(200)]

    def fill(self, x, y, w, h, c):
        for yy in range(y, min(200, y + h)):
            for xx in range(x, min(320, x + w)):
                self.px[yy][xx] = c

    def pic(self, rows, x, y):
        for j, row in enumerate(rows):
            for i, v in enumerate(row):
                if 0 <= y + j < 200 and 0 <= x + i < 320:
                    self.px[y + j][x + i] = v

    def text(self, font, c, x, y, s):
        height, widths, glyphs = font
        for ch in s:
            k = ord(ch) - 32
            if not 0 <= k < 95:
                k = 0
            w = widths[k]
            bpr = (w + 7) // 8
            g = glyphs[k]
            for j in range(height):
                for i in range(w):
                    if g[j * bpr + i // 8] & (0x80 >> (i % 8)):
                        if 0 <= y + j < 200 and 0 <= x + i < 320:
                            self.px[y + j][x + i] = c
            x += w
        return x

    def width(self, font, s):
        height, widths, glyphs = font
        return sum(widths[min(94, max(0, ord(ch) - 32))] for ch in s)

    def save(self, path, slots):
        rows = [b''.join(bytes(slots[v]) for v in row) for row in self.px]
        png(path, 320, 200, rows)


def render(dl, art, lumps_pics, fonts, screen=None):
    s = screen or Screen()
    for c in dl.cmds:
        if c[0] == 'fill':
            s.fill(c[1], c[2], c[3], c[4], c[5])
        elif c[0] == 'pic':
            _, lump, name, x, y = c
            n = dict((p, i) for ln, _, items in LUMPS if ln == lump for p, i in items)[name]
            s.pic(art.picture(n, DKRED if name in PANEL_PICS else None)[2], x, y)
        elif c[0] == 'text':
            s.text(fonts[c[1]], c[2], c[3], c[4], c[5])
    return s


# ---------------------------------------------------------------------------
# screens

MENU_ITEMS = ['New Game', 'Load Game', 'Save Game', 'Options', 'View Scores',
              'Back to Game', 'Quit']
ITEM_X, ITEM_Y, ITEM_STEP = 100, 55, 13


def screen_main():
    d = DL()
    d.fill(0, 0, 320, 200, DKRED)
    d.fill(0, 10, 320, 24, BLACK)
    d.fill(0, 32, 320, 1, RED)
    d.pic('main', 'options', 84, 0)
    d.pic('common', 'hint', 112, 184)
    d.window(68, 52, 178, 8 * ITEM_STEP + 14, BLACK, RED, DKRED)
    return d


def bytes_lines(data, indent='              .byte '):
    out = []
    for i in range(0, len(data), 16):
        out.append(indent + ', '.join(str(b) for b in data[i:i + 16]))
    return out


def font_asm(n, font):
    height, widths, glyphs = font
    offsets, bits = [], bytearray()
    for w, g in zip(widths, glyphs):
        offsets.append(len(bits))
        bits += g
    out = [f'f{n}_w:'] + bytes_lines(widths + [0])
    out += [f'f{n}_o:', '              .word ' + ', '.join(str(o) for o in offsets[:8])]
    for i in range(8, len(offsets), 8):
        out.append('              .word ' + ', '.join(str(o) for o in offsets[i:i + 8]))
    out += [f'f{n}_g:'] + bytes_lines(list(bits))
    return out


NG_ITEMS = ['Can I play, Daddy?', "Don't hurt me.", "Bring 'em on!", 'I am Death incarnate!']


def screen_newgame():
    d = DL()
    d.fill(0, 0, 320, 200, DKRED)
    d.pic('common', 'hint', 112, 184)
    d.text(1, YELLOW, 70, 68, 'How tough are you?')
    d.window(44, 90, 226, 67, BLACK, RED, DKRED)
    return d


def screen_slots(lump, name):
    d = DL()
    d.fill(0, 0, 320, 200, DKRED)
    d.fill(0, 10, 320, 24, BLACK)
    d.fill(0, 32, 320, 1, RED)
    d.pic(lump, name, 52, 0)
    d.pic('common', 'hint', 112, 184)
    d.window(76, 54, 188, 8 * 13 + 12, BLACK, RED, DKRED)
    return d


def screen_banner(lump, name, x, color_bar=True):
    """A page with the black stripe and one banner, as in the original."""
    d = DL()
    d.fill(0, 0, 320, 200, DKRED)
    d.fill(0, 10, 320, 24, BLACK)
    d.fill(0, 32, 320, 1, RED)
    d.pic(lump, name, x, 0)
    d.pic('common', 'hint', 112, 184)
    return d


def screen_options():
    d = screen_banner('main', 'options', 84)
    d.window(56, 54, 208, 9 * 13 + 10, BLACK, RED, DKRED)
    return d


def screen_scores():
    return screen_banner('scores', 'highscores', 48)


CT_ITEMS = 11                    # ten actions and Default Keys
CT_X, CT_Y, CT_STEP = 72, 55, 11
CT_VALUE_X = 176


def screen_controls():
    d = screen_banner('controls', 'customize', 84)
    d.window(36, 50, 248, CT_ITEMS * CT_STEP + 9, BLACK, RED, DKRED)
    return d


def adb_ascii():
    """(plain, shifted): the character of each raw ADB key code for typing a name; 0 for none."""
    plain, shift = [0] * 128, [0] * 128
    codes = dict(zip(range(0x24), 'asdfhgzxcv?bqweryt123465=97-80]ou[ip'))
    for k, c in codes.items():
        if c == '?':
            continue
        plain[k] = ord(c)
        shift[k] = ord(c.upper()) if c.isalpha() else ord({'1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
                                                             '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
                                                             '=': '+', '-': '_', ']': '}', '[': '{'}[c])
    more = {0x25: ('l', 'L'), 0x26: ('j', 'J'), 0x27: ("'", '"'), 0x28: ('k', 'K'), 0x29: (';', ':'),
            0x2a: ('\\', '|'), 0x2b: (',', '<'), 0x2c: ('/', '?'), 0x2d: ('n', 'N'), 0x2e: ('m', 'M'),
            0x2f: ('.', '>'), 0x31: (' ', ' '), 0x32: ('`', '~')}
    for k, (a, b) in more.items():
        plain[k], shift[k] = ord(a), ord(b)
    return bytes(plain), bytes(shift)


def adb_names():
    """8 bytes for each of the 128 raw ADB key codes: the name, then zeros."""
    names = ['Key %02X' % k for k in range(128)]
    for k, c in enumerate('ASDFHGZXCV?BQWERYT123465=97-80]OU[IP'):
        if c != '?':
            names[k] = c
    names[0x24:0x3f] = ['Return', 'L', 'J', 'Quote', 'K', ';', '\\', ',', '/', 'N', 'M', '.', 'Tab',
                        'Space', 'Grave',
                        'Delete', names[0x34], 'Esc', 'Ctrl', 'Cmd', 'Shift', 'Caps', 'Opt', 'Left',
                        'Right', 'Down', 'Up']
    for k, n in {0x41: 'KP .', 0x43: 'KP *', 0x45: 'KP +', 0x47: 'Clear', 0x4b: 'KP /', 0x4c: 'KP Ent',
                 0x4e: 'KP -', 0x51: 'KP =', 0x5b: 'KP 8', 0x5c: 'KP 9', 0x60: 'F5', 0x61: 'F6', 0x62: 'F7',
                 0x63: 'F3', 0x64: 'F8', 0x65: 'F9', 0x67: 'F11', 0x69: 'F13', 0x6b: 'F14', 0x6d: 'F10',
                 0x6f: 'F12', 0x70: 'Mouse 2', 0x71: 'F15', 0x72: 'Help', 0x73: 'Home', 0x74: 'Page Up',
                 0x75: 'Del', 0x76: 'F4', 0x77: 'End', 0x78: 'F2', 0x79: 'Page Dn', 0x7a: 'F1',
                 0x7b: 'R Shift', 0x7c: 'R Opt', 0x7d: 'R Ctrl', 0x7e: 'Mouse 1', 0x7f: 'Reset'}.items():
        names[k] = n
    for k in range(8):
        names[0x52 + k] = 'KP %d' % k
    out = bytearray()
    for n in names:
        assert len(n) <= 7, n
        out += n.encode('ascii').ljust(8, b'\0')
    return bytes(out)


SCREENS = [('dlMain', screen_main), ('dlNewGame', screen_newgame),
           ('dlOptions', screen_options), ('dlScores', screen_scores), ('dlControls', screen_controls),
           ('dlLoad', lambda: screen_slots('load', 'loadgame')),
           ('dlSave', lambda: screen_slots('save', 'savegame'))]


def main():
    import build_campaign
    build_campaign.main()
    import build_frontend
    build_frontend.configure(sys.modules[__name__])
    art = Art()
    fonts = {}
    blob, directory, pics = build_lumps(art, fonts)
    out = ROOT / 'build/assets'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'menu.bin').write_bytes(blob)
    import endtext
    endtext.build(source_data(), out)
    gen = ROOT / 'build/gen'
    gen.mkdir(parents=True, exist_ok=True)
    asm = ['              .public fontInfo, lumpTable, scoreTable, fadeTab, keyNames, adbPlain, adbShift, benchRoute, '
           + ', '.join(n for n, _ in SCREENS), 'fontInfo:']
    asm += ['              .word 10, .word0 (smallWidths), .word0 (smallOffsets), .word0 (smallBanks)', '              .word 17, .word0 (steelWidths), .word0 (steelOffsets), .word0 (steelBanks)', '              .word 13, .word0 (mediumWidths), .word0 (mediumOffsets), .word0 (mediumBanks)', '#include "steel-font.inc"']
    for label, fn in SCREENS:
        asm += fn().asm(label, pics)
    # the original table of high scores: name, score, floor
    names = ["id software-'92", 'Adrian Carmack', 'John Carmack', 'Kevin Cloud', 'Tom Hall', 'John Romero', 'Jay Wilbur']
    asm.append('scoreTable:')
    for name in names:
        row = name.encode('ascii')[:15].ljust(16, b'\0') + struct.pack('<IBBBB', 10000, 1, 0, 0, 0)
        asm += bytes_lines(list(row))
    # Nearest perceptual shades, with the same 17-by-16 runtime lookup.
    asm.append('fadeTab:')
    for row in fade_table():
        asm.append('              .byte ' + ', '.join(map(str, row)))
    asm.append('keyNames:')
    asm += bytes_lines(list(adb_names()))
    plain, shifted = adb_ascii()
    asm.append('adbPlain:')
    asm += bytes_lines(list(plain))
    asm.append('adbShift:')
    asm += bytes_lines(list(shifted))
    asm += bench_route.asm()
    asm.insert(0, f'BENCH_FRAMES .equ {bench_route.check() - 1}')
    asm.insert(0, f'CT_ITEMS .equ {CT_ITEMS}')
    asm.insert(0, f'CT_X .equ {CT_X}')
    asm.insert(0, f'CT_Y .equ {CT_Y}')
    asm.insert(0, f'CT_STEP .equ {CT_STEP}')
    asm.insert(0, f'CT_VALUE_X .equ {CT_VALUE_X}')
    # lump directory for the loader: first block, blocks, staging offset
    asm.append('lumpTable:')
    for name, first, count, stage, size in directory:
        asm.append(f'              .word {first}, {count}, {stage}, {size}  ; {name}')
    for i, (name, *_rest) in enumerate(directory):
        asm.insert(0, f'LUMP_{name.upper()} .equ {i}')
    for name, value in sorted(PAGE_CONSTS.items()):
        asm.insert(0, f'{name} .equ {value}')
    for (lump, name), (off, wb, h) in sorted(pics.items()):
        asm.insert(0, f'PIC_{lump.upper()}_{name.upper()} .equ {off}')
        asm.insert(0, f'PIC_{lump.upper()}_{name.upper()}_WB .equ {wb}')
        asm.insert(0, f'PIC_{lump.upper()}_{name.upper()}_H .equ {h}')
    asm.insert(0, f'STEEL_COLD_BYTES .equ {(ROOT / "build/assets/frontend-font.bin").stat().st_size}')
    asm.insert(0, f'ITEM_X .equ {ITEM_X}')
    asm.insert(0, f'ITEM_Y .equ {ITEM_Y}')
    asm.insert(0, f'ITEM_STEP .equ {ITEM_STEP}')
    const = [l for l in asm if ' .equ ' in l]
    data = [l for l in asm if ' .equ ' not in l]
    (gen / 'menu.inc').write_text('\n'.join(const) + '\n')
    (gen / 'menu_data.inc').write_text('\n'.join(data) + '\n')
    print('menu art:', len(blob), 'bytes', len(directory), 'lumps')


if __name__ == '__main__':
    main()
