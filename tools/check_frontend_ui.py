"""Native UI gallery, real key navigation, boot-sign and resident-menu checks."""
import memmap
import argparse,json,re,subprocess,sys
from pathlib import Path
from elf import read
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--name',default='frontend-ui');args=ap.parse_args()
out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
_,sym=read(ROOT/'build/wolf.elf')
shots=['main-title','floors','difficulty','options','display','controls','keys','keys-last','slots','scores','game','main-game','quit','thanks']
lua=memmap.fill('''CALLS={}
local function now() return manager.machine.time:as_double() end
local function capture(name)
 local f=assert(io.open(OUT.."/"..name..".shr","wb"));local b={}
 for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 f:write(table.concat(b));f:close();print("CAPTURE "..name.." "..now())
end
local firstFull=false
local busyAt=nil
local signs={}
mem:install_write_tap(BOOT,BOOT,"boot-full",function(a,d,m)
 if d==1 and not firstFull then firstFull=true;capture("boot-full") end
end)
emu.add_machine_frame_notifier(function()
 if mem:read_u16(BUSY)==1 then
  if not busyAt then busyAt=now()+0.15 end
  local kind=mem:read_u16(KIND)
  if now()>=busyAt and not signs[kind] then
   signs[kind]=true;capture("sign-"..kind)
  end
 else busyAt=nil end
end)
''').replace('OUT',json.dumps(str(out))).replace('BOOT',str(sym['bootComplete'])).replace('BUSY',str(sym['busyShown'])).replace('KIND',str(sym['busyKind']))
for n in shots:lua+='CALLS[%s]=function() capture(%s) end\n'%(json.dumps(n),json.dumps(n))
for n in ['MenuBoot','UiQuitRom','MenuOpen','MenuDimOpen','MenuPrepare','ListRun','MenuFinish','MenuDimClose','UiLeave','BusyShow','LoadLump']:
 a=sym[n];lua+='mem:install_read_tap(%d,%d,%s,function(a,d,m) if cpu.state.PC.value==a+1 then print("ENTER %s "..now()) end end)\n'%(a,a,json.dumps(n),n)
(out/'observe.lua').write_text(lua)
steps='wait=1;sleep=1;key=Return;wait=2;sleep=1;call=main-title;key=Return;wait=15;sleep=2;call=floors;key=Return;wait=3;sleep=2;call=difficulty;key=Esc;wait=15;sleep=1;key=Esc;wait=2;sleep=1;key=Down;key=Down;key=Return;wait=7;sleep=1;call=options;key=Return;wait=17;sleep=2;call=display;key=Esc;wait=7;sleep=1;key=Down;key=Return;wait=18;sleep=1;call=controls;key=Down;key=Down;key=Return;wait=9;sleep=2;call=keys;key=Up;sleep=2;call=keys-last;key=Esc;wait=18;sleep=1;key=Esc;wait=7;sleep=1;key=Esc;wait=2;sleep=1;key=Down;key=Return;wait=6;sleep=1;call=scores;key=Esc;wait=2;sleep=1;key=Up;key=Up;key=Return;wait=4;sleep=1;key=Down;key=Up;call=slots;key=Esc;wait=2;sleep=1;key=Up;key=Return;wait=15;sleep=1;key=Return;wait=3;sleep=1;key=Return;wait=0;sleep=2;call=game;key=Esc;wait=2;sleep=1;call=main-game;key=Esc;wait=0;sleep=1;key=Esc;wait=2;sleep=1;key=q;key=Return;sleep=1;call=quit;key=Y;wait=16;sleep=1;call=thanks;key=Return;sleep=35;end='
subprocess.run([sys.executable,str(ROOT/'tools/ui_test.py'),'--name',args.name,'--hd','--debug','--seconds','350','--lua',str(out/'observe.lua'),'--steps',steps],cwd=ROOT,check=True)
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
from render import shr_screen,Face,Screen,blank
from imaging import png
for p in out.glob('*.shr'):
 screen=shr_screen(p.read_bytes());png(p.with_suffix('.png'),screen.rows);png(p.with_name(p.stem+'@2x.png'),screen.rows,2)
 (p.with_suffix('.palettes.json')).write_text(json.dumps(screen.metadata(),indent=2)+'\n')
# Compare every opaque font pixel against the approved renderer, including selected and disabled states.
f=Face('BlackOpsOne-Regular.ttf',ROOT/'build/frontend/native');expected=Screen(blank(320,200,0x333))
for i,text in enumerate(['New Game','Load Game','Save Game','Options','High Scores','End Game','Quit','Back to Demo']):
 f.draw(expected,text,99,48+18*i,'selected' if i==0 else 'dim' if i in (2,5) else 'normal')
actual=shr_screen((out/'main-title.shr').read_bytes()).rows
errors=sum(c!=actual[y][x] for y,row in enumerate(expected.rows) for x,c in enumerate(row) if c!=0x333)
assert errors==0,('approved font pixel mismatch',errors)
log=(out/'mame.log').read_text();events=[(m[1],float(m[2])) for m in re.finditer(r'ENTER (\w+) ([\d.]+)',log)]
opens=[];closes=[]
for i,(name,t) in enumerate(events):
 if name=='MenuOpen':
  seq=[]
  for n,at in events[i+1:]:
   seq.append(n)
   if n=='MenuFinish':opens.append(at-t);break
  assert 'BusyShow' not in seq and 'LoadLump' not in seq
 if name=='MenuDimClose':
  for n,at in events[i+1:]:
   if n=='UiLeave':closes.append(at-t);break
   if n=='MenuOpen':break
assert 'ENTER UiQuitRom ' in log, 'quit did not reach firmware reset'
assert log.count('ENTER MenuBoot ')==2, 'quit key did not reboot into the game'
first_title=float(re.search(r'CAPTURE main-title ([\d.]+)',log)[1])
assert all(t>first_title for n,t in events if n=='BusyShow'), 'a sign was shown during initial loading'
report=dict(rebooted=True,boot_loading_signs=0,screens=len(list(out.glob('*.shr'))),approved_font_differences=errors,menu_open_seconds=opens,restore_to_leave_seconds=closes)
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
html=['<!doctype html><meta charset="utf-8"><title>Wolf3D native UI</title><style>body{background:#181818;color:#ddd;font:16px system-ui}img{image-rendering:pixelated}figure{display:inline-block;margin:12px}figcaption{margin:8px 0}</style>']
for p in sorted(out.glob('*@2x.png')):html.append('<figure><figcaption>'+p.stem+'</figcaption><img src="'+p.name+'" width="640" height="400"></figure>')
(out/'index.html').write_text('\n'.join(html)+'\n');print(json.dumps(report,indent=2))
