"""Generate a passive loading-line observer for any guarded MAME fixture."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import memmap
from elf import read
ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args()
_,s=read(ROOT/'build/wolf.elf')
lua=memmap.fill(r'''do
local cpu=manager.machine.devices[':maincpu'];local mem=cpu.spaces['program']
local function now() return manager.machine.time:as_double() end
local function log(tag)
 print(string.format('PROGRESS_EVENT %.6f %s %d %d %d %d',now(),tag,mem:read_u16(DONE),mem:read_u16(TOTAL),mem:read_u16(PIXEL),mem:read_u16(KIND)))
end
local active,last,bucket=false,-1,-1
local dismissing=false
local captures=0
local checkedFills=0
local function on()
 return not dismissing and mem:read_u16(BOOT)~=0 and mem:read_u16(SHOWN)~=0 and mem:read_u16(KIND)==0 and mem:read_u16(BLACK)==0
end
local function checkFill()
 local p=mem:read_u16(PIXEL)
 -- Count the fixed aligned bright-neutral slot after drawing. Its RGB belongs to
 -- the displayed picture and need not be white. Ignore in-flight fades.
 for y=109,111 do
  local n=0
  for x=0,159 do local b=mem:read_u8(@MM:SHR@+y*160+40+(x//2));local v=(x%2==0) and (b>>4) or (b&15);if v==1 then n=n+1 end end
  assert(n==p,string.format('visible loading fill %d differs from completed work %d on row %d',n,p,y))
 end
 checkedFills=checkedFills+1
end
local function tap(a,name,fn)
 mem:install_read_tap(a,a,name,function(ad,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then fn() end
 end)
end
tap(SHOW,'loading-show',function() dismissing=false end)
tap(HIDE,'loading-hide',function() dismissing=true end)
tap(FORGET,'loading-forget',function() dismissing=true end)
tap(PAL_BLACK,'loading-black',function() dismissing=true end)
tap(PIXELS_OUT,'loading-fill-done',function() if on() then checkFill() end end)
emu.add_machine_frame_notifier(function()
 local visible=on()
 if visible then
  local p=mem:read_u16(PIXEL)
  if not active then log('visible');last=-1;bucket=-1 end
  if p~=last then
   log('pixel');last=p
   local q=p//40
   if q~=bucket and captures<40 then
    bucket=q;captures=captures+1
    local f=assert(io.open(OUT..string.format('/loading-%02d-%03d.shr',captures,p),'wb'))
    local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
    f:write(table.concat(b));f:close()
   end
  end
 elseif active then log('hidden');print('LOADING_CHECKED_FILLS '..checkedFills) end
 active=visible
end)
''')
for k,v in {'DONE':s['progressDone'],'TOTAL':s['progressTotal'],'PIXEL':s['busyProgress'],'KIND':s['busyKind'],'BOOT':s['bootComplete'],'BLACK':s['screenBlack'],'SHOWN':s['busyShown'],'SHOW':s['BusyShow'],'HIDE':s['BusyHide'],'FORGET':s['BusyForget'],'PAL_BLACK':s['PalBlack'],'PIXELS_OUT':s['pixelsOut'],'OUT':json.dumps(str(a.output.parent.resolve()))}.items():
 import re
 lua=re.sub(r'\b'+k+r'\b',str(v),lua)
for name in ['ProgressFinish','ProgressPlan','ProgressRemaining','LoadFloorData','demoFloorLoaded','ApplyLevel','PrepareRayPages','gsRestore','SyncSaved','UiLoadDone','ExpandArt','expandDone','UiLoadSign']:
 if name in s:
  addr=s[name];lua+=f'mem:install_read_tap({addr},{addr},"phase-{name}",function(ad,d,m) if cpu.state.PC.value==ad+1 and mem:read_u16({s["bootComplete"]})~=0 then log("{name}") end end)\n'
lua+='end\n';a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(lua)
