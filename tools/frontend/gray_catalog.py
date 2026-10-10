"""Build-time gray tables and preview palettes for every palette the game loads.

One 288-byte record per distinct palette: a 256-byte pair table, then the
32-byte source-index gray palette. Records start at $3B:0800. The index at $3B:0000 is
what the palette writers use. Nothing here is built at Esc.

A missing source, or a catalog that does not fit in bank $3B, fails the build.
Bank $3C starts the separate paused menu frame.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import memmap
import struct
import sys
from pathlib import Path

from gray_pair import pair_table, preview_bytes, words_of

ROOT = Path(__file__).resolve().parents[2]
GRAY_BASE = memmap.GRAY_BASE
# Index entries retain their 4-byte pointer format. The catalog must end
# before the paused menu frame at $3C:0000; clean gray pixels remain at $3D:0000.
REC_SIZE = 288
RECS = 0x0800
CATALOG_LIMIT = memmap.SPR_RECORDS - GRAY_BASE  # $3C:0000-7CFF is the paused menu frame

# Index layout. Each entry is a 4-byte $3B/$3C/$3D address.
TINT_AT = 0x0000          # 220 longs
BOOT_AT = 0x0370          # 16 longs
PIC_AT = 0x03B0           # 6 pictures * 16 longs
STEEL_AT = 0x0530         # 1 long
BLACK_AT = 0x0534         # 1 long
from frontend.episode_previews import paths as episode_preview_paths
PREVIEW_COUNT = len(episode_preview_paths())
TALLY_AT = 0x05C8
OVERLAY_AT = 0x0600
EPISODE_PREV_AT = 0x0720  # Extra menu previews use the remaining index space.
PAGE_NAMES = ('title', 'credits', 'pg13', 'victory', 'end1', 'end2')
from shared_gray import STEEL as MENU_STEEL, OVERLAY_PAIRS, align_palette, check, preview, picture, tally

_cache = None


def band_palette(band, used):
    """The 16 colors DrawTitleCore writes, including the neutral fill."""
    return align_palette([int(c, 16) for c in band['colors_0rgb']])


def _letter_pals(titles):
    order = [
        'Wolfenstein 3-D', 'Options', 'Difficulty', 'Load Game', 'Save Game',
        'Display & Sound', 'Key Setup', 'High Scores', 'New Game', 'Controls',
        'Benchmark',
    ]
    keys = [k for k in order if k in titles] + [k for k in titles if k not in order]
    out = []
    for key in keys:
        cv = titles[key]
        bands = cv.get('bands') or []
        rows = cv.get('indices') or []
        used_by = {}
        for band in bands:
            used = used_by.setdefault(band['palette'], set())
            for row in rows[band['start']:band['end']]:
                used.update(v for v in row if v is not None)
        for band in bands:
            out.append(band_palette(band, used_by[band['palette']]))
    return out


def _add(found, colors, where):
    colors = tuple(colors)
    if len(colors) != 16:
        raise SystemExit(f'{where}: palette is {len(colors)} colors')
    check(colors, where)
    found.append((where, colors))


def _load_titles():
    sys.path.insert(0, str(ROOT / 'tools'))
    sys.path.insert(0, str(ROOT / 'tools' / 'frontend'))
    import json
    import build_frontend
    titles = build_frontend.title_data()
    for key, name in (('Difficulty', 'difficulty'), ('New Game', 'floors')):
        titles[key] = build_frontend.preview_title(name)
    return titles


def collect(titles=None, pages=None):
    from wolfdata import PROFILE
    tint_count = 130
    found = []
    _add(found, [0]*16, 'black')
    _add(found, MENU_STEEL, 'menuSteel')
    raw = (ROOT / 'build/assets/tints.bin').read_bytes()
    if len(raw) != tint_count * 32:
        raise SystemExit(f'tints.bin is {len(raw)} bytes, expected {tint_count * 32}')
    for i in range(tint_count):
        _add(found, words_of(raw[i * 32:(i + 1) * 32]), f'tint[{i}]')
    boot = (ROOT / 'build/assets/boot-shared.shr').read_bytes()
    if len(boot) < 32768:
        raise SystemExit('boot picture is short')
    for i in range(16):
        _add(found, words_of(boot[32256 + i * 32:32256 + (i + 1) * 32]), f'boot[{i}]')
    pages = pages or ROOT / 'build/frontend/native/pages'
    for name in (PAGE_NAMES[:4]):
        blob = picture((pages / f'{name}.bin').read_bytes(),name=='victory')
        if len(blob) < 32768:
            raise SystemExit(f'{name}.bin is {len(blob)} bytes')
        for i in range(16):
            _add(found, words_of(blob[32256 + i * 32:32256 + (i + 1) * 32]), f'{name}[{i}]')
    prevs = episode_preview_paths()
    if len(prevs) != PREVIEW_COUNT:
        raise SystemExit('preview lump list drifted')
    for path in prevs:
        blob = preview(path.read_bytes())
        if len(blob) < 10 + 64:
            raise SystemExit(f'{path.name} has no preview palettes')
        for j in range(2):
            off = 2 + j * 32
            _add(found, words_of(blob[off:off + 32]), f'{path.name}[{j}]')
    import json
    tally_data = tally((pages / 'tally.bin').read_bytes(),json.loads((pages/'constants.json').read_text()))
    base = 160
    if len(tally_data) < base + 96:
        raise SystemExit('tally.bin has no palettes')
    for j in range(3):
        _add(found, words_of(tally_data[base + j * 32:base + (j + 1) * 32]), f'tally[{j}]')
    if titles is None:
        titles = _load_titles()
    letters = _letter_pals(titles)
    if not letters:
        raise SystemExit('no lettering palettes')
    for i, pal in enumerate(letters):
        _add(found, pal, f'letter[{i}]')
    return found


def build(titles=None, pages=None):
    """Write the catalog and return color -> byte offset from $3B0000."""
    global _cache
    found = collect(titles, pages)
    from wolfdata import PROFILE
    from gray_local import build_local
    _cache = build_local(sys.modules[__name__], found, pages)
    return _cache


def offset_of(pal):
    if _cache is None:
        build()
    key = tuple(pal)
    if key not in _cache:
        raise SystemExit('lettering palette has no gray table')
    return _cache[key]


def _write_inc(path):
    lines = [
        ';;; Generated by tools/frontend/gray_catalog.py. Bank $3B.',
        f'GRAY_BASE    .equ 0x{GRAY_BASE:06x}',
        f'GRAY_TINT    .equ 0x{GRAY_BASE + TINT_AT:06x}',
        f'GRAY_BOOT    .equ 0x{GRAY_BASE + BOOT_AT:06x}',
        f'GRAY_PIC     .equ 0x{GRAY_BASE + PIC_AT:06x}',
        f'GRAY_STEEL   .equ 0x{GRAY_BASE + STEEL_AT:06x}',
        f'GRAY_BLACK   .equ 0x{GRAY_BASE + BLACK_AT:06x}',
        f'GRAY_TALLY   .equ 0x{GRAY_BASE + TALLY_AT:06x}',
        f'GRAY_RECS    .equ 0x{GRAY_BASE + RECS:06x}',
        f'OFF_TINT     .equ 0x{TINT_AT:04x}',
        f'OFF_BOOT     .equ 0x{BOOT_AT:04x}',
        f'OFF_PIC      .equ 0x{PIC_AT:04x}',
        f'OFF_STEEL    .equ 0x{STEEL_AT:04x}',
        f'OFF_BLACK    .equ 0x{BLACK_AT:04x}',
        f'OFF_EPISODE_PREV .equ 0x{EPISODE_PREV_AT:04x}',
        f'GRAY_PREVIEW_COUNT .equ {PREVIEW_COUNT}',
        f'OFF_TALLY    .equ 0x{TALLY_AT:04x}',
        memmap.fill('SLOT_REC     .equ @MM:SLOT_REC@'),
        memmap.fill('ROW_DONE     .equ @MM:ROW_DONE@'),
        memmap.fill('GRAY_STEEL_ON .equ @MM:GRAY_STEEL_ON@'),
        memmap.fill('PREVIEW_PACK .equ @MM:PREVIEW_PACK@'),
        memmap.fill('GRAY_SCRATCH .equ @MM:GRAY_SCRATCH@'),
        memmap.fill('SLOT_SAVE    .equ @MM:SLOT_SAVE@'),
        memmap.fill('GRAY_PIX     .equ @MM:HEIGHT_TABLE@'),  # not $42: that bank ghosts onto code bank $02
        '',
    ]
    path.write_text('\n'.join(lines))


def _write_unroll(path):
    """160 copies. 8-bit A, 16-bit X, B already 0. One table read, no branch.

    Each copy is 19 bytes and its second instruction is the colour-snapshot store:
    src/iigs/ui_gray.s GraySnapBank patches that store's bank byte (offset 7)."""
    # Convert offscreen. The visible picture keeps its original pixel indices
    # until publication; its own palettes can dim it immediately.
    direct = []
    for offset in range(160):
        direct.extend([
            f'              lda long:0x{memmap.SHR - 0x2000 + offset:06x},x',
            f'              sta long:0x{memmap.SNAP_PIX - 0x2000 + offset:06x},x',
            '              tay',
            '              lda [U_T0],y',
            f'              sta long:0x{memmap.GRAY_PAGE - 0x2000 + offset:06x},x',
            f'              sta long:0x{memmap.MENU_FRAME - 0x2000 + offset:06x},x',
        ])
    path.write_text(';;; Generated offscreen gray row. Do not edit.\n' + '\n'.join(direct) + '\n')


if __name__ == '__main__':
    build()
