"""The four centered Wolf fields. 120 keeps n mod 4 < 3 of the full 160."""
SIZES=(80,107,120,160)
HEIGHTS=list(range(2,161,2))+list(range(164,641,4))


def scale_height(rows):
    return min(HEIGHTS,key=lambda h:abs(h-rows))


def weapon_height(rows):
    """SimpleScaleShape receives viewheight+1 and discards its low bit."""
    return (rows+1)&~1


def midpoint_table():
    """Midpoint height and allowed texel gap for each pair of scaler heights."""
    indices = [min(range(len(HEIGHTS)), key=lambda i: abs(HEIGHTS[i]-h))
               for h in range(1025)]
    data = bytearray()
    for left in HEIGHTS:
        for index in range(256):
            right = HEIGHTS[min(index, len(HEIGHTS)-1)]
            height = indices[(left+right)//2]
            gap = min(255, 3*(left+right)//(2*abs(left-right))) if left != right else 255
            data += bytes((height, gap))
    return bytes(data)
