"""Fit lettering and its three dark backdrop tones together in each row band."""
from collections import Counter

SHARED=(0x000,0x111,0x222,0x333)

def dist(a,b):return sum(w*((a>>s&15)-(b>>s&15))**2 for s,w in ((8,3),(4,6),(0,1)))

def reduce(counts, shared=SHARED):
    groups=[[c,n,{c}] for c,n in sorted(counts.items()) if c not in shared]
    while len(groups)>16-len(shared):
        _,i,j=min((dist(a[0],b[0])*a[1]*b[1]/(a[1]+b[1]),i,j)
                    for i,a in enumerate(groups) for j,b in enumerate(groups) if i<j)
        a,b=groups[i],groups[j];rep=a[0] if a[1]>=b[1] else b[0]
        groups[i]=[rep,a[1]+b[1],a[2]|b[2]];groups.pop(j)
    mapping={c:c for c in shared}
    for c,n,members in groups:
        for v in members:mapping[v]=c
    error=sum(dist(c,mapping[c])*n for c,n in counts.items())
    colors=list(shared)+[g[0] for g in groups]
    return colors+[0]*(16-len(colors)),mapping,error

def convert(rows,limit=15,shared=SHARED):
    counts=[Counter(c for c in row if c is not None) for row in rows]
    cache={}
    def band(a,b):
        if (a,b) not in cache:
            count=sum(counts[a:b],Counter());cache[a,b]=reduce(count,shared)
        return cache[a,b]
    spans=[];start=0;seen=set(shared)
    for y,count in enumerate(counts):
        merged=seen|set(count)
        if len(merged)>16 and y>start:
            spans.append((start,y));start=y;seen=set(shared)|set(count)
        else:seen=merged
    spans.append((start,len(rows)))
    while len(spans)>limit:
        _,i=min((band(spans[i][0],spans[i+1][1])[2]-band(*spans[i])[2]-band(*spans[i+1])[2],i)
                for i in range(len(spans)-1))
        spans[i:i+2]=[(spans[i][0],spans[i+1][1])]
    out=[];indices=[];converted=[];err=0;maxerr=0;changed=0
    for index,(a,b) in enumerate(spans):
        pal,mapping,cost=band(a,b);err+=cost
        out.append(dict(start=a,end=b,palette=index,colors_0rgb=[f'{c:03X}' for c in pal]))
        for row in rows[a:b]:
            indices.append([None if c is None else pal.index(mapping[c]) for c in row])
            converted.append([None if c is None else mapping[c] for c in row])
            for c in row:
                if c is None:continue
                changed+=mapping[c]!=c
                maxerr=max(maxerr,max(abs((c>>s&15)-(mapping[c]>>s&15)) for s in (8,4,0)))
    return dict(width=len(rows[0]),height=len(rows),bands=out,indices=indices,
                rgb12=converted,weighted_error=err,changed_pixels=changed,max_channel_error=maxerr)
