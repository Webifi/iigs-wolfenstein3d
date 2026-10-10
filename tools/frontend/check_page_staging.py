"""Compare intermission pixels before/after moving their disposable staging bank."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import memmap
from elf import read
from emu816 import Emu
names=('title','credits','pg13','tally','victory','end1','end2')
class Machine(Emu):
 def step(self):
  pc=self.pb<<16|self.pc
  if pc==self.sym['CopyMenuBlocks']:
   first=self.rd16(self.d+0x42);count=self.rd16(self.d+0x44);dest=self.rd16(self.d+0x46)|(self.rd16(self.d+0x48)<<16)
   part=next((data[(first-start)*512:(first-start+count)*512] for start,data in self.pages if start<=first and first+count<=start+len(data)//512),None)
   assert part is not None,(first,count)
   self.load(dest,part);self.loads.append((dest,len(part)));self.pc=(self.pop16()+1)&65535;self.pb=self.pop8();return
  if self.m[pc]==0x54:
   target,source=self.m[pc+1:pc+3];count=self.a+1
   for _ in range(count):self.wr8(target<<16|self.y,self.rd8(source<<16|self.x));self.x=(self.x+1)&65535;self.y=(self.y+1)&65535
   self.a=65535;self.db=target;self.pc=(self.pc+3)&65535;return
  super().step()
def run(path,old):
 e=Machine();segs,e.sym=read(path)
 for seg in segs:e.load(seg['address'],seg['data'])
 ids={name:30+i for i,name in enumerate(names)} if old else {name[5:].lower():int(n) for name,_,n in (l.split() for l in (ROOT/'build/gen/menu.inc').read_text().splitlines() if l.startswith('LUMP_'))}
 e.pages=[];e.loads=[]
 for name in names:
  data=(ROOT/'build/frontend/native/pages'/(name+'.bin')).read_bytes();data=data.ljust((len(data)+511)&~511,b'\0')
  e.pages.append((e.rd16(e.sym['lumpTable']+ids[name]*8),data))
 for stub in ('InitFlash','WaitBlank'):e.m[e.sym[stub]]=0x6b
 e.d=0x100;e.db=2;e.load(memmap.SHR,bytes([0x35])*32768)
 def call(name,a=0,x=0,long=True):
  e.a=a;e.x=x;e.call(e.sym[name]>>16,e.sym[name]&65535,long_return=long)
 call('TallyPage');call('TallyReveal');result=[bytes(e.m[memmap.SHR:memmap.RAW_PLANES])]
 if not old:
  e.load(memmap.SNAP_PIX,bytes([0xa5])*32000);e.wr16(e.sym['tallyCacheValid'],0)
 for char in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:%!':
  e.wr16(e.sym['flowX'],100);e.wr16(e.sym['flowY'],120);call('TallyChar',ord(char));result.append(bytes(e.m[memmap.SHR:memmap.RAW_PLANES]))
 for frame in (0,1):
  if not old:e.load(memmap.SNAP_PIX,bytes([0x5a])*32000);e.wr16(e.sym['tallyCacheValid'],0)
  call('TallyBreathe',frame);result.append(bytes(e.m[memmap.SHR:memmap.RAW_PLANES]))
 e.db=e.sym['PageShow']>>16;call('PageShow',ids['victory'],1,False);result.append(bytes(e.m[memmap.SHR:memmap.RAW_PLANES]))
 for digit in range(10):
  e.wr16(e.sym['vicX'],100);e.wr16(e.sym['vicY'],100);call('DrawDigit',digit,long=False);result.append(bytes(e.m[memmap.SHR:memmap.RAW_PLANES]))
 if not old:
  for address,size in e.loads:
   assert memmap.SNAP_PIX<=address and address+size<=memmap.SNAP_SCB or memmap.SHR<=address and address+size<=memmap.RAW_PLANES,(hex(address),size)
 return result,e.loads
old,_=run(ROOT/'build/tests/ui-speed-round/before/wolf.elf',True);new,loads=run(ROOT/'build/wolf.elf',False)
assert old==new,[i for i,(a,b) in enumerate(zip(old,new)) if a!=b]
print(json.dumps(dict(exact_screens=len(new),loads=loads,menu_cache_writes=0),indent=2))
