"""Resident, borderless portraits and one clean floor preview per selection."""
from pathlib import Path
import struct,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/frontend/lettering')]
from frontend.previews.render import source,nearest,shrink,picture_band,Screen
from frontend.build_words import block
from gscolor import align8
from render import shr_screen
from imaging import blank,blit
OUT=ROOT/'data/frontend-previews'
GRAYS=[0,0x111,0x222,0x333,0x444,0x555]


def align_preview(words):
    """Keep the menu gray prefix. Permute the other colors onto ALIGN_REF."""
    def rgb(c):
        return ((c >> 8) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17)
    def word(c):
        r, g, b = (v // 17 for v in c)
        return (r << 8) | (g << 4) | b
    return [word(c) for c in align8([rgb(c) for c in words], len(GRAYS))]

def artwork(kind,index):
    if kind=='difficulty':return nearest(source(31+index,True),36,48),142,44
    raw=(OUT/'source'/f'floor-{index+1:02d}.rgb12').read_bytes()
    pixels=struct.unpack('<%dH'%(214*107),raw)
    rows=[pixels[y*214:(y+1)*214] for y in range(107)]
    return shrink(rows,106,53),107,42

def record(kind,index):
    picture,x,y=artwork(kind,index)
    top=44 if kind=='difficulty' else 40;art=blank(320,64,None);blit(art,picture,x,y-top)
    sc=Screen(blank(320,200,0));picture_band(sc,art,top)
    palettes=[align_preview((GRAYS+[c for c in sc.palettes[p] if c not in GRAYS]+[0]*16)[:16]) for p in (13,14)]
    rows=[[None if c is None else palettes[sc.scb[top+yy]-13].index(sc.rows[top+yy][xx]) for xx,c in enumerate(row)] for yy,row in enumerate(art)]
    return struct.pack('<H32H',top,*(c for pal in palettes for c in pal))+bytes(sc.scb[top:top+64])+block(rows,0)

if __name__=='__main__':
    for kind,count in (('difficulty',4),('floor',10)):
        for i in range(count):
            name=f'difficulty-{i+1}' if kind=='difficulty' else f'floor-{i+1:02d}'
            data=record(kind,i);(OUT/(name+'.bin')).write_bytes(data);print(name,len(data))
