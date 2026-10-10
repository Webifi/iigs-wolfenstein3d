"""Native ROM01 J13/ADB checks using physical emulator input fields.

Requires a MAME build with the J13 matrix model; --mame selects that binary.
No keyboard register, event, or game-state writes stand in for physical keys.
"""
import memmap
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path
from elf import read
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--mame',required=True,type=Path)
p.add_argument('--name',required=True)
p.add_argument('--j13',choices=('only','both'),default='both')
p.add_argument('--view',choices=(214,320),type=int,default=214)
p.add_argument('--case',choices=('keys','lifecycle','off-save','on-save','reload-off','reload-on','rom03'),default='keys')
p.add_argument('--disk',type=Path)
a=p.parse_args();out=ROOT/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
_,S=read(ROOT/'build/wolf.elf');shutil.copy2(ROOT/'build/wolf.elf',out/'wolf.elf')
lua=memmap.fill(r'''
local events={}
local completedFrames=0
local resizeFrom,resizeFrame,resizeTime=nil,nil,nil
local gameReadyFrame=nil
local confirmReady=false
mem:install_read_tap(S.confirmKey,S.confirmKey,'input-test-confirm',function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PC.value==a+1 then confirmReady=true end
end)
mem:install_write_tap(0x3f0,0x3f0,'input-test-frames',function(_,d)
 if d==2 then completedFrames=completedFrames+1 end
end)
local function field(name)
 for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do if f.name==name then return f end end end
 error('missing input field '..name)
end
local function check(ok,why)
 if not ok then
  print('FAIL_STATE W='..mem:read_u8(S.keyHeld+13)..' Left='..mem:read_u8(S.keyHeld+59)..' Shift='..mem:read_u8(S.keyHeld+56)..' Control='..mem:read_u8(S.keyHeld+54)..' cache='..mem:read_u16(S.physicalMods)..' mods='..mem:read_u16(S.j13Mods)..' valid='..mem:read_u16(S.physicalValid)..' phase='..mem:read_u16(S.j13State)..' owner='..mem:read_u16(S.j13Owner)..' row='..mem:read_u16(S.rowAddress)..' P3='..manager.machine.devices[':adbmicro'].spaces['program']:read_u8(0xe8))
  print('FAIL_KEYS '..mem:read_u16(S.j13Keys)..' '..mem:read_u16(S.j13Keys+2)..' '..mem:read_u16(S.j13Keys+4)..' count='..mem:read_u16(S.knownCount))
  for i=math.max(1,#events-20),#events do local e=events[i];print('FAIL_EVENT '..e[1]..' '..e[2]..' '..e[3]) end
  manager.machine:exit();error(why)
 end
end
local function value(n) return mem:read_u16(S[n]) end
local function held(k) return mem:read_u8(S.keyHeld+k) end
local function report(tag)
 print('INPUT_STATE '..tag..' enabled='..value('j13Enabled')..' manual='..value('j13Manual')..' mode='..value('j13Mode')..' timer='..value('j13Timer')..' owner='..value('j13Owner')..' state='..value('j13State'))
end
local function capture(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(OUTPUT..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
end
mem:install_write_tap(S.inputHead+1,S.inputHead+1,'input-events',function(_,d)
 if manager.machine:side_effects_disabled() then return end
 local h=mem:read_u16(S.inputHead)
 local slot=(h-8)&1023
 -- The low byte has been stored; the high byte in memory is still the old value.
 h=(mem:read_u8(S.inputHead)|(d<<8));slot=(h-8)&1023
 local p=S.inputRing+slot
 local typ=mem:read_u16(p+2);local code=mem:read_u16(p+4)
 if typ~=1 then events[#events+1]={typ,code,manager.machine.time:as_double()} end
end)
local function stage() events={} end
CALLS.defaults=function()
 check(value('j13Available')==1 and value('j13Enabled')==0,'default J13 must be off')
 check(value('j13Matrix')==1,'MCU fingerprint failed')
 check(value('mouseSensitivity')==4,'new mouse default is step 4')
 check(value('j13AdbPresent')==ADB,'ADB presence mismatch');report('defaults')
end
CALLS.auto=function() check(value('j13Enabled')==1 and value('j13Manual')==0,'menu must auto-enable');report('auto') end
CALLS.game=function()
 -- The page latch changes before a cold menu-return finishes restoring art.
 -- Exercise input only after the renderer has completed the resumed view.
 gameReadyFrame=gameReadyFrame or completedFrames+2
 if completedFrames<gameReadyFrame then return false end
 gameReadyFrame=nil
 check(value('j13Mode')==2,'game capture not installed');report('game')
end
CALLS.view=function() check(value('viewWidth')==VIEW//2,'requested view was not applied') end
CALLS.confirmarm=function() confirmReady=false end
CALLS.confirmwait=function() return confirmReady end
CALLS.resizebegin=function()
 resizeFrom=value('viewWidth');resizeFrame=completedFrames
 resizeTime=manager.machine.time:as_double()
end
CALLS.resizewait=function()
 -- Registered resizing loads view assets. Wait for the actual new picture,
 -- rather than send the next key while the disk transition resets input.
 if value('viewWidth')==resizeFrom or completedFrames<resizeFrame+2 then return false end
 print(string.format('RESIZE_READY %d %d %.6f',resizeFrom,value('viewWidth'),manager.machine.time:as_double()-resizeTime))
end
CALLS.clean=function()
 check(value('j13Timeouts')==0,'MCU transition timed out')
 check(value('inputDropped')==0,'input ring overflow')
 check(value('j13Matrix')==1,'row reads became disabled')
end
for n,f in pairs({w='J13 W',left='J13 Left',space='J13 Space',shift='J13 Shift',control='J13 Control',adbw='w  W'}) do
 local raw=f
 CALLS[n..'-down']=function() field(raw):set_value(1) end
 CALLS[n..'-up']=function() field(raw):set_value(0) end
end
CALLS.w=function() check(held(13)==2 and held(59)==0,'forward hold or partial turn release');CALLS.clean() end
CALLS.both=function() check(held(13)==2 and held(59)==2,'overlap missing');CALLS.clean() end
CALLS.three=function() check(held(13)==2 and held(59)==2 and held(49)==2,'three-key overlap missing');CALLS.clean() end
CALLS.partial=function() check(held(13)==2 and held(59)==0 and held(49)==2,'three-key partial release missing');CALLS.clean() end
CALLS.allup=function() check(held(13)==0 and held(59)==0 and held(49)==0 and held(54)==0 and held(56)==0,'stuck key');CALLS.clean() end
CALLS.stage=stage
CALLS.tap=function()
 local down,up=0,0
 for _,e in ipairs(events) do if e[1]==2 and e[2]==59 then down=down+1 elseif e[1]==2 and e[2]==187 then up=up+1 end end
 check(down==1 and up==1,'turn tap must produce one down/up, got '..down..'/'..up)
 CALLS.w();print('TAP_PASS '..down..' '..up)
end
CALLS.modtap=function()
 for _,code in ipairs({54,56}) do
  local downs,ups=0,0
  for _,e in ipairs(events) do if e[1]==2 and e[2]==code then downs=downs+1 elseif e[1]==2 and e[2]==code+128 then ups=ups+1 end end
  if downs>0 or ups>0 then check(downs==1 and ups==1,'modifier tap incomplete');print('MODIFIER_TAP_PASS '..code);return end
 end
 check(false,'modifier tap missing')
end
CALLS.shift=function() check(held(56)==2,'Shift not captured') end
CALLS.shiftup=function() check(held(56)==0,'Shift stuck');CALLS.w() end
CALLS.control=function() check(held(54)==2,'Control not captured') end
CALLS.controlup=function() check(held(54)==0,'Control stuck');CALLS.w() end
CALLS.sources=function() check(held(13)==3,'two keyboard ownership not merged') end
CALLS.adbheld=function() check(held(13)==1,'J13 release cleared ADB hold') end
CALLS.timer=function() check(value('musicActive')==0 and value('j13Timer')==1,'muted input timer not running');report('muted') end
CALLS.off=function()
 check(value('j13Enabled')==0 and value('j13Manual')==2,'explicit Off not retained');report('off')
 if mem:read_u8(0x3e4)==18 then capture('controls-off') end
end
CALLS.on=function()
 check(value('j13Enabled')==1 and value('j13Manual')==2,'explicit On not retained');report('on')
 if mem:read_u8(0x3e4)==18 then capture('controls-on') end
end
CALLS.offgame=function()
 check(value('j13Mode')==0 and value('j13Timer')==0,'off still captures gameplay')
 check(mem:read_u8(S.J13AdbSite)==0xaf,'off left private DATA handler installed')
 check(mem:read_u8(S.fastAlarmHandled)==0xc2,'off left DOC capture installed')
 check(held(13)==0,'off accepted J13 movement');report('off-game')
end
CALLS.rom03=function()
 check(value('j13Available')==0 and value('j13Enabled')==0,'ROM03 offered native J13')
 check(mem:read_u8(S.optActive+6)==0,'ROM03 J13 row selectable');report('rom03')
 capture('controls-rom03')
end
CALLS.done=function() report('DONE');print('J13_NATIVE_PASS') end
local mouseReports=0
mem:install_write_tap(S.inputHead+1,S.inputHead+1,'mouse-delivery',function(_,d)
 local head=mem:read_u8(S.inputHead)|(d<<8)
 if mem:read_u16(S.inputRing+((head-8)&1023)+2)==1 then mouseReports=mouseReports+1 end
end)
local mouseBefore=0
CALLS.mouse=function()
 mouseBefore=mouseReports;field('Mouse X'):set_value(12)
end
CALLS.mouseok=function() check(mouseReports>mouseBefore,'private MCU reads blocked ADB mouse');CALLS.clean();print('MOUSE_WITH_J13_PASS') end
CALLS.menuquiet=function()
 check(value('j13Mode')==1 and value('j13Owner')==0 and value('j13Timer')==0,'menu retained gameplay controller ownership')
 check(value('j13SendTimer')==0,'menu retained parameter alarm')
 CALLS.clean();report('menu-quiet')
end
CALLS.benchmarkquiet=function()
 check(value('j13Mode')==0 and value('j13Owner')==0 and value('j13Timer')==0,'benchmark retained gameplay capture')
 check(value('j13SendTimer')==0,'benchmark retained parameter alarm')
 CALLS.clean();report('benchmark-quiet')
end
CALLS.bindwaiting=function() check(value('menuBindMouse')==1,'mouse binding did not open') end
CALLS.bound=function()
 check(value('menuBindMouse')==0,'binding capture left enabled')
 check(mem:read_u16(S.boundKeys)==126 and mem:read_u16(S.boundBits)==1,'mouse button binding was ignored')
 print('MOUSE_BINDING_PASS')
end
CALLS.bindcancelled=function() check(value('menuBindMouse')==0,'cancel left mouse binding enabled') end
local mcu=manager.machine.devices[':adbmicro'].spaces['program']
local firmware=nil
local quitting=false
local restoredModes,restoredRepeat=false,false
local stopped=false
local function tap(addr,name,fn)
 mem:install_read_tap(addr,addr,name,function(ad)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then fn() end
 end)
end
tap(S.pollMouse,'binding-mouse-report',function()
 if value('menuBindMouse')==1 then local p=S.inputRing+cpu.state.X.value;print('BIND_MOUSE '..mem:read_u16(p+4)..' '..mem:read_u16(p+6)) end
end)
tap(S.ctlReserved,'binding-candidate',function() print('BIND_CANDIDATE '..cpu.state.A.value) end)
tap(S.J13Init,'firmware-before',function() firmware={mcu:read_u8(3),mcu:read_u8(12),mcu:read_u8(0),mcu:read_u8(1)} end)
tap(S.J13Stop,'firmware-restore',function() quitting=true end)
mcu:install_write_tap(1,3,'firmware-restored',function(ad,data)
 if not quitting or not firmware then return end
 if ad==1 and data==firmware[4] then restoredRepeat=true end
 if ad==3 and data==firmware[1] then restoredModes=true end
end)
tap(S.UiQuitRom+4,'quit-stop-return',function()
 check(value('j13Owner')==0 and value('j13Timer')==0 and value('j13Mode')==0,'quit left input capture running')
 check(value('j13SendTimer')==0,'quit retained parameter alarm')
 stopped=true
end)
emu.register_frame_done(function()
 if stopped and restoredModes and restoredRepeat then
  check(mcu:read_u8(12)==firmware[2] and mcu:read_u8(0)==firmware[3],'quit changed keyboard configuration')
  print('FIRMWARE_RESTORE_PASS');print('J13_NATIVE_PASS');manager.machine:exit()
 end
end)
''')
names=set(re.findall(r"value\('([^']+)'\)",lua))|set(re.findall(r'\bS\.(\w+)',lua))
lua='local OUTPUT='+json.dumps(str(out))+'\nlocal S={'+','.join(n+'='+str(S[n]) for n in sorted(names))+'}\n'+lua.replace('==ADB','=='+str(int(a.j13=='both'))).replace('VIEW',str(a.view))
(out/'observe.lua').write_text(lua)
# Menu movement uses the real keyboard as well.
j='J13 '
start=['key='+j+'Return','wait=15','sleep=0.3','key='+j+'Return','wait=3','sleep=0.3','key='+j+'Return','wait=0','sleep=1']
if len(json.loads((ROOT/'build/gen/campaign.json').read_text())['episodes']) > 1:
 start[1:1]=['wait=19','sleep=0.3','key='+j+'Return']
options=['key=Down','key=Down','key=Return','wait=7','sleep=0.3']
controls=['key=Down','key=Return','wait=18','sleep=0.3']
steps=['wait=1','sleep=1']
if a.case=='lifecycle':
 steps+=['call=defaults','key=J13 Escape','wait=2','sleep=0.3','call=auto']+start+['call=game','call=w-down','sleep=0.4','call=left-down','sleep=0.4','call=mouse','sleep=0.6','call=mouseok','key=F6','wait=18','sleep=0.3','call=w-up','call=left-up','sleep=0.3','call=menuquiet']
 # Mouse buttons are accepted only by the explicit key-binding prompt.
 steps+=['key=Down','key=Down','key=Down','key=Return','wait=9','sleep=0.3','key=Return','sleep=0.3','call=bindwaiting','key=Mouse Button 0','sleep=0.3','call=bindwaiting','key=Mouse Button 1','sleep=0.3','call=bound','key=Return','key=Esc','call=bindcancelled','key=End','key=Return','key=Esc','wait=18','key=Esc','wait=2','key=Esc','wait=0','sleep=0.4','call=game','call=allup']
 steps+=['key=Equals','sleep=0.7','call=game','key=Minus','sleep=0.7','call=game']
 # Start and abort the benchmark through its real confirmation dialog.
 steps+=['key=Esc','wait=2','sleep=0.3','key=Home','key=Down']+options+['key=Down','key=Down','key=Return','sleep=0.3','key=Y','wait=10','sleep=0.3','call=benchmarkquiet','key=J13 Escape','wait=7','sleep=0.3','call=menuquiet','key=Esc','wait=2','key=Esc','wait=0','sleep=0.4','call=game']
 steps+=['call=confirmarm','key=F10','call=confirmwait','key=Y','wait=16','sleep=0.3','key=Return','sleep=10','end=']
elif a.case=='keys':
 steps+=['call=defaults','key='+j+'Escape','wait=2','sleep=0.3','call=auto']+start
 if a.view==320:steps+=['key=Equals','sleep=0.8','key=Equals','sleep=0.8']
 steps+=['call=game','call=view','call=w-down','sleep=4','call=w']
 for duration in (0.05,0.1,0.2):
  steps+=['call=stage',f'hold=J13 Left,{duration}','sleep=0.4','call=tap']
 steps+=['call=left-down','sleep=1.5','call=both','call=space-down','sleep=0.4','call=three','call=left-up','sleep=0.4','call=partial','call=space-up','sleep=0.4','call=w']
 for mod in ('shift','control'):
  steps += ['call=stage','hold=J13 '+mod.capitalize()+',0.1','sleep=0.4','call=modtap','call='+mod+'-down','sleep=0.4','call='+mod,'call='+mod+'-up','sleep=0.4','call='+mod+'up']
 if a.j13=='both':
  steps+=['call=adbw-down','sleep=0.3','call=sources','call=w-up','sleep=0.3','call=adbheld','call=w-down','sleep=0.3','call=sources','call=adbw-up','sleep=0.3','call=w']
 steps+=['call=w-up','sleep=0.4','call=allup','key=J13 Escape','wait=2','sleep=0.3','key=Down']+options
 # Display & Sound / Music: mute with real menu input, then resume.
 steps+=['key=Return','wait=17','sleep=0.3','key=Down']+['key=Left']*15+['key=Esc','wait=7','key=Esc','wait=2','key=Esc','wait=0','sleep=1','call=timer','call=w-down','sleep=1','call=stage','hold=J13 Left,0.1','sleep=0.4','call=tap','call=w-up','sleep=0.4','call=allup','key=J13 Escape','wait=2','sleep=0.3','call=clean','snap=menu']
elif a.case in ('off-save','on-save'):
 steps+=['call=defaults','key=J13 Escape','wait=2','sleep=0.3','call=auto']+options+controls+['key=Down','key=Down','key=Return','sleep=0.2','call=off']
 if a.case=='on-save':steps+=['key=Return','sleep=0.2','call=on']
 steps+=['snap=controls','key=Esc','wait=7','sleep=0.3','key=Down','key=Down','key=Return','sleep=1','key=Esc','wait=2','sleep=0.3']
 if a.case=='off-save':
  steps+=['key=Up','key=Up']+start+['hold=J13 W,0.3','call=offgame','key=J13 Escape','wait=2','sleep=0.3','call=off']
elif a.case in ('reload-off','reload-on'):
 expected=a.case.split('-')[1]
 steps+=['call='+expected,'key=J13 Escape','wait=2','sleep=0.3','call='+expected]
else:
 steps+=['key=Esc','wait=2','sleep=0.3']+options+controls+['call=rom03','snap=controls-rom03']
if a.case!='lifecycle':steps+=['call=done','end=']
steps=[part for step in steps for part in
       (['call=resizebegin',step,'call=resizewait'] if step in ('key=Equals','key=Minus') else [step])]
if a.j13=='only' and a.case!='rom03':
 steps=[('key=J13 '+('Escape' if x[4:]=='Esc' else x[4:])) if x.startswith('key=') and not x.startswith('key=J13 ') else x for x in steps]
if a.case=='keys' and a.view==320:
 # Release events may be queued just after the frame's input frontier.
 # Allow the full-width painter to finish before checking consumer state;
 # physical tap lengths remain exactly 50/100/200 ms.
 steps=['sleep=0.8' if x in ('sleep=0.3','sleep=0.4') else x for x in steps]
cmd=[sys.executable,'tools/ui_test.py','--name',a.name,'--mame',str(a.mame),'--j13',a.j13,'--hd','--debug','--seconds','150','--lua',str(out/'observe.lua'),'--steps',';'.join(steps)]
if a.case=='rom03':cmd+=['--machine','apple2gs']
if a.disk:cmd+=['--disk',str(a.disk)]
r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=240)
(out/'driver.log').write_text(r.stdout+r.stderr)
log=(out/'mame.log').read_text() if (out/'mame.log').exists() else r.stdout+r.stderr
assert r.returncode==0 and 'J13_NATIVE_PASS' in log and '[LUA ERROR]' not in log,log[-5000:]
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
from render import shr_screen
from imaging import png
for shot in out.glob('*.shr'):png(shot.with_name(shot.stem+'@2x.png'),shr_screen(shot.read_bytes()).rows,2)
result=dict(case=a.case,j13=a.j13,view=a.view,passed=True,elf_sha256=hashlib.sha256((out/'wolf.elf').read_bytes()).hexdigest(),mame_sha256=hashlib.sha256(a.mame.read_bytes()).hexdigest(),tap_checks=log.count('TAP_PASS'),states=re.findall(r'^INPUT_STATE (.*)$',log,re.M),firmware_restored=('FIRMWARE_RESTORE_PASS' in log) if a.case=='lifecycle' else None,mouse_during_j13=('MOUSE_WITH_J13_PASS' in log) if a.case=='lifecycle' else None,mouse_binding=('MOUSE_BINDING_PASS' in log) if a.case=='lifecycle' else None)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
