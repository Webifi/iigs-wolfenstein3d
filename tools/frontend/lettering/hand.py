"""Eight hand-built masks on the original 30-row capital / 21-row body grid."""
import original as O

def poly(points):
    out=set()
    for y in range(min(y for x,y in points),max(y for x,y in points)+1):
        hits=[]
        for (a,b),(c,d) in zip(points,points[1:]+points[:1]):
            if min(b,d)<=y+.5<max(b,d):hits.append(a+(y+.5-b)*(c-a)/(d-b))
        hits.sort()
        for a,b in zip(hits[::2],hits[1::2]):
            for x in range(round(a),round(b)):out.add((x,y))
    return out

def rect(a,b,c,d):return {(x,y) for y in range(b,d+1) for x in range(a,c+1)}

def masks():
    # The flag, tapered counters, slits and feet are drawn on this grid;
    # no tinted source pixels or rescaled outside font glyphs are used.
    flag=poly([(0,20),(1,16),(7,12),(13,10),(18,12),(15,15),(8,17),(8,20)])
    stem=poly([(2,17),(8,15),(9,36),(11,38),(8,40),(1,38),(2,35)])
    N=flag|stem|poly([(17,14),(23,11),(25,13),(24,35),(26,38),(22,40),(17,38)])
    N|=poly([(7,14),(13,14),(23,35),(21,39),(17,35),(7,22)])
    N-=rect(5,20,5,29)
    N-=rect(21,17,21,23)
    D=flag|stem|poly([(7,12),(15,12),(21,15),(25,21),(25,32),(21,38),(15,40),(7,38)])
    D-=poly([(11,19),(15,21),(17,24),(17,31),(14,34),(11,32)])
    D-=rect(5,21,5,29)
    B=flag|stem|poly([(8,12),(17,13),(23,17),(23,21),(18,25),(22,28),(25,33),(23,37),(17,40),(8,38)])
    B-=poly([(11,18),(15,18),(16,21),(13,23),(11,22)])
    B-=poly([(11,29),(15,28),(18,32),(17,34),(13,35),(11,33)])
    B-=rect(5,22,5,30)
    K=flag|stem|poly([(8,27),(13,18),(20,12),(25,11),(26,14),(20,21),(13,29)])
    K|=poly([(9,26),(15,26),(18,31),(25,36),(26,39),(22,40),(17,37),(10,31)])
    K-=rect(5,21,5,30)
    k=poly([(1,20),(2,16),(8,12),(14,10),(18,12),(14,15),(9,17),(9,35),(11,38),(7,40),(2,38)])
    k|=poly([(8,30),(12,25),(17,20),(22,20),(23,23),(15,31)])
    k|=poly([(9,29),(15,29),(18,34),(23,37),(23,39),(19,40),(13,36),(8,33)])
    k-=rect(5,22,5,30)
    f=poly([(3,20),(5,15),(10,12),(17,10),(22,12),(22,14),(18,17),(14,16),(12,19),(12,36),(9,40),(3,38),(5,35),(5,23)])
    f|=poly([(0,24),(5,20),(12,21),(19,21),(18,25),(12,26),(5,25)])
    f-=rect(8,28,8,33)
    w=poly([(0,21),(3,19),(7,21),(8,33),(11,36),(13,32),(12,23),(15,20),(19,21),(20,33),(23,36),(25,32),(25,21),(29,19),(32,22),(31,33),(27,38),(22,40),(18,38),(16,36),(13,39),(9,40),(3,36),(1,32)])
    w-=rect(5,25,5,29)
    w-=rect(17,25,17,29)
    amp=poly([(5,13),(10,10),(16,11),(20,15),(20,19),(16,24),(10,27),(7,31),(8,35),(13,37),(17,33),(20,27),(24,24),(28,25),(27,28),(24,30),(21,36),(17,40),(10,41),(3,38),(0,33),(2,28),(8,24),(4,20)])
    amp-=poly([(10,15),(14,15),(15,18),(13,21),(10,20),(8,18)])
    amp|=poly([(7,21),(12,21),(18,30),(24,36),(28,37),(27,40),(23,40),(18,36),(11,29)])
    # The original L is the reference for the capitals' left swash and
    # tapered shaft. Keep that silhouette, then draw the new stroke topology.
    source=O.library()['L'][0]['px']
    left=set()
    for y in range(10,41):
        xs=[x for x,yy in source if yy==y and (x<=12 or y<=18)]
        if xs:left|=rect(min(xs),y,max(xs),y)
    left-=rect(5,23,5,30)
    N=left|poly([(19,14),(25,11),(27,13),(26,36),(28,38),(24,40),(20,38)])
    N|=poly([(9,16),(15,16),(25,34),(24,39),(18,32),(9,24)])
    N-=rect(23,18,23,23)
    K=left|poly([(10,27),(16,19),(22,13),(28,11),(29,14),(22,24),(17,29)])
    K|=poly([(10,26),(17,27),(20,32),(28,37),(28,40),(24,40),(18,36),(11,31)])
    t={(x+3,y) for x,y in O.library()['t'][0]['px'] if y>=20}
    f=t|poly([(5,22),(5,17),(8,13),(14,10),(21,11),(24,14),(21,17),(16,16),(12,19),(12,24)])
    return dict(N=N,D=D,B=B,K=K,w=w,k=k,f=f,**{'&':amp})

def library(model):
    out={}
    for c,mask in masks().items():
        x0=min(x for x,y in mask);mask={(x-x0,y) for x,y in mask}
        out[c]=dict(char=c,pic='hand',x0=0,x1=max(x for x,y in mask),width=max(x for x,y in mask)+1,px=model.shade(mask))
    return out
