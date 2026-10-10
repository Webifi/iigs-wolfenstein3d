"""Measure normal-boot live input cost in an unchanged, fully repainted room.

Real J13 H/J/T presses are unbound and leave the world unchanged. FIRST is
forced only in the repaint phases; the other phases exercise reused columns.
This controlled scene is a cost probe, not a representative gameplay FPS test.
"""
import memmap
import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
from elf import read

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--name', required=True)
p.add_argument('--mame', required=True, type=Path)
p.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf')
p.add_argument('--disk', type=Path, default=ROOT / 'build/wolf-hd.po')
p.add_argument('--mode', choices=('baseline', 'off', 'on'), required=True)
p.add_argument('--view', choices=(214, 320), type=int, default=214)
p.add_argument('--profile', action='store_true', help='attribute J13 time to sampling and controller service')
a = p.parse_args()
_, symbols = read(a.elf)
out = ROOT / 'build/tests' / a.name
out.mkdir(parents=True, exist_ok=True)
lua = memmap.fill(r'''
local phases={}
for _,repaint in ipairs({1,0}) do
 for _,keys in ipairs({0,1,2,3,0}) do phases[#phases+1]={repaint,keys} end
end
local phase,index,count,begin,last=nil,0,0,0,nil
local samples={}
local profile={}
local starts={}
local returnTaps={}
local function instruction(ad)
 return not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1
end
local function finishProfile(ret)
 local pending=starts[ret]
 if not pending or #pending==0 then return end
 local item=table.remove(pending)
 local row=profile[item.phase][item.name]
 row.seconds=row.seconds+manager.machine.time:as_double()-item.time
end
if PROFILE_ENABLED then
 for _,name in ipairs({'J13Sample','updateModifiers','scheduleRow','J13Pump','serviceController','pumpPreserve','parameterBurst'}) do
  local addr=S[name]
  if addr~=0 then mem:install_read_tap(addr,addr,'profile-'..name,function(ad)
   if not instruction(ad) or not phase or count<10 then return end
   profile[index]=profile[index] or {};local row=profile[index][name] or {calls=0,seconds=0};profile[index][name]=row
   row.calls=row.calls+1
   if name=='J13Pump' then local state=mem:read_u16(S.j13State);row['state'..state]=(row['state'..state] or 0)+1 end
   local ret=(ad&0xff0000)|((mem:read_u16(cpu.state.S.value+1)+1)&65535)
   starts[ret]=starts[ret] or {};table.insert(starts[ret],{name=name,phase=index,time=manager.machine.time:as_double()})
   if not returnTaps[ret] then
    returnTaps[ret]=true;mem:install_read_tap(ret,ret,'profile-return',function(at) if instruction(at) then finishProfile(at) end end)
   end
  end) end
 end
end
local function check(ok,why) if not ok then manager.machine:exit();error(why) end end
local function key(name,down)
 for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do
  if f.name==name then f:set_value(down);return end
 end end
 error('missing '..name)
end
local function nextPhase()
 index=index+1;phase=phases[index];count=0;last=nil
 if not phase then
  if MODE~='baseline' then
   check(mem:read_u16(S.j13Timeouts)==0,'controller timeout during measurement')
   check(mem:read_u16(S.j13Matrix)==1,'private reads disabled during measurement')
   check(mem:read_u16(S.inputDropped)==0,'input overflow during measurement')
  end
  for i,values in pairs(profile) do for name,v in pairs(values) do
   print(string.format('PROFILE %d %s %d %.9f %d %d %d %d',i,name,v.calls,v.seconds,v.state1 or 0,v.state2 or 0,v.state3 or 0,v.state4 or 0))
  end end
  print('INPUT_COST_PASS');manager.machine:exit();return
 end
 for n,name in ipairs({'J13 H','J13 J','J13 T'}) do key(name,n<=phase[2] and 1 or 0) end
end
CALLS.configure=function() mem:write_u8(0x3e1,VIEW==214 and 2 or 4) end
CALLS.begin=function()
 check(mem:read_u16(S.viewWidth)==VIEW//2,'view not applied')
 if MODE~='baseline' then
  check(mem:read_u16(S.j13Mode)==(MODE=='on' and 2 or 0),'wrong gameplay input mode')
 end
 nextPhase()
end
mem:install_write_tap(0x3f0,0x3f0,'live-input-cost',function(_,d)
 if not phase then return end
 local t=manager.machine.time:as_double()
 if d==1 then
  if last and count>=10 then print(string.format('PERIOD %d %.9f',index,t-last)) end
  begin=t;last=t
  if phase[1]==1 then mem:write_u16(0x1044,1) end
 elseif d==2 then
  count=count+1
  if count>10 then print(string.format('ACTIVE %d %.9f',index,t-begin)) end
  check(mem:read_u16(0x104a)==0,'unbound fixture key changed controls')
  if count==100 then
   if MODE=='on' then
    for n,raw in ipairs({4,38,17}) do
     check(mem:read_u8(S.keyHeld+raw)==(n<=phase[2] and 2 or 0),'held-key phase not exercised')
    end
   end
   local b={};for i=0,25599 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
   local f=assert(io.open(OUT..'/view-'..index..'.bin','wb'));f:write(table.concat(b));f:close()
   print('PHASE '..index..' '..phase[1]..' '..phase[2]);nextPhase()
  end
 end
end)
''')
names = set(re.findall(r'\bS\.(\w+)', lua)) | {'J13Sample','updateModifiers','scheduleRow','J13Pump','serviceController','pumpPreserve','parameterBurst'}
lua = 'local S={' + ','.join(n+'='+str(symbols.get(n, 0)) for n in sorted(names)) + '}\n' + lua
for k, v in {'MODE':json.dumps(a.mode), 'VIEW':str(a.view), 'OUT':json.dumps(str(out)), 'PROFILE_ENABLED':'true' if a.profile else 'false'}.items():
    lua = re.sub(r'\b'+k+r'\b', lambda m: v, lua)
(out/'observe.lua').write_text(lua)
steps = ['wait=1','sleep=1','key=Esc','wait=2','sleep=0.3','key=Return','wait=15','sleep=0.3','key=Return','wait=3','sleep=0.3','key=Return','wait=0','sleep=1']
if a.mode == 'on':
    steps += ['key=F6','wait=18','sleep=0.3','key=Down','key=Down','key=Return','key=Esc','wait=2','key=Esc','wait=0','sleep=1']
steps += ['call=configure','sleep=1','call=begin','sleep=240','end=']
r = subprocess.run([sys.executable,'tools/ui_test.py','--name',a.name,'--mame',str(a.mame),'--j13','both','--hd','--disk',str(a.disk),'--debug','--seconds','300','--lua',str(out/'observe.lua'),'--steps',';'.join(steps)], cwd=ROOT, capture_output=True, text=True, timeout=480)
(out/'driver.log').write_text(r.stdout+r.stderr)
log = (out/'mame.log').read_text()
assert r.returncode==0 and 'INPUT_COST_PASS' in log and '[LUA ERROR]' not in log, log[-4000:]
rows=[]
for idx, repaint, keys in re.findall(r'^PHASE (\d+) (\d) (\d)$',log,re.M):
    row=dict(phase=int(idx),repaint=int(repaint),keys=int(keys))
    for kind in ('ACTIVE','PERIOD'):
        values=[float(t)*1000 for t in re.findall(r'^'+kind+' '+idx+r' ([\d.]+)$',log,re.M)]
        row[kind.lower()]=dict(n=len(values),mean_ms=statistics.mean(values),p95_ms=sorted(values)[int(len(values)*.95)],max_ms=max(values))
    row['view_sha256']=hashlib.sha256((out/f'view-{idx}.bin').read_bytes()).hexdigest()
    rows.append(row)
result=dict(mode=a.mode,view=a.view,elf_sha256=hashlib.sha256(a.elf.read_bytes()).hexdigest(),disk_sha256=hashlib.sha256(a.disk.read_bytes()).hexdigest(),mame_sha256=hashlib.sha256(a.mame.read_bytes()).hexdigest(),phases=rows)
if a.profile:
    result['profile']=[dict(phase=int(i),routine=n,calls=int(c),seconds=float(t),state_calls=list(map(int,(s1,s2,s3,s4)))) for i,n,c,t,s1,s2,s3,s4 in re.findall(r'^PROFILE (\d+) (\w+) (\d+) ([\d.]+) (\d+) (\d+) (\d+) (\d+)$',log,re.M)]
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
