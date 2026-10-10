"""Convert the selected DOS campaign's episode illustrations for the menu."""
import hashlib
import json
import struct

from wolfdata import ROOT, PROFILE, source_data, palette


def paths():
    count = len(PROFILE.campaign.document['episode_menu_order'])
    return [ROOT/'build/assets/episode-previews'/f'episode-{i+1}.bin'
            for i in range(count)] if count > 1 else []


def build():
    targets = paths()
    if not targets:
        return []
    import wolfpics
    from frontend.build_words import block
    from shared_gray import align_palette, word, rgb
    source = source_data()
    chunks = source.graphics()
    first = source.graphics_layout['roles'].get('menu_episode_first')
    if first is None:
        raise ValueError('The selected graphics layout needs menu_episode_first for its episode menu')
    colors = palette()
    receipts = []
    for index, target in enumerate(targets):
        chunk = first + index
        width, height = struct.unpack_from('<HH', chunks[0], (chunk-3)*4)
        if width > 106 or height > 32:
            raise ValueError('Episode illustrations must fit the 106 by 32 menu area')
        data = chunks[chunk]
        if len(data) != width*height:
            raise ValueError('Episode illustration is not a planar picture')
        plane = width*height//4
        pixels = [[colors[data[(x&3)*plane+y*(width//4)+x//4]]
                   for x in range(width)] for y in range(height)]
        from collections import Counter
        hist = {y: Counter(row) for y, row in enumerate(pixels)}
        # The surrounding paused image uses these four tones. The other
        # twelve entries belong to this illustration's actual colors.
        backdrop = (0, 0x111, 0x222, 0x333)
        wolfpics.set_metric('rgb')
        row_palettes, fitted = wolfpics.search(hist, 2,
            fixed=tuple(rgb(c) for c in backdrop), rounds=10)
        palettes = [align_palette([word(c) for c in p]) for p in fitted]
        rows = [[None]*320 for _ in range(64)]
        scb = [13]*64
        left, top = (320-width)//2, (40-height)//2
        for y, row in enumerate(pixels):
            selected = row_palettes[y]
            scb[top+y] = 13+selected
            pal = palettes[selected]
            for x, color in enumerate(row):
                rows[top+y][left+x] = min(range(16), key=lambda i:wolfpics.rgb_dist(color, rgb(pal[i])))
        record = (struct.pack('<H32H',40,*(c for p in palettes for c in p))
                  +bytes(scb)+block(rows,0))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(record)
        receipts.append(dict(episode=index+1,source_chunk=chunk,width=width,height=height,
            source_sha256=hashlib.sha256(data).hexdigest(),
            record_sha256=hashlib.sha256(record).hexdigest()))
    (targets[0].parent/'source.json').write_text(json.dumps(dict(profile=PROFILE.key,
        graphics_layout=source.graphics_layout['name'],pictures=receipts),indent=2)+'\n')
    return targets
