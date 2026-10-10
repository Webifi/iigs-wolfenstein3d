"""Pack the status-bar pictures using tools/art_status.py: 12 palettes (SCB 1..12)
for 40 screen rows. Convert each picture at its HUD position so hud.s can copy bytes.

ui.bin: the pictures, 4 bits a pixel. The order is the one of hud.s: the bar, the weapons, the keys (none, gold, silver),
the empty digit, the digits 0-9, the 24 faces, and last a second picture of no key for the lower place.
ui.json: the palettes, the palette of each row and the records, for the tools that model the bar.
gen/ui.inc: uiPics (offset, width in bytes, height), uiPal (12 palettes of $0RGB words) and uiRows (the SCB of each row).
"""
import json
import struct

import art_status as st
import wolfpics as wp
from wolfdata import ROOT

FIRST_PALETTE = 1       # SCB of the first status palette: the view has 0
NO_KEY_LOWER = len(st.IDS)

# where hud.s draws each picture, x and y in the bar
NUMBER_AT = st.NUMBERS[0][:2]


def places():
    """[(picture, x, y)] in the order of ui.bin."""
    out = []
    for n in st.IDS:
        if n == st.BAR:
            at = (0, 0)
        elif n in st.WEAPONS:
            at = st.WEAPON_AT
        elif n == st.KEYS[2]:
            at = st.KEY_AT[1]
        elif n in st.KEYS:
            at = st.KEY_AT[0]
        elif n in st.FACES:
            at = st.FACE_AT
        else:
            at = NUMBER_AT
        out.append((n,) + tuple(at))
    out.append((st.KEYS[0],) + tuple(st.KEY_AT[1]))
    return out


def main():
    status = st.Status()
    blob = bytearray()
    records = []
    for n, x, y in places():
        idx = status.convert(n, x, y)
        records.append([len(blob), len(idx[0]) // 2, len(idx)])
        blob += wp.pack(idx)
    if [r[1:] for r in records[:2]] != [[160, 40], [24, 24]]:
        raise ValueError('v1.4 status layout')
    rows = [FIRST_PALETTE + p for p in status.row_pal]
    words = [[wp.word12(c) for c in pal] for pal in status.pals]
    (ROOT/'build/assets/ui.bin').write_bytes(bytes(blob))
    (ROOT/'build/assets/ui.json').write_text(json.dumps(
        dict(places=places(), palettes=[[list(c) for c in pal] for pal in status.pals], rows=rows, records=records),
        separators=(',', ':')) + '\n')
    lines = [' .section gamedata, data, root',
             'uiPics: .word ' + ','.join(str(v) for r in records for v in r),
             'uiPal: .word ' + ','.join(str(w) for pal in words for w in pal),
             'uiRows: .byte ' + ','.join(str(r) for r in rows)]
    (ROOT/'build/gen/ui.inc').write_text('\n'.join(lines) + '\n')
    # God faces use the existing row palettes and swap with the normal face
    # pixels only while enabled. No HUD palette or resident picture grows.
    faces = bytearray()
    if st.PROFILE.spear:
        first = st.FACES[0] + 23
        for number in range(first, first + 3):
            width, height, pixels = wp.picture(number)
            if (width, height) != (24, 32):
                raise ValueError('Spear god face must be 24 by 32 pixels')
            rgb = wp.rgb_rows(pixels)
            rp = status.row_pal[st.FACE_AT[1]:st.FACE_AT[1] + height]
            faces += wp.pack(wp.convert(rgb, rp, status.pals, 'nearest',
                                       first_row=st.STATUS_Y + st.FACE_AT[1]))
    (ROOT/'build/assets/debug-faces.bin').write_bytes(faces)
    (ROOT/'build/gen/debug-faces.inc').write_text(
        f'DEBUG_FACE_OFFSET .equ {records[19][0]}\nDEBUG_FACE_BYTES .equ {len(faces)}\n')
    print('status art:', len(blob), 'bytes,', len(records), 'pictures,', status.count, 'palettes')


if __name__ == '__main__':
    main()
