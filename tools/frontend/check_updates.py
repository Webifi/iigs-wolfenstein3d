"""Real-key menu update timings and transient wrong-write detection."""
import argparse,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import memmap
from elf import read
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);ap.add_argument('--strict',action='store_true');ap.add_argument('--floor-recolors',action='store_true');ap.add_argument('--all-actions',action='store_true');ap.add_argument('--elf',type=Path,default=ROOT/'build/wolf.elf');ap.add_argument('--disk',type=Path);a=ap.parse_args()
_,s=read(a.elf);out=ROOT/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
cases={}
steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=1','key=Return','wait=15','sleep=1','key=Return','wait=3','sleep=1','key=Return','wait=0','sleep=1','key=Esc','wait=2','sleep=1']
def key(name,k):
 cases[name]=k;steps.extend(['call='+name,'key='+k,'sleep=0.5'])
if a.all_actions:
 steps[steps.index('wait=2')+2:steps.index('wait=2')+2]=['call=title-capture']
 cases['open-menu']='Esc';steps[-4:-1]=['call=open-menu','key=Esc','wait=2']
key('main-down','Down');key('main-up','Up')
steps+=['key=Down','key=Down','key=Down'];key('open-options','Return');steps+=['wait=7','sleep=1']
key('options-down','Down');key('options-up','Up');key('open-display','Return');steps+=['wait=17','sleep=1']
key('sound-left','Left');key('sound-right','Right');key('sound-return','Return');key('display-down','Down');key('music-left','Left')
steps+=['key=Down'];key('view-left','Left');key('view-right','Right');steps+=['key=Down'];key('shade-return','Return');key('shade-left','Left')
key('display-back','Esc');steps+=['wait=7','sleep=1','key=Down'];key('open-controls','Return');steps+=['wait=18','sleep=1']
key('mouse-toggle','Return');steps+=['key=Down'];key('mouse-speed','Right');steps+=['key=Down','key=Down'];key('open-keys','Return');steps+=['wait=9','sleep=1']
key('keys-down','Down');key('keys-up','Up');key('bind-prompt','Return');key('bind-cancel','Esc');key('keys-scroll','Up');key('keys-defaults','Return')
key('keys-back','Esc');steps+=['wait=18','sleep=1','key=Esc','wait=7','sleep=1','key=Esc','wait=2','sleep=1']
# Main retains Options as its selected item.
steps+=['key=Up'];key('open-save','Return');steps+=['wait=4','sleep=1'];key('slots-down','Down');key('slots-up','Up');key('slots-back','Esc');steps+=['wait=2','sleep=1']
steps+=['key=Up','key=Up']
if a.all_actions:steps+=['call=visit-two']
key('open-floors','Return');steps+=['wait=15','sleep=1'];key('floor-disabled-down','Down')
if a.all_actions:key('floor-visited-up','Up');key('floor-visited-down','Down');key('floor-return-first','Up')
key('open-difficulty','Return');steps+=['wait=3','sleep=1'];key('difficulty-down','Down');key('difficulty-up','Up');key('difficulty-back','Esc');steps+=['wait=15','sleep=1','key=Esc','wait=2','sleep=1']
steps+=['key=Down','key=Down','key=Down'];key('options-again','Return');steps+=['wait=7','sleep=1','key=Esc','wait=2','sleep=1','key=q'];key('quit-confirm','Return');key('quit-cancel','n');steps+=['wait=2','sleep=1','end=']
if a.all_actions:
 steps.pop();key('close-menu','Esc');steps+=['wait=0','sleep=1','end=']
if a.floor_recolors:
 cases={}
 steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=1','call=visit-two','key=Return','wait=15','sleep=1']
 key('floor-visited-down','Down');key('floor-visited-up','Up');steps+=['end=']

lua=memmap.fill(r'''CALLS={}
local pending,active,started,before,writes=nil,false,0,nil,{}
local function capture(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local raw=table.concat(b);local f=assert(io.open(OUT..'/'..name..'.shr','wb'));f:write(raw);f:close();return raw
end
mem:install_read_tap(KEYDOWN,KEYDOWN,'key-start',function(ad,d,m)
 if pending and cpu.state.PB.value==KEYBANK and cpu.state.PC.value==ad+1 then
  before=capture(pending..'-before');started=manager.machine.time:as_double();writes={};active=true
 end
end)
local function screenWrite(ad,d,m)
 if not active then return end
 local w=writes[ad];if not w then w={};writes[ad]=w end
 w[#w+1]={manager.machine.time:as_double(),d&255}
end
mem:install_write_tap(@MM:SHR@,@MM:SHR+0x7cff@,'ui-writes',screenWrite)
local shadow=255
for _,at in ipairs({@MM:SHADOW_00@,@MM:SHADOW@}) do
 mem:install_write_tap(at,at,'ui-shadow-'..at,function(ad,d,m) shadow=d end)
end
mem:install_write_tap(@MM:WALL_COLUMNS@,@MM:SHR_SHADOW+0x7cff@,'ui-shadow-writes',function(ad,d,m)
 if (shadow&8)==0 then screenWrite(@MM:BANK_E1@|(ad&65535),d,m) end
end)
local function finishUpdate()
 if active then
  active=false;local elapsed=manager.machine.time:as_double()-started
  local final=capture(pending..'-after');local n,multi,wrong,exposed,changed=0,0,0,0,0
  for address,w in pairs(writes) do
   n=n+#w;if #w>1 then multi=multi+1 end
   local idx=address-@MM:SHR@+1;local old=before:byte(idx);local done=final:byte(idx);local bad,ex=false,false
   for i=1,#w-1 do if w[i][2]~=done then ex=true;if w[i][2]~=old then bad=true end end end
   if bad then wrong=wrong+1 end;if ex then exposed=exposed+1 end
  end
  for i=1,32000 do if before:byte(i)~=final:byte(i) then changed=changed+1 end end
  print(string.format('UPDATE %s %.6f %d %d %d %d %d',pending,elapsed,n,multi,wrong,exposed,changed));pending=nil
 end
end
mem:install_read_tap(GETKEY,GETKEY,'key-ready',function(ad,d,m)
 if cpu.state.PB.value==KEYBANK and cpu.state.PC.value==ad+1 then finishUpdate() end
end)
''').replace('OUT',json.dumps(str(out))).replace('KEYDOWN',str(s['keyDown'])).replace('KEYBANK',str(s['GetKey']>>16)).replace('GETKEY',str(s['GetKey']))
if a.all_actions:
 for symbol,label,action in [('MenuOpen','entry',"if pending=='open-menu' then before=capture(pending..'-before');started=manager.machine.time:as_double();writes={};active=true end"),('UiKeepView','return',"if pending=='close-menu' then finishUpdate() end")]:
  addr=s[symbol]
  lua+=f"mem:install_read_tap({addr},{addr},'{label}',function(ad,d,m) if cpu.state.PB.value=={addr>>16} and cpu.state.PC.value==ad+1 then {action} end end)\n"
if a.all_actions:
 lua+="CALLS['title-capture']=function() capture('title-menu') end\n"
 lua+="local entryShot=0; emu.add_machine_frame_notifier(function() if active and pending=='open-menu' then capture(string.format('entry-frame-%03d',entryShot));entryShot=entryShot+1 end end)\n"
 for symbol in ('BuildGray','BuildMap','CopyGray','CopyGrayDone','ConvertRange','ConvertHidden','DrawTitleCore','htDone','MenuFinish'):
  if symbol not in s:continue
  addr=s[symbol]
  lua+=f"mem:install_read_tap({addr},{addr},'phase-{symbol}',function(ad,d,m) if pending=='open-menu' and cpu.state.PB.value=={addr>>16} and cpu.state.PC.value==ad+1 then print(string.format('PHASE {symbol} %.6f',manager.machine.time:as_double())) end end)\n"
# Attribute action time to the resident routines without changing game code.
for symbol in ('ListPage','pageDone','PreviewCore','PictureDirect','RowSelectMove','pictureDone','previewWait','listItemPlain','listItem','ListCursorCore','listMoved','GrayRect','TitleGray','DrawTitleCore','htDone','EndUpdate'):
 if symbol not in s:continue
 addr=s[symbol]
 lua+=f"mem:install_read_tap({addr},{addr},'action-{symbol}',function(ad,d,m) if active and cpu.state.PB.value=={addr>>16} and cpu.state.PC.value==ad+1 then print(string.format('ACTION %s {symbol} %.6f',pending,manager.machine.time:as_double())) end end)\n"
if a.floor_recolors or a.all_actions:lua+='CALLS["visit-two"]=function() mem:write_u16(%d,3) end\n'%s['visitMask']
for name in cases:lua+='CALLS[%s]=function() if active then return false end;pending=%s end\n'%(json.dumps(name),json.dumps(name))
(out/'observe.lua').write_text(lua)
r=subprocess.run([sys.executable,'tools/ui_test.py','--name',a.name,'--hd','--debug','--seconds','180','--steps',';'.join(steps),'--lua',str(out/'observe.lua')]+(['--disk',str(a.disk)] if a.disk else []),cwd=ROOT,capture_output=True,text=True,timeout=600)
(out/'driver.log').write_text(r.stdout+r.stderr);log=(out/'mame.log').read_text();assert r.returncode==0,log[-2000:]
rows=[]
for n,t,w,m,b,e,c in re.findall(r'^UPDATE (\S+) (\S+) (\d+) (\d+) (\d+) (\d+) (\d+)$',log,re.M):rows.append(dict(case=n,seconds=float(t),frames_60hz=round(float(t)*60,3),writes=int(w),multiple=int(m),wrong=int(b),exposed=int(e),changed=int(c)))
assert {v['case'] for v in rows}==set(cases),set(cases)-{v['case'] for v in rows}
(out/'result.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows,indent=2))
if a.strict:
 rows=[v for v in rows if v['case'] not in ('open-menu','close-menu')]
 assert not any(v['wrong'] or v['exposed'] for v in rows), 'transient wrong pixels'
 assert all(v['writes']==v['changed'] for v in rows), 'unchanged or repeated screen stores'
