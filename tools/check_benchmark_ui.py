"""Real-key benchmark result, numeric and return checks on a frozen build."""
import memmap
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
from elf import read
from mame_kit import BINARY as DEFAULT_MAME
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);ap.add_argument('--view',type=int,choices=range(4),default=1);ap.add_argument('--game',action='store_true');ap.add_argument('--abort',action='store_true');ap.add_argument('--cancel',action='store_true');ap.add_argument('--repeat',action='store_true');ap.add_argument('--machine',default='apple2gsr1');ap.add_argument('--return-key',default='Return');ap.add_argument('--mame',type=Path);ap.add_argument('--accelerator',type=int,default=0);ap.add_argument('--card',choices=('zip','tw'),default='zip');ap.add_argument('--cache',type=int,choices=(8,16,32,64),default=32);a=ap.parse_args()
_,s=read(ROOT/'build/wolf.elf');out=ROOT/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
lua=memmap.fill(r'''CALLS={}
local count=0
local oldAssert=assert
local function assert(ok,why) if not ok then manager.machine:exit() end;return oldAssert(ok,why) end
local measuring=false
local restored=0
local slotBefore,slotAfter=nil,nil
local function ramPage()
 local b={};for i=0,255 do b[#b+1]=string.char(mem:read_u8(0xa00+i)) end;return table.concat(b)
end
mem:install_read_tap(@MM:ZIPSLOT@,@MM:ZIPSLOT@,'zip-entry',function(_,data)
 if measuring and slotBefore==nil then slotBefore=data&15 end
end)
mem:install_write_tap(@MM:ZIPSLOT@,@MM:ZIPSLOT@,'zip-restore',function(_,data)
 if measuring then slotAfter=data&15 end
end)
mem:install_read_tap(MEASURE,MEASURE,'calibration-entry',function(ad)
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=(ad>>16) or cpu.state.PC.value~=ad+1 then return end
 local before=ramPage()
 local tw=mem:read_u8(@MM:TW_CONFIG@)
 local dp,db,flags=cpu.state.D.value,cpu.state.DB.value,cpu.state.P.value
 local stack=cpu.state.S.value
 local ret=(mem:read_u8(stack+3)<<16)|((mem:read_u16(stack+1)+1)&65535)
 measuring=true;slotBefore=nil;slotAfter=nil
 mem:install_read_tap(ret,ret,'calibration-return',function(at)
  if not measuring or manager.machine:side_effects_disabled() or cpu.state.PB.value~=(at>>16) or cpu.state.PC.value~=at+1 then return end
  measuring=false
  assert(ramPage()==before,'calibration changed firmware scratch RAM')
  assert(cpu.state.D.value==dp and cpu.state.DB.value==db and cpu.state.P.value==flags,'calibration changed caller context')
  local card=mem:read_u16(CARD)
  if (card&2)~=0 then assert(mem:read_u8(@MM:TW_CONFIG@)==tw,'TransWarp configuration was not restored') end
  if (card&1)~=0 then assert(slotBefore==slotAfter,'ZipGS slot delays were not restored') end
  restored=restored+1;print('CALIBRATION_RESTORE_PASS '..card)
 end)
end)
local function capture(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(OUT..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
 local lit=0
 for y=0,199 do local p=mem:read_u8(@MM:SHR_SCB@+y)&15
  for x=0,159 do local v=mem:read_u8(@MM:SHR@+y*160+x)
   if mem:read_u16(@MM:SHR_PAL@+p*32+(v>>4)*2)~=0 then lit=lit+1 end
   if mem:read_u16(@MM:SHR_PAL@+p*32+(v&15)*2)~=0 then lit=lit+1 end
  end
 end
 if lit<=1000 then manager.machine:exit();error('blank key-wait screen') end;print('VISIBLE '..name..' '..lit)
end
CALLS.result=function()
 count=count+1;capture('result-'..count)
 local vals={};for i=0,9 do local v={};for j=0,15 do local c=mem:read_u8(OUTPUT+i*16+j);if c==0 then break end;v[#v+1]=string.char(c) end;vals[#vals+1]=table.concat(v) end
 print('VALUES '..table.concat(vals,'|'))
 print('TIMING '..mem:read_u16(FRAMES)..' '..mem:read_u32(TICS)..' '..mem:read_u16(SLOWEST))
 assert(mem:read_u16(DIM)~=0,'result lost gray backdrop')
end
CALLS.menu=function() if not CANCEL then assert(restored>0,'calibration return not observed') end;capture('menu-return') end
''')
for k,v in dict(OUT=json.dumps(str(out)),OUTPUT=s['benchOut'],FRAMES=s['benchFrames'],TICS=s['benchTics'],SLOWEST=s['benchSlowest'],DIM=s['menuDim'],MEASURE=s['CpuMeasure'],CARD=s['cpuCard'],CANCEL='true' if a.cancel else 'false').items():lua=re.sub(r'\b'+k+r'\b',lambda m:str(v),lua)
(out/'observe.lua').write_text(lua)
steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=1']
if a.game:steps+=['key=Return','wait=15','sleep=1','key=Return','wait=3','sleep=1','key=Return','wait=0','sleep=1','key=Esc','wait=2','sleep=1','key=Down']
steps+=['key=Down','key=Down','key=Return','wait=7','sleep=1','key=Return','wait=17','sleep=1','key=Down','key=Down']+['key=Left']*3+['key=Right']*a.view+['key=Esc','wait=7','sleep=1','key=Down','key=Down','key=Return']
if a.game:steps+=['sleep=1','key=N' if a.cancel else 'key=Y']
if a.cancel:steps+=['wait=7','sleep=1','call=menu']
else:
 steps+=['wait=10']
 if a.abort:steps+=['sleep=2','key=Esc','wait=7','sleep=1','call=menu']
 else:
  steps+=['wait=11','sleep=0.2','call=result','key='+a.return_key,'wait=7','sleep=1','call=menu']
  if a.repeat:steps+=['key=Return','wait=10','wait=11','sleep=0.2','call=result','key=Space','wait=7','sleep=1','call=menu']
steps+=['key=Esc','wait=2','sleep=1','key=Esc','wait=0' if not a.cancel else 'wait=0','sleep=1','end=']
extra=['--accelerator',str(a.accelerator),'--card',a.card,'--cache',str(a.cache)]+(['--mame',str(a.mame)] if a.mame else [])
r=subprocess.run([sys.executable,'tools/ui_test.py','--name',a.name,'--hd','--debug','--machine',a.machine,'--seconds','600','--steps',';'.join(steps),'--lua',str(out/'observe.lua')]+extra,cwd=ROOT,capture_output=True,text=True,timeout=900)
(out/'driver.log').write_text(r.stdout+r.stderr);log=(out/'mame.log').read_text();assert r.returncode==0 and 'TIMEOUT' not in log and '[LUA ERROR]' not in log and 'VISIBLE menu-return' in log,log[-2500:]
rows=[]
for vals,nums in zip(re.findall(r'^VALUES (.*)$',log,re.M),re.findall(r'^TIMING (\d+ \d+ \d+)$',log,re.M)):
 v=vals.split('|');frames,tics,slow=map(int,nums.split());assert frames>0 and 0<slow<=tics
 assert v[1]==['1/2','2/3','3/4','Full'][a.view],v
 assert v[2]==str(frames),v
 tenths=tics//7;assert v[3]==f'{tenths//10}.{tenths%10} s',v
 assert v[4]==f'{tics*1000//70//frames} ms',v
 assert v[5]==f'{slow*1000//70} ms',v
 fps=frames*7000//tics;assert v[6]==f'{fps//100}.{fps%100:02}',v
 assert len(v)==10 and v[7] in ('None detected','ZipGS','TransWarp GS','AppleSqueezer'),v
 assert re.fullmatch(r'\d+\.\d{2} MHz',v[8]),v
 rows.append(dict(values=v,frames=frames,tics=tics,slowest_tics=slow))
assert len(rows)==(0 if a.abort or a.cancel else 2 if a.repeat else 1)
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'));from render import shr_screen;from imaging import png
for p in out.glob('*.shr'):png(p.with_name(p.stem+'@2x.png'),shr_screen(p.read_bytes()).rows,2)
result=dict(machine=a.machine,view=a.view,game=a.game,abort=a.abort,cancel=a.cancel,results=rows,returned=True,calibration_restore_checks=log.count('CALIBRATION_RESTORE_PASS'),elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),mame_sha256=hashlib.sha256(Path(a.mame or DEFAULT_MAME).read_bytes()).hexdigest(),accelerator_selection=a.accelerator,card=a.card,requested_cache_kb=a.cache)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
