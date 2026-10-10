"""Measure decoded wall light using matched source texels, not fit error."""
import json
from pathlib import Path

from wolfdata import ROOT, vswap
from reference import render, project_sprites
from viewgeometry import HEIGHTS


def linear(c):
    c=c/255
    return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4


def luminance(rgb):
    return sum(k*linear(c) for k,c in zip((.2126,.7152,.0722),rgb))


def main():
    record=json.loads((ROOT/'build/palettes/0.json').read_text())
    palette=record['palette'];lights=record['wall_lights'];pages,_,_=vswap()
    state=json.loads((ROOT/'build/tests/timing-ref120/state12.json').read_text())
    state.update(x=8832,y=12040,angle=256)
    _,stats=render(state,160,interpolate=False)
    shapes=json.loads((ROOT/'build/assets/sprites.json').read_text())
    frame_bytes=json.loads((ROOT/'build/assets/sprite-stats.json').read_text())['frame_bytes']
    ids={i*frame_bytes:k for i,k in enumerate(sorted(shapes,key=int))}
    weapon=project_sprites(state,[],set(),160)[-1]
    wl,wr,_,frame,_,wh,_=weapon
    sums=[0.]*len(lights);n=0
    for x in range(160):
        if x%3==2:continue
        h,page,u,_,_,_=stats['records'][x]
        if h>32:continue
        for y in range(max(0,80-h//2),min(160,80+h//2)):
            if y%3==2:continue
            if wl<=x<wr:
                wu=round(32768/wh)*(x-wl)//256
                wy=(y-(80-wh//2))*64//wh
                if wu<64 and any(a<=wy<b for a,b,_ in shapes[ids[frame]]['columns'][wu]):continue
            tex=min(63,max(0,(y-(80-h//2))*64//h));c=pages[page][u*64+tex]
            for i in range(len(lights)):
                a,b=lights[i][c]
                sums[i]+=sum(luminance(palette[k]) for k in (a>>4,a&15,b>>4,b&15))/4
            n+=1
    assert n and sums[-1]>0
    ratio=sums[0]/sums[-1]
    assert ratio<.5, 'far wall lost its depth shading'
    assert all(a<b for a,b in zip(sums,sums[1:]))
    result=dict(camera={k:state[k] for k in ('x','y','angle')},wall_samples=n,
                matched_texel_luminance=[v/n for v in sums],dark_bright_ratio=ratio)
    out=ROOT/'build/tests/rewrite-shading';out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,separators=(',',':')))


if __name__=='__main__':main()
