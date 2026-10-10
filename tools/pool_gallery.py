"""Render same-frame native SHR comparisons, including per-row palettes."""
from pathlib import Path
import argparse,json,struct,zlib
ap=argparse.ArgumentParser();ap.add_argument('before',type=Path);ap.add_argument('after',type=Path);ap.add_argument('out',type=Path);args=ap.parse_args()
def png(path,rgb,w=320,h=200):
 def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
 rows=b''.join(b'\0'+rgb[y*w*3:(y+1)*w*3]for y in range(h))
 path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
def frame(path,n):
 with path.open('rb')as f:f.seek((n-1)*32768);data=f.read(32768)
 assert len(data)==32768
 out=bytearray()
 for y in range(200):
  pal=32256+(data[32000+y]&15)*32
  for packed in data[y*160:(y+1)*160]:
   for c in (packed>>4,packed&15):
    word=struct.unpack_from('<H',data,pal+c*2)[0];out.extend(((word>>8&15)*17,(word>>4&15)*17,(word&15)*17))
 return bytes(out)
out=args.out;out.mkdir(parents=True,exist_ok=True)
report=[]
for view in (214,320):
 for label,n in (('far',216),('middle',218),('near',219)):
  parts=[];names=[]
  for version,folder in (('before',args.before),('after',args.after)):
   rgb=frame(folder/f'd1-v{view}/0/frames.shr',n)
   name=f'v{view}-{label}-demo1-frame{n}-{version}.png';png(out/name,rgb);names.append(name);parts.append(rgb)
  pair=b''.join(parts[0][y*960:(y+1)*960]+parts[1][y*960:(y+1)*960]for y in range(200))
  name=f'v{view}-{label}-pair.png';png(out/name,pair,w=640)
  report.append(dict(view=view,distance=label,demo=1,frame=n,before=names[0],after=names[1],pair=name))
(out/'pairs.json').write_text(json.dumps(report,indent=2)+'\n')
print(out)
