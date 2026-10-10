"""Compare adaptive wall planes with one native DDA trace per output column.

Replay fixed camera fixtures at every supported view size.
Filled-span plane annotations are read-only Python observations: no runtime
instructions or walls are changed. Reference calls use private interpreter
memory and the same DDA, bypassing every interpolation/skip decision.
"""
import memmap
import sys,json,struct,zlib,argparse,hashlib
from pathlib import Path
sys.path.insert(0,'tools')
from model_shared_visibility import Cast
BASE=Path('build/before/wolf.elf')
class Replay:
 def __init__(self,view,elf,exact=False):
  self.tables={};self.r=Cast(view,elf);self.view=view;e,s=self.r.e,self.r.symbols
  if exact:
   code=bytearray()
   for col in range(view//2):
    code.extend(bytes((0xa9,))+struct.pack('<H',2*col)+bytes((0x85,s['SCAN'],0x22))+s['traceRay'].to_bytes(3,'little'))
   code.extend(bytes((0x5c,))+s['castDone'].to_bytes(3,'little'))
   e.load(memmap.TEST_CODE,code);e.load(s['runCastProgram']+1,(memmap.TEST_CODE).to_bytes(3,'little'))
 def run(self,data):
  e,s=self.r.e,self.r.symbols
  e.load(0x1000,data[:256]);e.load(self.r.world+0x32000,data[256:8448]);e.load(s['doorPosition'],data[8448:8576]);e.load(s['doorOrient'],data[8576:8704]);e.load(s['pwallPosition'],data[8704:8706]);e.wr16(0x1000+s['FIRST'],1)
  e.d,e.db,e.mf,e.xf,e.s=0x1000,2,0,0,0x1fff
  if 'InitWallRuns' in s:
   key=bytes(data[256:8448])
   if key not in self.tables:
    e.call(s['InitWallRuns']>>16,s['InitWallRuns']&65535,sentinel=memmap.CALL_SENTINEL_LOW,long_return=True)
    self.tables[key]=bytes(e.rd8(s['wallRunCells']+i) for i in range(8192))
   else:e.load(s['wallRunCells'],self.tables[key])
  planes=[None]*(self.view//2);step=e.step
  def geometry(plane):
   if "wallRunCells" in s and not plane&0x6000:
    return plane&(0x803f if plane&0x8000 else 0x0fc0)
   return plane
  def observe():
   pc=e.pb<<16|e.pc
   if pc==s['nextRay']:
    col=e.rd16(0x1000+s['SCAN'])//2;plane=e.rd16(s['hitPlane']+col*2)
    if plane==65535:
     cell=e.rd16(0x1000+s['MAPIDX']);plane=(cell&63)|0x8000 if e.rd16(0x1000+s['SIDE']) else cell&0xfc0
    planes[col]=geometry(plane)
   elif pc==s['spanFillDone']:
    center=e.rd16(0x1000+s['SCAN'])//2;half=e.rd16(s['raySpacing'])//2
    for col in range(center-half+1,center+half):planes[col]=geometry(e.rd16(0x1000+s['TILE']))
   step()
  e.step=observe;start=e.cycles
  try:e.call(2,s['castFrame']&65535,sentinel=memmap.CALL_SENTINEL_LOW)
  finally:e.step=step
  assert all(p is not None for p in planes)
  return dict(cycles=e.cycles-start,planes=planes,pages=[e.rd16(s['sourceBank']+2*c)>>8 for c in range(self.view//2)],heights=[e.rd16(s['heightIndex']+2*c) for c in range(self.view//2)])
def compare(values):
 before,after,reference=values
 planes=[[c for c,(a,b) in enumerate(zip(v['planes'],reference['planes'])) if a!=b] for v in (before,after)]
 pages=[[c for c,(a,b) in enumerate(zip(v['pages'],reference['pages'])) if a!=b] for v in (before,after)]
 introduced=[c for c in pages[1] if c not in pages[0]]
 return dict(old_bad=planes[0],new_bad=planes[1],old_page_disagreements=pages[0],new_page_disagreements=pages[1],introduced_page_disagreements=introduced)

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--before',type=Path,default=BASE)
 ap.add_argument('--after',type=Path,default=Path('build/wolf.elf'))
 ap.add_argument('--out',type=Path,default=Path('docs/evidence/rays/wall-openings/session-native.json'))
 args=ap.parse_args()
 folder=Path('docs/evidence/rays/wall-openings')
 receipt=json.loads((folder/'session-scenes.json').read_text())
 selected=receipt['poses'];world=zlib.decompress((folder/'session-scenes.bin.z').read_bytes())
 assert len(world)==len(selected)*8706
 allrows=[]
 for view in (160,214,240,320):
  # The full-column reference includes the door-coordinate repair. Its
  # subdivision decisions are independent of the adaptive caster.
  rigs=[Replay(view,args.before),Replay(view,args.after),Replay(view,args.after,True)];rows=[]
  for i,p in enumerate(selected):
   data=world[i*8706:(i+1)*8706];values=[r.run(data) for r in rigs]
   row=dict(pose=p,**compare(values),cycles=[v['cycles'] for v in values])
   if row['new_bad'] or row['introduced_page_disagreements']:row['details']=values
   rows.append(row)
  result=dict(view=view,old_wrong_planes=sum(len(r['old_bad']) for r in rows),new_wrong_planes=sum(len(r['new_bad']) for r in rows),inherited_material_disagreements=sum(len(r['new_page_disagreements']) for r in rows),introduced_material_disagreements=sum(len(r['introduced_page_disagreements']) for r in rows),rows=rows)
  print(view,{k:v for k,v in result.items() if k!='rows'},flush=True);allrows.append(result)
  args.out.write_text(json.dumps(dict(note=__doc__,reference='One native DDA per output column from the repaired ELF. Existing material-coordinate rounding is counted separately; every new plane or material regression fails.',before_sha256=hashlib.sha256(args.before.read_bytes()).hexdigest(),after_sha256=hashlib.sha256(args.after.read_bytes()).hexdigest(),cases=allrows),indent=2)+'\n')
 assert all(not c['new_wrong_planes'] and not c['introduced_material_disagreements'] for c in allrows)
if __name__=='__main__':main()
