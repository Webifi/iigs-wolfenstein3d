"""Exercise actual ADB mouse reports, calibrated gains and unclipped turning."""
import argparse,json,re,subprocess,sys
from pathlib import Path
from elf import read
from gen_mouse import TURN,MOVE
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--name',required=True);a=p.parse_args()
_,S=read(ROOT/'build/wolf.elf');out=ROOT/'build/tests'/a.name;out.mkdir(parents=True,exist_ok=True)
lua=r'''
local TURN=TURN_DATA
local MOVE=MOVE_DATA
local phase=nil
local pending=nil
local maxTurn=0
local completedFrames,readyFrame=0,nil
mem:install_write_tap(0x3f0,0x3f0,'mouse-test-frames',function(_,d)
 if d==2 then completedFrames=completedFrames+1 end
end)
CALLS.ready=function()
 -- A cold menu return can still be restoring art after the page latch.
 readyFrame=readyFrame or completedFrames+2
 if completedFrames<readyFrame then return false end
 readyFrame=nil
end
local function signed(v) return v>=32768 and v-65536 or v end
local function word(n) return mem:read_u16(S[n]) end
local function check(ok,why) if not ok then manager.machine:exit();error(why) end end
local function field(name)
 for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do if f.name:find(name,1,true) then return f end end end
 error('missing '..name)
end
local function tap(n,addr,fn)
 mem:install_read_tap(addr,addr,n,function(ad,d)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then fn() end
 end)
end
tap('mouse-enter',S.MouseControls,function()
 if not phase then return end
 pending={signed(word('mouseCountX')),signed(word('mouseCountY'))}
 phase.rx=phase.rx+pending[1];phase.ry=phase.ry+pending[2]
end)
tap('mouse-return',S.mouseControls+4,function()
 if not phase or not pending then return end
 phase.x=phase.x+signed(cpu.state.X.value);phase.y=phase.y+signed(cpu.state.Y.value)
 phase.calls=phase.calls+1;pending=nil
end)
tap('game-turn',S.ticTurnReady,function()
 if (word('controlBits')&64)==0 then maxTurn=math.max(maxTurn,math.abs(signed(cpu.state.A.value))) end
end)
local mx,my=0,0
for name,d in pairs({slow=3,fast=63,reverse=-63}) do
 local delta=d
 CALLS[name]=function() mx=(mx+delta)&255;my=(my+delta)&255;field('Mouse X'):set_value(mx);field('Mouse Y'):set_value(my) end
end
CALLS.strafe=function() field('Option / Solid Apple'):set_value(1) end
CALLS.unstrafe=function() field('Option / Solid Apple'):set_value(0) end
for _,step in ipairs({0,4,15}) do
 local speed=step
 for _,kind in ipairs({'turn','strafe','no-walk'}) do
  local role=kind
  CALLS['begin-'..speed..'-'..role]=function()
   check(word('mouseSensitivity')==speed,'wrong speed')
   -- The consumer resets the X fraction on the first report after a turn/
   -- strafe change. Pressing Option while stationary does not consume it.
   local mode=role=='strafe' and 64 or 0
   local fx=word('mouseStrafe')==mode and signed(word('mouseFracX')) or 0
   phase={speed=speed,role=role,rx=0,ry=0,x=0,y=0,calls=0,fx=fx,fy=signed(word('mouseFracY'))}
  end
 end
end
CALLS.finish=function()
 check(phase and phase.calls>0 and phase.rx~=0,'fixture delivered no mouse reports')
 local gx=(phase.role=='strafe' and MOVE or TURN)[phase.speed+1]
 local gy=phase.role=='no-walk' and 0 or MOVE[phase.speed+1]*2
 check(phase.rx*gx==phase.x*256+signed(word('mouseFracX'))-phase.fx,'X gain lost counts')
 check(phase.ry*gy==phase.y*256+signed(word('mouseFracY'))-phase.fy,'Y gain lost counts')
 print('MOUSE_GAIN '..phase.speed..' '..phase.role..' '..phase.rx..' '..phase.ry..' '..phase.x..' '..phase.y)
 phase=nil
end
CALLS.done=function() check(maxTurn>100,'fast turn remained clipped');print('MOUSE_NATIVE_PASS peak_turn='..maxTurn) end
'''
names=set(re.findall(r"word\('([^']+)'\)",lua))|set(re.findall(r'\bS\.(\w+)',lua))
lua='local S={'+','.join(n+'='+str(S[n]) for n in sorted(names))+'}\n'+lua.replace('TURN_DATA','{'+','.join(map(str,TURN))+'}').replace('MOVE_DATA','{'+','.join(map(str,MOVE))+'}')
(out/'observe.lua').write_text(lua)
steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=0.3','key=Return','wait=15','sleep=0.3','key=Return','wait=3','sleep=0.3','key=Return','wait=0','sleep=1']
if len(json.loads((ROOT/'build/gen/campaign.json').read_text())['episodes']) > 1:
 steps[6:6]=['wait=19','sleep=0.3','key=Return']
for speed in (0,4,15):
 steps+=['key=F6','wait=18','sleep=0.3','key=Down']+['key=Left']*15+['key=Right']*speed+['key=Esc','wait=2','key=Esc','wait=0','sleep=0.5',f'call=begin-{speed}-turn']
 for name in ('slow','fast','fast','reverse','slow'):steps+=['call='+name,'sleep=0.15']
 steps+=['sleep=0.4','call=finish','call=strafe','sleep=0.3',f'call=begin-{speed}-strafe']
 for name in ('fast','slow','reverse','fast'):steps+=['call='+name,'sleep=0.15']
 steps+=['sleep=0.4','call=finish','call=unstrafe','sleep=0.3']
# Toggle Mouse Walk Off through Controls; horizontal turning must remain calibrated.
steps+=['key=F6','wait=18','sleep=0.3','key=Return','key=Esc','wait=2','key=Esc','wait=0','sleep=0.5','call=begin-15-no-walk','call=fast','sleep=0.4','call=finish','call=done','end=']
steps=[part for step in steps for part in ([step,'call=ready'] if step=='wait=0' else [step])]
r=subprocess.run([sys.executable,'tools/ui_test.py','--name',a.name,'--hd','--debug','--seconds','150','--lua',str(out/'observe.lua'),'--steps',';'.join(steps)],cwd=ROOT,capture_output=True,text=True,timeout=240)
(out/'driver.log').write_text(r.stdout+r.stderr)
log=(out/'mame.log').read_text() if (out/'mame.log').exists() else r.stdout+r.stderr
assert r.returncode==0 and 'MOUSE_NATIVE_PASS' in log and '[LUA ERROR]' not in log,log[-4000:]
result={'passed':True,'gains':re.findall(r'^MOUSE_GAIN (.*)$',log,re.M),'peak_turn':int(re.search(r'peak_turn=(\d+)',log)[1])}
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
