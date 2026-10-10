"""Convert the selected DOS quit page to 21 rows of ROM 80-column text.

The source is a 4000-byte B800 text page inside a seven-byte BLOAD header.
Keep every word and block-art row. Remove only decorative or blank rows to
leave Applesoft two line feeds and its prompt below the page. Each output row
contains 40 auxiliary-page bytes followed by 40 main-page bytes.
"""
import hashlib
import json
import struct

ROWS, COLUMNS = 21, 80
SHADING = {0xb0, 0xb1, 0xb2}
VERTICAL = {0xb3, 0xba}
BOX = set(range(0xb3, 0xdb))
# The small checker, full checker and inverse small checker retain the
# three DOS shade densities. MouseText supplies continuous horizontal lines.
# The ROM has no half-block glyphs; block lettering becomes connected strokes.
GLYPHS = {0xb0: 0xff, 0xb1: 0x56, 0xb2: 0x7f,
          0xc4: 0x53, 0xcd: 0x53, 0xb3: 0xfc, 0xba: 0xfc,
          0xdb: 0x20, 0xdc: 0xdf, 0xdf: 0x4c, 0xfe: 0x5e}
GLYPHS.update({c: 0xab for c in BOX if c not in GLYPHS})


def apple(ch):
    if ch in GLYPHS:
        return GLYPHS[ch]
    if ch in (0, 0x20, 0xff):
        return 0xa0
    if 0x21 <= ch < 0x7f:
        return ch | 0x80
    raise ValueError(f'quit page character 0x{ch:02x} has no ROM text mapping')


def apple_row(row):
    block = {0xdb, 0xdc, 0xdf}
    half = {0xdc, 0xdf}
    result = bytearray()
    for x, ch in enumerate(row):
        left = row[x-1] if x else 0x20
        right = row[x+1] if x+1 < len(row) else 0x20
        if ch in half:
            if left not in block and right in half and ch != right:
                result.append(0xaf if ch == 0xdc else 0xdc)
            elif right not in block and left in half and ch != left:
                result.append(0xdc if ch == 0xdc else 0xaf)
            else:
                result.append(0x53)
        elif ch == 0xdb:
            result.append(0xab if left in half or right in half else 0xfc)
        else:
            result.append(apple(ch))
    return bytes(result)


def convert(chunk):
    if len(chunk) not in (4007, 4008) or chunk[:7] != struct.pack('<BHHH', 0xfd, 0xb800, 0, 4000):
        raise ValueError('quit page must be an 80x25 B800 BLOAD image')
    if len(chunk) == 4008 and chunk[-1] != 0x1a:
        raise ValueError('unexpected quit page trailer')
    page = chunk[7:4007:2]
    rows = [page[i:i+COLUMNS] for i in range(0, len(page), COLUMNS)]
    keep = list(range(25))
    ornament = SHADING | {0, 0x20, 0xff}
    while keep and set(rows[keep[0]]) <= ornament:
        keep.pop(0)
    while keep and set(rows[keep[-1]]) <= ornament:
        keep.pop()
    # Empty bordered rows go first; then an interior separator, never text.
    for allowed in (ornament | VERTICAL, ornament | BOX):
        for index in keep[1:-1]:
            if len(keep) <= ROWS:
                break
            if set(rows[index]) <= allowed:
                keep.remove(index)
    if len(keep) > ROWS:
        raise ValueError('quit page cannot fit without losing text or block art')
    mapped = [apple_row(rows[index]) for index in keep]
    mapped += [bytes([0xa0])*COLUMNS]*(ROWS-len(mapped))
    return b''.join(row[::2]+row[1::2] for row in mapped), keep


def build(source, out):
    chunks = source.graphics()
    number = source.graphics_layout['roles']['quit_text']
    chunk = chunks[number]
    data, keep = convert(chunk)
    (out/'quit-text.bin').write_bytes(data)
    (out/'quit-text.json').write_text(json.dumps(dict(
        source_chunk=number, source_sha256=hashlib.sha256(chunk).hexdigest(),
        source_rows=keep, rows=ROWS, columns=COLUMNS, bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest()), indent=2)+'\n')
