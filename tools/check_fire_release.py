"""Check held fire and delayed releases through physical emulator keys.

Equipment/health are fixture values. Keyboard registers, input queues, attack
state and game clocks remain untouched. Observe both captured transitions and
actual attack starts/shots for three seconds after releasing Control.
"""
import memmap
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from elf import read

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--name', required=True)
p.add_argument('--mame', required=True, type=Path)
p.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf')
p.add_argument('--disk', type=Path, default=ROOT / 'build/wolf-hd.po')
p.add_argument('--j13', choices=('only', 'both', 'off'), default='only')
p.add_argument('--view', type=int, choices=(214, 320), default=214)
p.add_argument('--weapons', default='1,2,3')
p.add_argument('--muted', action='store_true')
a = p.parse_args()
_, symbols = read(a.elf)
out = ROOT / 'build/tests' / a.name
out.mkdir(parents=True, exist_ok=True)
shutil.copy2(a.elf, out / 'wolf.elf')
variables = {n: int(h, 16) + memmap.OLD_WORLD for n, h in re.findall(
    r'(V_\w+) \.equ 0x([0-9a-f]+)', (ROOT / 'build/gen/logic.inc').read_text())}
lua = memmap.fill(r'''
local active=false
local scenario,weapon,start,released,downs,ups,attacks,shots
local failures=0
local rawSource=J13_MODE=='off' and 0 or 2
local prefix=J13_MODE=='off' and '' or 'J13 '
local mcu=manager.machine.devices[':adbmicro'].spaces.program
local function key(name,down)
 local wanted=prefix..name
 if prefix=='' and name=='W' then wanted='w  W' end
 if prefix=='' and name=='Left' then wanted='Left Arrow' end
 for _,port in pairs(manager.machine.ioport.ports) do for _,f in pairs(port.fields) do
  if f.name==wanted then f:set_value(down);return end
 end end
 error('missing input field '..wanted)
end
local function elapsed() return manager.machine.time:as_double()-start end
local function trace(kind,value)
 print(string.format('FIRE_TRACE %s w=%d %.9f %s %d c025=%d p3=%d mods=%d cache=%d valid=%d known=%d owner=%d phase=%d row=%d',
  scenario,weapon,elapsed(),kind,value,mem:read_u8(@MM:KEYMODREG@),mcu:read_u8(0xe8),
  mem:read_u16(S.j13Mods),mem:read_u16(S.physicalMods),mem:read_u16(S.physicalValid),
  mem:read_u16(S.knownCount),mem:read_u16(S.j13Owner),mem:read_u16(S.j13State),mem:read_u16(S.rowAddress)))
end
mem:install_write_tap(S.inputHead+1,S.inputHead+1,'fire-transitions',function(_,d)
 if not active or manager.machine:side_effects_disabled() then return end
 local head=mem:read_u8(S.inputHead)|(d<<8)
 local slot=S.inputRing+((head-8)&1023)
 local source=mem:read_u16(slot+2)
 local code=mem:read_u16(slot+4)
 if source==rawSource and (code==54 or code==182) then
  if code==54 then downs=downs+1 else ups=ups+1 end
  trace('event',code)
 end
end)
for _,name in ipairs({'CmdFire','GunAttack'}) do
 local kind=name
 local previousTime=nil
 mem:install_read_tap(S[name],S[name],'fire-'..name,function(ad)
  if not active or manager.machine:side_effects_disabled() or cpu.state.PB.value~=(ad>>16) or cpu.state.PC.value~=ad+1 then return end
  local time=manager.machine.time:as_double()
  if time==previousTime then return end
  previousTime=time
  if kind=='CmdFire' then attacks=attacks+1 else shots=shots+1 end
  trace(kind,kind=='CmdFire' and attacks or shots)
 end)
end
local lastHeld=nil
emu.register_frame_done(function()
 if not active then return end
 local held=mem:read_u8(S.keyHeld+54)
 if held~=lastHeld then trace('held',held);lastHeld=held end
end)
CALLS.configure=function() mem:write_u8(0x3e1,VIEW==214 and 2 or 4) end
CALLS.muted=function() assert(mem:read_u16(S.musicActive)==0,'music remains active') end
for w=1,3 do
 local n=w
 CALLS['weapon'..w]=function()
  mem:write_u16(V.V_ammo,99)
  mem:write_u16(V.V_health,100)
  mem:write_u16(V.V_bestweapon,n)
  mem:write_u16(V.V_chosenweapon,n)
  mem:write_u16(V.V_weapon,n)
  weapon=n
 end
end
for _,name in ipairs({'alone','move-kept','move-released','together','move-last','turn-kept'}) do
 local label=name
 CALLS[label]=function()
  scenario=label;start=manager.machine.time:as_double();released=nil
  downs=0;ups=0;attacks=0;shots=0;lastHeld=nil;active=true
  assert(mem:read_u16(S.viewWidth)==VIEW//2,'view not applied')
  assert(mem:read_u16(S.j13Mode)==(J13_MODE=='off' and 0 or 2),'wrong input mode')
 end
end
for _,name in ipairs({'Control','W','Left'}) do
 for _,down in ipairs({0,1}) do
  local k,d=name,down
  CALLS[k..d]=function()
   key(k,d)
   if k=='Control' and d==0 then released=elapsed() end
   trace('physical-'..k,d)
  end
 end
end
CALLS.togetherup=function()
 key('Control',0);key('W',0);released=elapsed();trace('physical-both',0)
end
CALLS.check=function()
 local held=mem:read_u8(S.keyHeld+54)
 local good=downs==1 and ups==1 and attacks==1 and held==0 and shots>0
 if weapon==1 then good=good and shots==1 else good=good and shots>=4 end
 good=good and mem:read_u16(S.j13Timeouts)==0 and mem:read_u16(S.inputDropped)==0
 good=good and mem:read_u16(V.V_playstate)==0 and mem:read_u16(V.V_health)>0
 if not good then failures=failures+1 end
 print(string.format('FIRE_RESULT %s %d %d %d %d %d %d %.9f %s',scenario,weapon,downs,ups,attacks,shots,held,elapsed()-released,good and 'PASS' or 'FAIL'))
 active=false
end
CALLS.done=function() print('FIRE_DONE '..failures) end
''')
names = set(re.findall(r'\bS\.(\w+)', lua)) | {'CmdFire', 'GunAttack'}
vnames = set(re.findall(r'\bV\.(\w+)', lua))
lua = ('local S={' + ','.join(n+'='+str(symbols[n]) for n in sorted(names)) + '}\n'
       + 'local V={' + ','.join(n+'='+str(variables[n]) for n in sorted(vnames)) + '}\n' + lua)
for key, value in {'J13_MODE': json.dumps(a.j13), 'VIEW': str(a.view)}.items():
    lua = re.sub(r'\b'+key+r'\b', lambda m: value, lua)
(out / 'observe.lua').write_text(lua)
j = '' if a.j13 == 'off' else 'J13 '
steps = ['wait=1', 'key='+j+('Esc' if not j else 'Escape'), 'wait=2', 'sleep=0.5',
         'key='+j+'Return', 'wait=15', 'sleep=0.3', 'key='+j+'Return', 'wait=3',
         'sleep=0.3', 'key='+j+'Return', 'wait=0', 'sleep=1', 'call=configure', 'sleep=1']
if a.muted:
    esc = 'key='+j+('Esc' if not j else 'Escape')
    steps += [esc, 'wait=2', 'sleep=0.3', 'key='+j+'O', 'key='+j+'Return',
              'wait=7', 'sleep=0.3', 'key='+j+'Return', 'wait=17', 'sleep=0.3',
              'key='+j+'Down'] + ['key='+j+'Left']*15 + [esc, 'wait=7', esc,
              'wait=2', esc, 'wait=0', 'sleep=1', 'call=muted']
cases = {
    'alone': ['call=Control1', 'sleep=2', 'call=Control0', 'sleep=3'],
    'move-kept': ['call=W1', 'sleep=0.4', 'call=Control1', 'sleep=2', 'call=Control0', 'sleep=3', 'call=W0', 'sleep=1'],
    'move-released': ['call=Control1', 'sleep=0.4', 'call=W1', 'sleep=1', 'call=W0', 'sleep=1', 'call=Control0', 'sleep=3'],
    'together': ['call=Control1', 'sleep=0.4', 'call=W1', 'sleep=2', 'call=togetherup', 'sleep=3'],
    'move-last': ['call=Control1', 'sleep=0.4', 'call=W1', 'sleep=2', 'call=Control0', 'sleep=0.05', 'call=W0', 'sleep=3'],
    'turn-kept': ['call=Left1', 'sleep=0.4', 'call=Control1', 'sleep=2', 'call=Control0', 'sleep=3', 'call=Left0', 'sleep=1'],
}
first = True
for weapon in map(int, a.weapons.split(',')):
    for name, actions in cases.items():
        if not first:
            steps += ['key='+j+('Esc' if not j else 'Escape'), 'wait=2', 'sleep=0.5',
                      'key='+j+'N', 'key='+j+'Return', 'wait=15', 'sleep=0.3',
                      'key='+j+'Return', 'wait=3', 'sleep=0.3', 'key='+j+'Return',
                      'sleep=0.5', 'key='+j+'Y', 'wait=0', 'sleep=1',
                      'call=configure', 'sleep=1']
        first = False
        # Warm the modifier cache with a released, unbound ordinary key.
        # Start a fresh game per case so alerted guards cannot kill a later
        # fixture or turn its release observation into a death animation.
        steps += ['hold='+j+'H,0.4', 'sleep=0.4']
        if a.muted:
            steps += ['call=muted']
        steps += ['call=weapon'+str(weapon), 'sleep=0.4', 'call='+name] + actions + ['call=check', 'sleep=0.5']
steps += ['call=done', 'end=']
cmd = [sys.executable, 'tools/ui_test.py', '--name', a.name, '--mame', str(a.mame),
       '--j13', a.j13, '--hd', '--disk', str(a.disk), '--debug', '--seconds', '500',
       '--lua', str(out/'observe.lua'), '--steps', ';'.join(steps)]
r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1120)
(out/'driver.log').write_text(r.stdout+r.stderr)
log = (out/'mame.log').read_text()
rows = []
for name,w,down,up,attack,shot,held,after,status in re.findall(
        r'^FIRE_RESULT (\S+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) ([\d.]+) (\S+)$', log, re.M):
    rows.append(dict(case=name, weapon=int(w), downs=int(down), ups=int(up), attacks=int(attack),
                     shots=int(shot), held=int(held), seconds_after_release=float(after), passed=status=='PASS'))
result = dict(j13=a.j13, view=a.view, muted=a.muted, elf_sha256=hashlib.sha256(a.elf.read_bytes()).hexdigest(),
              disk_sha256=hashlib.sha256(a.disk.read_bytes()).hexdigest(),
              mame_sha256=hashlib.sha256(a.mame.read_bytes()).hexdigest(),
              completed=r.returncode==0 and 'FIRE_DONE ' in log and '[LUA ERROR]' not in log,
              cases=rows)
result['passed'] = result['completed'] and bool(rows) and all(row['passed'] for row in rows)
(out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
if not result['passed']:
    print(log[-3000:])
    raise SystemExit(1)
