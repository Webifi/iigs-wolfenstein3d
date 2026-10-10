"""Native title-page menu conversion and exact Escape round-trip checks."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from elf import read

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/frontend'))
from gray_pair import pair_table, words_of


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--mame', required=True, type=Path)
    args = parser.parse_args()
    out = ROOT / 'build/tests' / args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT / 'build/wolf.elf')
    constants = dict((k, int(v)) for k, v in re.findall(
        r'(?m)^LUMP_(\w+)\s+\.equ\s+(\d+)', (ROOT / 'build/gen/menu.inc').read_text()))
    menu = (ROOT / 'build/assets/menu.bin').read_bytes()
    for name in ('pg13', 'title', 'credits'):
        block = struct.unpack_from('<H', menu, 8 + constants[name.upper()] * 8)[0]
        picture = menu[block * 512:block * 512 + 32768]
        tables = [pair_table(words_of(picture[32256 + i * 32:32288 + i * 32])) for i in range(16)]
        gray = bytes(tables[picture[32000 + y] & 15][pixel]
                     for y in range(200) for pixel in picture[y * 160:(y + 1) * 160])
        (out / (name + '-expected.shr')).write_bytes(picture)
        (out / (name + '-expected.gray')).write_bytes(gray)
    script = memmap.fill(r'''
local out=@OUT@
local ready,menuReady,resumed=false,false,false
local current=nil
local names={[14]='pg13',[1]='title',[12]='credits'}
local handles={}
local function entry(pc,name,fn)
 handles[#handles+1]=mem:install_read_tap(pc,pc,name,function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PC.value==a+1 then fn() end
 end)
end
local function read(path) local f=assert(io.open(path,'rb'));local b=f:read('a');f:close();return b end
local function compare(addr,bytes)
 local bad=0;for i=1,#bytes do if mem:read_u8(addr+i-1)~=bytes:byte(i) then bad=bad+1 end end;return bad
end
local function snapshot(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(out..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
 screen:snapshot(name..'.png')
end
local function sourceCheck(name)
 local b=read(out..'/'..name..'-expected.shr')
 return compare(@MM:SHR@,b:sub(1,32000))+compare(@MM:SHR_SCB@,b:sub(32001,32200))+compare(@MM:SHR_PAL@,b:sub(32257,32768))
end
entry(@WAIT@,'page-ready',function() current=names[mem:read_u8(0x3e4)];ready=current~=nil end)
entry(@KEY@,'menu-ready',function() if mem:read_u8(0x3e4)==2 then menuReady=true end end)
entry(@RESUME@,'attract-resume',function() resumed=true end)
CALLS=CALLS or {}
for _,name in pairs(names) do
 CALLS[name..'-ready']=function()
  if not ready or current~=name then return false end
  assert(sourceCheck(name)==0,name..' source pixels/colors differ');ready=false;menuReady=false;resumed=false
 end
 CALLS[name..'-menu']=function()
  if not menuReady then return false end
  local bad=compare(@MM:HEIGHT_TABLE@,read(out..'/'..name..'-expected.gray'))
  snapshot(name..'-menu');print('GRAY '..name..' '..bad);assert(bad==0,name..' stale palette conversion')
 end
 CALLS[name..'-resumed']=function()
  if not resumed then return false end
  local bad=sourceCheck(name);snapshot(name..'-resumed');print('RESTORE '..name..' '..bad)
  assert(bad==0,name..' pixels/colors changed by menu');resumed=false
 end
end
''')
    for key, value in dict(OUT=json.dumps(str(out)), WAIT=symbols['WaitInput'],
                           KEY=symbols['GetKey'], RESUME=symbols['attractResume']).items():
        script = script.replace('@' + key + '@', str(value))
    (out / 'observer.lua').write_text(script)
    steps = []
    for name, number in (('pg13', 14), ('title', 1), ('credits', 12)):
        steps.extend([f'wait={number}', f'call={name}-ready', 'key=J13 Escape',
                      'wait=2', f'call={name}-menu', 'key=J13 Escape', f'call={name}-resumed'])
    steps.append('end=')
    command = [sys.executable, 'tools/ui_test.py', '--name', args.name, '--mame', str(args.mame),
               '--hd', '--debug', '--j13', 'only', '--seconds', '180',
               '--steps', ';'.join(steps), '--lua', str(out / 'observer.lua')]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (out / 'driver.log').write_text(result.stdout + result.stderr)
    log = (out / 'mame.log').read_text()
    assert result.returncode == 0 and '[LUA ERROR]' not in log and 'TIMEOUT' not in log, log[-2500:]
    assert len(re.findall(r'^GRAY \w+ 0$', log, re.M)) == 3, log[-2500:]
    assert len(re.findall(r'^RESTORE \w+ 0$', log, re.M)) == 3, log[-2500:]
    report = dict(pages=3, converted_bytes=96000, wrong_gray_bytes=0, restore_differences=0,
                  real_j13_keys=True, machine='apple2gsr1', ram='4352K', accelerator='none',
                  elf_sha256=hashlib.sha256((ROOT / 'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((ROOT / 'build/wolf-hd.po').read_bytes()).hexdigest())
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
