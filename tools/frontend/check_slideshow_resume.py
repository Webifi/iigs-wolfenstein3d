"""Interrupt real slideshow phases with ADB keys; verify exact paused state."""
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
args = parser.parse_args()
out = ROOT / 'build/tests' / args.name
out.mkdir(parents=True, exist_ok=True)
_, symbols = read(ROOT / 'build/wolf.elf')
shutil.copy2(ROOT / 'build/wolf.elf', out / 'wolf.elf')
lua = memmap.fill(r'''
CALLS=CALLS or {}
local phase, expected, paused, number = '', nil, nil, 0
local function bytes(at,n)
 local t={};for i=0,n-1 do t[#t+1]=string.char(mem:read_u8(at+i)) end
 return table.concat(t)
end
local function screenBytes()
 return bytes(@MM:SHR@,32000)..bytes(@MM:SHR_SCB@,200)..bytes(@MM:SHR_PAL@,512)
end
local function tap(address,name,fn)
 mem:install_read_tap(address,address,name,function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(a>>16) and cpu.state.PC.value==a+1 then fn() end
 end)
end
tap(FADE_IN,'fade-in',function() if mem:read_u16(ACTIVE)~=0 then phase='in' end end)
tap(FADE_OUT,'fade-out',function() if mem:read_u16(ACTIVE)~=0 then phase='out' end end)
tap(WAIT_INPUT,'hold',function() if mem:read_u16(ACTIVE)~=0 then phase='hold' end end)
tap(PAUSED,'pause-state',function()
 number=number+1
 local id=mem:read_u8(0x3e4)
 assert(expected and id==expected.id and phase==expected.phase,'interrupted wrong slideshow phase')
 paused={screen=screenBytes(),dp=bytes(0x1100,256),palette=bytes(FADE_BASE,512),stack=cpu.state.S.value,id=id,phase=phase,time=manager.machine.time:as_double()}
 print(string.format('PAUSE %d %d %s %.6f',number,id,phase,paused.time))
 screen:snapshot(string.format('pause-%02d.png',number))
end)
tap(RESUME,'resume-state',function()
 assert(paused,'resume without pause')
 assert(screenBytes()==paused.screen,'slideshow screen did not restore exactly')
 assert(bytes(0x1100,256)==paused.dp,'slideshow working page changed')
 assert(bytes(FADE_BASE,512)==paused.palette,'unfaded palette changed')
 assert(cpu.state.S.value==paused.stack,'pause changed stack depth')
 assert(mem:read_u8(0x3e4)==paused.id,'wrong page resumed')
 print(string.format('SLIDE_RESUME %d %d %s %.6f %d',number,paused.id,paused.phase,manager.machine.time:as_double(),cpu.state.A.value))
 paused=nil;expected=nil
end)
local function target(name,id,want)
 CALLS[name]=function()
  if mem:read_u8(0x3e4)~=id or mem:read_u16(ACTIVE)==0 or phase~=want then return false end
  if want~='hold' then local step=mem:read_u16(0x1136);if step<5 or step>11 then return false end end
  expected={id=id,phase=want};return true
 end
end
target('pg-in',14,'in')
target('title-in',1,'in');target('title-hold',1,'hold');target('title-out',1,'out')
target('credits-in',12,'in');target('credits-hold',12,'hold');target('credits-out',12,'out')
target('scores-in',6,'in');target('scores-hold',6,'hold');target('scores-out',6,'out')
CALLS['still-holding']=function() assert(phase=='hold' and mem:read_u8(0x3e4)==1,'menu time consumed the page hold');print('HOLD_TIME_PRESERVED') end
CALLS['game-started']=function() assert(mem:read_u16(ACTIVE)==0 and mem:read_u16(GAME_ON)==1);print('NEW_GAME_UNWOUND_SLIDESHOW') end
''')
replacements = {
    'FADE_IN': symbols['FadeIn'], 'FADE_OUT': symbols['FadeOut'],
    'WAIT_INPUT': symbols['WaitInput'], 'ACTIVE': symbols['attractActive'],
    'PAUSED': symbols['attractPaused'], 'RESUME': symbols['attractResume'],
    'FADE_BASE': symbols['fadeBase'], 'GAME_ON': symbols['uiGameOn'],
}
for key, value in replacements.items():
    lua = re.sub(r'\b' + key + r'\b', str(value), lua)
(out / 'observe.lua').write_text(lua)
steps = []
for target, page in [('pg-in', 14), ('title-in', 1), ('title-hold', 1),
                     ('title-out', 1), ('credits-in', 12), ('credits-hold', 12),
                     ('credits-out', 12), ('scores-in', 6), ('scores-hold', 6),
                     ('scores-out', 6)]:
    steps += ['call=' + target, 'key=Esc', 'wait=2', 'sleep=1']
    if target == 'title-hold':
        steps += ['key=O', 'key=Return', 'wait=7', 'sleep=17', 'key=Esc', 'wait=2', 'sleep=1']
    if target == 'scores-out':
        steps += ['key=Home', 'key=Return', 'wait=15', 'sleep=1', 'key=Return',
                  'wait=3', 'sleep=1', 'key=Return', 'wait=0', 'sleep=1',
                  'call=game-started', 'snap=game', 'end=']
    else:
        steps += ['key=Esc', 'wait=' + str(page)]
        if target == 'title-hold':
            steps += ['sleep=1', 'call=still-holding']
command = [sys.executable, 'tools/ui_test.py', '--name', args.name, '--hd',
           '--debug', '--audio', '--seconds', '200', '--lua', str(out / 'observe.lua'),
           '--steps', ';'.join(steps)]
result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
(out / 'driver.log').write_text(result.stdout + result.stderr)
log = (out / 'mame.log').read_text()
assert result.returncode == 0 and 'NEW_GAME_UNWOUND_SLIDESHOW' in log and '[LUA ERROR]' not in log, log[-3500:]
pauses = re.findall(r'^PAUSE (\d+) (\d+) (\w+) ([\d.]+)$', log, re.M)
resumes = re.findall(r'^SLIDE_RESUME (\d+) (\d+) (\w+) ([\d.]+) (\d+)$', log, re.M)
assert len(pauses) == 10 and len(resumes) == 9, (pauses, resumes)
report = {'pauses': pauses, 'exact_resumes': resumes, 'hold_time_preserved': True,
          'new_game_unwinds': True, 'media_sha256': hashlib.sha256((out / 'wolf-hd.po').read_bytes()).hexdigest(),
          'elf_sha256': hashlib.sha256((out / 'wolf.elf').read_bytes()).hexdigest()}
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
