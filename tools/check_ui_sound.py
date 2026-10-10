"""Check real Options audio controls, disk persistence and recorded output."""
import memmap
import argparse
import array
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import wave
from elf import read
import logic_observer

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument('--name', default='ui-real-sound')
ap.add_argument('--in-game', action='store_true', help='open Options during play and verify the paused tic queue on return')
args = ap.parse_args()
out = ROOT/'build/tests'/args.name
out.mkdir(parents=True, exist_ok=True)
_, sym = read(ROOT/'build/wolf.elf')
observer = memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local active=false
local busy=0
local reads=0
local violations=0
local last=nil
local gameTics=0
local pausedTics=nil
local inMenu=false
local resumed=false
observeMenu=mem:install_write_tap(0x3e4,0x3e4,"audio-menu",function(a,d,m)
 if not INGAME or not active then return end
 if d==2 and not inMenu then inMenu=true;pausedTics=gameTics
 elseif inMenu and d==0 then
  assert(gameTics==pausedTics,"game advanced while the menu was open")
  inMenu=false;resumed=true
 end
end)
local function onGameTic(d)
 if d==1 then gameTics=gameTics+1 end
end
@LOGIC_TAPS@
observeGameFrame=mem:install_write_tap(0x3f0,0x3f0,"audio-game-frame",function(a,d,m)
 if d~=2 then return end
 if INGAME then active=true end
 if resumed then
  local debt=(mem:read_u16(0x104c)-mem:read_u16(0x1046))&65535
  print(string.format("AUDIO_RESUMED %d %d",gameTics-pausedTics,debt))
  resumed=false
 end
end)
local function boundary()
 if active and reads%2~=0 then violations=violations+1;print("AUDIO_ERROR odd read pair") end
 reads=0
end
observeBusy=mem:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,"audio-busy",function(a,d,m) busy=d end)
observeReads=mem:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,"audio-read",function(a,d,m)
 if not active then return end
 reads=reads+1
 if busy&128~=0 or cpu.state.P.value&4==0 then violations=violations+1;print("AUDIO_ERROR read access") end
end)
observeWrites=mem:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDADRH@,"audio-write",function(a,d,m)
 if a~=@MM:SOUNDDATA@ then boundary();return end
 if active and (busy&128~=0 or cpu.state.P.value&4==0) then violations=violations+1;print("AUDIO_ERROR write access") end
end)
emu.register_frame_done(function()
 local screen=mem:read_u8(0x3e4)
 if screen==14 or screen==1 then active=true end
 if not active then return end
 local state=string.format("%d %d %d %d",mem:read_u16(FX),mem:read_u16(MUSIC),mem:read_u16(ACTIVE),screen)
 if state~=last then print(string.format("AUDIO_UI %.9f %s",manager.machine.time:as_double(),state));last=state end
end)
''')
observer=observer.replace('INGAME', 'true' if args.in_game else 'false')
for token, symbol in [('FX','soundVolume'),('MUSIC','musicVolume'),('ACTIVE','musicActive')]:
    observer=observer.replace(token,str(sym[symbol]))
observer=observer.replace('@LOGIC_TAPS@',logic_observer.taps(sym,'logic','onGameTic',memory='mem',handle='observeGameTic'))
(out/'observe.lua').write_text(observer)
steps=['wait=1','sleep=2','key=Return','wait=2','sleep=0.5','key=Down','key=Down','key=Return',
       'wait=7','key=Return','wait=17','sleep=0.5','snap=options-sound','key=Left','sleep=0.4','key=Down','key=Left','sleep=0.4']
steps+=['key=Left']*14+['key=Up']+['key=Left']*14+['sleep=2','snap=options-muted',
       'key=Right','key=Down','key=Right','sleep=1']+['key=Esc','wait=7']+['key=Down']*3+['key=Return','sleep=2','snap=options-saved','end=']
if args.in_game:
    steps[:8]=['waitmem=0x3f0,2','sleep=1','key=Esc','wait=2','sleep=0.5',
               'key=Down','key=Down','key=Down','key=Return']
    steps[-1:]=['key=Esc','wait=2','sleep=0.5','key=Esc','wait=0','sleep=1',
                'hold=Control,1','sleep=1','snap=game-sound','end=']
subprocess.run([sys.executable,'tools/ui_test.py','--name',args.name,'--hd','--audio','--seconds','180',
                '--steps',';'.join(steps),'--lua',str(out/'observe.lua')]+(['--skip'] if args.in_game else []),cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
log=(out/'mame.log').read_text()
rows=[dict(time=float(t),effects=int(fx),music=int(music),active=int(active),screen=int(screen))
      for t,fx,music,active,screen in re.findall(r'^AUDIO_UI ([\d.]+) (\d+) (\d+) (\d+) (\d+)',log,re.M)]
assert rows and 'AUDIO_ERROR' not in log, 'GLU access or double-read violation'
assert any((r['effects'],r['music'])==(14,14) for r in rows),rows
silent=next(r for r in rows if (r['effects'],r['music'],r['active'])==(0,0,0))
resume=next(r for r in rows if r['time']>silent['time'] and r['effects']==1)
assert resume['time']-silent['time']>=2
assert (rows[-1]['effects'],rows[-1]['music'],rows[-1]['active'])==(1,1,1),rows[-1]
resume_checks=[tuple(map(int,m)) for m in re.findall(r'^AUDIO_RESUMED (\d+) (\d+)$',log,re.M)]
if args.in_game:
    assert resume_checks and all(tics<5 and debt<5 for tics,debt in resume_checks),resume_checks
media=(out/'wolf-hd.po').read_bytes()
# The header points to the native WOLF.SETTINGS block, shared with the UI.
block=int.from_bytes(media[512+436:512+438],'little')
record=media[block*512+496:block*512+512]
assert record[:8]==b'WSD1\x01\x01\x5b\xa4',record.hex()
with wave.open(str(out/'audio.wav'),'rb') as wav:
    assert wav.getsampwidth()==2
    rate,channels=wav.getframerate(),wav.getnchannels()
    def segment(start,seconds):
        wav.setpos(round(start*rate));data=wav.readframes(round(seconds*rate))
        values=array.array('h',data)
        return dict(seconds=len(values)/channels/rate,peak=max(map(abs,values),default=0),
                    rms=(sum(v*v for v in values)/max(1,len(values)))**.5)
    title=segment(rows[0]['time']+.2,1.5)
    mute=segment(silent['time']+.7,.8)
    assert title['peak']>100,title
    assert mute['peak']==0,mute
reload_name=args.name+'-reload'
subprocess.run([sys.executable,'tools/ui_test.py','--name',reload_name,'--hd',
                '--disk',str(out/'wolf-hd.po'),'--seconds','80',
                '--steps','wait=14;sleep=1;end=','--lua',str(out/'observe.lua')],
               cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
reload_log=(ROOT/'build/tests'/reload_name/'mame.log').read_text()
assert re.search(r'^AUDIO_UI [\d.]+ 1 1 1 14$',reload_log,re.M),reload_log[-1500:]
assert 'AUDIO_ERROR' not in reload_log
report=dict(disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),
            elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
            machine='apple2gsr1',ramsize='4352K',rows=rows,title_audio=title,muted_audio=mute,
            settings_record=record.hex(),reloaded_levels=[1,1],glu_violations=0,steps=steps,
            in_game=args.in_game,menu_resume_checks=resume_checks)
(out/'audio-check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
