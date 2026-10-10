"""Build row palettes and converted pictures for the status bar and face.

The 40 rows of the status bar (screen rows 160-199) get their own palettes, made from a histogram
of everything the game can draw on each row, and each row picks one of them. Color 0 is black in
every palette. Every picture is then converted once, at its place, with the palette of each of
its rows, so the game still copies bytes (hud.s). The face counts 24 times in the histogram.

Pictures, as the v1.4 shareware VGAGRAPH has them: 98 the bar, 103-106 the weapons, 107-109 the
keys, 110 the empty digit, 111-120 the digits, 121-144 the faces: 121-141 for 7 health bands of
three looks, 142 the dead face, 143 the grin, 144 the mutant (shown for a death by needle, which the shareware floors do not have: it has no weight).
"""
import wolfpics as wp
import gscolor
from wolfdata import PROFILE, source_data

STATUS_Y = 160
HEIGHT = 40
COUNT = 12
TEAL = (0, 64, 64)                              # the border of the original bar (VGA 127)
BLUE = (0, 0, 164)
FIXED = ((0, 0, 0), BLUE)                       # black, and the blue that covers the bar in every row

BAR = 98
WEAPONS = list(range(103, 107))
KEYS = (107, 108, 109)          # none, gold, silver
BLANK = 110
DIGITS = list(range(111, 121))
FACES = list(range(121, 145))
IDS = [BAR] + WEAPONS + list(KEYS) + [BLANK] + DIGITS + FACES

MUTANT = 144                    # drawn only for a death by needle, which the shareware floors do not have

# hud.s draws face 122 + 3 b for health band b (the middle look) and 142 when dead
SHOWN_FACES = [122 + 3 * b for b in range(7)] + [142]

if PROFILE.spear:
    _source = source_data()
    _source.graphics()
    _roles = _source.graphics_layout['roles']
    BAR = _roles['status_bar']
    WEAPONS = list(range(_roles['weapon_first'], _roles['weapon_first'] + 4))
    KEYS = tuple(range(_roles['key_first'], _roles['key_first'] + 3))
    BLANK = _roles['hud_blank']
    DIGITS = list(range(_roles['hud_digit_first'], _roles['hud_digit_first'] + 10))
    FACES = list(range(_roles['face_first'], _roles['face_first'] + 23)) + [_roles['face_ouch']]
    IDS = [BAR] + WEAPONS + list(KEYS) + [BLANK] + DIGITS + FACES
    MUTANT = -1
    SHOWN_FACES = [_roles['face_first'] + 1 + 3 * b for b in range(7)] + [_roles['face_first'] + 21]

# HUD field positions relative to the status bar; must match hud.s.
NUMBERS = ((16, 16, 2), (48, 16, 6), (112, 16, 1), (168, 16, 3), (216, 16, 2))   # x, y, digits
FACE_AT = (136, 4)
WEAPON_AT = (256, 8)
KEY_AT = ((240, 4), (240, 20))


class Status:
    def __init__(self, count=COUNT, fixed=FIXED, face_weight=24, other_face_weight=1, align=True, border=(0, 0, 0), **search):
        self.count = count
        self.fixed = fixed
        self.pics = {n: wp.picture(n) for n in IDS}
        self.rgb = {n: wp.rgb_rows(self.pics[n][2]) for n in IDS}
        if border:
            self.rgb[BAR] = [[border if wp.is_teal(c) else c for c in row] for row in self.rgb[BAR]]
        hist = self._histogram(face_weight, other_face_weight)
        search = {'restarts': 12, **search}
        self.row_pal, self.pals = wp.search(hist, count, fixed=fixed, rows=range(HEIGHT), **search)
        if align:
            self._align()

    def _histogram(self, face_weight, other_face_weight):
        hist = {y: {} for y in range(HEIGHT)}

        def add(n, x, y, weight):
            wp.rowhist_of(self.rgb[n], None, x, y, hist, weight)
        add(BAR, 0, 0, 4)
        for n in WEAPONS:
            add(n, *WEAPON_AT, 2)
        for n in KEYS:
            for at in KEY_AT:
                add(n, *at, 1)
        for n in [BLANK] + DIGITS:
            for x, y, count in NUMBERS:
                for i in range(count):
                    add(n, x + 8 * i, y, 1)
        for n in FACES:
            if n != MUTANT:
                add(n, *FACE_AT, face_weight if n in SHOWN_FACES else other_face_weight)
        return hist

    def _align(self):
        """Align slots through shared_gray.align_palette while preserving the fixed prefix."""
        from shared_gray import align_palette, rgb, word
        self.pals = [[rgb(c) for c in align_palette([word(c) for c in p], len(self.fixed))] for p in self.pals]

    # -- pictures at their places

    def convert(self, n, x, y, mode='nearest', snap=700):
        """Palette indexes (rows) of picture n drawn at x, y of the bar."""
        rgb = self.rgb[n]
        rp = [self.row_pal[y + i] for i in range(len(rgb))]
        return wp.convert(rgb, rp, self.pals, mode, first_row=STATUS_Y + y, snap=snap)

    def frame(self, face, weapon=1, keys=(True, True), numbers=(1, 12340, 3, 100, 50), mode='nearest', snap=700):
        """RGB rows of the whole bar as the game shows it, and the same in VGA colors."""
        shown = [list(r) for r in wp.rgb_rows(self.pics[BAR][2])]
        indexes = self.convert(BAR, 0, 0, mode, snap)

        def put(n, x, y):
            idx = self.convert(n, x, y, mode, snap)
            for j, row in enumerate(idx):
                for i, k in enumerate(row):
                    indexes[y + j][x + i] = k
        put(FACES[face], *FACE_AT)
        put(WEAPONS[weapon], *WEAPON_AT)
        put(KEYS[1] if keys[0] else KEYS[0], *KEY_AT[0])
        put(KEYS[2] if keys[1] else KEYS[0], *KEY_AT[1])
        for (x, y, count), value in zip(NUMBERS, numbers):
            text = str(value).rjust(count)[-count:]
            for i, ch in enumerate(text):
                put(BLANK if ch == ' ' else DIGITS[int(ch)], x + 8 * i, y)
        return wp.shown(indexes, self.row_pal, self.pals)

    def frame_vga(self, face, weapon=1, keys=(True, True), numbers=(1, 12340, 3, 100, 50)):
        """The bar as the game shows it, as VGA color indexes."""
        rows = [list(r) for r in self.pics[BAR][2]]

        def put(n, x, y):
            for j, row in enumerate(self.pics[n][2]):
                rows[y + j][x:x + len(row)] = row
        put(FACES[face], *FACE_AT)
        put(WEAPONS[weapon], *WEAPON_AT)
        put(KEYS[1] if keys[0] else KEYS[0], *KEY_AT[0])
        put(KEYS[2] if keys[1] else KEYS[0], *KEY_AT[1])
        for (x, y, count), value in zip(NUMBERS, numbers):
            text = str(value).rjust(count)[-count:]
            for i, ch in enumerate(text):
                put(BLANK if ch == ' ' else DIGITS[int(ch)], x + 8 * i, y)
        return rows

    def frame_original(self, face, **kw):
        return wp.rgb_rows(self.frame_vga(face, **kw))
