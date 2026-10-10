"""Load selected registered floors through the actual firmware and engine.

The fixture selects the floor and one-packet length in demo zero's RAM
directory and requests its ordinary native start. It changes no asset bytes
or loader code. Every art
byte is read back before the first packet, then a complete frame is drawn.
This is correctness evidence; capture timings are not performance evidence.
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from build_logic import RAW_PLANES_ADDRESS
from elf import read
import lua_guard
import mame_kit
import music_capture
from registered_loads import art_rows
import test_media
from wolfdata import ROOT, PROFILE


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--disk', type=Path, default=ROOT/'build/wolf-hd.po')
    p.add_argument('--floors', type=int, nargs='+', default=list(range(1, 61)))
    p.add_argument('--name', default='registered-native-floors')
    p.add_argument('--host-limit', type=int, default=1800)
    p.add_argument('--check-music', action='store_true', help='verify native song-start headers and GLU accesses')
    a = p.parse_args()
    if PROFILE.key != 'wolf3d' or any(not 1 <= f <= 60 for f in a.floors):
        p.error('registered Wolf and floor numbers 1..60 required')
    out = ROOT/'build/tests'/a.name
    out.mkdir(parents=True, exist_ok=False)
    cfg = out/'cfg'
    cfg.mkdir()
    (cfg/'apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input>'
        '<port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/>'
        '</input></system></mameconfig>')
    _, symbols = read(ROOT/'build/wolf.elf')
    expected = {}
    for floor in a.floors:
        f = floor-1
        rows = art_rows(f)
        rows += [dict(file=f'build/levels/{f}/source-planes.bin', address=RAW_PLANES_ADDRESS),
                 dict(file=f'build/levels/{f}/spriteFrame.bin', address=symbols['spriteFrame'])]
        expected[f] = '{'+','.join('{%s,%d}' % (json.dumps(str(ROOT/r['file'])), r['address']) for r in rows)+'}'
    script = memmap.fill('''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local floors=@FLOORS@
local checks={@CHECKS@}
local index=0
local checked=false
local pending=false
local started=false
local limit=@LIMIT@
local function fail(message)
 print('ERROR '..message);io.stdout:flush();manager.machine:exit()
end
for _,name in ipairs({"a2_config","bus_timing","ram_start"}) do
 local port=manager.machine.ioport.ports[":"..name]
 if port then print('SETTING '..name..' '..port:read()) end
end
local function nextFloor()
 index=index+1
 if index>#floors then
  print('COMPLETE '..#floors);io.stdout:flush();manager.machine:exit();return
 end
 local floor=floors[index]
 s:write_u16(@MM:DEMOS+0x2@,1)
 s:write_u16(@MM:DEMOS+0x4@,floor)
 s:write_u8(0x3e3,1)
 s:write_u8(0x3e2,1)
 checked=false;pending=true
 print('REQUEST '..(floor+1));io.stdout:flush()
end
packetTap=s:install_write_tap(0x3f7,0x3f7,'floor-art',function(_,d)
 if d~=1 or not pending or checked then return end
 local floor=floors[index]
 if s:read_u16(@LEVEL@)~=floor then return end
 local total,bad=0,0
 for _,check in ipairs(checks[floor]) do
  local f=assert(io.open(check[1],'rb'));local raw=f:read('*a');f:close()
  local first,count=nil,0
  for i=1,#raw do
   if s:read_u8(check[2]+i-1)~=raw:byte(i) then first=first or i-1;count=count+1 end
  end
  if count~=0 then print(string.format('MISMATCH floor %d address %06x count %d first %d',floor+1,check[2],count,first)) end
  total=total+#raw;bad=bad+count
 end
 print(string.format('CHECKED %d %d %d',floor+1,total,bad));io.stdout:flush()
 if bad~=0 then fail('prepared asset mismatch');return end
 checked=true
end)
frameTap=s:install_write_tap(0x3f0,0x3f0,'floor-frame',function(_,d)
 if d~=2 then return end
 if index==0 then started=true;nextFloor();return end
 if not checked then return end
 pending=false
 print('DRAWN '..(floors[index]+1));io.stdout:flush()
 manager.machine.screens[':screen']:snapshot(string.format('floor-%02d.png',floors[index]+1))
 nextFloor()
end)
emu.register_frame_done(function()
 if not started then s:write_u16(0x3e8,0x5a5a) end
 if manager.machine.time:as_double()>limit then
  fail(string.format('timeout pc %02x:%04x failed-group %d',cpu.state.PB.value,cpu.state.PC.value,s:read_u16(@FAILED@)))
 end
end)
''')
    replacements = dict(FLOORS='{'+','.join(str(f-1) for f in a.floors)+'}',
                        CHECKS=','.join(f'[{f}]={rows}' for f,rows in expected.items()),
                        LIMIT=200+len(a.floors)*100, LEVEL=symbols['levelIndex'], FAILED=symbols['overlayFailedGroup'])
    for name, value in replacements.items():
        script = script.replace('@'+name+'@', str(value))
    if a.check_music:
        script += '\nlocal mem=s\n' + music_capture.lua()
    media, swaps = test_media.prepare(a.disk, out)
    lua_guard.write(out/'run.lua', script+'\n'+swaps)
    cmd = ['nice','-n','20',mame_kit.BINARY,'apple2gsr1','-rompath',
           mame_kit.ROMPATH,
           '-ramsize','4352K',*media,'-video','none','-sound','none','-nothrottle','-skip_gameinfo',
           '-seconds_to_run',str(replacements['LIMIT']+10),'-autoboot_delay','0',
           '-autoboot_script',str(out/'run.lua'),'-cfg_directory',str(cfg),
           '-nvram_directory',str(out/'nvram'),'-state_directory',str(out/'state'),
           '-snapshot_directory',str(out)]
    (out/'command.json').write_text(json.dumps(cmd, indent=2)+'\n')
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
    with (out/'mame.log').open('w') as log:
        process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=a.host_limit)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    log = (out/'mame.log').read_text()
    settings = dict((key,int(value)) for key,value in re.findall(r'^SETTING (\w+) (\d+)$',log,re.M))
    checks = [tuple(map(int,row)) for row in re.findall(r'^CHECKED (\d+) (\d+) (\d+)$',log,re.M)]
    assert process.returncode == 0 and 'ERROR ' not in log, log[-3000:]
    assert [r[0] for r in checks] == a.floors and all(r[2] == 0 for r in checks), log[-3000:]
    assert f'COMPLETE {len(a.floors)}' in log
    assert settings['a2_config'] == 0 and settings['bus_timing'] & ~6 == 0 and settings['ram_start'] == 5
    result = dict(floors=a.floors, asset_bytes=sum(r[1] for r in checks), settings=settings,
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  performance_evidence=False, selection_fixture='demo directory floor and one-packet length')
    if a.check_music:
        songs = music_capture.events(log)
        expected_songs = [PROFILE.music_names.index(PROFILE.document['audio']['floor_songs'][f-1]) for f in a.floors]
        actual = songs[-len(a.floors):]
        assert [(s['floor']+1, s['song']) for s in actual] == list(zip(a.floors, expected_songs)), songs
        result['music_starts'] = actual
        result['music_headers_and_glu_accesses_verified'] = True
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)


if __name__ == '__main__':
    main()
