"""One offline lettering round. Python stdlib and installed Swift/CoreText only."""
import argparse,hashlib,json,struct,subprocess,time,os
from pathlib import Path
from collections import Counter
import original as O
import hand
from shader import Model,check
from assets import graphics,palette
from imaging import png,blank,blit,word,rgb,glyph_rows
from bands import convert,SHARED

HERE=Path(__file__).resolve().parent
FRONT=Path(os.environ.get('WOLF_FRONTEND_ROOT',str(Path(__file__).resolve().parents[3])))
DEFAULT=FRONT/'build/frontend/lettering-mockups'
CANDIDATES=[('A','BlackOpsOne-Regular.ttf','Black Ops One'),
            ('B','AlfaSlabOne-Regular.ttf','Alfa Slab One'),
            ('C','Anton-Regular.ttf','Anton — wide pixel cut'),('D','RussoOne-Regular.ttf','Russo One')]
WHOLE={'Options':22,'Control':38,'Customize':39,'Load Game':40,'Save Game':41,
       'High Scores':102,'Get Psyched!':146}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source_rows(n,box=None):
    rows,w,h=O.picture(n)
    if box is None:
        _,x0,x1,y0,y1=O.SOURCES[n];box=(x0,y0,min(w,x1),min(h,y1))
    a,b,c,d=box;pal=palette()
    result=[[None if rows[y][x]==0 else word(pal[rows[y][x]]) for x in range(a,c)] for y in range(b,d)]
    points=[(x,y) for y,row in enumerate(result) for x,p in enumerate(row) if p is not None]
    x0=min(x for x,y in points);x1=max(x for x,y in points)
    y0=min(y for x,y in points);y1=max(y for x,y in points)
    return [row[x0:x1+1] for row in result[y0:y1+1]]

def logo():
    rows=source_rows(13,(6,3,166,32))
    return rows

def compose(text,lib):
    placed=[];x=0;prev=None
    for ch in text:
        if ch==' ':x+=9;prev=None;continue
        g=lib[ch][0]
        if prev is not None and not(prev['pic']==g['pic'] and prev['x1']+1==g['x0']):x+=1
        if ch=='f' and prev is not None and prev.get('char')=='f':x-=7
        placed.append((x,g));x+=g['width'];prev=g
    top=min(y for _,g in placed for xx,y in g['px']);bottom=max(y for _,g in placed for xx,y in g['px'])
    rows=blank(x,bottom-top+1,None);pal=palette()
    for xx,g in placed:
        for (dx,dy),v in g['px'].items():rows[dy-top][xx+dx]=word(pal[v])
    return rows

def gray(raw):
    pals=struct.unpack_from('<256H',raw,0x7e00)
    mapping=[]
    for c in pals:
        lum=3*(c>>8&15)+6*(c>>4&15)+(c&15)
        mapping.append(0 if lum<20 else 0x111 if lum<62 else 0x222)
    rows=[]
    for y in range(200):
        off=(raw[0x7d00+y]&15)*16
        rows.append([mapping[off+v] for b in raw[y*160:(y+1)*160] for v in (b>>4,b&15)])
    for y in range(160,200):rows[y]=[0]*320
    return rows

class Screen:
    def __init__(self,background):
        self.rows=[row[:] for row in background];self.scb=[15]*200
        self.palettes={15:[i*0x111 for i in range(16)]};self.bands=[]
    def title(self,rows,y):
        art=convert(rows,15);x=(320-len(rows[0]))//2
        for band in art['bands']:
            index=band['palette'];a=y+band['start'];b=y+band['end']
            self.palettes[index]=[int(c,16) for c in band['colors_0rgb']]
            self.scb[a:b]=[index]*(b-a)
            self.bands.append(dict(start=a,end=b,palette=index,colors_0rgb=band['colors_0rgb']))
        blit(self.rows,art['rgb12'],x,y)
        return art
    def raw(self):
        out=bytearray(32768)
        for y,row in enumerate(self.rows):
            colors=self.palettes[self.scb[y]]
            assert all(c in colors for c in row),(y,set(row)-set(colors))
            slots=[colors.index(c) for c in row]
            out[y*160:(y+1)*160]=bytes((a<<4)|b for a,b in zip(slots[::2],slots[1::2]))
        out[0x7d00:0x7dc8]=bytes(self.scb)
        for index,pal in self.palettes.items():struct.pack_into('<16H',out,0x7e00+index*32,*pal)
        return out
    def metadata(self):
        bands=[];start=0
        for y in range(1,201):
            if y==200 or self.scb[y]!=self.scb[start]:
                bands.append(dict(start=start,end=y,palette=self.scb[start],
                    colors_0rgb=[f'{c:03X}' for c in self.palettes[self.scb[start]]]))
                start=y
        return dict(width=320,height=200,bands=bands,shared_background_0rgb=['000','111','222'])

def shr_screen(raw):
    screen=Screen(blank(320,200));screen.scb=list(raw[0x7d00:0x7dc8])
    screen.palettes={i:list(struct.unpack_from('<16H',raw,0x7e00+i*32)) for i in range(16)}
    screen.rows=[[screen.palettes[screen.scb[y]&15][v] for b in raw[y*160:(y+1)*160] for v in (b>>4,b&15)] for y in range(200)]
    return screen

def reference_screen(rows):
    art=convert(rows,16);screen=Screen(art['rgb12']);screen.palettes={}
    for b in art['bands']:
        screen.palettes[b['palette']]=[int(c,16) for c in b['colors_0rgb']]
        screen.scb[b['start']:b['end']]=[b['palette']]*(b['end']-b['start'])
    return screen

class Face:
    def __init__(self,file,work,size=12):
        path=work/(file+('' if size==12 else f'.{size}')+'.json')
        if not path.exists():subprocess.run([str(work/'rasterize'),str(HERE/'fonts'/file),str(size),str(path),'all'],check=True)
        data=json.loads(path.read_text());glyphs=data['glyphs']
        ys=[y for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for y,row in enumerate(glyphs[c]) if '#' in row]
        top,bottom=min(ys),max(ys)
        self.glyphs={c:rows[top:bottom+1] for c,rows in glyphs.items()}
        if file=='Anton-Regular.ttf':
            self.glyphs={c:[''.join(row[min(len(row)-1,int(x/1.7))] for x in range(round(len(row)*1.7))) for row in rows] for c,rows in self.glyphs.items()}
        self.height=bottom-top+1;self.gap=2
    def width(self,text):return sum((5 if c==' ' else len(self.glyphs[c][0])+self.gap) for c in text.upper())-self.gap
    def draw(self,screen,text,x,y,state='normal'):
        text=text.upper();ink={};outlines=set()
        if x is None:x=(320-self.width(text))//2
        for c in text:
            if c==' ':x+=5;continue
            rows=self.glyphs[c]
            mask={(xx,yy) for yy,row in enumerate(rows) for xx,v in enumerate(row) if v=='#'}
            for xx,yy in mask:
                for dx in (-1,0,1):
                    for dy in (-1,0,1):outlines.add((x+xx+dx,y+yy+dy))
                # A continuous opaque face and an inset lit rim. The black
                # contour is never part of the ramp or offset as a shadow.
                t=yy/max(1,self.height-1)
                face=round(9+4*t/.5) if t<=.5 else round(8+3*(t-.5)/.5)
                top_left=(xx-1,yy) not in mask or (xx,yy-1) not in mask
                bottom_right=(xx+1,yy) not in mask or (xx,yy+1) not in mask
                if top_left:level=min(15,face+2)
                elif bottom_right:level=max(6,face-3)
                else:level=face
                if state=='selected':level=min(15,level+1)
                elif state=='dim':level=max(4,min(8,level-5))
                ink[x+xx,y+yy]=level*0x111
            x+=len(rows[0])+self.gap
        for xx,yy in outlines:
            assert 0<=xx<320 and 0<=yy<200,(text,xx,yy)
            screen.rows[yy][xx]=0
        for (xx,yy),c in ink.items():screen.rows[yy][xx]=c
        return len(ink)

def pistol(screen,x,y):
    rows,w,h=O.picture(23);pal=palette()
    for yy,row in enumerate(rows):
        for xx,c in enumerate(row):
            if c!=45:screen.rows[y+yy][x+xx]=round(pal[c][0]/17)*0x111

def wad_reference():
    path=Path(os.environ['WOLF_DOOM_WAD']);data=path.read_bytes()
    _,count,start=struct.unpack_from('<4sII',data);lumps={}
    for i in range(count):
        p,n,name=struct.unpack_from('<II8s',data,start+16*i);lumps[name.rstrip(b'\0').decode()]=data[p:p+n]
    pal=[word(tuple(lumps['PLAYPAL'][i:i+3])) for i in range(0,768,3)]
    def patch(name):
        raw=lumps[name];w,h,_,_=struct.unpack_from('<hhhh',raw);rows=blank(w,h,None)
        for x in range(w):
            p=struct.unpack_from('<I',raw,8+4*x)[0]
            while raw[p]!=255:
                y,n=raw[p:p+2];p+=3
                for j,v in enumerate(raw[p:p+n]):rows[y+j][x]=pal[v]
                p+=n+1
        return rows
    rows=patch('TITLEPIC')
    bg=[]
    for row in rows:
        r=[]
        for c in row:
            c=c or 0;lum=3*(c>>8&15)+6*(c>>4&15)+(c&15)
            r.append(0 if lum<20 else 0x111 if lum<62 else 0x222)
        bg.append(r)
    blit(bg,patch('M_DOOM'),94,2)
    for i,name in enumerate(('M_NGAME','M_OPTION','M_LOADG','M_SAVEG','M_RDTHIS','M_QUITG')):
        if name in lumps:blit(bg,patch(name),97,64+i*16)
    blit(bg,patch('M_SKULL1'),65,59)
    return bg,dict(path=str(path),sha256=sha(path),patches=['M_DOOM','M_NGAME','M_OPTION','M_LOADG','M_SAVEG','M_RDTHIS','M_QUITG','M_SKULL1'],
                   note='Original WAD patches converted to 16 SHR row palettes; comparison reference, not a proposed Wolf screen.')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=DEFAULT);args=ap.parse_args()
    out=args.out;out.mkdir(parents=True,exist_ok=True);work=HERE/'.build';work.mkdir(exist_ok=True)
    if not (work/'rasterize').exists() or (work/'rasterize').stat().st_mtime<(HERE/'rasterize.swift').stat().st_mtime:
        subprocess.run(['swiftc','-O',str(HERE/'rasterize.swift'),'-o',str(work/'rasterize')],check=True)
    start=time.monotonic();model=Model();lib=O.library();new=hand.library(model)
    for c,g in new.items():lib[c]=[g]
    manifest=dict(status='Lettering proposals awaiting user choice; no runtime change',screens=[],assets=[],
                  sources=dict(wolf_vgagraph=sha(FRONT/'game-data/shareware/VGAGRAPH.WL1')))
    def save(name,screen,description):
        png(out/(name+'.png'),screen.rows);png(out/(name+'@2x.png'),screen.rows,2)
        (out/(name+'.shr')).write_bytes(screen.raw())
        (out/(name+'.palettes.json')).write_text(json.dumps(screen.metadata(),indent=2)+'\n')
        manifest['screens'].append(dict(name=name,description=description,sha256=sha(out/(name+'@2x.png'))))
    def comparison(name,left,right,description):
        rows=[a+b for a,b in zip(left.rows,right.rows)]
        png(out/(name+'.png'),rows);png(out/(name+'@2x.png'),rows,2)
        (out/(name+'.palettes.json')).write_text(json.dumps(dict(panels=[left.metadata(),right.metadata()]),indent=2)+'\n')
        manifest['screens'].append(dict(name=name,description=description,sha256=sha(out/(name+'@2x.png'))))
    background=gray((FRONT/'build/frontend/sources/game.shr').read_bytes())
    originals={s:source_rows(n) for s,n in WHOLE.items()};originals['Wolfenstein 3-D']=logo()
    words={s:compose(s,lib) for s in ('New Game','Key Setup','Difficulty','Display & Sound','Benchmark','Controls')}
    for text,rows in dict(originals,**words).items():
        cv=convert(rows);name='word-'+text.lower().replace(' ','-').replace('&','and').replace('!','')
        png(out/(name+'.png'),[[c or 0 for c in row] for row in cv['rgb12']]);png(out/(name+'@2x.png'),[[c or 0 for c in row] for row in cv['rgb12']],2)
        payload={k:v for k,v in cv.items() if k!='rgb12'};payload['text']=text;payload['source']='original pixels' if text in originals else 'original letters plus hand masks'
        (out/(name+'.json')).write_text(json.dumps(payload,indent=1)+'\n');manifest['assets'].append(dict(name=name,text=text,palettes=len(cv['bands']),colors=len({c for row in cv['rgb12'] for c in row if c is not None}),changed_pixels=cv['changed_pixels'],max_channel_error=cv['max_channel_error']))
    for i,(text,reference) in enumerate(zip(words,('Load Game','Options','Customize','Save Game','Load Game','Control')),1):
        a=Screen(background);b=Screen(background);a.title(originals[reference],65);b.title(words[text],65)
        comparison(f'title-{i:02}-{text.lower().replace(" ","-").replace("&","and")}',a,b,f'Original {reference} on the left; new {text} on the right. Same native size; only lettering.')
    # Reconstruct complete original Load/Save words solely from their masks.
    for text,n in [('Load Game',40),('Save Game',41)]:
        a=Screen(background);b=Screen(background);originals_word=source_rows(n);a.title(originals_word,65)
        gs=[g for values in O.library().values() for g in values if g['pic']==n]
        x0=min(g['x0'] for g in gs);x1=max(g['x1'] for g in gs)
        ys=[y for g in gs for x,y in g['px']];top,bottom=min(ys),max(ys)
        reconstructed=blank(x1-x0+1,bottom-top+1,None);pal=palette()
        for g in gs:
            for (x,y),v in model.shade(g['px']).items():reconstructed[y-top][g['x0']-x0+x]=word(pal[v])
        b.title(reconstructed,65)
        comparison('shader-proof-'+text.lower().replace(' ','-'),a,b,'Original left; mask-only model reconstruction right. In-sample fit; held-out results are reported separately.')
    fit=dict(in_sample=check(model),held_out_character=check(model,True),
             limitation='The exact local-context table reconstructs seen masks. Held-out accuracy is lower; it does not establish an indistinguishable match for new letters.',
             method='Row plus 9x9 binary mask context and capped directional stroke distances; unseen contexts use a continuous measured stem profile with surface-normal edge lighting.')
    (out/'shader-fit.json').write_text(json.dumps(fit,indent=2)+'\n')
    (out/'hand-masks.json').write_text(json.dumps({c:dict(origin_y=min(y for x,y in mask),rows=[''.join('#' if (x,y) in mask else '.' for x in range(max(x for x,y in mask)+1)) for y in range(min(y for x,y in mask),max(y for x,y in mask)+1)]) for c,mask in hand.masks().items()},indent=2)+'\n')
    doom,doom_source=wad_reference();manifest['sources']['doom']=doom_source
    doom=reference_screen(doom)
    wolf=shr_screen((FRONT/'build/frontend/sources/title.shr').read_bytes())
    save('reference-doom',doom,'Original Doom M_ menu patches, converted to native SHR palettes for comparison only.')
    save('reference-wolf',wolf,'Existing native IIgs Wolf title, used only as the color and lettering reference.')
    # Two native panels show all eight new masks against existing letters.
    # Each strip shares a row palette; captions remain outside the game panel.
    pairs=[('N','L'),('D','G'),('B','S'),('K','C'),('w','m'),('k','h'),('f','t'),('&','e')]
    chart=[];chart_meta=[]
    for offset in (0,4):
        strips=[]
        for c,ref in pairs[offset:offset+4]:
            rows=blank(320,45,None)
            for x,g in [(80,lib[ref][0]),(200,new[c])]:
                for (xx,yy),color in g['px'].items():rows[yy-6][x+xx]=word(palette()[color])
            strips+=rows
        strips+=blank(320,20,None)
        panel=reference_screen([[0x111 if v is None else v for v in row] for row in strips]);chart.append(panel)
    comparison('hand-letter-comparison',chart[0],chart[1], 'Left panel: original L/G/S/C beside new N/D/B/K. Right panel: original m/h/t/e beside new w/k/f/&. Original body size; two native panels.')
    for key,file,label in CANDIDATES:
        face=Face(file,work)
        a=Screen(background);a.title(originals['Wolfenstein 3-D'],5)
        for i,text in enumerate(('NEW GAME','LOAD GAME','SAVE GAME','OPTIONS','HIGH SCORES','END GAME','QUIT')):
            face.draw(a,text,99,48+i*18,'selected' if i==0 else 'normal')
        pistol(a,69,45)
        b=Screen(background);b.title(originals['Options'],5)
        for i,text in enumerate(('DISPLAY & SOUND','CONTROLS','BENCHMARK','SAVE SETTINGS')):
            face.draw(b,text,60,66+i*27,'selected' if i==0 else 'dim' if i==3 else 'normal')
        pistol(b,30,63)
        save(f'candidate-{key}-main',a,label+' with opaque steel faces and a complete per-letter dark contour.')
        save(f'candidate-{key}-options',b,label+'; selection brighter, unchanged settings dimmer, no boxes or hints.')
        rows=[d+w for d,w in zip(doom.rows,wolf.rows)]+[x+y for x,y in zip(a.rows,b.rows)]
        name=f'candidate-{key}-comparison';png(out/(name+'.png'),rows);png(out/(name+'@2x.png'),rows,2)
        (out/(name+'.palettes.json')).write_text(json.dumps(dict(width=640,height=400,panels=[dict(x=x,y=y,**s.metadata()) for x,y,s in [(0,0,doom),(320,0,wolf),(0,200,a),(320,200,b)]]),indent=2)+'\n')
        manifest['screens'].append(dict(name=name,description=f'{label}: Doom patches / original Wolf title above; candidate main / Options below.',sha256=sha(out/(name+'@2x.png'))))
        s=Screen(background)
        for text,y in [('LOADING',36),('SAVING',69),('INSERT DISK 1',102),('QUIT WOLFENSTEIN 3D?',145),('PRESS Y OR N.',171)]:face.draw(s,text,None,y)
        save(f'candidate-{key}-signs',s,label+' for signs and messages, directly on the gray copy.')
        (out/f'candidate-{key}-font.json').write_text(json.dumps(dict(source=file,label=label,height=face.height,gap=face.gap,glyphs=face.glyphs),indent=1)+'\n')
    manifest['seconds']=round(time.monotonic()-start,3)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    cards=''.join(f'<article><h2>{r["name"]}</h2><p>{r["description"]}</p><img src="{r["name"]}@2x.png"></article>' for r in manifest['screens'])
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Wolf lettering choices</title><style>body{background:#171717;color:#ddd;font:16px system-ui;margin:24px}img{image-rendering:pixelated;max-width:none}article{margin:32px 0}h2{font-size:18px}p{max-width:1000px}</style><h1>Wolf lettering — one review round</h1><p>Original titles retained. Six new-title comparisons, source-mask reconstruction, and four outlined steel item faces. Every game panel is 320×200, shown at exactly 2×. Captions are review labels outside the game images. No boxes, frames, shadows or hint lines are drawn in the Wolf panels.</p>'+cards)
    print(json.dumps(dict(output=str(out),screens=len(manifest['screens']),assets=len(manifest['assets']),seconds=manifest['seconds'],fit=fit)))

if __name__=='__main__':main()
