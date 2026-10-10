"""Replay a closed recorded HD session on a private copy and trace movement.

Uses the recorded run's media, CFG and NVRAM, with the ELF of that build.
Observers read RAM and code boundaries only; no input or game-state injection.
The trace is diagnostic: observer reads can perturb this MAME's timing slightly.
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from elf import read
import logic_observer
from timedemo import MAME, ROMS, ROOT
import lua_guard


LUA = memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local S=@SYMBOLS@
local frame,slotCount=0,0
local started=nil
local pending=nil
local tics,keyTics,mouseX,mouseY,turn=0,0,0,0,0
local paused=false
local function now() return manager.machine.time:as_double() end
local function signed(x) return x>=32768 and x-65536 or x end
local function pose()
 return {s:read_u32(@MM:OLD_WORLD+0x3000@),s:read_u32(@MM:OLD_WORLD+0x3004@),s:read_u16(@MM:OLD_WORLD+0x3032@),signed(s:read_u16(@MM:OLD_WORLD+0x6c34@))}
end
local function live() return s:read_u16(S.demoMode)==0 end
replayCommands=s:install_read_tap(S.buildNext,S.buildNext,"replay-command",function()
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 or not live() then return end
 local count=s:read_u16(S.ticCount)
 if count<=slotCount then return end
 slotCount=count
 local p=S.ticCommands+(count-1)*8
 local bits=s:read_u16(p)
 local x,y=signed(s:read_u16(p+2)),signed(s:read_u16(p+4))
 if bits&0x30f~=0 then keyTics=keyTics+1 end
 mouseX=mouseX+x;mouseY=mouseY+y
 print(string.format('REPLAY_COMMAND {"time":%.9f,"frame":%d,"slot":%d,"until":%d,"held":%d,"bits":%d,"mouse_x":%d,"mouse_y":%d}',now(),frame,count-1,s:read_u16(S.inputUntil),s:read_u16(S.heldCommand),bits,x,y))
end)
local function tic(d)
 if not live() then return end
 if d==1 then
  pending={pose=pose(),x=signed(s:read_u16(@MM:OLD_WORLD+0x6c3e@)),y=signed(s:read_u16(@MM:OLD_WORLD+0x6c40@)),bits=s:read_u16(0x104a)}
 elseif d==6 and pending then
  local q,p=pose(),pending
  tics=tics+1;turn=turn+p.x
  print(string.format('REPLAY_TIC {"time":%.9f,"frame":%d,"bits":%d,"controlx":%d,"controly":%d,"x0":%d,"y0":%d,"a0":%d,"x1":%d,"y1":%d,"a1":%d}',now(),frame,p.bits,p.x,p.y,p.pose[1],p.pose[2],p.pose[3],q[1],q[2],q[3]))
  pending=nil
 end
end
@TAPS@
replayUI=s:install_write_tap(0x3e4,0x3e4,"replay-menu",function(a,d,m)
 if d==2 or d==4 then paused=true end
 print(string.format('REPLAY_UI {"time":%.9f,"screen":%d}',now(),d))
end)
replayFrame=s:install_write_tap(0x3f0,0x3f0,"replay-frame",function(a,d,m)
 if d==1 then
  frame=frame+1;slotCount=0;started=now()
  tics=0;keyTics=0;mouseX=0;mouseY=0;turn=0;paused=false
 elseif d==2 and started then
  local p=pose()
  print(string.format('REPLAY_FRAME {"time":%.9f,"frame":%d,"seconds":%.9f,"live":%s,"paused":%s,"tics":%d,"key_tics":%d,"mouse_x":%d,"mouse_y":%d,"turn_units":%d,"held":%d,"doc":%d,"played":%d,"x":%d,"y":%d,"angle":%d,"anglefrac":%d,"view":%d}',now(),frame,now()-started,tostring(live()),tostring(paused),tics,keyTics,mouseX,mouseY,turn,s:read_u16(S.heldCommand),s:read_u16(0x104c),s:read_u16(0x1046),p[1],p[2],p[3],p[4],2*s:read_u16(S.viewWidth)))
 end
end)
''')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session',type=Path)
    ap.add_argument('--elf',type=Path,required=True)
    ap.add_argument('--name',required=True)
    ap.add_argument('--limit',type=int,default=2400)
    ap.add_argument('--host-limit',type=int,default=600)
    args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.name):ap.error('unsafe output name')
    source=args.session.resolve(strict=True)
    running=subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout
    if any(str(source) in line and '-record ' in line for line in running.splitlines()):
        raise SystemExit('Recording is still open; leave its process and files untouched')
    if str(ROOT/'build/tests') in running:raise SystemExit('Another main worker MAME is running')
    assert (source/'session.inp').stat().st_size>64,'empty recording'
    manifest=source.parent/'manifest.json'
    if manifest.exists():assert json.loads(manifest.read_text())['elf_sha256']==sha(args.elf),'ELF differs from recorded build'
    out=ROOT/'build/tests'/args.name
    out.mkdir()
    work=out/'session'
    shutil.copytree(source,work)
    _,symbols=read(args.elf)
    names=('buildNext','ticCount','ticCommands','inputUntil','heldCommand','demoMode','viewWidth')
    script=LUA.replace('@SYMBOLS@','{'+','.join(f'{k}={symbols[k]}' for k in names)+'}')
    script=script.replace('@TAPS@',logic_observer.taps(symbols,'logic','tic',handle='replayTic'))
    # The logic variable layout belongs to the recording's source revision.
    assert symbols['LogicPlayerTick']>>16==13
    lua_guard.write(out/'observe.lua', script)
    for name in ('cfg','nvram','state','snap'):(work/name).mkdir(exist_ok=True)
    cmd=['nice','-n','20',str(MAME),'apple2gsr1','-rompath',ROMS,'-ramsize','4352K',
         '-sl7','cffa3000','-hard1',str(work/'wolf-hd.po'),'-video','none','-sound','none',
         '-nothrottle','-skip_gameinfo','-input_directory',str(work),'-playback','session.inp',
         '-exit_after_playback','-seconds_to_run',str(args.limit),'-autoboot_delay','0',
         '-autoboot_script',str(out/'observe.lua')]
    for flag,directory in [('cfg','cfg'),('nvram','nvram'),('state','state'),('snapshot','snap')]:
        cmd+=['-'+flag+'_directory',str(work/directory)]
    before={n:sha(source/n) for n in ('session.inp','wolf-hd.po')}
    (out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
    with (out/'mame.log').open('w') as log:
        process=subprocess.Popen(cmd,cwd=work,stdout=log,stderr=subprocess.STDOUT,env=env)
        try:code=process.wait(timeout=args.host_limit)
        finally:
            if process.poll() is None:process.kill();process.wait()
    log=(out/'mame.log').read_text()
    assert code==0 and 'Total playback frames:' in log and 'Lua error' not in log,log[-3000:]
    assert before=={n:sha(source/n) for n in before},'source recording changed during replay'
    data={kind.lower():[json.loads(x) for x in re.findall(r'^REPLAY_'+kind+r' (\{.*\})$',log,re.M)] for kind in ('COMMAND','TIC','FRAME','UI')}
    assert data['frame'] and data['tic'],'no live movement trace'
    keyboard=[r for r in data['frame'] if r['live'] and not r['paused'] and r['key_tics'] and not r['mouse_x'] and not r['mouse_y']]
    mouse=[r for r in data['frame'] if r['live'] and not r['paused'] and not r['key_tics'] and (r['mouse_x'] or r['mouse_y'])]
    summary=dict(method=__doc__,source=str(source),elf_sha256=sha(args.elf),source_hashes=before,
                 playback_frames=int(re.search(r'Total playback frames: (\d+)',log)[1]),
                 keyboard_frames=len(keyboard),mouse_frames=len(mouse),
                 largest_keyboard_turns=sorted(keyboard,key=lambda r:abs(r['turn_units']),reverse=True)[:20],
                 largest_mouse_turns=sorted(mouse,key=lambda r:abs(r['turn_units']),reverse=True)[:20])
    (out/'trace.json').write_text(json.dumps(data,indent=2)+'\n')
    (out/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
