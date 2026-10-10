"""Replay recorded camera poses frame by frame on stock MAME and time each
paint and frame, so two builds draw exactly the same pictures."""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
from elf import read
from logic_capture import lua as logic_lua
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument('--name',required=True)
ap.add_argument('--poses',type=Path,required=True,help='frames.json of a playtest run')
ap.add_argument('--start',type=float,default=1.0)
ap.add_argument('--end',type=float,default=6.0)
ap.add_argument('--disk',type=Path,default=ROOT/'build/disk1.po')
ap.add_argument('--elf',type=Path,default=ROOT/'build/wolf.elf')
ap.add_argument('--profile',choices=('paint','frame'),help='sum PC time over the replayed frames')
ap.add_argument('--trace',type=int,help='count instructions in the paint of this pose')
args=ap.parse_args()
rows=[r for r in json.loads(args.poses.read_text()) if args.start<=r['time']<args.end]
poses=[(r['x'],r['y'],r['angle']) for r in rows]
out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
for d in ('cfg','snap','state'):(out/d).mkdir(exist_ok=True)
(out/'cfg/apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
_,symbols=read(args.elf)
script=r'''
local s=manager.machine.devices[":maincpu"].spaces["program"]
local poses=POSES
local i=0
local ready=false
local frameStart=nil
local paintStart=nil
local paint=nil
local castStart=nil
local cast=nil
local prof=manager.machine.memory.regions[":zipprof"]
local acc={}
local base=nil
local counted=0
local ranges={{0x0800,0x08ff},{0x2000,0x5fff},{0x6d80,0x6dff},{0x8fea,0x8fff}}
local function snap() local t={};for _,r in ipairs(ranges) do for k=r[1],r[2] do t[k]=prof:read_u64(0x200100+k*24+16) end end;return t end
local function add(b) local e=snap();for _,r in ipairs(ranges) do for k=r[1],r[2] do acc[k]=(acc[k] or 0)+e[k]-b[k] end end;counted=counted+1 end
local function installPose()
if ready and i<#poses then i=i+1;local p=poses[i];if LOGIC then logicSpawn(p[1],p[2],p[3]) else s:write_u16(0x1000,p[1]);s:write_u16(0x1002,p[2]);s:write_u16(0x1004,p[3]) end end
end
tapC=s:install_write_tap(0x3f2,0x3f2,"cast",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then castStart=t elseif d==2 and castStart then cast=t-castStart;castStart=nil end end)
tapP=s:install_write_tap(0x3f3,0x3f3,"paint",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then paintStart=t;if @PROFILE@=='paint' and i>=3 then base=snap() end
if i==@TRACE@ then manager.machine.debugger:command('trace '..@OUT@..'/instructions.trace,:maincpu,noloop') end
elseif d==2 and paintStart then paint=t-paintStart;if base and @PROFILE@=='paint' then add(base);base=nil end
if i==@TRACE@ then manager.machine.debugger:command('trace off,:maincpu') end end end)
tapF=s:install_write_tap(0x3f0,0x3f0,"frame",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then frameStart=t;paint=nil;cast=nil;installPose();if @PROFILE@=='frame' and ready and i>=3 then base=snap() end
elseif d==2 then
if not ready then ready=true
else if @PROFILE@=='frame' and base then add(base);base=nil end
print(string.format('POSE %d %.9f %.9f %.9f',i,t-frameStart,paint or 0,cast or 0))
if i>=#poses then
if @PROFILE@~='none' then local f=io.open(@OUT@..'/profile.txt','w');for _,r in ipairs(ranges) do for k=r[1],r[2] do if (acc[k] or 0)>0 then local addr=k>=0x6000 and (k-0x6000)*256 or k*16;f:write(string.format('%06x %d\n',addr,acc[k])) end end end;f:close();print('PROFILED '..counted) end
manager.machine:exit() end end
end end)
emu.register_frame_done(function() if not ready then s:write_u16(0x3e8,0x5a5a) end;if manager.machine.time:as_double()>200 then print('TIMEOUT');manager.machine:exit() end end)
'''
script=script.replace('@TRACE@',str(args.trace if args.trace is not None else -1))
script=script.replace('@PROFILE@',repr(args.profile or 'none')).replace('@OUT@',json.dumps(str(out)))
script=script.replace('POSES','{'+','.join('{%d,%d,%d}'%p for p in poses)+'}')
if 'LogicFrame' in symbols:
    script=script.replace('local s=manager.machine.devices[":maincpu"].spaces["program"]','local s=manager.machine.devices[":maincpu"].spaces["program"]\n'+logic_lua(),1)
    script=script.replace('LOGIC','true')
else:
    script=script.replace('LOGIC','false')
lua_guard.write(out/'bench.lua', script)
binary=mame_kit.BINARY
cmd=['nice','-n','20',binary,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K','-flop3',str(args.disk),'-sound','none','-video','none','-nothrottle','-skip_gameinfo','-seconds_to_run','220','-autoboot_delay','0','-autoboot_script',str(out/'bench.lua'),'-cfg_directory',str(out/'cfg'),'-state_directory',str(out/'state'),'-nvram_directory',str(out/'nvram'),'-snapshot_directory',str(out/'snap')]
if (args.disk.parent/'disk2.po').exists():cmd+=['-flop4',str(args.disk.parent/'disk2.po')]
if args.trace is not None:
    (out/'debug.txt').write_text('go\n')
    cmd+=['-debug','-debugger','none','-debugscript',str(out/'debug.txt')]
live=[l for l in subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout.splitlines() if str(ROOT/'build/tests') in l]
if len(live)>=1:raise SystemExit('A worker MAME process is already running.')
env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
with (out/'mame.log').open('w') as log:
    p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:p.wait(timeout=240)
    except subprocess.TimeoutExpired:
        import signal;os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5)
log=(out/'mame.log').read_text()
data=[(int(n),float(f)*1000,float(q)*1000,float(c)*1000) for n,f,q,c in re.findall(r'^POSE (\d+) ([\d.]+) ([\d.]+) ([\d.]+)',log,re.M)]
data=[d for d in data if d[0]>=3]   # the first replayed frames jump from the spawn
if not data:raise SystemExit(log[-2000:])
profiled=re.search(r'^PROFILED (\d+)',log,re.M)
result=dict(profile_frames=int(profiled[1]) if profiled else None,frames=len(data),frame_mean_ms=statistics.mean(d[1] for d in data),paint_mean_ms=statistics.mean(d[2] for d in data),cast_mean_ms=statistics.mean(d[3] for d in data),per_frame=data)
if args.trace is not None:
    import collections,bisect,time
    _,syms=read(args.elf)
    lab=sorted((v,k) for k,v in syms.items() if 0x20000<=v<0x60000);addrs=[v for v,k in lab]
    counts=collections.Counter();entries=collections.Counter()
    for line in (out/'instructions.trace').read_text().splitlines():
        m=re.match(r'^([0-9A-Fa-f]{2}):?([0-9A-Fa-f]{4}):',line)
        if not m:continue
        pc=int(m[1]+m[2],16);k=bisect.bisect_right(addrs,pc)-1
        if k<0:continue
        counts[lab[k][1]]+=1
        if pc==lab[k][0]:entries[lab[k][1]]+=1
    result['trace']={k:[n,entries[k]] for k,n in counts.most_common()}
    (out/'instructions.trace').rename(Path.home()/'.Trash'/('posebench-%d.trace'%time.time_ns()))
(out/'result.json').write_text(json.dumps(result)+'\n')
print('%s: %d frames, frame %.2f ms, paint %.2f ms, cast %.2f ms'%(args.name,result['frames'],result['frame_mean_ms'],result['paint_mean_ms'],result['cast_mean_ms']))
