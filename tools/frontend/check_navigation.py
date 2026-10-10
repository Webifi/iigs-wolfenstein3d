"""Native real-key navigation, all resident previews, and injected ADB motion packets."""
import json,sys,subprocess,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import memmap
from elf import read
_,s=read(ROOT/'build/wolf.elf');name=sys.argv[1] if len(sys.argv)>1 else 'approved-ui-navigation'
out=ROOT/'build/tests'/name;out.mkdir(parents=True,exist_ok=True)
checks=[];steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=2'];callbacks=[]
def check(label,page,cur,shot=False):
    checks.append(label);steps.append('call='+label)
    callbacks.append(f'CALLS[{json.dumps(label)}]=function() if not ready then return false end;assert(mem:read_u8(0x3e4)=={page},"page {label}");assert(mem:read_u16(0x116e)=={cur},"cursor {label}: "..mem:read_u16(0x116e));print("NAV {label}");'+(f'capture("{label}");' if shot else '')+'end')
def key(k):steps.extend(['key='+k,'sleep=0.2'])
check('main',2,0,True);key('q');check('letter-quit',2,6);key('Home');check('home-main',2,0);key('Page Down');check('page-down-main',2,7);key('Page Up');check('page-up-main',2,0);key('End');check('end-main',2,7);key('Home')
steps+=['call=visits'];key('Return');steps+=['wait=15'];check('floor-01',15,0,True)
for i in range(1,10):key('Down');check(f'floor-{i+1:02d}',15,i,True)
key('Home');check('floor-home',15,0);key('Right');check('floor-column-right',15,4);key('Left');check('floor-column-left',15,0);key('End');check('floor-end',15,9);key('Home');key('Return');steps+=['wait=3'];key('Home');check('difficulty-1',3,0,True)
for i in range(1,4):key('Down');check(f'difficulty-{i+1}',3,i,True)
key('F4');steps+=['wait=17'];check('nested-F4',17,0,True)
key('F5');steps+=['wait=17'];check('nested-F5',17,2)
for _ in range(3):key('Left')
check('view-0',17,2,True)
for i in range(1,4):key('Right');check(f'view-{i}',17,2,True)
key('F6');steps+=['wait=18'];check('nested-F6',18,0)
key('F3');steps+=['wait=4'];check('nested-F3',4,0)
key('Esc');steps+=['wait=2'];key('Home');check('mouse-before',2,0)
steps+=['call=mouse-down','sleep=0.3'];check('mouse-down-ignored',2,0);steps+=['sleep=1'];check('mouse-no-repeat',2,0)
steps+=['call=mouse-up','sleep=0.3'];check('mouse-up-ignored',2,0)
key('Return');steps+=['wait=15'];key('Return');steps+=['wait=3'];key('Return');steps+=['wait=0','sleep=2'];key('F4');steps+=['wait=17'];check('game-F4',17,0)
key('F10');steps+=['sleep=1'];key('n');steps+=['wait=2'];key('Esc');steps+=['wait=0','end=']
lua=memmap.fill('''CALLS={}
local ready=false
local function capture(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(OUT..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
end
mem:install_read_tap(READY,READY,'ready',function(a,d,m) if cpu.state.PC.value==a+1 then ready=true end end)
mem:install_read_tap(KEY,KEY,'key',function(a,d,m) if cpu.state.PC.value==a+1 then ready=false end end)
CALLS.visits=function() mem:write_u16(VISITS,1023) end
local function mouse(y)
 local head=mem:read_u16(HEAD);assert(head==mem:read_u16(TAIL),'input not drained')
 mem:write_u16(RING+head,0);mem:write_u16(RING+head+2,1)
 mem:write_u16(RING+head+4,0x80);mem:write_u16(RING+head+6,0x80|(y&127))
 mem:write_u16(HEAD,(head+8)&1023)
end
CALLS['mouse-down']=function() mouse(8) end
CALLS['mouse-up']=function() mouse(-8) end
''')
for k,v in dict(OUT=json.dumps(str(out)),READY=s['GetKey'],KEY=s['keyDown'],VISITS=s['visitMask'],HEAD=s['inputHead'],TAIL=s['inputTail'],RING=s['inputRing']).items():lua=re.sub(r'\b'+k+r'\b',lambda m:str(v),lua)
(out/'observe.lua').write_text(lua+'\n'+'\n'.join(callbacks))
r=subprocess.run([sys.executable,'tools/ui_test.py','--name',name,'--hd','--debug','--seconds','200','--lua',str(out/'observe.lua'),'--steps',';'.join(steps)],cwd=ROOT,capture_output=True,text=True,timeout=600)
(out/'driver.log').write_text(r.stdout+r.stderr);log=(out/'mame.log').read_text()
assert r.returncode==0 and '[LUA ERROR]' not in log and 'TIMEOUT' not in log,log[-2000:]
assert re.findall(r'^NAV (\S+)$',log,re.M)==checks,log[-2000:]
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'));from render import shr_screen;from imaging import png
for p in out.glob('*.shr'):png(p.with_name(p.stem+'@2x.png'),shr_screen(p.read_bytes()).rows,2)
report=dict(checks=checks,real_keys=True,mouse='injected ADB report at existing ring boundary',screens=len(list(out.glob('*.shr'))))
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
