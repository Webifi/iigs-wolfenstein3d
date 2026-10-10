"""Original New Game lettering, fitted to the menu's scan-line palettes."""
import struct

import memmap
from frontend.titlecolor import convert_original
from frontend.gray_pair import pair_table, preview_bytes
from shared_gray import GRAYS, align_palette, remap
from wolfdata import palette, source_data

PICTURE_WIDTH, PICTURE_HEIGHT = 156, 30
WIDTH, HEIGHT = max(180, PICTURE_WIDTH + 16), PICTURE_HEIGHT + 14
X, Y = (320 - WIDTH) // 2, 118 - HEIGHT
RECORD = WIDTH * HEIGHT // 2


def original_rows(picture_width, picture_height):
    source = source_data()
    chunks = source.graphics()
    number = source.graphics_layout['roles']['menu_getpsyched']
    width, height = struct.unpack_from('<2H', chunks[0], (number - 3) * 4)
    if (width, height) != (224, 48):
        raise ValueError(f'menu_getpsyched: expected 224x48, got {width}x{height}')
    # The inner rectangle retains the letters and their shadow, without the
    # source picture's panel edge or rivets. Resample before quantization.
    source_x, source_y = 8, 3
    source_width, source_height = width - 16, height - 8
    colors = palette()
    plane = width * height // 4
    rows = []
    for y in range(picture_height):
        row = []
        y0, y1 = y * source_height, (y + 1) * source_height
        for x in range(picture_width):
            x0, x1 = x * source_width, (x + 1) * source_width
            total = [0, 0, 0]
            for sy in range(y0 // picture_height, (y1 + picture_height - 1) // picture_height):
                wy = min(y1, (sy + 1) * picture_height) - max(y0, sy * picture_height)
                for sx in range(x0 // picture_width, (x1 + picture_width - 1) // picture_width):
                    wx = min(x1, (sx + 1) * picture_width) - max(x0, sx * picture_width)
                    px, py = sx + source_x, sy + source_y
                    color = chunks[number][(px & 3) * plane + py * (width // 4) + (px >> 2)]
                    for c in range(3):
                        total[c] += wx * wy * colors[color][c]
            word = sum(round(v / (source_width * source_height * 17)) << s
                       for v, s in zip(total, (8, 4, 0)))
            row.append(word or None)
        rows.append(row)
    return rows


def build(picture_width=PICTURE_WIDTH, picture_height=PICTURE_HEIGHT):
    box_width, box_height = max(180, picture_width + 16), picture_height + 14
    box_x, box_y = (320 - box_width) // 2, 118 - box_height
    left = (box_width - picture_width) // 2
    cv = convert_original(original_rows(picture_width, picture_height), bands=3)
    rows = [[0] * box_width for _ in range(box_height)]
    for y in range(box_height):
        for x in range(box_width):
            if x < 2 or x >= box_width - 2 or y < 2 or y >= box_height - 2:
                rows[y][x] = 12
    record = bytearray(struct.pack('<3H', picture_width, picture_height, len(cv['bands'])))
    records = bytearray()
    gray_start = box_width * box_height // 2 + 6 + 52 * len(cv['bands']) + 6
    for band in cv['bands']:
        old = [int(c, 16) for c in band['colors_0rgb']]
        pal = align_palette(old)
        # The untouched pixels beside the plate use these aligned gray slots.
        if pal[12:16] != list(GRAYS):
            raise ValueError(f'loading band lacks the aligned backdrop grays: {pal}')
        mapping = remap(old, pal)
        for y in range(band['start'], band['end']):
            for x, ink in enumerate(cv['indices'][y]):
                if ink is not None:
                    rows[y + 3][x + left] = mapping[ink]
        address = memmap.NEWGAME_PIC + gray_start + len(records)
        record.extend(bytes((band['start'], band['end'], band['palette'], 0)))
        record.extend(struct.pack('<16H', *pal))
        record.extend(bytes(12))  # The native heading path already has aligned gray pixels.
        record.extend(address.to_bytes(3, 'little') + b'\0')
        records.extend(pair_table(pal) + preview_bytes(pal))
    # The plate supplies the pixels; the standard heading record publishes
    # its palette bands and gray-table bindings with an empty word block.
    record.extend(struct.pack('<3H', 4, 4, 0xffff))
    for y in range(109 - box_y - 2, 109 - box_y + 5):
        for x in range(80 - box_x - 2, 80 - box_x + 162):
            rows[y][x] = 12
    for y in range(109 - box_y, 109 - box_y + 3):
        for x in range(80 - box_x, 80 - box_x + 160):
            rows[y][x] = 0
    pixels = bytes((a << 4) | b for row in rows for a, b in zip(row[::2], row[1::2]))
    result = pixels + record + records
    assert len(result) <= memmap.NEWGAME_PIC_SIZE
    return result
