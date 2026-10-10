"""Menu pictures fitted from original artwork or native engine RGB pixels."""
from collections import Counter, deque
import hashlib
import json
import struct

from wolfdata import ROOT, PROFILE, source_data, palette
from shared_gray import align_palette, rgb, word


def portrait_paths():
    return [ROOT/'build/assets/difficulty-previews'/f'difficulty-{i+1}.bin' for i in range(4)]


def picture_record(pixels, left, top, band):
    """Two row palettes that hold the menu's overlay inks in the menu's slots (black, white and its four
    grays, shared_gray.OVERLAY_SLOTS of STEEL): the loading box and the dimmed backdrop, which cross the
    portrait's rows, then show the same colors there as on the menu's own rows."""
    import wolfpics
    from frontend.build_words import block
    from shared_gray import OVERLAY_SLOTS, STEEL
    wolfpics.set_metric('rgb')
    hist = {y: Counter(rgb(c) for c in row if c is not None) for y, row in enumerate(pixels)}
    inks = tuple(rgb(STEEL[slot]) for slot in OVERLAY_SLOTS)
    selected, fitted = wolfpics.search(hist, 2, fixed=inks, rounds=10)
    # search puts the fixed colors first, in OVERLAY_SLOTS order; slot 0 is kept in place.
    pins = {i: slot for i, slot in enumerate(OVERLAY_SLOTS) if i}
    pals = [align_palette([word(c) for c in p], fixed_slots=pins) for p in fitted]
    rows = [[None]*320 for _ in range(64)]
    scb = [13]*64
    for y, row in enumerate(pixels):
        p = selected[y]; scb[top-band+y] = 13+p
        mapping = {c: min(range(16), key=lambda i: wolfpics.rgb_dist(rgb(c), rgb(pals[p][i]))) for c in row if c is not None}
        rows[top-band+y][left:left+len(row)] = [None if c is None else mapping[c] for c in row]
    return struct.pack('<H32H',band,*(c for p in pals for c in p))+bytes(scb)+block(rows,0)


def build_portraits():
    source = source_data(); chunks = source.graphics(); colors = palette()
    first = source.graphics_layout['roles']['difficulty_first']; receipt=[]
    for index, path in enumerate(portrait_paths()):
        chunk=first+index; width,height=struct.unpack_from('<HH',chunks[0],(chunk-3)*4)
        raw=chunks[chunk]; plane=width*height//4
        if len(raw)!=width*height: raise ValueError('Difficulty portrait is not a planar picture')
        rows=[[raw[(x&3)*plane+y*(width//4)+x//4] for x in range(width)] for y in range(height)]
        background=rows[0][0]
        todo=deque([(x,y) for x in range(width) for y in (0,height-1)]+[(x,y) for x in (0,width-1) for y in range(height)])
        while todo:
            x,y=todo.popleft()
            if not (0<=x<width and 0<=y<height) or rows[y][x]!=background: continue
            rows[y][x]=None;todo.extend(((x-1,y),(x+1,y),(x,y-1),(x,y+1)))
        pixels=[[None if rows[y*height//48][x*width//36] is None else word(colors[rows[y*height//48][x*width//36]]) for x in range(36)] for y in range(48)]
        record=picture_record(pixels,142,44,44)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(record)
        receipt.append(dict(chunk=chunk,source_sha256=hashlib.sha256(raw).hexdigest(),record_sha256=hashlib.sha256(record).hexdigest()))
    (portrait_paths()[0].parent/'source.json').write_text(json.dumps(dict(profile=PROFILE.key,pictures=receipt),indent=2)+'\n')
    return portrait_paths()
