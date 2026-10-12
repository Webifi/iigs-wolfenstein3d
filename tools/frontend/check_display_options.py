"""Real-key options, legacy settings migration and live-menu restoration."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import memmap
import logic_capture
from elf import read

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--name', required=True)
p.add_argument('--mame', type=Path)
p.add_argument('--resume', action='store_true', help='resume saved-boot checks after the key route passed')
p.add_argument('--legacy-disk', required=True, type=Path,
               help='older image with valid saved Buffered Draw On settings')
a = p.parse_args()
out = ROOT / 'build/tests' / a.name
out.mkdir(parents=True, exist_ok=a.resume)
elf = ROOT / 'build/wolf.elf'
segments, symbols = read(elf)
assert not any(n in symbols for n in ('HiddenPaintSet', 'hiddenOn', 'hiddenPaint', 'hdBandPublish'))
if a.resume:
    assert elf.read_bytes()==(out/'wolf.elf').read_bytes(), 'build changed since key route'
else:
    shutil.copy2(elf, out / 'wolf.elf')


def settings(image):
    block = struct.unpack_from('<H', image, 948)[0]
    return block * 512, image[block * 512:(block + 1) * 512]


legacy_image = a.legacy_disk.read_bytes()
_, legacy = settings(legacy_image)
assert legacy[:8] == b'WOLFSET\x02' and legacy[18] == 1
assert legacy[12] in (1, 255) and legacy[13:16] == bytes((1, 1, 5))
assert struct.unpack_from('<H', legacy, 8)[0] == sum(legacy[12:496]) & 65535
media = bytearray((ROOT / 'build/wolf-hd.po').read_bytes())
offset, _ = settings(media)
media[offset:offset + 512] = legacy
fixture = out / 'legacy-settings.po'
fixture.write_bytes(media)
lua = memmap.fill(r'''
local S=SYMBOLS
local loaded,restores,frames=nil,0,0
local paused=nil
local directScalers=nil
local fastHeaders,originalHeaders,pauseWorld=nil,nil,nil
local qualityStart=nil
local qualitySwitches=0
local LC=LOGIC_FIELDS
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(at+i)) end;return table.concat(b)
end
local function world()
 return bytes(LC.OBJLIST,64)..bytes(LC.V_health,2)..bytes(LC.V_ammo,2)..bytes(LC.V_score,4)..bytes(LC.V_lives,2)..bytes(LC.STATICS,3200)
end
local function whole() return bytes(@MM:SHR@,32000)..bytes(@MM:SHR_SCB@,200)..bytes(@MM:SHR_PAL@,512) end
local function tap(a,n,f)
 mem:install_read_tap(a,a,n,function(ad)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then f() end
 end)
end
local function rows(expected)
 assert(mem:read_u16(0x1162)==#expected,'wrong options row count')
 local items=@MM:REGISTERED_MENU@+mem:read_u16(0x1160)
 for i,text in ipairs(expected) do
  local ptr=@MM:REGISTERED_MENU@+mem:read_u16(items+(i-1)*2)
  assert(bytes(ptr,#text+1)==text..'\0','wrong option label/order')
 end
end
tap(S.LoadSettings,'settings-load',function() loaded=mem:read_u8(0x7c12) end)
tap(S.MenuDimOpen,'pause',function()
 if mem:read_u16(S.uiGameOn)~=0 and mem:read_u8(0x3e4)==0 then paused=whole();pauseWorld=world() end
end)
tap(S.UiKeepView,'restore',function()
 if paused then assert(whole()==paused,'menu return changed game picture');paused=nil;restores=restores+1 end
end)
if S.resumeKept then tap(S.resumeKept,'repaint-restore',function()
 if paused then assert(whole()==paused,'menu repaint changed game picture');paused=nil;restores=restores+1 end
end) end
tap(S.resumeView,'world-restore',function()
 if pauseWorld then assert(world()==pauseWorld,'option transition changed the paused world');pauseWorld=nil end
end)
tap(S.ApplyTransparency,'quality-start',function()
 qualityStart=manager.machine.time:as_double()
end)
tap(S.transparencyDone,'quality-end',function()
 assert(mem:read_u16(@MM:SPRITE_QUALITY_STATE@+4)==mem:read_u16(S.fastTransparencyOn),'quality was not applied')
 if qualityStart then
  print(string.format('TRANSPARENCY_APPLY_MS %.6f',(manager.machine.time:as_double()-qualityStart)*1000))
  qualityStart=nil
 end
end)
local function headers() return bytes(@MM:SPRITE_CMDS@,HEADER_BYTES) end
CALLS['fast-default']=function() assert(mem:read_u16(S.fastTransparencyOn)==1,'legacy setting did not default on') end
CALLS['paint-default']=function()
 assert(mem:read_u16(S.wallPaintOn)==0 and mem:read_u16(S.bufferOn)==0,'painting did not default to Direct')
end
CALLS['fast-game-on']=function()
 assert(mem:read_u16(S.fastTransparencyOn)==1 and mem:read_u16(@MM:SPRITE_QUALITY_STATE@+4)==1)
 if fastHeaders then assert(headers()==fastHeaders,'On did not restore fast headers') else fastHeaders=headers() end
 qualitySwitches=qualitySwitches+1
end
CALLS['fast-pending-off']=function()
 assert(mem:read_u16(S.fastTransparencyOn)==0 and mem:read_u16(@MM:SPRITE_QUALITY_STATE@+4)==1)
 assert(headers()==fastHeaders,'headers changed inside the menu')
end
CALLS['fast-game-off']=function()
 assert(mem:read_u16(S.fastTransparencyOn)==0 and mem:read_u16(@MM:SPRITE_QUALITY_STATE@+4)==0)
 assert(headers()~=fastHeaders,'Off kept fast headers')
 if originalHeaders then assert(headers()==originalHeaders,'Off did not restore original headers') else originalHeaders=headers() end
 qualitySwitches=qualitySwitches+1
end
mem:install_write_tap(0x3f0,0x3f0,'frames',function(_,d) if d==2 then frames=frames+1 end end)
CALLS['display']=function()
 assert(loaded==1,'legacy On setting was not loaded')
 assert(mem:read_u8(0x7c12)==0,'retired setting not cleared')
 rows({'Sound Effects','Music','View Size','Depth Shading','Vsync','Painting','Fast transparency'})
 directScalers=bytes(@MM:SEG_SCALE3@,3*65536)
 assert(mem:read_u16(S.bufferOn)==0,'draw buffer defaults to on')
end
CALLS['vsync-on']=function()
 assert(mem:read_u16(S.vsyncOn)==1 and mem:read_u8(S.preparedAll)==0x4c)
 assert(mem:read_u16(S.preparedAll+1)==((mem:read_u16(S.bufferOn)==1 and S.bufferBridge or S.vsyncB)&65535))
end
CALLS['vsync-off']=function()
 assert(mem:read_u16(S.vsyncOn)==0)
 if mem:read_u16(S.bufferOn)==0 then assert(bytes(S.preparedAll,3)==string.char(0xe2,0x20,0x6b)) end
end
CALLS['buffer-on']=function()
 assert(mem:read_u16(S.bufferOn)==1 and mem:read_u16(S.preparedAll+1)==(S.bufferBridge&65535))
end
CALLS['buffer-off']=function()
 assert(mem:read_u16(S.bufferOn)==0)
 assert(bytes(@MM:SEG_SCALE3@,3*65536)==directScalers,'off did not restore scaler bytes')
end
CALLS['walls-menu-on']=function()
 assert(mem:read_u16(S.wallPaintOn)==1 and mem:read_u16(S.bufferOn)==0)
end
CALLS['walls-game-on']=function()
 CALLS['walls-menu-on']()
 assert(mem:read_u16(S.tightDispatch+1)==(S.wallPaintBridge&65535),'wall painter was not installed on return')
end
CALLS['walls-game-off']=function()
 assert(mem:read_u16(S.wallPaintOn)==0 and mem:read_u16(S.bufferOn)==0)
 assert(mem:read_u16(S.tightDispatch+1)==(S.tightLoop&65535),'direct painter was not restored')
end
CALLS['shade-off']=function() assert(mem:read_u16(S.columnLight)==0) end
CALLS['shade-on']=function() assert(mem:read_u16(S.columnLight)==1) end
CALLS['view-larger']=function() assert(mem:read_u16(S.weaponViewIndex)==4) end
CALLS['view-restored']=function() assert(mem:read_u16(S.weaponViewIndex)==2) end
CALLS['controls']=function() rows({'Mouse Walk','Mouse Speed','J13 Keyboard','Key Setup'}) end
CALLS['mouse-off']=function() assert(mem:read_u16(S.mouseWalk)==0) end
CALLS['mouse-on']=function() assert(mem:read_u16(S.mouseWalk)==1) end
CALLS['speed-up']=function() assert(mem:read_u16(S.mouseSensitivity)==6) end
CALLS['done']=function()
 assert(restores>=1 and frames>10 and not paused and qualitySwitches==4)
 print(string.format('DISPLAY_OPTIONS_PASS %d %d',restores,frames))
end
CALLS['reboot']=function()
 assert(loaded==0 and mem:read_u8(0x7c12)==0)
 rows({'Sound Effects','Music','View Size','Depth Shading','Vsync','Painting','Fast transparency'})
 CALLS['vsync-on']()
 CALLS['walls-menu-on']()
 assert(mem:read_u16(S.columnLight)==1 and mem:read_u16(S.weaponViewIndex)==2)
 assert(mem:read_u16(S.mouseWalk)==1 and mem:read_u16(S.mouseSensitivity)==5)
 assert(mem:read_u16(S.fastTransparencyOn)==0 and mem:read_u8(@MM:SETTINGS_IN@+30)==2,'fast transparency Off was not saved')
 print('DISPLAY_SAVED_BOOT_PASS')
end
''').replace('SYMBOLS', '{' + ','.join(f'{n}={symbols[n]}' for n in (
    'LoadSettings', 'MenuDimOpen', 'UiKeepView', 'uiGameOn', 'columnLight',
    'weaponViewIndex', 'mouseWalk', 'mouseSensitivity', 'vsyncOn', 'preparedAll', 'vsyncB', 'resumeKept', 'bufferOn', 'bufferBridge','fastTransparencyOn','ApplyTransparency','transparencyDone','resumeView','wallPaintOn','tightDispatch','wallPaintBridge','tightLoop') if n in symbols) + '}')
lua=lua.replace('LOGIC_FIELDS','{'+','.join(f'{n}={v}' for n,v in logic_capture.layout(symbols).items())+'}')
lua=lua.replace('HEADER_BYTES',str(json.loads((ROOT/'build/levels/0/registered-art.json').read_text())['frames']*202))
(out / 'observe.lua').write_text(lua)
display = ['key=O', 'key=Return', 'wait=7', 'sleep=0.5', 'key=Home', 'key=Return', 'wait=17', 'sleep=0.5']
start = ['key=Home','key=Return','wait=15','sleep=0.5','key=Return','wait=3','sleep=0.5','key=Return','wait=0','sleep=2']
if int(re.search(r'#define CAMPAIGN_EPISODES (\d+)', (ROOT/'build/gen/campaign.inc').read_text()).group(1))>1:
    start[2:2]=['wait=19','sleep=0.5','key=Return']
steps = ['wait=1','sleep=1','key=Esc','wait=2','sleep=0.5'] + display
steps += ['call=display','call=fast-default','call=paint-default','call=vsync-off','call=buffer-off','snap=display-sound',
          'key=End','key=Up','key=Right','sleep=1','call=buffer-on','call=vsync-off','snap=buffer-on',
          'key=Up','key=Right','call=vsync-on','call=buffer-on',
          'key=Down','key=Left','sleep=1','call=buffer-off','call=vsync-on',
          'key=Right','sleep=1','call=buffer-on','key=Up','key=Left','call=vsync-off','call=buffer-on',
          'key=Right','call=vsync-on','snap=both-on','key=Up','key=Left','call=shade-off','key=Right','call=shade-on',
          'key=Up','key=Right','call=view-larger','key=Left','call=view-restored','key=Esc','wait=7',
          'key=Home','key=Down','key=Return','wait=18','sleep=0.5','call=controls','snap=controls',
          'key=Left','call=mouse-off','key=Right','call=mouse-on','key=Down','key=Right','call=speed-up','key=Left',
          'key=End','key=Return','wait=9','sleep=0.5','snap=key-setup','key=Esc','wait=18','key=Esc','wait=7',
          'key=End','key=Return','sleep=1','key=Esc','wait=2'] + start
steps += ['call=fast-game-on']
for mode in ('off','on','off'):
    steps += ['key=Esc','wait=2','sleep=0.5'] + display + ['key=End','key=Right','sleep=0.5','snap=fast-'+mode]
    if mode=='off': steps += ['call=fast-pending-off']
    steps += ['key=Esc','wait=7','key=End','key=Return','sleep=1','key=Esc','wait=2','key=Esc','wait=0','sleep=1','call=fast-game-'+mode]
for key,enabled in (('Right',True),('Right',False),('Left',True)):
    steps += ['key=Esc','wait=2','sleep=0.5'] + display + [
        'key=End','key=Up','key='+key,'sleep=0.5']
    if enabled: steps += ['call=walls-menu-on']
    steps += ['key=Esc','wait=7','key=End','key=Return','sleep=1',
              'key=Esc','wait=2','key=Esc','wait=0','sleep=5',
              'call=walls-game-'+('on' if enabled else 'off')]
steps += ['hold=Left,0.5','sleep=2','snap=game','key=Esc','wait=2','sleep=0.8','snap=game-menu',
          'key=Esc','wait=0','sleep=5','snap=resumed','call=done','end=']


def run(name, steps, disk):
    cmd = [sys.executable, 'tools/ui_test.py', '--name', name, '--hd', '--debug',
           '--seconds', '240', '--lua', str(out / 'observe.lua'), '--disk', str(disk), '--steps', ';'.join(steps)]
    if a.mame:
        cmd += ['--mame',str(a.mame)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    target = ROOT / 'build/tests' / name
    (target / 'driver.log').write_text(result.stdout + result.stderr)
    log = (target / 'mame.log').read_text()
    assert result.returncode == 0 and '[LUA ERROR]' not in log, log[-4000:]
    return log


log = (out/'mame.log').read_text() if a.resume else run(a.name, steps, fixture)
assert 'DISPLAY_OPTIONS_PASS' in log, log[-4000:]
receipt=out/'media/media.json'
if not receipt.exists():receipt=out/'media.json'
saved_disk = Path(json.loads(receipt.read_text())[0]['file'])
saved_image = saved_disk.read_bytes()
_, saved = settings(saved_image)
assert saved[18] == 0 and saved[12] == legacy[12]
assert struct.unpack_from('<H', saved, 8)[0] == sum(saved[12:496]) & 65535
expected = bytearray(legacy)
expected[18] = 0
expected[28:32] = bytes((1, 2, 2, 1))
if legacy[31] != 1:
    for segment in segments:
        at = symbols['boundKeys'] - segment['address']
        if 0 <= at and at + 52 <= len(segment['data']):
            expected[52:58] = segment['data'][at + 40:at + 52:2]
            break
    else:
        raise AssertionError('default keypad bindings absent from ELF')
struct.pack_into('<H', expected, 8, sum(expected[12:496]) & 65535)
assert saved == expected, ('saved settings differ',
                          [(i, a, b) for i, (a, b) in enumerate(zip(expected, saved)) if a != b])
boot = run(a.name + '-saved', ['wait=1','sleep=1','key=Esc','wait=2','sleep=0.5'] + display +
           ['snap=saved-display','call=reboot','end='], saved_disk)
assert 'DISPLAY_SAVED_BOOT_PASS' in boot, boot[-4000:]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
report = dict(legacy_on_ignored=True, other_settings_preserved=True, saved_boot=True,
              painting_default='Direct',
              game_picture_restored=True, display_rows=7, fast_transparency_saved_off=True, fast_transparency_live_toggle=True, control_rows=4, vsync_saved_on=True, fast_walls_saved_on=True, fast_walls_live_toggle=True, draw_buffer_independent=True, draw_buffer_toggle_restores_scalers=True, vsync_toggle_restores_bytes=True,
              media_sha256=sha(ROOT / 'build/wolf-hd.po'), elf_sha256=sha(elf),
              legacy_fixture_sha256=sha(fixture))
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
