"""Native queued-input, preview-publication, loading-fill and game-return checks."""
import argparse
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import memmap
from elf import read
import screen_ram_guard

parser = argparse.ArgumentParser()
parser.add_argument('--name', required=True)
parser.add_argument('--check-free-screen-ram', action='store_true')
args = parser.parse_args()
OUT = ROOT / 'build/tests' / args.name
OUT.mkdir(parents=True, exist_ok=True)
_, symbols = read(ROOT / 'build/wolf.elf')
shutil.copy2(ROOT / 'build/wolf.elf', OUT / 'wolf.elf')
subprocess.run([sys.executable, 'tools/frontend/loading_observer.py', str(OUT / 'loading.lua')], cwd=ROOT, check=True)
lua = memmap.fill(r'''
local OUT=OUTPUT
local preparing,copying,serial,frames=false,false,0,0
local category, started, publish = 0,0,0
local writes=0
local completed=0
local stream=false
local queued=false
local paused=nil
local gameScreen=nil
local drawerSnapshot=nil
local function now() return manager.machine.time:as_double() end
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(at+i)) end;return table.concat(b)
end
local function drawerBytes()
 local chunks={}
 for _,r in ipairs(DRAWER_REGIONS) do chunks[#chunks+1]=bytes(r[1],r[2]) end
 return table.concat(chunks)
end
local function pixels()
 local visible=bytes(@MM:SHR@,32000)
 if CHECK_MIRROR then assert(bytes(@MM:WALL_COLUMNS@,32000)==visible,'fast screen mirror is stale') end
 return visible
end
local function whole() return pixels()..bytes(@MM:SHR_SCB@,200)..bytes(@MM:SHR_PAL@,512) end
local function dump(name)
 pixels()
 local f=assert(io.open(OUT..'/'..name..'.shr','wb'));f:write(bytes(@MM:SHR@,32768));f:close()
end
local function tap(a,n,f)
 mem:install_read_tap(a,a,n,function(ad,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then f() end
 end)
end
tap(STREAM,'stream-start',function()
 if mem:read_u16(0x11a6)==1 then stream=true;print('TITLE_COPY_START '..now()) end
end)
tap(STREAM_DONE,'stream-done',function() if stream then stream=false;print('TITLE_COPY_DONE '..now()) end end)
CALLS['title-copy']=function() if stream then queued=true;print('QUEUED_KEY_DURING_COPY '..now());return true end;return false end
tap(PAUSED,'queued-menu',function()
 if queued then assert(mem:read_u8(0x3e4)==1);paused=whole();print('QUEUED_KEY_ACCEPTED '..now()) end
end)
tap(RESUME,'queued-resume',function()
 if paused then assert(whole()==paused);paused=nil;queued=false;print('QUEUED_KEY_RESUMED_EXACTLY') end
end)
tap(PREVIEW_CHANGED,'preview-start',function()
 if mem:read_u16(LAST)~=65535 and mem:read_u16(FRAME)==0 then
  serial=serial+1;preparing=true;writes=0;started=now();category=mem:read_u16(PICTURES)
  dump(string.format('swap-%02d-before',serial))
  print(string.format('PREVIEW_START %d %d %.6f',serial,category,started))
  if category==1 then frames=12 end
 end
end)
mem:install_write_tap(@MM:SHR@,@MM:SHR_PAL+0x1ff@,'preview-visible-writes',function(a,d,m)
 if preparing and not manager.machine:side_effects_disabled() then writes=writes+1 end
end)
local shadow=255
for _,at in ipairs({@MM:SHADOW_00@,@MM:SHADOW@}) do
 mem:install_write_tap(at,at,'preview-shadow-'..at,function(a,d,m) shadow=d end)
end
mem:install_write_tap(@MM:WALL_COLUMNS@,@MM:SHR_SHADOW+0x7cff@,'preview-shadow-writes',function(a,d,m)
 if preparing and (shadow&8)==0 and not manager.machine:side_effects_disabled() then writes=writes+1 end
end)
tap(PUBLISH,'preview-publish',function()
 assert(preparing and writes==0,'preview preparation touched visible screen');preparing=false;copying=true;publish=now()
 print(string.format('PREVIEW_PUBLISH %d %.6f %d',serial,publish,writes))
end)
tap(COPY_DONE,'preview-done',function()
 assert(copying);copying=false;completed=completed+1;dump(string.format('swap-%02d-after',serial))
 print(string.format('PREVIEW_DONE %d %d %.6f %.6f %.6f',serial,category,now(),(now()-publish)*1000,(now()-started)*1000))
end)
emu.register_frame_done(function()
 if frames>0 then screen:snapshot(string.format('swap-%02d-frame-%02d.png',serial,12-frames));frames=frames-1 end
end)
CALLS['visited-fixture']=function() mem:write_u16(VISITED,1023);print('FIXTURE all floor previews enabled') end
tap(OPEN_MENU,'game-snapshot',function()
 if mem:read_u16(GAME_ON)~=0 and mem:read_u8(0x3e4)==0 then gameScreen=whole();drawerSnapshot=drawerBytes();dump('game-before-menu') end
end)
tap(KEEP_VIEW,'game-restore',function()
 if gameScreen then assert(whole()==gameScreen,'game screen not restored exactly');assert(drawerBytes()==drawerSnapshot,'menu overwrote resident weapon drawers');gameScreen=nil;drawerSnapshot=nil;print('GAME_RESTORED_EXACTLY');dump('game-after-menu') end
end)
CALLS['loaded-floor']=function() assert(mem:read_u16(LEVEL)==1);print('COLD_FLOOR_2_STARTED') end
CALLS['done']=function() assert(not queued and not paused and serial>=10 and completed==serial);if checkFreeScreenRam then checkFreeScreenRam() end;print('INTERACTIONS_PASSED') end
''')
for key, name in {'STREAM':'StreamCachedPicture','STREAM_DONE':'cachedPictureDone','PAUSED':'attractPaused','RESUME':'attractResume','PREVIEW_CHANGED':'previewChanged','LAST':'previewLast','FRAME':'framePending','PICTURES':'listPictures','PUBLISH':'previewPublish','COPY_DONE':'previewCopyDone','VISITED':'visitMask','OPEN_MENU':'MenuDimOpen','KEEP_VIEW':'UiKeepView','GAME_ON':'uiGameOn','LEVEL':'levelIndex'}.items():
    lua = re.sub(r'\b' + key + r'\b', str(symbols[name]), lua)
lua = lua.replace('OUTPUT', json.dumps(str(OUT)))
if args.check_free_screen_ram:
    lua += screen_ram_guard.lua(symbols)
lua = lua.replace('CHECK_MIRROR', 'true' if 'InitScreenReadback' in symbols else 'false')
regions_path=ROOT/'build/assets/weapon-drawer-loads.json'
regions=json.loads(regions_path.read_text()) if regions_path.exists() else []
lua=lua.replace('DRAWER_REGIONS','{'+','.join('{%d,%d}'%(r['address'],r['bytes']) for r in regions)+'}')
(OUT / 'observe.lua').write_text(lua + '\n' + (OUT / 'loading.lua').read_text())
steps = ['call=title-copy','key=Esc','wait=2','sleep=1','snap=queued-title-menu','key=Esc','wait=1','sleep=1',
         'key=Esc','wait=2','sleep=1','call=visited-fixture','key=Home','key=Return','wait=15','sleep=1',
         'snap=floors','key=Down','sleep=1','snap=floor-2','key=Up','sleep=1','snap=floor-1-back',
         'key=Return','wait=3','sleep=1','snap=portrait-1']
for i in range(2,5): steps += ['key=Down','sleep=1',f'snap=portrait-{i}']
steps += ['key=Up','key=Up','key=Up','sleep=1','snap=portrait-back','key=Esc','wait=15','key=Esc','wait=2',
          'key=O','key=Return','wait=7','sleep=1','key=Return','wait=17','sleep=1','snap=display',
          'key=Down','key=Down','key=Left','key=Left','key=Left','sleep=1','snap=view-small',
          'key=Right','sleep=1','key=Right','sleep=1','key=Right','sleep=1','snap=view-large',
          'key=Left','sleep=1','snap=view-back','key=Esc','wait=7','key=Esc','wait=2',
          'key=Home','key=Return','wait=15','sleep=1','key=Home','key=Down','sleep=1','key=Return','wait=3','sleep=1',
          'key=Return','wait=0','sleep=1','call=loaded-floor','snap=game','key=Esc','wait=2','sleep=1',
          'snap=game-menu','key=Esc','wait=0','sleep=1','snap=game-returned','call=done','end=']
command=[sys.executable,'tools/ui_test.py','--name',OUT.name,'--hd','--debug','--audio','--seconds','145','--lua',str(OUT/'observe.lua'),'--steps',';'.join(steps)]
result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
(OUT/'driver.log').write_text(result.stdout+result.stderr)
log=(OUT/'mame.log').read_text()
assert result.returncode==0 and 'INTERACTIONS_PASSED' in log and 'GAME_RESTORED_EXACTLY' in log and '[LUA ERROR]' not in log, log[-4500:]
if args.check_free_screen_ram:assert 'FREE_SCREEN_RAM_OK 32768' in log
checked_fills = int(re.search(r'^LOADING_CHECKED_FILLS (\d+)$', log, re.M)[1])
assert checked_fills >= 100, checked_fills
times = [dict(serial=int(n),category=int(c),time=float(t),copy_ms=float(copy),total_ms=float(total))
         for n,c,t,copy,total in re.findall(r'^PREVIEW_DONE (\d+) (\d+) ([\d.]+) ([\d.]+) ([\d.]+)$',log,re.M)]
assert len(times) >= 10, 'preview publication checks did not complete'
report={'previews':times,'preparation_visible_writes':0,'queued_during_copy':True,'cold_floor_2_loaded':True,'game_restored_exactly':True,
        'resident_drawer_bytes_preserved':sum(r['bytes'] for r in regions),
        'reclaimed_ram_bytes_checked':32768 if args.check_free_screen_ram else 0,
        'loading_fill_checks':checked_fills,
        'media_sha256':hashlib.sha256((OUT/'wolf-hd.po').read_bytes()).hexdigest(),
        'elf_sha256':hashlib.sha256((OUT/'wolf.elf').read_bytes()).hexdigest()}
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
