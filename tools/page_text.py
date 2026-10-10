"""Original ending-page text layout."""
import re
TEXTROWS = (200 - 16 - 32) // 10
FONTHEIGHT = 10
TOPMARGIN = 16
LEFTMARGIN = 16
RIGHTMARGIN = 16
PICMARGIN = 8
SPACEWIDTH = 7
SCREENMID = 160


class Layout:
    def __init__(self, font, pics):
        self.height, self.widths, _ = font
        self.pics = pics                 # number -> (width, height)

    def width(self, word):
        return sum(self.widths[min(94, max(0, ord(c) - 32))] for c in word)

    def page(self, body):
        """(runs, pictures): runs are (x, y, color, text with chr(1) for a 7 pixel gap)."""
        self.t = body
        self.i = 0
        self.runs = []
        self.pictures = []
        self.cur = None
        self.left = [LEFTMARGIN] * TEXTROWS
        self.right = [320 - RIGHTMARGIN] * TEXTROWS
        self.px, self.py, self.row = LEFTMARGIN, TOPMARGIN, 0
        self.done = False
        self.color = 0
        self.gap = 0
        t = self.t
        while self.i < len(t) and not self.done:
            ch = t[self.i]
            if ch == '^':
                self.command()
            elif ch == '\t':
                self.px = (self.px + 8) & 0xf8
                self.i += 1
                self.gap = 0
                self.cur = None
            elif ord(ch) <= 32:
                self.i += 1
                if ch == '\n':
                    self.newline()
            else:
                self.word()
        self.flush()
        return self.runs, self.pictures

    def flush(self):
        self.cur = None

    def newline(self):
        self.cur = None
        self.gap = 0
        self.row += 1
        if self.row == TEXTROWS:
            self.done = True
            return
        self.px = self.left[self.row]
        self.py += FONTHEIGHT

    def number(self):
        t = self.t
        while self.i < len(t) and not t[self.i].isdigit():
            self.i += 1
        j = self.i
        while j < len(t) and t[j].isdigit():
            j += 1
        n = int(t[self.i:j])
        self.i = j
        return n

    def rip(self):
        while self.i < len(self.t) and self.t[self.i] != '\n':
            self.i += 1
        self.i += 1

    def command(self):
        t = self.t
        self.i += 1
        c = t[self.i].upper()
        if c in 'PE':
            self.done = True
        elif c == ';':
            self.rip()
        elif c == 'B':
            for _ in range(4):
                self.number()
            self.rip()
        elif c == 'C':
            self.color = int(t[self.i + 1:self.i + 3], 16)
            self.i += 3
            self.cur = None
        elif c == '>':
            self.px = 160
            self.i += 1
            self.cur = None
        elif c == 'L':
            py = self.number()
            self.row = (py - TOPMARGIN) // FONTHEIGHT
            self.py = TOPMARGIN + self.row * FONTHEIGHT
            self.px = self.number()
            self.rip()
            self.cur = None
        elif c in 'GT':
            y = self.number()
            x = self.number()
            n = self.number()
            if c == 'T':
                self.number()
            self.rip()
            self.picture(x & ~7, y, n)
        else:
            raise ValueError('page command ^' + c)

    def picture(self, x, y, n):
        w, h = self.pics[n]
        self.pictures.append((x, y, n))
        mid = x + w // 2
        margin = x - PICMARGIN if mid > SCREENMID else x + w + PICMARGIN
        top = max(0, (y - TOPMARGIN) // FONTHEIGHT)
        bottom = min(TEXTROWS - 1, (y + h - TOPMARGIN) // FONTHEIGHT)
        for r in range(top, bottom + 1):
            if mid > SCREENMID:
                self.right[r] = margin
            else:
                self.left[r] = margin
        if self.px < self.left[self.row]:
            self.px = self.left[self.row]

    def word(self):
        t = self.t
        j = self.i + 1
        while j < len(t) and t[j] > ' ':
            j += 1
        w = t[self.i:j]
        self.i = j
        ww = self.width(w)
        while self.px + ww > self.right[self.row]:
            self.newline()
            if self.done:
                return
        spaces = 0
        k = self.i
        while k < len(t) and t[k] == ' ':
            spaces += 1
            k += 1
        cur = self.cur
        if cur and cur['y'] == self.py and cur['color'] == self.color and cur['end'] + self.gap * SPACEWIDTH == self.px:
            cur['text'] += chr(1) * self.gap + w
            cur['end'] = self.px + ww
        else:
            cur = dict(x=self.px, y=self.py, color=self.color, text=w, end=self.px + ww)
            self.runs.append(cur)
            self.cur = cur
        self.px += ww
        self.gap = spaces
        self.px += 0
        self.i = k
        # the gap before the next word is made of these spaces
        self.px += spaces * SPACEWIDTH
