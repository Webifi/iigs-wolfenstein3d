"""Paired timedemos and separate native picture runs for paint acceptance."""
import memmap
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import timedemo, demo_capture
from elf import read
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('disk',type=Path);p.add_argument('elf',type=Path);p.add_argument('--views',nargs='+',type=int,default=[214,320]);p.add_argument('--demos',nargs='+',type=int,default=list(range(4)));p.add_argument('--capture-only',action='store_true');p.add_argument('--seed',type=int,help='explicit diagnostic RAM seed; default keeps stock startup');a=p.parse_args()
a.disk=a.disk.resolve(strict=True);a.elf=a.elf.resolve(strict=True)
if a.disk.stat().st_mtime_ns<a.elf.stat().st_mtime_ns:
 raise SystemExit('Disk predates ELF: finish the build or use a preserved matching pair')
disk_hash=timedemo.sha(a.disk);elf_hash=timedemo.sha(a.elf)
out=timedemo.ROOT/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
_,symbols=read(a.elf)
original=timedemo.LUA
summaries=[]
for view in a.views:
 for demo in a.demos:
  results=[]
  for repeat in ((0,) if a.capture_only else (0,1,2)):
   target=out/f'd{demo}-v{view}'/str(repeat)
   frames=[81,174,216,217,218,219,220,221,222,883] if demo==1 else [1,100,318,836,891]
   script=original
   # Picture reads perturb this model's clocks, so only runs 1 and 2 are timed.
   if repeat==0:
    addition=demo_capture.lua(symbols,frames,target)+memmap.fill('''\nlocal pixels=assert(io.open(@PIXELS@,"wb"))
local function allPixels()
 local parts={};for i=0,32767,4 do parts[#parts+1]=string.pack("<I4",s:read_u32(@MM:SHR@+i)) end
 pixels:write(table.concat(parts));pixels:flush()
end
''')
    addition=addition.replace('@PIXELS@',json.dumps(str(target/'frames.shr')))
    script=script.replace('local first, previous, frames',addition+'\nlocal first, previous, frames')
    script=script.replace('frames=frames+1','frames=frames+1\n    allPixels();capturePicture(frames)')
   timedemo.LUA=script
   task=SimpleNamespace(machine='apple2gsr1',seed=a.seed,pal=False,view=view,demo=demo,limit=650,disk=a.disk.resolve(),disk2=None,drives=2,mame=timedemo.MAME,host_limit=600)
   result=timedemo.run(task,target)
   assert timedemo.sha(a.disk)==disk_hash and timedemo.sha(a.elf)==elf_hash, "Build inputs changed during measurement"
   if repeat:results.append(result)
   if repeat==0:(target/'result.json').write_text(json.dumps(dict(result,**demo_capture.metadata(symbols)),indent=2)+'\n')
   print(f'{a.name} d{demo} v{view} run {repeat}: {result["seconds"]:.9f} s',flush=True)
  if a.capture_only:continue
  assert results[0]['frame_times']==results[1]['frame_times'], 'Repeated frame timings differ'
  summary=dict(demo=demo,view=view,identical_runs=2,**{k:v for k,v in results[0].items() if k!='frame_times'})
  summaries.append(summary);(out/'summary.json').write_text(json.dumps(dict(disk=str(a.disk),disk_sha256=disk_hash,elf_sha256=elf_hash,mame_sha256=timedemo.sha(timedemo.MAME),machine='apple2gsr1',ram='4352K',seed=a.seed,cases=summaries),indent=2)+'\n')
print(out if a.capture_only else out/'summary.json',flush=True)
