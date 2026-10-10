"""Replay fixed camera poses with the world frozen; measure native cast cost."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
from elf import read
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument('--name',required=True)
ap.add_argument('--poses',type=Path,required=True)
ap.add_argument('--start',type=float,default=1)
ap.add_argument('--end',type=float,default=6)
ap.add_argument('--disk',type=Path,default=ROOT/'build/disk1.po')
ap.add_argument('--elf',type=Path,default=ROOT/'build/wolf.elf')
args=ap.parse_args()
if args.disk.resolve()==ROOT/'build/disk1.po' and args.disk.stat().st_mtime_ns < args.elf.stat().st_mtime_ns:
    ap.error('disk image is older than the linked game; wait for make to finish')
poses=[]
for r in json.loads(args.poses.read_text()):
    p=[r['x'],r['y'],r['angle']]
    if args.start<=r['time']<args.end and (not poses or poses[-1]!=p):poses.append(p)
assert len(poses)>2
out=ROOT/'build/tests'/args.name
for d in ('cfg','nvram','state','snap'):(out/d).mkdir(parents=True,exist_ok=True)
(out/'cfg/apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
_,symbols=read(args.elf)
# The frameAngle write tap installs each pose before world/cast work.
script=r'''
local s=manager.machine.devices[":maincpu"].spaces["program"]
local poses=POSES
local i=0;local ready=false;local start=nil;local cast=nil
poseTap=s:install_write_tap(FRAMEANGLE,FRAMEANGLE+1,"pose",function(a,d,m)
if ready and a==FRAMEANGLE and i<#poses then
 i=i+1;local p=poses[i]
 s:write_u16(0x1000,p[1]);s:write_u16(0x1002,p[2]);s:write_u16(0x1004,p[3])
 s:write_u16(0x1048,0);s:write_u16(WORLDLEAD,0)
end end)
castTap=s:install_write_tap(0x3f2,0x3f2,"cast",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then start=t elseif d==2 and start then cast=t-start end
end)
frameTap=s:install_write_tap(0x3f0,0x3f0,"frame",function(a,d,m)
if d==2 then
 if not ready then ready=true else
 print(string.format('POSE %d %.9f',i,cast or 0));io.stdout:flush()
 if i==#poses then manager.machine:exit() end
 end
end end)
emu.register_frame_done(function() if not ready then s:write_u16(0x3e8,0x5a5a) end;if manager.machine.time:as_double()>180 then print('TIMEOUT');manager.machine:exit() end end)
'''
if 'LogicFrame' in symbols:
    start=script.index('poseTap=')
    end=script.index('castTap=',start)
    script=script[:start]+script[end:]
    script=script.replace('if d==1 then start=t',
        'if d==1 then if ready and i<#poses then i=i+1;local p=poses[i];s:write_u16(0x1000,p[1]);s:write_u16(0x1002,p[2]);s:write_u16(0x1004,p[3]) end;start=t')
    script=script.replace('if not ready then ready=true',
        'if not ready then s:write_u8(%d,0x6b);ready=true'%symbols['LogicFrame'])
script=script.replace('POSES','{'+','.join('{%d,%d,%d}'%tuple(p) for p in poses)+'}').replace('FRAMEANGLE',str(symbols['frameAngle'])).replace('WORLDLEAD',str(symbols.get('worldLead',0)))
lua_guard.write(out/'bench.lua', script)
binary=mame_kit.BINARY
cmd=['nice','-n','20',binary,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K','-flop3',str(args.disk),'-sound','none','-video','none','-nothrottle','-skip_gameinfo','-seconds_to_run','185','-autoboot_delay','0','-autoboot_script',str(out/'bench.lua'),'-cfg_directory',str(out/'cfg'),'-state_directory',str(out/'state'),'-nvram_directory',str(out/'nvram'),'-snapshot_directory',str(out/'snap')]
if (args.disk.parent/'disk2.po').exists():cmd+=['-flop4',str(args.disk.parent/'disk2.po')]
live=[l for l in subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout.splitlines() if str(ROOT/'build/tests') in l]
if len(live)>=1:raise SystemExit('A worker MAME process is already running.')
env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
with (out/'mame.log').open('w') as log:
    p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:p.wait(timeout=55)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
log=(out/'mame.log').read_text()
data=[(int(n),float(t)*1000) for n,t in re.findall(r'^POSE (\d+) ([\d.]+)',log,re.M)]
if p.returncode or [n for n,t in data if n>=3]!=list(range(3,len(poses)+1)):raise SystemExit(log[-2000:])
data=[row for row in data if row[0]>=3]   # omit jumps from the initial camera
result=dict(mame_binary=binary,elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),disk_sha256=hashlib.sha256(args.disk.read_bytes()).hexdigest(),poses_sha256=hashlib.sha256(json.dumps(poses).encode()).hexdigest(),frames=len(data),cast_mean_ms=statistics.mean(t for n,t in data),per_pose=data,world_frozen=True)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
