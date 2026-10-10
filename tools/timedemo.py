"""Measure complete recorded-demo frames in the stock IIgs model with a 4 MiB expansion card.

Only the request latches are written. No game state, floor data or clock is
injected. A disk without native support for the requested floor fails.
"""
import memmap
from mame_target import ram_size
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import test_media
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
import lua_guard
import mame_kit

ROOT = Path(__file__).resolve().parents[1]
MAME = Path(mame_kit.BINARY)
ROMS = mame_kit.ROMPATH

LUA = memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local requested, active, packet = false, false, false
local first, previous, frames = nil, nil, 0
for _,name in ipairs({"a2_config","bus_timing","ram_start","ram_seed"}) do
  local port=manager.machine.ioport.ports[":"..name]
  if port then print("SETTING "..name.." "..port:read()) end
end
packetTap=s:install_write_tap(0x3f7,0x3f7,"demo-packet",function(a,d,m)
  if active and d==1 then
    packet=true
    if first==nil then first=manager.machine.time:as_double(); previous=first end
  end
end)
frameTap=s:install_write_tap(0x3f0,0x3f0,"demo-frame",function(a,d,m)
  if d==1 and not requested then
    requested=true
    if @PAL@ then s:write_u8(@MM:LANGSEL@,s:read_u8(@MM:LANGSEL@)|0x10) end
    s:write_u8(0x3e1,@VIEW@)
    s:write_u8(0x3e3,1)
    s:write_u8(0x3e2,@DEMO@+1)
  elseif d==2 and active and packet then
    local t=manager.machine.time:as_double()
    frames=frames+1
    print(string.format("FRAME %d %d %.9f",frames,frames*4,t-previous))
    previous=t; packet=false
  end
end)
demoTap=s:install_write_tap(0x3f5,0x3f5,"demo-state",function(a,d,m)
  if d==1 then active=true
  elseif d==2 and active then
    if first then print(string.format("DONE %d %.9f",frames,previous-first))
      print(string.format("REFRESH %.6f",1/manager.machine.screens[":screen"].frame_period))
    else print("ERROR missing packet timing marker") end
    manager.machine:exit()
  elseif d==3 and requested then
    print("ERROR demo unavailable or its floor cannot be loaded from this disk")
    manager.machine:exit()
  end
end)
emu.register_frame_done(function()
  if not requested then s:write_u16(0x3e8,0x5a5a) end
  if manager.machine.time:as_double()>@LIMIT@ then
    print(string.format("ERROR time limit after %d demo frames at %02x:%04x",frames,cpu.state.PB.value,cpu.state.PC.value))
    manager.machine:exit()
  end
end)
''')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, out):
    cfg = out / 'cfg'
    cfg.mkdir(parents=True)
    ports = [('a2_config', 7, 0, 0)]
    if args.seed is not None:
        ports += [('ram_start', 7, 4, 5), ('ram_seed', 0xffffffff, 0, args.seed)]
    (cfg / (args.machine + '.cfg')).write_text(
        '<mameconfig version="10"><system name="%s"><input>%s</input></system></mameconfig>' %
        (args.machine, ''.join('<port tag=":%s" type="CONFIG" mask="%d" defvalue="%d" value="%d"/>' % p for p in ports)))
    script = (LUA.replace('@VIEW@', str({160: 1, 214: 2, 240: 3, 320: 4}[args.view]))
              .replace('@DEMO@', str(args.demo)).replace('@LIMIT@', str(args.limit))
              .replace('@PAL@', 'true' if args.pal else 'false'))
    lua_guard.write(out / 'run.lua', script)
    media,swaps=test_media.prepare(args.disk,out,args.disk2,args.drives)
    lua_guard.write(out / 'run.lua', script+'\n'+swaps)
    cmd = ['nice', '-n', '20', str(args.mame), args.machine, '-rompath', ROMS,
           '-ramsize', ram_size(args.machine), *media, '-video', 'none', '-sound', 'none', '-nothrottle',
           '-skip_gameinfo', '-seconds_to_run', str(args.limit + 5), '-autoboot_delay', '0',
           '-autoboot_script', str(out / 'run.lua'), '-cfg_directory', str(cfg),
           '-state_directory', str(out / 'state'), '-nvram_directory', str(out / 'nvram'),
           '-snapshot_directory', str(out / 'snap')]
    if getattr(args, 'debug', False):
        cmd += ['-debug', '-debugger', 'none']
    live = subprocess.run(['pgrep', '-fl', '/iigs.app/Contents/MacOS/iigs'],
                          capture_output=True, text=True, check=False).stdout.splitlines()
    if sum(str(ROOT / 'build/tests') in line for line in live) >= 1:
        raise RuntimeError('A MAME process for this checkout is already running')
    (out / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
    with (out / 'mame.log').open('w') as log:
        process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=args.host_limit)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    text = (out / 'mame.log').read_text()
    errors = re.findall(r'^ERROR (.*)$', text, re.M)
    done = re.findall(r'^DONE (\d+) ([\d.]+)$', text, re.M)
    if process.returncode or errors or len(done) != 1:
        raise RuntimeError('%s; see %s' % (errors[-1] if errors else 'playback did not finish', out / 'mame.log'))
    settings = dict((name, int(value)) for name, value in re.findall(r'^SETTING (\w+) (\d+)$', text, re.M))
    # The kit has no bus timing option: the real timing is always on. Bits 1-2 of bus_timing are the ZipGS cache size,
    # every other bit is an accelerator option. ram_start 5 is the default power-on RAM pattern.
    if settings.get('a2_config') != 0 or settings.get('bus_timing', -1) & ~0x6 or settings.get('ram_start') != 5:
        raise RuntimeError('Stock configuration was not applied: %r' % settings)
    refresh = re.findall(r'^REFRESH ([\d.]+)$', text, re.M)
    if len(refresh) != 1 or abs(float(refresh[0]) - (50 if args.pal else 60)) > 1:
        raise RuntimeError('Requested video refresh was not applied: %r' % refresh)
    rows = [dict(frame=int(f), tic=int(t), ns=round(float(s) * 1e9))
            for f, t, s in re.findall(r'^FRAME (\d+) (\d+) ([\d.]+)$', text, re.M)]
    frames, seconds = int(done[0][0]), float(done[0][1])
    if not rows or frames != len(rows) or [r['frame'] for r in rows] != list(range(1, frames + 1)):
        raise RuntimeError('Incomplete frame timing data')
    result = dict(frames=frames, seconds=seconds, mean_ms=seconds * 1000 / frames,
                  slowest=sorted(rows, key=lambda r: (-r['ns'], r['frame']))[:10],
                  frame_times=rows, settings=settings, refresh_hz=float(refresh[0]))
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('disk', type=Path)
    ap.add_argument('--demo', type=int, choices=range(4), default=0)
    ap.add_argument('--view', type=int, choices=(160, 214, 240, 320), default=214)
    ap.add_argument('--repeat', type=int, default=2)
    ap.add_argument('--all', action='store_true', help='all four demos at all four view sizes')
    ap.add_argument('--jobs', type=int, choices=(1,), default=1, help='one MAME process for --all under the shared-host limit')
    ap.add_argument('--disk2', type=Path)
    ap.add_argument('--drives', type=int, choices=(1,2), default=2)
    ap.add_argument('--machine', choices=('apple2gsr1', 'apple2gs'), default='apple2gsr1')
    ap.add_argument('--pal', action='store_true', help='set the IIgs video mode to 50 Hz before playback')
    ap.add_argument('--mame', type=Path, default=MAME)
    ap.add_argument('--limit', type=int, default=1200, help='emulated seconds, including boot')
    ap.add_argument('--host-limit', type=int, default=600)
    ap.add_argument('--seed', type=int, help='explicit diagnostic RAM pattern seed; default leaves the stock startup setting')
    args = ap.parse_args()
    if args.repeat < 1 or args.limit < 1 or args.host_limit < 1 or (args.seed is not None and not 0 <= args.seed <= 0xffffffff):
        ap.error('repeat and limits must be positive; seed must fit 32 bits')
    args.disk = args.disk.resolve(strict=True)
    if args.disk2:
        args.disk2 = args.disk2.resolve(strict=True)
    tests = ROOT / 'build/tests'
    tests.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='timedemo-', dir=tests))
    def measure(demo, view):
        task=copy(args)
        task.demo,task.view=demo,view
        target=out/('demo%d-view%d'%(demo,view)) if args.all else out
        target.mkdir(parents=True,exist_ok=True)
        identity=dict(disk=str(args.disk),disk_sha256=sha(args.disk),mame_sha256=sha(args.mame),
                      demo=demo,view=view,machine=args.machine,seed=args.seed,pal=args.pal)
        results=[]
        try:
            for n in range(args.repeat):
                result=run(task,target/str(n+1));results.append(result)
                print('demo %d view %d run %d: %d frames, %.9f s, %.6f ms/frame'%
                      (demo,view,n+1,result['frames'],result['seconds'],result['mean_ms']),flush=True)
            if any(r['frame_times']!=results[0]['frame_times'] or r['seconds']!=results[0]['seconds'] for r in results[1:]):
                raise RuntimeError('Repeated runs differ; benchmark is not deterministic')
            if sha(args.disk)!=identity['disk_sha256']:
                raise RuntimeError('Disk changed during measurement')
        except (RuntimeError,subprocess.TimeoutExpired) as exc:
            (target/'summary.json').write_text(json.dumps(dict(identity,error=str(exc)),indent=2)+'\n')
            raise
        result=results[0]
        worst=sorted((r['ns'] for r in result['frame_times']),reverse=True)[:20]
        summary=dict(identity,frames=result['frames'],seconds=result['seconds'],mean_ms=result['mean_ms'],
                     slowest=result['slowest'],worst20_mean_ms=sum(worst)/len(worst)/1e6,identical_runs=len(results))
        (target/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        return summary

    if args.all:
        live=[line for line in subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout.splitlines()
              if str(ROOT/'build/tests') in line]
        if live:
            raise SystemExit("Finish this worker's existing MAME runs before starting the matrix.")
        results=[]
        try:
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                futures=[executor.submit(measure,demo,view) for view in (320,240,214,160) for demo in range(4)]
                for future in as_completed(futures):results.append(future.result())
        except (RuntimeError,subprocess.TimeoutExpired) as exc:
            raise SystemExit(str(exc))
        results.sort(key=lambda r:-r['slowest'][0]['ns'])
        slowest=sorted([dict(row,demo=r['demo'],view=r['view']) for r in results for row in r['slowest']],key=lambda r:-r['ns'])[:10]
        (out/'summary.json').write_text(json.dumps(dict(cases=results,slowest=slowest),indent=2)+'\n')
        print('Slowest frames across all demos and views:')
        for row in slowest:
            print('demo %d view %d frame %4d tic %5d %10.6f ms'%(row['demo'],row['view'],row['frame'],row['tic'],row['ns']/1e6))
    else:
        try:result=measure(args.demo,args.view)
        except (RuntimeError,subprocess.TimeoutExpired) as exc:raise SystemExit(str(exc))
        for row in result['slowest']:
            print('frame %4d  tic %5d  %10.6f ms'%(row['frame'],row['tic'],row['ns']/1e6))
    print('Evidence:',out/'summary.json')


if __name__ == '__main__':
    main()
