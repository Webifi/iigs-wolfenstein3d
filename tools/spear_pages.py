"""Spear ending screens, with each original screen's own VGA palette."""
from wolfdata import source_data
import art_pages as ap
import wolfpics as wp

# WL_INTER.C EndSpear: two caption frames on screen 3, then screen 2 last.
ORDER = (1,3,3,4,5,6,7,8,9,2)
CAPTIONS = (
    ('We owe you a great debt, Mr. Blazkowicz.', 'You have served your country well.'),
    ('With the spear gone, the Allies will finally', 'be able to destroy Hitler...'),
)


def pages(font):
    source = source_data(); chunks = source.graphics(); roles = source.graphics_layout['roles']
    out = []
    caption = 0
    for number in ORDER:
        chunk = roles['ending_picture_'+str(number)]
        raw_palette = chunks[roles['ending_palette_'+str(number)]]
        if len(raw_palette) != 768 or max(raw_palette) > 63:
            raise ValueError('invalid Spear ending VGA palette')
        palette = [tuple(c*4 for c in raw_palette[i:i+3]) for i in range(0,768,3)]
        width,height,indices = wp.picture(chunk)
        if (width,height) != (320,200):
            raise ValueError('Spear ending screen must be 320 by 200')
        page = [[palette[c] for c in row] for row in indices]
        if number == 3:
            page[180:] = [[palette[0]]*320 for _ in range(20)]
            for line,text in enumerate(CAPTIONS[caption]):
                width = sum(font[1][ord(c)-32] for c in text)
                ap.draw_text(page,font,(320-width)//2,180+line*10,text,palette[0xd0])
            caption += 1
        out.append(ap.record(*ap.new_end(page,None)))
    return out
