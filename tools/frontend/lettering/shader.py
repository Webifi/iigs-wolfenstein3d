"""Learn row/edge shading from original masks, without glyph identity keys."""
from collections import Counter,defaultdict
import original as O
from assets import palette

RINGS=[[(x,y) for y in range(-r,r+1) for x in range(-r,r+1)] for r in (1,2,4)]

def feature(mask,x,y):
    patches=tuple(sum(1<<i for i,(dx,dy) in enumerate(ring) if (x+dx,y+dy) in mask) for ring in RINGS)
    distances=[]
    for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):
        d=0
        while d<9 and (x+(d+1)*dx,y+(d+1)*dy) in mask:d+=1
        distances.append(d)
    return patches,tuple(distances)

class Model:
    def __init__(self,skip=None):
        self.rows=defaultdict(list)
        self.exact=defaultdict(Counter)
        self.training=[]
        self.faces=defaultdict(Counter)
        for char,gs in O.library().items():
            if char==skip:continue
            for g in gs:
                if g['pic'] not in (40,41):continue
                for (x,y),color in sorted(g['px'].items()):
                    f=feature(g['px'],x,y)
                    self.exact[(y,f)][color]+=1
                    self.rows[y].append((f,color))
                    if min(f[1])>=2:self.faces[y][color]+=1
                self.training.append(g)
        self.rows={y:list(dict.fromkeys(rows)) for y,rows in self.rows.items()}
        self.cache={}

    def material(self,mask,x,y):
        """Continuous steel faces with coherent normals; no nearest-pixel noise."""
        pal=palette()
        # L's long stem exposes both complete faces. Its highlight and black
        # horizon include zero pixels, which an ink-only histogram would miss.
        profile={10:27,11:26,12:26,13:25,14:25,15:24,16:23,17:23,
                 18:22,19:7,20:7,21:7,22:20,23:20,24:19,25:18,
                 26:16,27:15,28:7,29:0,30:45,31:43,32:40,33:4,
                 34:36,35:34,36:53,37:12,38:51,39:23,40:27}
        face=pal[profile[min(profile,key=lambda v:abs(v-y))]]
        L,R,U,D=feature(mask,x,y)[1]
        depth=min(L,R,U,D)
        normal=sum((-dx-dy) for dx,dy in RINGS[0] if (x+dx,y+dy) not in mask)
        if depth==0:
            if L==0 and U>0 and 12<=y<=22:rgb=(220,36,36)
            elif normal>1:rgb=(252,252,252) if y<29 else (252,216,216)
            elif normal>=-1:rgb=(168,168,168)
            else:rgb=(72,72,72)
        elif depth==1:
            if L<R or U<D:rgb=tuple(min(252,v+28) for v in face)
            else:rgb=tuple(max(0,v-32) for v in face)
        else:rgb=face
        return min(range(256),key=lambda i:sum((a-b)**2 for a,b in zip(pal[i],rgb)))

    def shade(self,mask):
        result={}
        for x,y in sorted(mask):
            f=feature(mask,x,y);key=(y,f)
            if key in self.cache:result[x,y]=self.cache[key];continue
            if key in self.exact:
                color=self.exact[key].most_common(1)[0][0]
            else:
                color=self.material(mask,x,y)
            self.cache[key]=color;result[x,y]=color
        return result

def check(model,heldout=False):
    pal=palette();total=exact=rgb_exact=near=0;errors=[]
    for char,gs in O.library().items():
        m=Model(skip=char) if heldout else model
        for g in gs:
            if g['pic'] not in (40,41):continue
            res=m.shade(g['px'])
            for k,v in g['px'].items():
                a=tuple(round(n/17) for n in pal[v]);b=tuple(round(n/17) for n in pal[res[k]])
                error=max(abs(x-y) for x,y in zip(a,b))
                total+=1;exact+=v==res[k];rgb_exact+=a==b;near+=error<=1;errors.append(error)
    return dict(ink_pixels=total,exact_vga_index=exact/total,exact_rgb12=rgb_exact/total,
                within_one_nibble=near/total,mean_max_channel_error=sum(errors)/total,
                held_out_by_character=heldout)

if __name__=='__main__':
    import json,time
    start=time.monotonic();model=Model()
    print(json.dumps(dict(fit=check(model),heldout=check(model,True),seconds=time.monotonic()-start),indent=2))
