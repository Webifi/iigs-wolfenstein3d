"""All view sizes retain the same field of view and center row."""
from pathlib import Path
import math
import struct
from buildconfig import config
from viewgeometry import SIZES
TRUE=config()['pixels']=='true'
OUT=Path(__file__).resolve().parents[1]/'build/gen/views.inc'
sizes=SIZES
lines=[' .section gamedata, data, root']
heights=list(range(2,161,2))+list(range(164,641,4))
indices=[2*min(range(len(heights)),key=lambda i:abs(heights[i]-h)) for h in range(1025)]
recip=[min(1024,round(56000/max(d,1))) for d in range(16384)]
packed=bytearray(len(sizes)*2)
for i,n in enumerate(sizes):
    struct.pack_into('<H',packed,i*2,len(packed))
    factor=round(n*256/160)
    values=[indices[r*factor//256] for r in recip]
    raw=struct.pack('<%dH'%len(values),*values)
    assert len(raw)==32768
    (OUT.parents[1]/'assets').mkdir(parents=True,exist_ok=True)
    (OUT.parents[1]/'assets'/f'view-height-{n}.bin').write_bytes(raw)
    start=0
    while start<len(values):
        end=start+1
        while end<len(values) and values[end]==values[start]:end+=1
        packed+=struct.pack('<HH',end*2,values[start])
        start=end
assert len(packed)<=0x1200  # loaded at $0B5000; shading starts at $0B6200
lines.append('heightStreams: .word '+','.join(str(0x5000+struct.unpack_from('<H',packed,i*2)[0]) for i in range(len(sizes))))
for name,values in [('viewSizes',sizes),('viewFactors',[round(n*256/160) for n in sizes]),('viewAngles',['.word0 angles%d'%n for n in sizes]),('viewCosines',['.word0 cosines%d'%n for n in sizes])]:
    lines.append(name+': .word '+','.join(str(v) for v in values))
for n in sizes:
    columns=n*(2 if TRUE else 1)
    offsets=[round(math.atan(((columns-1)/2-i)/(columns/2)*(0x10000/(2*(0x5700+0x5800))))*1024/math.tau) for i in range(columns)]
    lines.append('angles%d: .word '%n+','.join(str(a&65535) for a in offsets))
    lines.append('cosines%d: .word '%n+','.join(str(round(math.cos(a*math.tau/1024)*256)) for a in offsets))
lines += ['pixelAngle: .space '+str(640 if TRUE else 320),'pixelCos: .space '+str(640 if TRUE else 320)]
lines += ['screenRows: .word '+','.join(str(row*160) for row in range(200))]
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text('\n'.join(lines)+'\n')
(OUT.parents[1]/'assets/view-height.bin').write_bytes(packed)
