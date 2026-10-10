"""Observe a native death/restart: keep pixels under red, repaint, then reveal.

The existing physical-key room walk supplies movement and combat. This
observer changes no input, player state, screen memory or palette registers.
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from elf import read

ROOT = Path(__file__).resolve().parents[1]

LUA = memmap.fill(r'''
do
local cpu=manager.machine.devices[':maincpu']
local mem=cpu.spaces.program
local screen=manager.machine.screens[':screen']
local phase='idle'
local before,first=nil,nil
local loadingChanges,visibleWrites,revealChanges=0,0,0
local repainted={}
local function bytes(base,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(base+i)) end
 return table.concat(b)
end
local function dump(label)
 local f=assert(io.open(OUT..'/'..label..'.shr','wb'))
 f:write(bytes(@MM:SHR@,32768));f:close()
end
local function inView(a)
 local o=a-@MM:SHR@
 return o>=0 and o<25600 and o//160>=mem:read_u16(S.viewTop)
  and o//160<mem:read_u16(S.viewBottom) and o%160>=mem:read_u16(S.viewLeft)
  and o%160<mem:read_u16(S.viewLeft)+mem:read_u16(S.viewBytes)
end
local function viewBytes()
 local b={}
 for y=mem:read_u16(S.viewTop),mem:read_u16(S.viewBottom)-1 do
  b[#b+1]=bytes(@MM:SHR@+y*160+mem:read_u16(S.viewLeft),mem:read_u16(S.viewBytes))
 end
 return table.concat(b)
end
local function redPalette()
 for i=0,15 do if mem:read_u16(@MM:SHR_PAL@+i*2)~=0xa00 then return false end end
 return true
end
local function tap(name,fn)
 mem:install_read_tap(S[name],S[name],'death-check-'..name,function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(a>>16) and cpu.state.PC.value==a+1 then fn() end
 end)
end
tap('DeathFadeStep',function()
 if phase=='idle' then phase='fade';dump('01-fade-start') end
end)
tap('DeathLoading',function()
 if phase=='fade' then
  phase='loading';before=viewBytes();dump('02-loading-start')
  assert(redPalette(),'death did not reach the red palette')
 end
end)
tap('DeathReveal',function()
 if phase=='loading' then
  dump('03-reveal-start')
  print('DEATH_PRESERVED '..tostring(before==viewBytes()))
  assert(before==viewBytes(),'restart replaced the picture before rendering the new life')
  assert(redPalette(),'floor colors appeared before the new life was rendered')
 end
end)
tap('paintSiteDeath',function() if phase=='loading' then phase='paint' end end)
tap('revealLoop',function()
 if phase=='paint' then
  phase='reveal';first=viewBytes();dump('04-first-scene')
  assert(redPalette(),'first scene was not painted beneath red')
 end
end)
tap('InitFlash',function()
 if phase~='reveal' then return end
 dump('05-revealed')
 local count=0;for _ in pairs(repainted) do count=count+1 end
 local wrong=0
 for _,p in ipairs({0,13,14,15}) do for i=0,15 do
  if mem:read_u16(@MM:SHR_PAL@+p*32+i*2)~=mem:read_u16(S.deathSave+p*32+i*2) then wrong=wrong+1 end
 end end
 print(string.format('DEATH_TRANSITION {"loading_pixel_changes":%d,"visible_palette_writes":%d,"reveal_pixel_changes":%d,"repainted_bytes":%d,"view_bytes":%d,"wrong_final_colors":%d,"reveal_preserved_pixels":%s}',
  loadingChanges,visibleWrites,revealChanges,count,#first,wrong,tostring(first==viewBytes())))
 phase='done'
end)
mem:install_write_tap(@MM:SHR@,@MM:SHR_PAL+0x1ff@,'death-transition-writes',function(a,d,m)
 if phase=='idle' or phase=='done' or manager.machine:side_effects_disabled() then return end
 if inView(a) then
  if phase=='loading' and d~=mem:read_u8(a) then loadingChanges=loadingChanges+1 end
  if phase=='paint' then repainted[a]=true end
  if phase=='reveal' and d~=mem:read_u8(a) then revealChanges=revealChanges+1 end
 elseif a>=@MM:SHR_PAL@ and (phase=='fade' or phase=='reveal') then
  if screen:time_until_pos(216)<screen:time_until_pos(16) then visibleWrites=visibleWrites+1 end
 end
end)
end
''')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--view', type=int, choices=(160, 214, 240, 320), default=214)
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT/'build/wolf.elf')
    names = set(re.findall(r'S\.(\w+)', LUA)) | set(re.findall(r"tap\('(\w+)'", LUA))
    script = ('local S={'+','.join(n+'='+str(symbols[n]) for n in sorted(names))+'}\n'
              + LUA.replace('OUT', json.dumps(str(out))))
    observer = out/'observe.lua'
    observer.write_text(script)
    cmd = [sys.executable, 'tools/room_walk.py', '--name', args.name, '--view', str(args.view),
           '--disk', 'build/wolf-hd.po', '--seconds', '40']
    r = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, WOLF_LOADING_TRACE=str(observer)),
                       capture_output=True, text=True, timeout=240)
    (out/'driver.log').write_text(r.stdout+r.stderr)
    log = (out/'mame.log').read_text()
    rows = re.findall(r'^DEATH_TRANSITION (.*)$', log, re.M)
    assert r.returncode==0 and '[LUA ERROR]' not in log and len(rows)==1, log[-3000:]
    result = json.loads(rows[0])
    result.update(view=args.view, elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),
                  method=__doc__)
    result['passed'] = (all(result[n]==0 for n in ('loading_pixel_changes', 'visible_palette_writes',
                                                 'reveal_pixel_changes', 'wrong_final_colors'))
                        and result['repainted_bytes']==result['view_bytes']
                        and result['reveal_preserved_pixels'])
    (out/'transition-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    assert result['passed'], result


if __name__=='__main__':
    main()
