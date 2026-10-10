"""Execute resident preview composition; compare source-record RGB and gray background."""
import json, random, struct, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/frontend/lettering')]
import memmap
from elf import read
from emu816 import Emu
from shared_gray import STEEL
from wolfdata import PROFILE
segments,symbols=read(ROOT/'build/wolf.elf')
cache=json.loads((ROOT/'build/assets/menu-cache.json').read_text())
rng=random.Random(20261003)
class Traced(Emu):
    def __init__(self):
        super().__init__();self.stores={};self.trace=False
    def step(self):
        pc=(self.pb<<16)|self.pc
        if self.m[pc]!=0x54:return super().step()
        destination,source_bank=self.m[pc+1:pc+3]
        count=self.a+1
        for _ in range(count):
            self.wr8((destination<<16)|self.y,self.rd8((source_bank<<16)|self.x))
            self.x=(self.x+1)&65535;self.y=(self.y+1)&65535
        self.a=65535;self.db=destination;self.pc=(self.pc+3)&65535
        self.cycles+=7*count;self.count+=count
    def wr8(self,a,v):
        if self.trace and memmap.SHR<=a<memmap.SHR_SCB:self.stores.setdefault(a,[]).append(v&255)
        super().wr8(a,v)
    def wr16(self,a,v):self.wr8(a,v);self.wr8(a+1,v>>8)
def record_pixels(data):
 x,y,w,h,band=struct.unpack_from('<5H',data);at=138;tag=struct.unpack_from('<H',data,at)[0];at+=2
 rows=[]
 if tag==0xfffa:
  stride,height=struct.unpack_from('<2H',data,at);at+=4
  for yy in range(height):
   row=[c for v in data[at+yy*stride:at+(yy+1)*stride] for c in (v>>4,v>>4,v&15,v&15)];rows.extend([row,row])
 elif tag==0xfffb:
  stride,height,left,right=struct.unpack_from('<4H',data,at);at+=8
  masks=[15&((m>>(8*(i//2)))>>(4 if i%2==0 else 0)) for m in (left,right) for i in range(4)]
  for yy in range(height):
   row=[c for v in data[at+yy*stride:at+(yy+1)*stride] for c in (v>>4,v&15)]
   for i in range(4):
    if masks[i]:row[i]=None
    if masks[4+i]:row[-4+i]=None
   rows.append(row)
 elif tag==0xfffc:
  groups,height=struct.unpack_from('<2H',data,at);at+=4
  for yy in range(height):
   pos=at+struct.unpack_from('<H',data,at+2*yy)[0];row=[]
   for group in range(groups):
    mask=data[pos];pos+=1
    cells=[None]*8
    if mask!=255:
     vals=[c for v in data[pos:pos+4] for c in (v>>4,v&15)];pos+=4
     cells=[None if mask&(1<<i) else v for i,v in enumerate(vals)]
    row+=cells
   rows.append(row[:w])
 else:raise ValueError(hex(tag))
 assert len(rows)==h and all(len(r)==w for r in rows),(hex(tag),x,y,w,h,len(rows),[len(r) for r in rows[:3]])
 return x,y,w,h,band,rows

checks=[]
initial={}
from frontend.episode_previews import paths as episode_paths
for kind,count in ((1,4),(2,PROFILE.floors),(4,len(episode_paths()))):
    for phase in ("initial","change"):
      for index in range(count):
        e=Traced()
        for segment in segments:e.load(segment['address'],segment['data'])
        for r in cache['regions']:e.load(r['start'],(ROOT/'build/assets'/r['file']).read_bytes())
        e.m[symbols['WaitVBL']]=0x60 # Isolate pixels; MAME checks the actual blank synchronization.
        e.d=memmap.UI_DP;e.db=memmap.MENU>>16
        e.m[symbols['EnsureUIAssets']]=0x6b  # The complete title payload is already loaded.
        e.wr16(symbols['selectedFloorList'],symbols['chosenFloor']&65535)
        rng.seed(20261003+kind*100+index)
        gray=bytes(rng.choice((0,13,14,15))*16+rng.choice((0,13,14,15)) for _ in range(32000))
        e.load(memmap.SNAP_PIX,gray);e.load(memmap.HEIGHT_TABLE,gray);e.load(memmap.SHR,gray)
        e.load(memmap.SHR_PAL+480,struct.pack('<16H',*STEEL))
        e.load(memmap.SNAP_SCB,bytes(200));e.load(memmap.SHR_SCB,bytes([15])*200)
        e.load(memmap.SLOT_REC,bytes(((b>>4)%6)*16+(b&15)%6 for b in range(256)))
        e.load((memmap.UI_BANK+0x9000),bytes(range(6))+bytes(10))
        e.wr16(symbols['menuDim'],1);e.wr16(symbols['listPictures'],kind)
        e.wr16(symbols['previewLast'],65535);e.wr16(e.d+symbols['UL_CUR'],0 if kind==2 else index);e.wr16(symbols['chosenFloor'],index)
        e.load(memmap.AUX_BANK,bytes([0xcd])*memmap.AUX_BANK_SIZE)
        if phase=='change':
            other=(index+1)%count;e.wr16(e.d+symbols['UL_CUR'],0 if kind==2 else other);e.wr16(symbols['chosenFloor'],other)
            e.call(symbols['PreviewCore']>>16,symbols['PreviewCore']&65535,long_return=True)
            e.wr16(e.d+symbols['UL_CUR'],0 if kind==2 else index);e.wr16(symbols['chosenFloor'],index)
        before=bytes(e.m[memmap.SHR:memmap.SHR_SCB])
        e.trace=True;e.call(symbols['PreviewCore']>>16,symbols['PreviewCore']&65535,long_return=True);e.trace=False
        actual=bytes(e.m[memmap.SHR:memmap.SHR_SCB]);changed={memmap.SHR+i for i,(a,b) in enumerate(zip(before,actual)) if a!=b}
        assert changed <= set(e.stores),(kind,index,'missing writes')
        assert all(all(b==actual[a-memmap.SHR] for b in values) for a,values in e.stores.items()),(kind,index,'intermediate pixels')
        assert e.m[memmap.AUX_BANK:memmap.AUX_BANK_END]==bytes([0xcd])*memmap.AUX_BANK_SIZE
        assert e.db==0x3f
        if phase=='initial':initial[kind,index]=actual
        else:assert actual==initial[kind,index],(kind,index,'changed picture differs from fresh picture')
        address=e.rd16(symbols['nativeRecord'])+65536*e.rd8(symbols['nativeBank'])
        record=bytes(e.m[address:address+8192])
        try:x,y,w,h,band,rows=record_pixels(record)
        except Exception as error:raise AssertionError((kind,index,phase,hex(address),str(error))) from error
        foreground={}
        for yy,row in enumerate(rows,y):
            pal=record[74+yy-band]
            palette=struct.unpack_from('<16H',record,10+32*(pal-13))
            for xx,indexed in enumerate(row,x):
                if indexed is not None:foreground[xx,yy]=palette[indexed]
        for yy in range(200):
            pal=e.rd8(memmap.SHR_SCB+yy)&15
            for xx in range(320):
                off=yy*160+xx//2;shift=0 if xx&1 else 4
                want=foreground.get((xx,yy),STEEL[(gray[off]>>shift)&15])
                got=e.rd16(memmap.SHR_PAL+32*pal+2*((actual[off]>>shift)&15))
                assert got==want,(kind,index,xx,yy,hex(got),hex(want))
        pixels=len(foreground)
        before=e.count;e.call(symbols['PreviewCore']>>16,symbols['PreviewCore']&65535,long_return=True)
        assert e.count-before<50,(kind,index,'unchanged picture was recomposed')
        checks.append(dict(phase=phase,kind=kind,index=index,approved_pixels=pixels,changed_bytes=len(changed),wrong_stores=0))
print(json.dumps(dict(cases=checks,count=len(checks)),indent=2))
