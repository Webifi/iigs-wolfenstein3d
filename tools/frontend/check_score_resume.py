"""Use real keys to pause/resume all score phases and open menu High Scores."""
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
a = p.parse_args()
out = ROOT/'build/tests'/a.name
out.mkdir(exist_ok=False)
_, symbols = read(ROOT/'build/wolf.elf')
shutil.copy2(ROOT/'build/wolf.elf', out/'wolf.elf')
lua = memmap.fill(r'''
local phase,paused,restores='',nil,0
local normalScore=false
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(at+i)) end;return table.concat(b)
end
local function whole() return bytes(@MM:SHR@,32000)..bytes(@MM:SHR_SCB@,200)..bytes(@MM:SHR_PAL@,512) end
local function dump(name)
 local f=assert(io.open(OUT..'/'..name..'.shr','wb'));f:write(bytes(@MM:SHR@,32768));f:close()
end
local function tap(ad,name,fn)
 mem:install_read_tap(ad,ad,name,function(addr,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(addr>>16) and cpu.state.PC.value==addr+1 then fn() end
 end)
end
local function setPhase(value)
 if mem:read_u8(0x3e4)==6 and mem:read_u16(ACTIVE)~=0 then phase=value end
end
tap(FADE_IN,'score-fade-in',function() setPhase('in') end)
tap(FADE_OUT,'score-fade-out',function() setPhase('out') end)
tap(WAIT_INPUT,'score-hold',function() setPhase('hold') end)
for _,value in ipairs({'in','hold','out'}) do
 CALLS[value]=function()
  local step=mem:read_u16(0x1136)
  return phase==value and mem:read_u8(0x3e4)==6 and (value=='hold' or (step>=3 and step<=12))
 end
end
tap(PAUSED,'score-paused',function()
 assert(mem:read_u8(0x3e4)==6,'pause did not occur on scores')
 paused={screen=whole(),page=bytes(0x1100,256),fade=bytes(FADE_BASE,512),phase=phase}
 dump('paused-'..phase);print('SCORE_PAUSED '..phase)
end)
tap(RESUME,'score-resumed',function()
 assert(paused and whole()==paused.screen,'score pixels/SCBs/palettes changed during menu')
 assert(bytes(0x1100,256)==paused.page,'paused UI working page changed')
 assert(bytes(FADE_BASE,512)==paused.fade,'fade target changed')
 restores=restores+1;print('SCORE_RESTORED '..paused.phase);paused=nil
end)
for i=1,3 do CALLS['restored-'..i]=function() return restores==i end end
CALLS['normal-score']=function()
 assert(mem:read_u16(ACTIVE)==0 and mem:read_u8(0x3e4)==6)
 assert(mem:read_u16(BLACK)==0,'menu scores remained black')
 dump('menu-scores');normalScore=true;print('MENU_SCORES_VISIBLE')
end
CALLS.done=function() assert(restores==3 and normalScore and not paused);print('SCORE_RESUME_PASSED') end
''')
for key,name in dict(ACTIVE='attractActive',FADE_IN='FadeIn',FADE_OUT='FadeOut',WAIT_INPUT='WaitInput',
                     PAUSED='attractPaused',RESUME='attractResume',FADE_BASE='fadeBase',BLACK='screenBlack').items():
    lua=re.sub(r'\b'+key+r'\b',str(symbols[name]),lua)
(out/'observe.lua').write_text(lua.replace('OUT',json.dumps(str(out))))
steps=['call=in','key=Esc','wait=2','sleep=0.4','key=Esc','call=restored-1',
       'call=hold','key=Esc','wait=2','sleep=0.4','key=H','key=Return','wait=6','sleep=0.4',
       'call=normal-score','key=Esc','wait=2','sleep=0.4','key=Esc','call=restored-2',
       'call=out','key=Esc','wait=2','sleep=0.4','key=Esc','call=restored-3',
       'wait=13','sleep=1','call=done','end=']
r=subprocess.run([sys.executable,'tools/ui_test.py','--name',a.name,'--hd','--debug','--seconds','145',
                  '--lua',str(out/'observe.lua'),'--steps',';'.join(steps)],cwd=ROOT,capture_output=True,text=True,timeout=400)
(out/'driver.log').write_text(r.stdout+r.stderr)
log=(out/'mame.log').read_text()
assert r.returncode==0 and 'SCORE_RESUME_PASSED' in log and '[LUA ERROR]' not in log,log[-4500:]
phases=re.findall(r'^SCORE_RESTORED (\w+)$',log,re.M)
assert phases==['in','hold','out'],phases
report=dict(exact_restores=phases,menu_scores_visible=True,
            elf_sha256=hashlib.sha256((out/'wolf.elf').read_bytes()).hexdigest(),
            disk_sha256=hashlib.sha256((out/'wolf-hd.po').read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
from render import shr_screen
from imaging import png
for f in out.glob('*.shr'):png(f.with_suffix('.png'),shr_screen(f.read_bytes()).rows,2)
print(json.dumps(report,indent=2))
