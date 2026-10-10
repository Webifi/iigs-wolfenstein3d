"""The floor completed screen as the game draws it, for tools/check_floor_flow.py: rows 0-159 of the screen from the
pieces of the lump tally (tools/art_lumps.py), the way Write() of WL_INTER.C lays them out (src/iigs/tally.s)."""
import re
import struct

from wolfdata import ROOT

PAR = (90, 120, 120, 210, 180, 180, 150, 150)
CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:%!'


def constants():
    return {m.group(1): int(m.group(2)) for m in re.finditer(r'^(\w+)\s+\.equ\s+(\d+)', (ROOT / 'build/gen/menu.inc').read_text(), re.M)}


def lump():
    c = constants()
    raw = (ROOT / 'build/assets/menu.bin').read_bytes()
    first, count, _, size = struct.unpack_from('<HHHH', raw, 8 + 8 * c['LUMP_TALLY'])
    return raw[first * 512:(first + count) * 512], c


def screen(tally, secret, pose=0):
    """(pixels of rows 0-159, the palette of each row, the 3 palettes) of the screen with BJ in pose 0 or 1; tally is the
    record of FLOW_TALLY: floor (index), bonus, seconds. The ratios of the test are 100, 0 and 50."""
    data, c = lump()
    px = bytearray([c['TALLY_FILL']]) * 25600
    for row in range(88):
        px[(16 + row) * 160:(16 + row) * 160 + 52] = data[c['TALLY_BJ1'] + row * 52:c['TALLY_BJ1'] + row * 52 + 52]
    if pose:
        for row in range(c['TALLY_BJ2_H']):
            at = (16 + c['TALLY_BJ2_Y'] + row) * 160 + c['TALLY_BJ2_X']
            px[at:at + c['TALLY_BJ2_W']] = data[c['TALLY_BJ2'] + row * c['TALLY_BJ2_W']:c['TALLY_BJ2'] + (row + 1) * c['TALLY_BJ2_W']]

    def char(ch, x, y):
        if ch in CHARS:
            at = struct.unpack_from('<H', data, c['TALLY_GLYPHS'] + 2 * CHARS.index(ch))[0]
            width = 4 if ch in ':!' else 8
            for row in range(16):
                px[(y + row) * 160 + x // 2:(y + row) * 160 + x // 2 + width] = data[at + row * width:at + (row + 1) * width]
        return x + (8 if ch in ':!' else 16)

    def text(x, y, s):
        for ch in s:
            x = char(ch, x, y)

    def clock(seconds, y):
        m, s = divmod(seconds, 60)
        text(208, y, '%02d:%02d' % (m, s))

    def value(v, right, y):
        s = str(v)
        text(right - 16 * len(s), y, s)
    if secret:
        text(112, 32, 'SECRET FLOOR')
        text(112, 48, 'COMPLETED!')
        text(80, 128, '15000 BONUS!')
    else:
        text(112, 16, 'FLOOR')
        text(112, 32, 'COMPLETED')
        text(208, 16, str(tally['floor'] + 1))
        text(112, 56, 'BONUS')
        text(128, 80, 'TIME')
        text(128, 96, 'PAR')
        text(72, 112, 'KILL RATIO    %')
        text(40, 128, 'SECRET RATIO    %')
        text(8, 144, 'TREASURE RATIO    %')
        clock(tally['seconds'], 80)
        clock(PAR[tally['floor']], 96)
        value(tally['bonus'], 288, 56)
        for y, v in zip((112, 128, 144), (100, 0, 50)):
            value(v, 296, y)
    scb = data[c['TALLY_SCB']:c['TALLY_SCB'] + 160]
    pals = data[c['TALLY_PALS']:c['TALLY_PALS'] + 96]
    return bytes(px), bytes(scb), bytes(pals)
