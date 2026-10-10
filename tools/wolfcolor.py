"""Reviewed Wolf view colors; quantization and dithering happen in the packer."""

# Keep the source's teal frame apart from both gray flats. Two blue tones
# leave room for steel, skin and uniforms; pale blue gains a little gray.
COLORS=((0,0,0),(221,221,221),(170,34,17),(85,17,17),
        (187,136,85),(119,85,51),(34,85,34),(51,34,17),
        (0,68,68),(68,85,153),(34,51,102),(34,136,136),
        (153,153,153),(119,119,119),(68,68,68),(34,34,34))

def distance(a,b):
    return sum(w*(x-y)**2 for w,x,y in zip((3,4,2),a,b))

def mapping(palette):
    pairs=[]
    for i,a in enumerate(COLORS):
        for j,b in enumerate(COLORS[i:],i):
            pairs.append((tuple((x+y)/2 for x,y in zip(a,b)),i*16+j,distance(a,b)/8))
    out=[]
    for color in palette:
        r,g,b=color
        if b>2*max(r,g) and b>40:
            color=(max(r,b*.16),max(g,b*.22),b*.88)
            i=min((0,9,10),key=lambda i:distance(color,COLORS[i]))
            out.append(i*17)             # blue masonry stays solid in motion
            continue
        out.append(min(pairs,key=lambda p:distance(color,p[0])+p[2])[1])
    for c in range(194,214):
        i=min((4,5,7),key=lambda i:distance(palette[c],COLORS[i]))
        out[c]=i*17                      # the enlarged hands keep a clean edge
    # Flats and frame stay solid. A dotted boundary distracts in motion.
    out[0x19]=0xdd;out[0x1d]=0xee
    out[127]=0x88;out[125]=0xbb;out[124]=0xbb
    return out

def ordered(byte,x,y):
    return ((byte&15)<<4)|(byte>>4) if (x+y)&1 else byte
