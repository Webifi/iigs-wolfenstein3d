"""Physical J13 presses, releases, and held-key transitions in native MAME.

--case preheld holds Up through New Game loading; resume holds Up through a
menu round trip; modifier does the same with Shift. These transition cases
require Left to clear within 300 ms, and retain every physical, queued, and
player-command timestamp. The holds case retains its older 700 ms gate; its
pass alone is not evidence of prompt release. No game or keyboard state is
written by these observers: only physical emulator fields supply input.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

p=argparse.ArgumentParser()
p.add_argument('--no-debug',action='store_true')
p.add_argument('--mouse',action='store_true')
p.add_argument('--nvram',type=Path)
p.add_argument('--ramsize',default='4352K')
p.add_argument('--disk',type=Path,required=True)
p.add_argument('--mame',type=Path,required=True)
p.add_argument('--name',required=True)
p.add_argument('--j13',choices=('only','both'),required=True)
p.add_argument('--accelerator',type=int,choices=(0,5),required=True)
p.add_argument('--case',choices=('rapid','holds','sweep','preheld','resume','modifier'),default='rapid')
p.add_argument('--view',type=int,choices=(214,320))
p.add_argument('--mute',action='store_true')
a=p.parse_args();root=Path(__file__).resolve().parents[1];out=root/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'tools'))
from elf import read
_,symbols=read(root/'build/wolf.elf')
names=['j13Enabled','j13Mode','j13Matrix','j13AdbPresent','j13Timeouts','j13Keys','knownCount','keyHeld','inputHead','inputRing','J13Sample','j13Samples','j13Events','j13State','j13Owner','physicalValid','j13LastAscii','sampleAscii','sampleAKD','sampleMods','viewWidth','musicActive','LogicTicControls','rowAddress','rowValue','rowExpected','rowGeneration','j13Generation','rowNext','rowDeadline','sendBudget','keyTalk','keyPending','keyReply','inputDropped','controllerTime']
S={k:symbols[k] for k in names}
codes={'Left':59,'Right':60,'Up':62,'Down':61,'W':13,'Space':49}
cases=[]
for duration in (0.05,0.1,0.15):
 for overlap in (0,0.03):
  for phase in (0,1/60):
   for sequence in (['Left','Right','Left'],['Up','Down'],['Left','Up']):
    # A switch cannot be pressed again before its prior hold ends. In the
    # 50 ms / 30 ms overlap triple, the two Left holds would overlap.
    if any(sequence[i]==sequence[j] and (j-i)*(duration-overlap)<=duration
           for i in range(len(sequence)) for j in range(i+1,len(sequence))):
     continue
    events=[];expected={}
    for i,key in enumerate(sequence):
     t=phase+i*(duration-overlap)
     events.extend([dict(t=t,key='J13 '+key,value=1),dict(t=t+duration,key='J13 '+key,value=0)])
     expected[str(codes[key])]=expected.get(str(codes[key]),0)+1
    events.sort(key=lambda e:(e['t'],-e['value']))
    cases.append(dict(name=f'{"-".join(sequence)}-{duration}-{overlap}-{phase}',events=events,
                      expected=expected,end=events[-1]['t']+0.8))
for duration in (0.05,0.1,0.15):
 for key in ('W','Left','Space'):
  events=[]
  for i in range(8):
   events.extend([dict(t=i*(duration+0.05),key='J13 '+key,value=1),
                  dict(t=i*(duration+0.05)+duration,key='J13 '+key,value=0)])
  cases.append(dict(name=f'repress-{key}-{duration}',events=events,
                    expected={str(codes[key]):8},end=events[-1]['t']+0.8))
if a.case=='holds':
 cases=[]
 for key in ('Left','Right'):
  for duration in (0.05,0.1,0.2):
   events=[dict(t=0,key='J13 Up',value=1),
           dict(t=4.5,key='J13 '+key,value=1),dict(t=4.5+duration,key='J13 '+key,value=0),
           dict(t=8,key='J13 '+key,value=1),dict(t=9.5,key='J13 '+key,value=0),
           dict(t=13,key='J13 Up',value=0)]
   cases.append(dict(name=f'Up-held-{key}-tap-{duration}',events=events,
                     expected={'62':1,str(codes[key]):2},end=14,
                     gates=[dict(start=0.75,stop=13,key=62,held=2),
                            dict(start=5.2,stop=8,key=codes[key],held=0),
                            dict(start=10.2,stop=13,key=codes[key],held=0)]))
if a.case=='sweep':
 cases=[]
 for base in ('Up','W'):
  for delay in (0.05,0.2,0.5,0.75,1.0,4.5):
   for duration in (0.05,0.1,0.2):
    events=[dict(t=0,key='J13 '+base,value=1),dict(t=delay,key='J13 Left',value=1),dict(t=delay+duration,key='J13 Left',value=0),dict(t=delay+duration+2,key='J13 '+base,value=0)]
    cases.append(dict(name=f'{base}-held-Left-{delay}-{duration}',events=events,expected={str(codes[base]):1,'59':1},end=delay+duration+2.5,gates=[dict(start=delay+duration+0.3,stop=delay+duration+2,key=59,held=0)]))
if a.case=='preheld':
 cases=[dict(name='Up-held-through-game-start-Left-tap',events=[dict(t=1,key='J13 Left',value=1),dict(t=1.1,key='J13 Left',value=0),dict(t=8,key='J13 Up',value=0)],expected={'59':1,'62':0},end=9,gates=[dict(start=0.1,stop=8,key=62,held=2),dict(start=1.4,stop=8,key=59,held=0)])]
if a.case in ('resume','modifier'):
 cases=[dict(name='Up-held-menu-return-Left-tap',events=[dict(t=0,key='J13 Up',value=1),dict(t=2,key='J13 Escape',value=1),dict(t=2.15,key='J13 Escape',value=0),dict(t=3.5,key='J13 Escape',value=1),dict(t=3.65,key='J13 Escape',value=0),dict(t=5,key='J13 Left',value=1),dict(t=5.1,key='J13 Left',value=0),dict(t=12,key='J13 Up',value=0)],expected={'62':2,'59':1,'53':2},end=13,gates=[dict(start=0.75,stop=1.9,key=62,held=2),dict(start=4.5,stop=12,key=62,held=2),dict(start=5.4,stop=12,key=59,held=0)])]
if a.case=='modifier':
 c=cases[0];c['name']='Shift-held-menu-return-Left-tap';c['expected']={'56':2,'59':1,'53':2}
 for e in c['events']:
  if e['key']=='J13 Up':e['key']='J13 Shift'
 for g in c['gates']:
  if g['key']==62:g['key']=56
def lua(v):
 if isinstance(v,dict):return '{'+','.join('['+lua(k)+']='+lua(x) for k,x in v.items())+'}'
 if isinstance(v,list):return '{'+','.join(map(lua,v))+'}'
 if isinstance(v,str):return json.dumps(v)
 return str(v)
script='local moveMouse='+str(int(a.mouse))+'\nlocal S='+lua(S)+'\nlocal cases='+lua(cases)+'\nlocal wantedView='+str(a.view or 0)+'\nlocal wantedMusic='+str(int(not a.mute))+'\nlocal OUTPUT='+lua(str(out))+'\n'+r'''
local fields={}
for _,port in pairs(manager.machine.ioport.ports) do for _,f in pairs(port.fields) do fields[f.name]=f end end
local events=assert(io.open(OUTPUT..'/events.tsv','w'))
events:setvbuf('line')
local stateLog=assert(io.open(OUTPUT..'/state.tsv','w'));stateLog:setvbuf('line')
local lastState=''
local hardware=assert(io.open(OUTPUT..'/hardware.tsv','w'))
local reports=assert(io.open(OUTPUT..'/cases.jsonl','w'))
local lastHeld='';local ci,ei=1,1;local active=false;local start=nil;local counts={};local passes=0;local gateErrors=0
local frames=0;local ready=nil;local resizeKey,resizeRelease=nil,nil
local function time() return manager.machine.time:as_double() end
local function value(name) return mem:read_u16(S[name]) end
mem:install_read_tap(S.LogicTicControls,S.LogicTicControls,'pair-player-command',function(ad)
 if not active or manager.machine:side_effects_disabled() or cpu.state.PC.value~=ad+1 then return end
 local t=time()-start;local command=cpu.state.A.value&65535
 events:write(string.format('%.9f\t%d\tplayer-command\t%d\n',time(),ci,command))
 for _,g in ipairs(cases[ci].gates or {}) do
  if t>=g.start and t<g.stop then
   g.commandChecks=(g.commandChecks or 0)+1
   local bit=({[62]=1,[59]=4,[60]=8,[56]=128})[g.key]
   if ((command&bit)~=0)~=(g.held~=0) then
    gateErrors=gateErrors+1
    events:write(string.format('%.9f\t%d\tcommand-fail\t%d\t%d\t%d\n',time(),ci,g.key,g.held,command))
   end
  end
 end
end)
mem:install_write_tap(0x3f0,0x3f0,'rapid-frames',function(_,d) if d==2 then frames=frames+1 end end)
mem:install_write_tap(S.inputHead+1,S.inputHead+1,'rapid-queue',function(_,d)
 if not active or manager.machine:side_effects_disabled() then return end
 local head=mem:read_u8(S.inputHead)|(d<<8)
 local slot=S.inputRing+((head-8)&1023)
 local typ=mem:read_u16(slot+2);local code=mem:read_u16(slot+4)
 events:write(string.format('%.9f\t%d\tqueue\t%d\t%d\n',time(),ci,typ,code))
 if typ==2 then counts[code]=(counts[code] or 0)+1 end
end)
for _,address in ipairs({0xe0c000,0xe0c010,0xe0c025}) do
 mem:install_read_tap(address,address,'rapid-register-'..address,function(ad,d)
  if active and not manager.machine:side_effects_disabled() then
   hardware:write(string.format('%.9f\t%d\t%06x\t%02x\t%06x\n',time(),ci,ad,d,cpu.state.PC.value))
  end
 end)
end
CALLS.ready=function()
 ready=ready or frames+2
 if frames<ready then return false end
 if resizeRelease then
  if time()<resizeRelease then return false end
  fields[resizeKey]:set_value(0);resizeRelease=nil;ready=frames+5
  return false
 end
 if wantedView~=0 and value('viewWidth')*2~=wantedView then
  resizeKey=value('viewWidth')*2>wantedView and 'J13 Minus' or 'J13 Equals'
  fields[resizeKey]:set_value(1);resizeRelease=time()+0.15
  return false
 end
 assert(value('j13Mode')==2,'J13 gameplay must be active')
 assert(value('musicActive')==wantedMusic,'music mode mismatch')
 print(string.format('MODE enabled=%d mode=%d matrix=%d adb=%d accelerator=%d view=%d music=%d',value('j13Enabled'),value('j13Mode'),value('j13Matrix'),value('j13AdbPresent'),manager.machine.ioport.ports[':a2_config']:read(),value('viewWidth')*2,value('musicActive')))
end
CALLS.preheld=function() fields['J13 Up']:set_value(1) end
CALLS.run=function() active=true;start=time() end
CALLS.done=function() return not active end
emu.register_frame_done(function()
 if not active then return end
 local t=time()-start;local c=cases[ci]
 if moveMouse==1 then
  for _,f in pairs(manager.machine.ioport.ports[':macadb:MOUSE1'].fields) do f:set_value(math.floor(time()*120)%256) end
  for _,f in pairs(manager.machine.ioport.ports[':macadb:MOUSE2'].fields) do f:set_value(math.floor(time()*90)%256) end
 end
 local st={}
 for _,name in ipairs({'j13Matrix','j13Timeouts','knownCount','j13State','j13Owner','rowAddress','rowValue','rowExpected','rowGeneration','j13Generation','rowNext','rowDeadline','sendBudget','keyTalk','keyPending','keyReply','inputDropped','controllerTime'}) do st[#st+1]=name..'='..value(name) end
 local state=table.concat(st,',')
 if state~=lastState then stateLog:write(string.format('%.9f\t%d\t%s\n',time(),ci,state));lastState=state end
 while c.events[ei] and c.events[ei].t<=t do
  local e=c.events[ei];assert(fields[e.key],e.key):set_value(e.value)
  events:write(string.format('%.9f\t%d\tphysical\t%s\t%d\n',time(),ci,e.key,e.value));ei=ei+1
 end
 local held={}
 for _,k in ipairs({13,49,59,60,61,62}) do held[#held+1]=mem:read_u8(S.keyHeld+k) end
 local h=table.concat(held,',')
 if h~=lastHeld then events:write(string.format('%.9f\t%d\theld\t%s\n',time(),ci,h));lastHeld=h end
 for _,g in ipairs(c.gates or {}) do
  if t>=g.start and t<g.stop and mem:read_u8(S.keyHeld+g.key)~=g.held then
   gateErrors=gateErrors+1
   events:write(string.format('%.9f\t%d\tgate-fail\t%d\t%d\t%d\n',time(),ci,g.key,g.held,mem:read_u8(S.keyHeld+g.key)))
  end
 end
 if t<c['end'] then return end
 local ok=gateErrors==0;local actual={};local commandChecks=0
 for _,g in ipairs(c.gates or {}) do
  commandChecks=commandChecks+(g.commandChecks or 0)
  if not g.commandChecks then ok=false end
 end
 for code,n in pairs(c.expected) do
  local k=tonumber(code);local down,up=counts[k] or 0,counts[k+128] or 0
  local expectedUp=n
  if (c.name=='Up-held-through-game-start-Left-tap' or c.name=='Up-held-menu-return-Left-tap') and k==62 then expectedUp=1 end
  if c.name=='Shift-held-menu-return-Left-tap' and k==56 then expectedUp=1 end
  if down~=n or up~=expectedUp then ok=false end
  actual[#actual+1]=string.format('"%s":[%d,%d,%d]',code,n,down,up)
 end
 for code,n in pairs(counts) do
  local ordinary=code&127
  if n>0 and not c.expected[tostring(ordinary)] then ok=false end
 end
 for _,v in ipairs(held) do if v~=0 then ok=false end end
 if value('j13Timeouts')~=0 or value('j13Matrix')~=1 then ok=false end
 if ok then passes=passes+1 end
 reports:write(string.format('{"case":%d,"name":"%s","passed":%s,"counts":{%s},"held":"%s","timeouts":%d,"held_state_failures":%d,"player_command_checks":%d}\n',ci,c.name,tostring(ok),table.concat(actual,','),h,value('j13Timeouts'),gateErrors,commandChecks))
 print(string.format('RAPID_CASE %d %s %s %s',ci,c.name,tostring(ok),table.concat(actual,',')))
 ci=ci+1;ei=1;counts={};gateErrors=0;start=time()
 if ci>#cases then
  active=false;events:close();hardware:close();reports:close()
  print(string.format('RAPID_DONE %d %d',passes,#cases))
 end
end)
'''
(out/'observe.lua').write_text(script)
steps=['wait=1','sleep=1','key=J13 Escape','wait=2','sleep=0.3','key=J13 Return','wait=15','sleep=0.3','key=J13 Return','wait=3','sleep=0.3','key=J13 Return','wait=0','sleep=1','call=ready','call=run','call=done','end=']
if a.case=='preheld':
 steps.insert(steps.index('wait=3')+2,'call=preheld')
 steps.insert(steps.index('call=preheld')+1,'sleep=0.5')
if a.mute:
 prepare=['key=J13 Down','key=J13 Down','key=J13 Return','wait=7','sleep=0.3','key=J13 Return','wait=17','sleep=0.3','key=J13 Down']+['key=J13 Left']*15+['key=J13 Escape','wait=7','key=J13 Escape','wait=2','sleep=0.3','key=J13 Up','key=J13 Up']
 # Give repeated menu keys a full release interval. This does not alter the
 # measured gameplay pulses, which begin only after CALLS.ready succeeds.
 steps[5:5]=[part for step in prepare for part in ([step,'sleep=0.1'] if step.startswith('key=') else [step])]
cmd=[sys.executable,'tools/ui_test.py','--name',a.name,'--mame',str(a.mame),'--disk',str(a.disk.resolve()),'--j13',a.j13,'--accelerator',str(a.accelerator),'--hd','--ramsize',a.ramsize,'--seconds','220','--lua',str(out/'observe.lua'),'--steps',';'.join(steps)]
if not a.no_debug:cmd.append('--debug')
if a.nvram:
 import shutil
 shutil.copytree(a.nvram,out/'nvram',dirs_exist_ok=True)
(out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
r=subprocess.run(cmd,cwd=root,capture_output=True,text=True,timeout=400)
(out/'driver.log').write_text(r.stdout+r.stderr)
log=(out/'mame.log').read_text()
if r.returncode or 'RAPID_DONE' not in log:raise RuntimeError(log[-4000:])
rows=[json.loads(x) for x in (out/'cases.jsonl').read_text().splitlines()]
import re
mode=re.search(r'MODE enabled=(\d+) mode=(\d+) matrix=(\d+) adb=(\d+) accelerator=(\d+) view=(\d+) music=(\d+)',log)
assert mode
configuration=dict(zip(('enabled','mode','matrix','adb','accelerator','view','music'),map(int,mode.groups())))
result=dict(configuration=configuration,case=a.case,passed=sum(x['passed'] for x in rows),total=len(rows),cases=rows,
            accelerator=a.accelerator,j13=a.j13,
            disk_sha256=hashlib.sha256(a.disk.read_bytes()).hexdigest(),
            elf_sha256=hashlib.sha256((root/'build/wolf.elf').read_bytes()).hexdigest(),
            mame_sha256=hashlib.sha256(a.mame.read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))

if result['passed']!=result['total']:raise SystemExit('J13 pair assertions failed')
