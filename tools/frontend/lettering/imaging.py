import struct,zlib
from pathlib import Path

def rgb(c):return tuple((c>>s&15)*17 for s in (8,4,0))
def word(c):return sum(round(v/17)<<s for v,s in zip(c,(8,4,0)))

def png(path,rows,scale=1):
    def chunk(k,d):return struct.pack('>I',len(d))+k+d+struct.pack('>I',zlib.crc32(k+d))
    h=len(rows);w=len(rows[0]);scan=[]
    for row in rows:
        r=b'\0'+b''.join(bytes(rgb(c))*scale for c in row)
        scan.extend([r]*scale)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w*scale,h*scale,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(scan),9))+chunk(b'IEND',b''))

def blank(w,h,color=0):return [[color]*w for _ in range(h)]

def blit(dst,src,x,y,transparent=None):
    for yy,row in enumerate(src):
        for xx,c in enumerate(row):
            if c is not transparent:
                assert 0<=y+yy<len(dst) and 0<=x+xx<len(dst[0]),(x,y,xx,yy)
                dst[y+yy][x+xx]=c

def glyph_rows(g,palette,top=9,bottom=43):
    rows=blank(g['width'],bottom-top+1)
    for (x,y),c in g['px'].items():
        if top<=y<=bottom:rows[y-top][x]=word(palette[c])
    return rows
