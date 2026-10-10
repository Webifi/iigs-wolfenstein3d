"""The four centered Wolf fields. 120 keeps n mod 4 < 3 of the full 160."""
SIZES=(80,107,120,160)
HEIGHTS=list(range(2,161,2))+list(range(164,641,4))


def scale_height(rows):
    return min(HEIGHTS,key=lambda h:abs(h-rows))


def weapon_height(rows):
    """SimpleScaleShape receives viewheight+1 and discards its low bit."""
    return (rows+1)&~1
