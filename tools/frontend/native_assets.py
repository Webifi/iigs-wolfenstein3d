"""Native alpha blocks and compact picture rectangles for the paused UI."""
import struct


def unpack_block(data, at, height=200):
    rows = [[None] * 320 for _ in range(height)]
    while True:
        off = struct.unpack_from('<H', data, at)[0]; at += 2
        if off == 65535:
            return rows
        masked = off & 32768
        off &= 32767
        if masked:
            mask, ink = struct.unpack_from('<HH', data, at); at += 4
            values = [(mask & 255, ink & 255), (mask >> 8, ink >> 8)]
        else:
            count = struct.unpack_from('<H', data, at)[0]; at += 2
            values = [(0, c) for c in data[at:at + count]]; at += count
        y, x = divmod(off, 160); x *= 2
        for mask, ink in values:
            for shift in (4, 0):
                if not (mask >> shift & 15):
                    rows[y][x] = ink >> shift & 15
                x += 1


def alpha(rows):
    """Eight pixels: an alpha byte and four native SHR bytes, no pixel shifts."""
    groups = (len(rows[0]) + 7) // 8
    blocks=[]
    for row in rows:
        row = row + [None] * (groups * 8 - len(row))
        block=bytearray()
        for x in range(0, len(row), 8):
            cells = row[x:x + 8]
            mask=sum((c is None) << i for i, c in enumerate(cells))
            block.append(mask)
            if mask != 255:
                block.extend(((a or 0) << 4) | (b or 0) for a, b in zip(cells[::2], cells[1::2]))
        blocks.append(block)
    out=bytearray(struct.pack('<3H',0xfffc,groups,len(rows)))
    offset=2*len(rows)
    for block in blocks:
        out+=struct.pack('<H',offset);offset+=len(block)
    return bytes(out)+b''.join(blocks)


def solid(rows):
    masks=[];pixels=bytearray()
    for row in rows:
        masks.append(tuple(c is None for c in row))
        pixels.extend(((a or 0)<<4)|(b or 0) for a,b in zip(row[::2],row[1::2]))
    if any(mask!=masks[0] for mask in masks) or any(masks[0][4:-4]):
        return alpha(rows)
    def mask(cells):
        v=sum((15 if c else 0)<<(12-i*4) for i,c in enumerate(cells))
        return (v>>8)|((v&255)<<8)
    return struct.pack('<5H',0xfffb,len(rows[0])//2,len(rows),mask(masks[0][:4]),mask(masks[0][-4:]))+pixels


def title(data):
    width, height, bands = struct.unpack_from('<3H', data)
    base = 6 + bands * 52
    phases = struct.unpack_from('<2H', data, base)
    phase = next(i for i, value in enumerate(phases) if value != 65535)
    rows = unpack_block(data, base + phases[phase], height)
    pixels = alpha([row[:width + phase] for row in rows])
    return data[:base] + struct.pack('<2H', *(4 if i == phase else 65535 for i in range(2))) + pixels


def picture(data, scale=1):
    top = struct.unpack_from('<H', data)[0]
    rows = unpack_block(data, 130, 64)
    used = [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c is not None]
    left = min(x for x, y in used) & ~3
    right = (max(x for x, y in used) + 4) & ~3
    first = min(y for x, y in used)
    last = max(y for x, y in used) + 1
    if scale == 2:
        pixels = [row[left:right] for row in rows[first:last]]
        assert all(c is not None for row in pixels for c in row)
        width, height = right-left, last-first
        assert width*2 <= 104 and height*2 <= 48
        x, y = (320-width*2)//2, 32+(48-height*2)//2
        scb = [13]*64
        for n in range(height): scb[y-32+2*n:y-32+2*n+2] = [data[66+first+n]]*2
        header = struct.pack('<5H',x,y,width*2,height*2,32)
        packed = bytes((a<<4)|b for row in pixels for a,b in zip(row[::2],row[1::2]))
        return header + data[2:66] + bytes(scb) + struct.pack('<3H',0xfffa,width//2,height) + packed
    assert scale == 1
    # Palette rows remain the original fixed band; pixels occupy only their rectangle.
    header = struct.pack('<5H', left, top + first, right - left, last - first, top)
    return header + data[2:130] + solid([row[left:right] for row in rows[first:last]])
