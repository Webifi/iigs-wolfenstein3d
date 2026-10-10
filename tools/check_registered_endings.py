"""Run registered boss replay and ending display through the native engine.

A private checkpoint loads the requested boss floor. The fixture isolates
the boss and starts its death state; combat arithmetic is tested separately.
The native state machine, Hitler morph, camera, notice, victory flow, page
loader and palette publication run normally. Return uses real ADB input.
"""
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
from floor_check import checkpoint, checkpoint_lua
import music_capture
from wolfdata import ROOT, PROFILE


LUA = memmap.fill(r'''
local S=@SYMBOLS@
local V=@VARS@
local F=@FIELDS@
local states=@STATES@
local W=@MM:LOGIC_BASE@
local player=W+@PLAYER@
local started=false
local morphed=false
local prepared={}
local pages={}
local ready=-1
local pressed=false
local releaseAt=0
local victorySeen=false
local function startDeath(ob,kind,state)
 mem:write_u16(W+ob+F.O_STATE,state)
 mem:write_u16(W+ob+F.O_TICS,1)
 mem:write_u16(W+ob+F.O_ACTIVE,1)
 mem:write_u16(W+ob+F.O_FLAGS,(mem:read_u16(W+ob+F.O_FLAGS)&~1)|4)
 print('DEATH_STATE '..kind)
 prepared[kind]=true
end
deathFixture=mem:install_write_tap(0x3f0,0x3f0,'registered-death-fixture',function(_,d)
 if d~=2 or mem:read_u8(0x3e4)~=0 then return end
 if not started then
  assert(mem:read_u16(S.levelIndex)==@FLOOR@,'wrong boss floor')
  local ob=mem:read_u16(player+F.O_NEXT)
  if @CLASS@==0 then
   -- BJ's native run is checked by check_floor_flow. This case checks pages.
   mem:write_u16(V.playstate,6);started=true;return
  end
  while ob~=0 and mem:read_u16(W+ob+F.O_CLASS)~=@CLASS@ do ob=mem:read_u16(W+ob+F.O_NEXT) end
  assert(ob~=0,'boss absent')
  mem:write_u16(player+F.O_NEXT,ob)
  mem:write_u16(W+ob+F.O_PREV,@PLAYER@)
  mem:write_u16(W+ob+F.O_NEXT,0)
  mem:write_u16(V.lastobj,ob)
  for i=0,4095 do
   local a=W+@ACTORAT@+i*2
   if mem:read_u16(a)>=@PLAYER@ then mem:write_u16(a,0) end
  end
  mem:write_u32(V.killx,mem:read_u32(player+F.O_X))
  mem:write_u32(V.killy,mem:read_u32(player+F.O_Y))
  startDeath(ob,@CLASS@,@STATE@)
  started=true
 end
 if @CLASS@==10 and not prepared[16] then
  local ob=mem:read_u16(player+F.O_NEXT)
  while ob~=0 do
   if mem:read_u16(W+ob+F.O_CLASS)==16 then
    startDeath(ob,16,states.s_hitlerdie1);morphed=true;break
   end
   ob=mem:read_u16(W+ob+F.O_NEXT)
  end
 end
end)
phaseTap=mem:install_write_tap(V.deathcam_phase,V.deathcam_phase,'registered-camera-phase',function(_,d)
 if started then print('CAMERA_PHASE '..d) end
end)
pageTap=mem:install_read_tap(S.epOut,S.epOut,'registered-ending-ready',function(a,d,m)
 if manager.machine:side_effects_disabled() or cpu.state.PC.value~=a+1 then return end
 local hold=mem:read_u16(S.holdScreen)
 ready=hold*100+(hold==2 and mem:read_u16(S.flowStep) or 0)
end)
local function press()
 field('Return'):set_value(1);pressed=true;releaseAt=now()+0.15
end
local function checkPage(index)
 local f=assert(io.open(@OUT@..'/expected-'..index..'.shr','rb'))
 local raw=f:read('*a');f:close()
 local wrong=0
 for i=0,32767 do
  if i<32200 or i>=32256 then
   if mem:read_u8(@MM:SHR@+i)~=raw:byte(i+1) then wrong=wrong+1 end
  end
 end
 print('ENDING_BYTES '..index..' '..wrong)
 assert(wrong==0,'ending pixels, rows or palettes differ')
 screen:snapshot('ending-'..index..'.png')
end
emu.register_frame_done(function()
 if pressed and now()>=releaseAt then field('Return'):set_value(0);pressed=false;releaseAt=now()+0.3 end
 if not started or pressed or now()<releaseAt then return end
 if mem:read_u8(0x3e4)==1 and mem:read_u16(S.currentSong)==7 then
  assert(pages[0] and pages[1],'ending pages skipped')
  assert(@CLASS@~=10 or morphed,'native Hitler morph skipped')
  print('ENDING_COMPLETE');manager.machine:exit()
 elseif ready==100 and not victorySeen and mem:read_u16(S.holdScreen)==1 then
  victorySeen=true;press()
 elseif mem:read_u16(S.holdScreen)==2 then
  local index=mem:read_u16(S.flowStep)
  if index<2 and ready==200+index and not pages[index] then
   checkPage(index);pages[index]=true;press()
  end
 end
end)
''')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episodes', type=int, nargs='+', default=[1, 2, 3, 4, 5, 6])
    p.add_argument('--name', default='registered-endings')
    a = p.parse_args()
    assert PROFILE.key == 'wolf3d' and all(1 <= n <= 6 for n in a.episodes)
    _, symbols = read(ROOT/'build/wolf.elf')
    logic = json.loads((ROOT/'build/assets/logic.json').read_text())
    variables = {n:memmap.LOGIC_BASE+logic['layout']['VARS']+2*i for i,n in enumerate(logic['vars'])}
    menu = (ROOT/'build/assets/menu.bin').read_bytes()
    lumps = {n:int(v) for n,v in re.findall(r'^LUMP_(\w+)\s+\.equ\s+(\d+)$',
              (ROOT/'build/gen/menu.inc').read_text(), re.M)}
    cases = [(0, None), (8, 's_schabbdie1'), (10, 's_mechadie1'),
             (18, 's_giftdie1'), (0, None), (19, 's_fatdie1')]
    out = ROOT/'build/tests'/a.name
    out.mkdir(parents=True, exist_ok=False)
    reports = []
    for episode in a.episodes:
        folder = out/f'episode-{episode}'
        folder.mkdir()
        floor = episode*10-2
        disk = checkpoint(ROOT/'build/wolf-hd.po', folder, floor)
        for page in range(2):
            index = lumps[f'END{(episode-1)*2+page+1}']
            first = struct.unpack_from('<H', menu, 8+index*8)[0]
            (folder/f'expected-{page}.shr').write_bytes(menu[first*512:first*512+32768])
        kind, state = cases[episode-1]
        script = LUA
        names = ('levelIndex','epOut','holdScreen','flowStep','currentSong')
        table = lambda d:'{'+','.join(k+'='+str(v) for k,v in d.items())+'}'
        for token, value in dict(SYMBOLS=table({n:symbols[n] for n in names}),
             VARS=table(variables),FIELDS=table(logic['fields']),STATES=table(logic['states']),
             PLAYER=logic['layout']['OBJLIST'],ACTORAT=logic['layout']['ACTORAT'],FLOOR=floor,
             CLASS=kind,STATE=logic['states'][state] if state else 0,OUT=json.dumps(str(folder))).items():
            script = script.replace('@'+token+'@', str(value))
        script += checkpoint_lua()+music_capture.lua()
        (folder/'observe.lua').write_text(script)
        steps='wait=1;sleep=1;key=Esc;wait=2;sleep=1;key=Down;key=Return;wait=4;sleep=1;key=Return;wait=0;sleep=500;end='
        command=[sys.executable,'tools/ui_test.py','--name',a.name+f'/episode-{episode}',
                 '--hd','--disk',str(disk),'--seconds','500','--lua',str(folder/'observe.lua'),'--steps',steps]
        run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=800)
        (folder/'driver.log').write_text(run.stdout+run.stderr)
        log=(folder/'mame.log').read_text()
        assert run.returncode==0 and 'ENDING_COMPLETE' in log and '[LUA ERROR]' not in log, log[-4000:]
        phases=list(map(int,re.findall(r'^CAMERA_PHASE (\d+)$',log,re.M)))
        if kind: assert phases==[1,2,3,0], phases
        assert re.findall(r'^ENDING_BYTES (\d+) (\d+)$',log,re.M)==[('0','0'),('1','0')]
        row=dict(episode=episode,floor=floor,camera_phases=phases,songs=music_capture.events(log),ending_byte_differences=0)
        reports.append(row)
        print(json.dumps(row),flush=True)
    (out/'result.json').write_text(json.dumps(dict(cases=reports,method=__doc__,
        elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest()),indent=2)+'\n')


if __name__ == '__main__':
    main()
