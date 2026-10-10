"""Observe scores preparation and two automatic-demo loading transitions.

No game state is written. --baseline retains the reported failures. Optional
fight profiling observes the first automatic demo's actual completed pictures.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import memmap
from elf import read

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--name', required=True)
p.add_argument('--baseline', action='store_true')
p.add_argument('--profile', action='store_true')
p.add_argument('--mame', type=Path,
               help='emulator containing the ROM01 J13 keyboard implementation')
a = p.parse_args()
out = ROOT/'build/tests'/a.name
out.mkdir(exist_ok=False)
_, symbols = read(ROOT/'build/wolf.elf')
shutil.copy2(ROOT/'build/wolf.elf', out/'wolf.elf')
lua = memmap.fill(r'''
local scoreBuilding,loading,active=false,false,false
local scoreNumber,demos,frames,packets=0,0,0,0
local earlyColors,loadFrames,signFrames=0,0,0
local signReady=false
local worldAt,visibilityAt,staticsAt,actorsAt=nil,nil,nil,nil
local worldMs,visibilityMs,staticsMs,actorsMs=0,0,0,0
local frameAt,logicAt,castAt,prepareAt,paintAt=nil,nil,nil,nil,nil
local profileStart,profileTime=nil,nil
local prof=manager.machine.memory.regions[':zipprof']
local function stamp(tag) print(string.format('TRANSITION %.9f %s',now(),tag)) end
local function tap(ad,name,fn)
 mem:install_read_tap(ad,ad,name,function(addr,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(addr>>16) and cpu.state.PC.value==addr+1 then fn() end
 end)
end
local function dump(name)
 local f=assert(io.open(OUT..'/'..name..'.shr','wb'))
 local b={};for i=0,32767,4 do b[#b+1]=string.pack('<I4',mem:read_u32(@MM:SHR@+i)) end
 f:write(table.concat(b));f:close()
end
local function counters()
 local v={};for i=0,0x15fff do v[i]=prof:read_u64(@MM:ART_BRIGHT+0x100@+i*24+16) end;return v
end
tap(MENU_OPEN,'score-entry',function()
 if mem:read_u8(0x3e4)==12 and mem:read_u16(ACTIVE)~=0 and mem:read_u16(BLACK)~=0 then
  scoreBuilding=true;scoreNumber=scoreNumber+1;earlyColors=0;stamp('scores-begin')
 end
end)
mem:install_write_tap(@MM:SHR_PAL@,@MM:SHR_PAL+0x1ff@,'score-palette',function(ad,d,m)
 if scoreBuilding and d~=0 then earlyColors=earlyColors+1 end
end)
tap(DEMO_START,'loading-start',function()
 loading=true;signReady=false;loadFrames=0;signFrames=0;stamp('loading-begin')
end)
tap(SIGN_READY,'loading-painted',function() if loading then signReady=true end end)
tap(WAIT_INPUT,'scores-shown',function()
 if mem:read_u8(0x3e4)==6 then dump('scores-shown-'..scoreNumber) end
end)
tap(WORLD_START,'world-work',function() if active then worldAt=now() end end)
tap(VIEW_START,'world-done',function()
 if active and worldAt then worldMs=worldMs+now()-worldAt;worldAt=nil;visibilityAt=now() end
end)
tap(STATICS_START,'visibility-done',function()
 if active and visibilityAt then visibilityMs=visibilityMs+now()-visibilityAt;visibilityAt=nil;staticsAt=now() end
end)
tap(ACTORS_START,'statics-done',function()
 if active and staticsAt then staticsMs=staticsMs+now()-staticsAt;staticsAt=nil;actorsAt=now() end
end)
tap(OBJECTS_DONE,'actors-done',function()
 if active and actorsAt then actorsMs=actorsMs+now()-actorsAt;actorsAt=nil end
end)
mem:install_write_tap(0x3e4,0x3e4,'screen',function(ad,d,m)
 if d==6 and scoreBuilding then
  print(string.format('SCORES_PREPARED %d %d',scoreNumber,earlyColors));dump('scores-prepared-'..scoreNumber)
  scoreBuilding=false;stamp('scores-ready')
 elseif d==13 then
  demos=demos+1;loading=false
  print(string.format('DEMO_LOADING %d %d %d',demos,loadFrames,signFrames));stamp('demo-ready')
  if demos==1 then active=true end
 end
end)
local lastProgress=-1
emu.add_machine_frame_notifier(function()
 if not loading then return end
 loadFrames=loadFrames+1
 if signReady and mem:read_u16(SHOWN)~=0 and mem:read_u16(BLACK)==0 then
  local visible=false
  for y=82,113 do
   local pal=@MM:SHR_PAL@+32*(mem:read_u8(@MM:SHR_SCB@+y)&15)
   for x=40,119 do
    local b=mem:read_u8(@MM:SHR@+y*160+x)
    if mem:read_u16(pal+2*(b&15))~=0 or mem:read_u16(pal+2*(b>>4))~=0 then visible=true;break end
   end
   if visible then break end
  end
  if visible then
   signFrames=signFrames+1
   local progress=mem:read_u16(PROGRESS)
   if signFrames==1 then dump('loading-'..(demos+1));stamp('loading-visible');lastProgress=-1 end
   if progress~=lastProgress then
    print(string.format('LOAD_PROGRESS %d %.9f %d',demos+1,now(),progress));lastProgress=progress
   end
  end
 end
end)
mem:install_write_tap(0x3f7,0x3f7,'packet',function(ad,d,m)
 if active and d==1 then packets=packets+1 end
end)
tap(PUBLISH,'logic-done',function() if active and frameAt then logicAt=now() end end)
mem:install_write_tap(0x3f2,0x3f2,'cast',function(ad,d,m)
 if active and frameAt then if d==1 then castAt=now() else prepareAt=now() end end
end)
mem:install_write_tap(0x3f3,0x3f3,'paint',function(ad,d,m)
 if active and frameAt and d==1 then paintAt=now() end
end)
mem:install_write_tap(0x3f0,0x3f0,'frame',function(ad,d,m)
 if not active then return end
 if d==1 then
  frameAt=now();logicAt=nil;castAt=nil;prepareAt=nil;paintAt=nil
  worldMs=0;visibilityMs=0;staticsMs=0;actorsMs=0
  if PROFILE and not profileStart and packets>=800 and packets<980 then
   profileStart=counters();profileTime=frameAt;stamp('profile-begin')
  end
 elseif d==2 and frameAt then
  frames=frames+1
  if logicAt and castAt and prepareAt and paintAt then
   print(string.format('FIGHT_FRAME %d %d %.9f %.9f %.9f %.9f %.9f',frames,packets,
    now()-frameAt,logicAt-frameAt,castAt-logicAt,prepareAt-castAt,paintAt-prepareAt))
   print(string.format('FIGHT_PAINT %d %.9f',frames,now()-paintAt))
   print(string.format('FIGHT_LOGIC %d %.9f %.9f %.9f %.9f',frames,worldMs,visibilityMs,staticsMs,actorsMs))
  end
  if PROFILE and profileStart and packets>=980 then
   local final=counters();local f=assert(io.open(OUT..'/profile.txt','w'))
   for i=0,0x15fff do local delta=final[i]-profileStart[i]
    if delta>0 then f:write(string.format('%06x %d\n',i<0x6000 and i*16 or (i-0x6000)*256,delta)) end
   end
   f:close();print(string.format('FIGHT_PROFILE %.9f',now()-profileTime));profileStart=nil;PROFILE=false
  end
 end
end)
mem:install_write_tap(0x3f5,0x3f5,'demo-end',function(ad,d,m) if active and d==2 then active=false end end)
CALLS.checked=function() assert(demos==2,'two automatic loads required');stamp('done') end
''')
for key, name in dict(MENU_OPEN='MenuDimOpen',ACTIVE='attractActive',BLACK='screenBlack',
                      DEMO_START='PlayTitleDemo',SHOWN='busyShown',PROGRESS='busyProgress',PUBLISH='publishFrame',
                      SIGN_READY='busySuppressed',WAIT_INPUT='WaitInput',WORLD_START='advanceLogic',
                      VIEW_START='finishLogic',STATICS_START='refreshStatics',ACTORS_START='refreshActors',
                      OBJECTS_DONE='logicObjectsDone').items():
    lua=re.sub(r'\b'+key+r'\b',str(symbols[name]),lua)
lua=lua.replace('OUT',json.dumps(str(out)))
lua=re.sub(r'\bPROFILE\b','profileEnabled',lua)
lua='local profileEnabled='+('true' if a.profile else 'false')+'\n'+lua
(out/'observe.lua').write_text(lua)
steps='wait=12;wait=6;sleep=0.5;snap=scores;wait=13;sleep=2;wait=1;wait=12;wait=6;sleep=0.5;wait=13;sleep=1;call=checked;end='
command=[sys.executable,'tools/ui_test.py','--name',a.name,'--hd','--debug','--j13','only','--seconds','400',
         '--lua',str(out/'observe.lua'),'--steps',steps]
if a.mame:
    command += ['--mame',str(a.mame.resolve())]
r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=600)
(out/'driver.log').write_text(r.stdout+r.stderr)
log=(out/'mame.log').read_text()
assert r.returncode==0 and '[LUA ERROR]' not in log and re.search(r'^TRANSITION [\d.]+ done$',log,re.M),log[-3000:]
scores=[dict(cycle=int(n),premature_palette_writes=int(c)) for n,c in re.findall(r'^SCORES_PREPARED (\d+) (\d+)$',log,re.M)]
loads=[dict(demo=int(n),preparation_video_frames=int(f),visible_sign_frames=int(s))
       for n,f,s in re.findall(r'^DEMO_LOADING (\d+) (\d+) (\d+)$',log,re.M)]
progress=[dict(demo=int(n),time=float(t),pixels=int(p)) for n,t,p in re.findall(r'^LOAD_PROGRESS (\d+) ([\d.]+) (\d+)$',log,re.M)]
report=dict(scores=scores,loads=loads,progress=progress,baseline=a.baseline,
            elf_sha256=hashlib.sha256((out/'wolf.elf').read_bytes()).hexdigest(),
            disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
if not a.baseline:
    assert len(scores)==2 and all(s['premature_palette_writes']==0 for s in scores),scores
    assert len(loads)==2 and all(s['visible_sign_frames']>20 for s in loads),loads
    assert all(len({p['pixels'] for p in progress if p['demo']==n})>=3 for n in (1,2)),progress
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
from render import shr_screen
from imaging import png
for f in out.glob('*.shr'):png(f.with_suffix('.png'),shr_screen(f.read_bytes()).rows,2)
print(json.dumps(report,indent=2))
