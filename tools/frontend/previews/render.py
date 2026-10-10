"""Native 320x200 proposals: original skill/episode art and engine floor previews."""
import hashlib,json,sys
from collections import Counter,deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/frontend/lettering')]
import wolfpics as wp
from build_frontend import prepare,title_data
from imaging import png,word,rgb,blank,blit
from render import Screen,Face,shr_screen
GRAYS=(0,0x111,0x222,0x333,0x444,0x555)
FONT=[0,0x111,0x222,0x333,0x444,0x555]+[i*0x111 for i in range(6,16)]
OUT=ROOT/'build/frontend/portraits-previews-clean'
WORK=ROOT/'build/frontend/floor-previews-clean'

def gray(rows):
    return [[min(GRAYS,key=lambda g:abs((g&15)*18-(3*(c>>8&15)+6*(c>>4&15)+(c&15)))) if c==0 else min(GRAYS[1:],key=lambda g:abs((g&15)*18-(3*(c>>8&15)+6*(c>>4&15)+(c&15)))) for c in row] for row in rows]

def source(n,cutout=False,scale=1):
    w,h,p=wp.picture(n)
    if cutout:
        color=p[0][0];todo=deque([(x,y) for x in range(w) for y in (0,h-1)]+[(x,y) for x in (0,w-1) for y in range(h)]);seen=set()
        while todo:
            x,y=todo.popleft()
            if (x,y) in seen or not(0<=x<w and 0<=y<h) or p[y][x]!=color:continue
            seen.add((x,y));todo.extend(((x-1,y),(x+1,y),(x,y-1),(x,y+1)))
        for x,y in seen:p[y][x]=None
    pal=wp.vga();rows=[[None if c is None else word(pal[c]) for c in row] for row in p]
    return [[c for c in row for _ in range(scale)] for row in rows for _ in range(scale)]

def nearest(rows,w,h):
    return [[rows[y*len(rows)//h][x*len(rows[0])//w] for x in range(w)] for y in range(h)]

def pistol(sc,x,y):
    _,_,rows=wp.picture(23);pal=wp.vga()
    for yy,row in enumerate(nearest(rows,18,12)):
        for xx,c in enumerate(row):
            if c!=45:sc.rows[y+yy][x+xx]=FONT[round(pal[c][0]/17)]

def floor_position(f):
    column,row=(0,f) if f<4 else (1,f-4) if f<7 else (2,f-7)
    return 50+column*100,108+row*12


def shrink(rows,w,h):
    # Area averages remove the engine's alternating color pairs at thumbnail scale.
    sw,sh=len(rows[0]),len(rows);out=[]
    for y in range(h):
        line=[]
        for x in range(w):
            cells=[rows[yy][xx] for yy in range(y*sh//h,max(y*sh//h+1,(y+1)*sh//h)) for xx in range(x*sw//w,max(x*sw//w+1,(x+1)*sw//w))]
            line.append(sum(round(sum(c>>s&15 for c in cells)/len(cells))<<s for s in (8,4,0)))
        out.append(line)
    return out

def title(sc,cv,limit=13):
    rows=cv['rgb12'];sets=[{c for c in row if c is not None}|{0,0x222} for row in rows];bins=[];members=[]
    for y in sorted(range(len(rows)),key=lambda y:len(sets[y]),reverse=True):
        g=sets[y];fit=[(len(g-b),-len(b),i) for i,b in enumerate(bins) if len(g|b)<=16]
        if fit:i=min(fit)[2];bins[i]|=g;members[i].append(y)
        else:bins.append(g);members.append([y])
    assert len(bins)<=limit,(len(bins),cv['width'])
    x=(320-len(rows[0]))//2
    for i,(colors,ys) in enumerate(zip(bins,members)):
        colors=set(colors)
        for g in GRAYS:
            if len(colors)<16:colors.add(g)
        pal=sorted(colors)+[0]*(16-len(colors));sc.palettes[i]=pal
        neutrals=[c for c in pal if (c>>8&15)==(c>>4&15)==(c&15)]
        for y in ys:
            yy=y+5;sc.scb[yy]=i;sc.rows[yy]=[min(neutrals,key=lambda c:abs((c&15)-(g&15))) for g in sc.rows[yy]]
    blit(sc.rows,rows,x,5)
    assert all(sc.rows[y+5][x+xx]==c for y,row in enumerate(rows) for xx,c in enumerate(row) if c is not None)
    return len(bins)

def picture_band(sc,art,top):
    # Slots 13/14 belong only to the picture rows; lettering keeps its exact colors.
    h=len(art);hist={y:Counter(rgb(c) for c in row if c is not None) for y,row in enumerate(art)}
    wp.set_metric('rgb');rp,pals=wp.search(hist,2,fixed=tuple(rgb(c) for c in GRAYS),rounds=10)
    palettes=[[word(c) for c in p] for p in pals]
    for i,p in enumerate(palettes):sc.palettes[13+i]=p
    cache={}
    for y,row in enumerate(art):
        sc.scb[top+y]=13+rp[y];pal=palettes[rp[y]]
        for x,c in enumerate(row):
            if c is None:continue
            key=(rp[y],c)
            if key not in cache:cache[key]=min(pal,key=lambda q:sum(w*((q>>s&15)-(c>>s&15))**2 for s,w in ((8,3),(4,4),(0,2))))
            sc.rows[top+y][x]=cache[key]
    return dict(top=top,height=h,palettes=[13,14])

def main():
    OUT.mkdir(parents=True,exist_ok=True);titles=title_data();face=Face('BlackOpsOne-Regular.ttf',prepare(),size=6);assert face.height==8
    backdrop=shr_screen((ROOT/'build/tests/help-removed-gallery/game.shr').read_bytes()).rows
    back=gray(backdrop);only_difficulty='--difficulty' in sys.argv
    manifest=[] if not only_difficulty else [m for m in json.loads((OUT/'manifest.json').read_text())['screens'] if not m['name'].startswith('difficulty-')]
    def screen(name,pictures=True):
        sc=Screen(back);sc.palettes[15]=FONT;title(sc,titles[name],13 if pictures else 15);return sc
    def save(name,sc,description,**meta):
        raw=sc.raw();(OUT/(name+'.shr')).write_bytes(raw);png(OUT/(name+'.png'),sc.rows);png(OUT/(name+'@2x.png'),sc.rows,2)
        palettes=sc.metadata();palettes['shared_background_0rgb']=[f'{v:03X}' for v in GRAYS];(OUT/(name+'.palettes.json')).write_text(json.dumps(palettes,indent=2)+'\n')
        assert shr_screen(raw).rows==sc.rows
        manifest.append(dict(name=name,description=description,sha256=hashlib.sha256(raw).hexdigest(),**meta))
    labels=['Can I play, Daddy?',"Don't hurt me.","Bring 'em on!",'I am Death incarnate!']
    for i,label in enumerate(labels):
        sc=screen('Difficulty');art=blank(320,64,None);blit(art,source(31+i,True,2),136,0);picture_band(sc,art,44)
        for j,text in enumerate(labels):face.draw(sc,text,98,112+j*12,'selected' if i==j else 'normal')
        pistol(sc,72,110+i*12)
        save('difficulty-'+str(i+1),sc,'Original BJ difficulty portrait at 48×64 with exact doubled pixels; original red backdrop removed. Only selected word, cursor and portrait change.',source_chunk=31+i,title_ink_exact=True,item_cap_height=face.height,content_bottom=158,picture_rects=[[136,44,48,64]],item_rects=[[97,111+j*12,face.width(t)+2,face.height+2] for j,t in enumerate(labels)],cursor_rect=[72,110+i*12,18,12])
    ep=source(42,scale=2)
    for n in ([] if only_difficulty else range(1,11)):
        raw=(WORK/f'floor-{n:02d}.shr').read_bytes();rows=shr_screen(raw).rows
        preview=shrink([r[52:266] for r in rows[26:133]],128,64)
        png(OUT/f'preview-{n:02d}.png',preview);png(OUT/f'preview-{n:02d}@2x.png',preview,2)
        sc=screen('New Game');art=blank(320,64,None);blit(art,ep,36,8);blit(art,preview,156,0);picture_band(sc,art,40)
        for f in range(10):
            x,y=floor_position(f)
            face.draw(sc,'Floor '+str(f+1),x,y,'selected' if n==f+1 else 'normal' if f+1<=n else 'dim')
        cx,cy=floor_position(n-1);pistol(sc,cx-24,cy-2)
        save(f'floor-{n:02d}',sc,'Episode 1 original castle picture at left; selected floor start at right, rendered without the weapon and cropped above the HUD. Example progression: this floor and earlier floors visited; later floors unavailable.',selected_floor=n,visited_mask=(1<<n)-1,source_chunk=42,title_ink_exact=True,item_cap_height=face.height,content_bottom=154,picture_rects=[[36,48,96,48],[156,40,128,64]],item_rects=[[floor_position(f)[0]-1,floor_position(f)[1]-1,face.width('Floor '+str(f+1))+2,face.height+2] for f in range(10)],cursor_rect=[cx-24,cy-2,18,12])
    if not only_difficulty:
        # A nonconsecutive visited set proves unavailable floors keep their place.
        sc=screen('New Game');art=blank(320,64,None);blit(art,ep,36,8)
        rows=shr_screen((WORK/'floor-03.shr').read_bytes()).rows;blit(art,shrink([r[52:266] for r in rows[26:133]],128,64),156,0);picture_band(sc,art,40)
        for f in range(10):face.draw(sc,'Floor '+str(f+1),*floor_position(f),'selected' if f==2 else 'normal' if f==0 else 'dim')
        cx,cy=floor_position(2);pistol(sc,cx-24,cy-2);save('floor-03-visited-1-3',sc,'Only floors 1 and 3 visited: floor 2 stays dim and is skipped by navigation.',selected_floor=3,visited_mask=5,title_ink_exact=True,item_cap_height=face.height,content_bottom=154,picture_rects=[[36,48,96,48],[156,40,128,64]],item_rects=[[floor_position(f)[0]-1,floor_position(f)[1]-1,face.width('Floor '+str(f+1))+2,face.height+2] for f in range(10)],cursor_rect=[cx-24,cy-2,18,12])
    manifest.sort(key=lambda m:m['name'])
    (OUT/'manifest.json').write_text(json.dumps(dict(native_size=[320,200],palette_limit=16,colors_per_row=16,screens=manifest,source=json.loads((WORK/'source.json').read_text())),indent=2)+'\n')
    cards=''.join(f'<figure><figcaption>{m["name"]}</figcaption><img width="640" height="400" src="{m["name"]}@2x.png"><p>{m["description"]}</p></figure>' for m in manifest)
    (OUT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Wolf3D portraits and floor previews</title><style>body{background:#181818;color:#ddd;font:16px system-ui;margin:24px}figure{display:inline-block;vertical-align:top;margin:12px}img{image-rendering:pixelated}p{max-width:640px}figcaption{margin:8px 0}</style><h1>Difficulty portraits and floor previews</h1><p>Native 320×200 proposals at 2×. A items use eight-pixel capitals, with every list and cursor above the status bar. BJ portraits are 48×64; clean floor previews are 128×64. Three evenly spaced floor columns fit below the two separated pictures. All title ink remains pixel-exact; 13 title palettes + 2 picture palettes + 1 text palette. No runtime changes yet.</p><p><a href="audit.md">Original-menu audit</a></p>'+cards)
    print(json.dumps(dict(screens=len(manifest),out=str(OUT))))
if __name__=='__main__':main()
