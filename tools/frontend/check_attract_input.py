"""Exercise real ADB mouse input and the slideshow-to-demo display handoff."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import memmap
from elf import read

parser = argparse.ArgumentParser()
parser.add_argument('--name', required=True)
parser.add_argument('--baseline', action='store_true', help='record the reported failures')
parser.add_argument('--disk', type=Path, help='private media with saved settings to exercise')
parser.add_argument('--mame', type=Path, help='emulator binary, including a J13-capable kit')
parser.add_argument('--j13', choices=('off', 'only', 'both'), default='off')
parser.add_argument('--detection-only', action='store_true', help='ignored slideshow keys must not enable J13 gameplay')
args = parser.parse_args()
out = ROOT / 'build/tests' / args.name
out.mkdir(parents=True, exist_ok=True)
_, symbols = read(ROOT / 'build/wolf.elf')
shutil.copy2(ROOT / 'build/wolf.elf', out / 'wolf.elf')
lua = memmap.fill(r'''
local phase, mouseReports, menus, demoFrames = '',0,0,0
local firstDemoImage=nil
local function tap(a,name,fn)
 mem:install_read_tap(a,a,name,function(ad,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then fn() end
 end)
end
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(at+i)) end;return table.concat(b)
end
local function dump(name)
 local f=assert(io.open(OUTPUT..'/'..name..'.shr','wb'));f:write(bytes(@MM:SHR@,32768));f:close()
end
local function realField(name)
 for _,p in pairs(manager.machine.ioport.ports) do
  for _,f in pairs(p.fields) do if f.name:find(name,1,true) then return f end end
 end
 error('missing input field '..name)
end
tap(FADE_IN,'fade-in',function() if mem:read_u16(ACTIVE)~=0 then phase='in' end end)
tap(FADE_OUT,'fade-out',function() if mem:read_u16(ACTIVE)~=0 then phase='out' end end)
tap(WAIT_INPUT,'hold',function() if mem:read_u16(ACTIVE)~=0 then phase='hold' end end)
tap(MOUSE,'mouse-report',function() mouseReports=mouseReports+1 end)
tap(MAIN_MENU,'main-menu',function() menus=menus+1 end)
tap(SCREEN_INIT,'screen-init',function()
 print(string.format('STATE_SCREEN_INIT %.6f viewKeep=%d palHold=%d',manager.machine.time:as_double(),mem:read_u16(VIEW_KEEP),mem:read_u16(PAL_HOLD)))
end)
tap(DEMO_STEP,'demo-step',function() demoFrames=demoFrames+1 end)
for _,p in ipairs({'in','hold','out'}) do
 CALLS['title-'..p]=function()
  return mem:read_u8(0x3e4)==1 and phase==p and mem:read_u16(ACTIVE)~=0
 end
end
local dx,dy=0,0
CALLS['mouse-move']=function()
 dx=(dx+24)%256;dy=(dy+24)%256
 realField('Mouse X'):set_value(dx);realField('Mouse Y'):set_value(dy)
 print('MOUSE_MOVED '..manager.machine.time:as_double())
end
CALLS['mouse-no-menu']=function()
 assert(mouseReports>0,'mouse fixture produced no ADB report')
 assert(menus==0,'mouse motion opened a menu')
 print('MOUSE_MOTION_IGNORED '..mouseReports)
end
CALLS['reset-menus']=function() menus=0 end
CALLS['keyboard-mode']=function()
 if J13 then
  assert(mem:read_u16(J13_MODE)==1,'titles must use the menu compatibility reader')
  local modes=manager.machine.devices[':adbmicro'].spaces['program']:read_u8(3)
  assert((modes&1)==RAW_ADB,'keyboard firmware mode does not match keyboard presence')
  print('TITLE_KEYBOARD_MODE '..modes)
 end
end
CALLS['title-menu']=function()
 assert(mem:read_u8(0x3e4)==2,'Escape did not open the title menu')
 if J13 then assert(mem:read_u16(J13_ENABLED)==1,'J13 menu use did not enable gameplay') end
 print('TITLE_ESCAPE_MENU '..manager.machine.time:as_double())
end
CALLS['not-detected']=function()
 assert(menus==0,'ignored attract input opened a menu')
 assert(mem:read_u16(J13_ENABLED)==0,'ignored attract input enabled J13 gameplay')
 print('J13_NOT_DETECTED '..mem:read_u8(0x3e4))
end
CALLS['menu-mouse']=function()
 local before=mem:read_u16(0x116e)
 CALLS['menu-mouse-changed']=function()
  assert(mem:read_u8(0x3e4)==2 and mem:read_u16(0x116e)==before,'mouse moved the menu selection')
  print('MENU_MOUSE_NAVIGATION_IGNORED')
 end
 CALLS['mouse-move']()
end
CALLS['demo-picture']=function()
 local lit=0
 for y=0,199 do
  local palette=@MM:SHR_PAL@+32*(mem:read_u8(@MM:SHR_SCB@+y)&15)
  for x=0,159 do
   local b=mem:read_u8(@MM:SHR@+y*160+x)
   if mem:read_u16(palette+2*(b>>4))~=0 then lit=lit+1 end
   if mem:read_u16(palette+2*(b&15))~=0 then lit=lit+1 end
  end
 end
 print(string.format('DEMO_PICTURE frames=%d lit=%d viewKeep=%d palHold=%d',demoFrames,lit,mem:read_u16(VIEW_KEEP),mem:read_u16(PAL_HOLD)))
 dump('demo')
 if BASELINE then assert(lit==0,'baseline did not reproduce black demo')
 else
  assert(lit>10000 and demoFrames>1,'demo is not visibly playing')
  local current=bytes(@MM:SHR@,32000)
  if firstDemoImage then assert(current~=firstDemoImage,'demo picture did not advance') else firstDemoImage=current end
 end
end
CALLS['done']=function() print('ATTRACT_INPUT_CHECK_DONE') end
''')
for key, label in {'FADE_IN':'FadeIn','FADE_OUT':'FadeOut','WAIT_INPUT':'WaitInput','ACTIVE':'attractActive','MOUSE':'pollMouse','MAIN_MENU':'MainMenu','SCREEN_INIT':'screenInit','VIEW_KEEP':'viewKeep','PAL_HOLD':'palHold','DEMO_STEP':'PlayDemoStep'}.items():
    lua = re.sub(r'\b'+key+r'\b', str(symbols[label]), lua)
lua=lua.replace('OUTPUT',json.dumps(str(out))).replace('BASELINE','true' if args.baseline else 'false')
for key, value in {'J13_MODE':symbols['j13Mode'], 'J13_ENABLED':symbols['j13Enabled'],
                   'RAW_ADB':int(args.j13!='only'), 'J13':'true' if args.j13!='off' else 'false'}.items():
    lua=re.sub(r'\b'+key+r'\b',str(value),lua)
(out/'observe.lua').write_text(lua)
if args.detection_only:
    assert args.j13!='off', '--detection-only requires a J13 profile'
    steps=[]
    for screen in (14,1,12,6,13):
        steps += ['wait='+str(screen),'sleep=0.3','key=Return','key=Space','key=W',
                  'key=Mouse Button 0','key=Mouse Button 1','call=mouse-move','sleep=0.2','call=not-detected']
    steps += ['key=Esc','wait=2','sleep=0.3','call=title-menu','call=done','end=']
elif args.baseline:
    steps=['wait=1','sleep=1','call=mouse-move','wait=2','sleep=1','snap=mouse-opened-menu','key=Esc','wait=1',
           'wait=13','sleep=2','call=demo-picture','snap=black-demo','call=done','end=']
else:
    steps=['call=title-in','call=keyboard-mode','call=mouse-move','sleep=0.15','call=mouse-no-menu',
           'key=Esc','wait=2','sleep=0.3','call=title-menu','snap=fade-in-menu','key=Esc','wait=1','call=reset-menus',
           'call=title-hold','key=Return','key=Space','key=W','key=Mouse Button 0','key=Mouse Button 1','call=mouse-move','sleep=0.15','call=mouse-no-menu',
           'key=Esc','wait=2','sleep=1','call=title-menu','call=menu-mouse','key=Mouse Button 0','key=Mouse Button 1','sleep=0.5','call=menu-mouse-changed',
           'key=Esc','wait=1','call=reset-menus',
           'call=title-out','call=mouse-move','sleep=0.15','call=mouse-no-menu',
           'key=Esc','wait=2','sleep=0.3','call=title-menu','snap=fade-out-menu','key=Esc','wait=1','call=reset-menus',
           'wait=12','sleep=1','call=keyboard-mode','key=Esc','wait=2','sleep=0.3','call=title-menu','key=Esc','wait=12','call=reset-menus',
           'wait=6','sleep=1','call=keyboard-mode','key=Esc','wait=2','sleep=0.3','call=title-menu','key=Esc','wait=6','call=reset-menus',
           'wait=13','sleep=2','call=demo-picture','snap=demo-first',
           'call=mouse-move','sleep=2','call=mouse-no-menu','call=demo-picture','snap=demo-moving',
           'key=Esc','wait=2','sleep=1','snap=demo-menu','key=Esc','wait=1',
           'wait=13','sleep=2','call=demo-picture','snap=demo-second-start','call=done','end=']
if args.j13!='off':
    steps=[('key=J13 '+('Escape' if x[4:]=='Esc' else x[4:]))
           if x.startswith('key=') and not x.startswith('key=Mouse ') else x for x in steps]
command=[sys.executable,'tools/ui_test.py','--name',args.name,'--hd','--debug','--audio','--seconds','260',
         '--j13',args.j13,'--lua',str(out/'observe.lua'),'--steps',';'.join(steps)]
if args.mame: command += ['--mame',str(args.mame)]
if args.disk: command += ['--disk',str(args.disk)]
result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
(out/'driver.log').write_text(result.stdout+result.stderr)
log=(out/'mame.log').read_text()
assert result.returncode==0 and '[LUA ERROR]' not in log and 'ATTRACT_INPUT_CHECK_DONE' in log,log[-4000:]
pictures=[dict(frames=int(f),lit=int(l),view_keep=int(v),pal_hold=int(p))
          for f,l,v,p in re.findall(r'^DEMO_PICTURE frames=(\d+) lit=(\d+) viewKeep=(\d+) palHold=(\d+)$',log,re.M)]
report={'baseline_failures_reproduced':args.baseline,'pictures':pictures,
        'detection_only':args.detection_only,'ignored_pages_checked':log.count('J13_NOT_DETECTED'),
        'j13':args.j13,'title_escape_checks':log.count('TITLE_ESCAPE_MENU'),
        'mouse_motion_checks':len(re.findall(r'^MOUSE_MOTION_IGNORED',log,re.M)),
        'menu_mouse_navigation_ignored':'MENU_MOUSE_NAVIGATION_IGNORED' in log,
        'media_sha256':hashlib.sha256((out/'wolf-hd.po').read_bytes()).hexdigest(),
        'elf_sha256':hashlib.sha256((out/'wolf.elf').read_bytes()).hexdigest()}
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
