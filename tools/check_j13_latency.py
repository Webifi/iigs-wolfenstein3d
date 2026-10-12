"""Measure physical second-key edges through the queue and actual player command."""
import argparse,hashlib,json,re,statistics,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path,nargs='?',default=Path(__file__).resolve().parents[1]);p.add_argument('--mame',type=Path,required=True);p.add_argument('--disk',type=Path,required=True);p.add_argument('--name',required=True);p.add_argument('--accelerator',type=int,choices=(0,5),required=True);p.add_argument('--view',type=int,choices=(214,320),default=214);p.add_argument('--j13',choices=('only','both'),default='only');p.add_argument('--input',choices=('j13','adb'),default='j13');p.add_argument('--samples',type=int,default=24);p.add_argument('--mute',action='store_true')
a=p.parse_args();root=a.root.resolve();out=root/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'tools'));from elf import read
_,symbols=read(root/'build/wolf.elf')
names=['LogicTicControls','j13Enabled','j13Mode','j13Matrix','j13Timeouts','inputDropped','viewWidth','musicActive','inputHead','inputTail','inputRing','inputUntil','lastMadeTic','keyHeld','j13State','rowAddress','j13Owner','J13Frame','sampleTime','controllerTime','knownCount','rowValue','rowNext','j13Irq']
S={n:symbols[n] for n in names}
def lua(v):
 if isinstance(v,dict):return '{'+','.join('['+lua(k)+']='+lua(x) for k,x in v.items())+'}'
 if isinstance(v,list):return '{'+','.join(map(lua,v))+'}'
 if isinstance(v,str):return json.dumps(v)
 return str(v)
sequence=[];t=2
for i in range(a.samples):
 key=('Left','Right')[i%2];duration=(0.1,0.2,0.35,0.15)[i%4]
 sequence.extend([dict(time=t,code=(59 if key=='Left' else 60),key=key,value=1,trial=i+1),dict(time=t+duration,code=(59 if key=='Left' else 60),key=key,value=0,trial=i+1)])
 t+=duration+0.87+(i%5)/60
sequence.append(dict(time=t+2,code=62,key='Up',value=0,trial=0))
script='local S='+lua(S)+'\nlocal edges='+lua(sequence)+'\nlocal OUT='+lua(str(out))+'\nlocal requestedView='+str(a.view)+'\nlocal inputKind='+lua(a.input)+'\nlocal requiredMusic='+str(int(not a.mute))+'\n'+r'''
local file=assert(io.open(OUT..'/events.tsv','w'));file:setvbuf('line')
local active=false;local start=0;local nextEdge=1;local frames=0;local ready=nil;local resizeKey=nil;local releaseAt=nil;local command=0
local fields={};for _,port in pairs(manager.machine.ioport.ports) do for _,f in pairs(port.fields) do fields[f.name]=f end end
local function time() return manager.machine.time:as_double() end
local function value(n) return mem:read_u16(S[n]) end
local function log(kind,...) if active then file:write(string.format('%.9f\t%s',time(),kind));for _,x in ipairs({...}) do file:write('\t'..tostring(x)) end;file:write('\n') end end
local function key(k,v) local n=inputKind=='j13' and 'J13 '..k or k..' Arrow';assert(fields[n],n):set_value(v) end
CALLS.ready=function()
 ready=ready or frames+3
 if frames<ready then return false end
 if releaseAt then
  if time()<releaseAt then return false end
  fields[resizeKey]:set_value(0);releaseAt=nil;ready=frames+4;return false
 end
 if value('viewWidth')*2~=requestedView then
  resizeKey=value('viewWidth')*2>requestedView and 'J13 Minus' or 'J13 Equals'
  fields[resizeKey]:set_value(1);releaseAt=time()+0.15;return false
 end
 assert(value('j13Mode')==2 and value('j13Enabled')==1 and value('j13Matrix')==1)
 assert(value('musicActive')==requiredMusic)
 print('LATENCY_MODE '..value('viewWidth')*2 ..' '..value('j13Mode')..' '..value('j13Matrix'))
end
CALLS.start=function() active=true;start=time();key('Up',1);log('physical',62,1,0) end
CALLS.done=function() return not active end
mem:install_read_tap(S.LogicTicControls,S.LogicTicControls,'latency-player',function(ad)
 if active and not manager.machine:side_effects_disabled() and cpu.state.PC.value==ad+1 then
  command=cpu.state.A.value&65535;log('player',command)
 end
end)
mem:install_read_tap(S.J13Frame,S.J13Frame,'latency-poll',function(ad)
 if active and not manager.machine:side_effects_disabled() and cpu.state.PC.value==ad+1 then log('poll',value('lastMadeTic'),value('inputHead'),value('inputTail'),value('j13State'),value('rowAddress')) end
end)
mem:install_write_tap(S.inputHead+1,S.inputHead+1,'latency-event',function(_,d)
 if active and not manager.machine:side_effects_disabled() then
  local h=mem:read_u8(S.inputHead)|(d<<8);local ptr=S.inputRing+((h-8)&1023)
  log('queue',mem:read_u16(ptr+2),mem:read_u16(ptr+4),mem:read_u16(ptr),value('lastMadeTic'),value('inputUntil'))
 end
end)
mem:install_write_tap(S.j13State,S.j13State,'latency-phase',function(_,d) log('phase',d,value('rowAddress'),value('rowNext'),value('knownCount'),value('rowValue')) end)
mem:install_read_tap(S.j13Irq,S.j13Irq,'latency-wake',function(ad) if active and cpu.state.PC.value==ad+1 and not manager.machine:side_effects_disabled() then log('wake') end end)
mem:install_read_tap(0xe0c000,0xe0c000,'latency-strobe',function(_,d)
 if active and not manager.machine:side_effects_disabled() and (d&128)~=0 then log('strobe',d&127) end
end)
mem:install_write_tap(0x3f0,0x3f0,'latency-frame',function(_,d) if d==2 then frames=frames+1;log('frame',command) end end)
emu.register_frame_done(function()
 if not active then return end
 local elapsed=time()-start
 while edges[nextEdge] and edges[nextEdge].time<=elapsed do
  local e=edges[nextEdge];key(e.key,e.value);log('physical',e.code,e.value,e.trial);nextEdge=nextEdge+1
 end
 if nextEdge>#edges and elapsed>edges[#edges].time+1 then
  log('final',value('j13Timeouts'),value('inputDropped'),value('j13Matrix'))
  assert(value('j13Timeouts')==0 and value('inputDropped')==0 and value('j13Matrix')==1)
  for _,code in ipairs({59,60,62}) do assert(mem:read_u8(S.keyHeld+code)==0,'held after all physical releases') end
  active=false;file:close();print('LATENCY_DONE')
 end
end)
'''
(out/'observe.lua').write_text(script)
steps='wait=1;sleep=1;key=J13 Escape;wait=2;sleep=0.3;key=J13 Return;wait=15;sleep=0.3;key=J13 Return;wait=3;sleep=0.3;key=J13 Return;wait=0;sleep=1;call=ready;call=start;call=done;end='
if a.mute:
 prepare=['key=J13 Down','key=J13 Down','key=J13 Return','wait=7','sleep=0.3','key=J13 Return','wait=17','sleep=0.3','key=J13 Down']+['key=J13 Left']*15+['key=J13 Escape','wait=7','key=J13 Escape','wait=2','sleep=0.3','key=J13 Up','key=J13 Up']
 parts=steps.split(';');parts[5:5]=[part for step in prepare for part in ([step,'sleep=0.1'] if step.startswith('key=') else [step])];steps=';'.join(parts)
cmd=[sys.executable,'tools/ui_test.py','--name',a.name,'--mame',str(a.mame),'--disk',str(a.disk.resolve()),'--j13',a.j13,'--accelerator',str(a.accelerator),'--hd','--debug','--seconds','200','--lua',str(out/'observe.lua'),'--steps',steps]
(out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
r=subprocess.run(cmd,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=400);(out/'driver.log').write_text(r.stdout)
log=(out/'mame.log').read_text();assert r.returncode==0 and 'LATENCY_DONE' in log and '[LUA ERROR]' not in log,log[-4000:]
rows=[line.split('\t') for line in (out/'events.tsv').read_text().splitlines()];events=[(float(row[0]),row[1],*[int(x) for x in row[2:]]) for row in rows]
trials=[]
for i in range(1,a.samples+1):
 down=next(e for e in events if e[1]=='physical' and e[3]==1 and e[4]==i);up=next(e for e in events if e[1]=='physical' and e[3]==0 and e[4]==i);code=down[2];bit=4 if code==59 else 8
 next_down=next((e[0] for e in events if e[0]>up[0] and e[1]=='physical' and e[3]==1),events[-1][0])
 source=2 if a.input=='j13' else 0
 qdown=next((e for e in events if down[0]<=e[0]<next_down and e[1]=='queue' and e[2]==source and e[3]==code),None)
 qup=next((e for e in events if up[0]<=e[0]<next_down and e[1]=='queue' and e[2]==source and e[3]==code+128),None)
 pdown=next((e for e in events if down[0]<=e[0]<next_down and e[1]=='player' and e[2]&bit),None)
 pup=next((e for e in events if pdown and max(up[0],pdown[0])<e[0]<next_down and e[1]=='player' and not e[2]&bit),None)
 trial=dict(trial=i,key=code,physical_down=down[0],physical_up=up[0],queue_down=qdown[0] if qdown else None,queue_up=qup[0] if qup else None,player_down=pdown[0] if pdown else None,player_up=pup[0] if pup else None)
 for kind,event,edge in [('queue_press',qdown,down),('queue_release',qup,up),('player_press',pdown,down),('player_release',pup,up)]:trial[kind+'_ms']=(event[0]-edge[0])*1000 if event else None
 trials.append(trial)
first=next(e[0] for e in events if e[1]=='physical' and e[2]==62 and e[3]==1);last=next(e[0] for e in events if e[1]=='physical' and e[2]==62 and e[3]==0)
forward_losses=[e for e in events if first+1<e[0]<last and e[1]=='player' and not e[2]&1]
summary={}
for kind in ['queue_press','queue_release','player_press','player_release']:
 values=[r[kind+'_ms'] for r in trials if r[kind+'_ms'] is not None];values.sort()
 summary[kind]=dict(count=len(values),median_ms=statistics.median(values),max_ms=max(values),min_ms=min(values)) if values else dict(count=0)
result=dict(accelerator=a.accelerator,view=a.view,j13=a.j13,input=a.input,music=int(not a.mute),trials=trials,summary=summary,forward_losses=len(forward_losses),disk_sha256=hashlib.sha256(a.disk.read_bytes()).hexdigest(),elf_sha256=hashlib.sha256((root/'build/wolf.elf').read_bytes()).hexdigest(),mame_sha256=hashlib.sha256(a.mame.read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='trials'},indent=2))
assert not forward_losses and all(s['count']==a.samples for s in summary.values()),'lost or incomplete physical input'
