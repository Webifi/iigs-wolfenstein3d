"""Measure the first automatic demo through normal boot, without game writes.

Count recorded packets separately from completed pictures, and require the
recorded game clock to stay caught up. Benchmark throughput cannot substitute
for this title-loop route. Optional actor observations measure death states
at picture completion, including actors outside the view. Plain timing runs
do not read actor or pixel memory.
"""
import memmap
import argparse
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import timedemo
from elf import read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name', required=True)
    p.add_argument('--disk', type=Path, default=timedemo.ROOT/'build/wolf-hd.po')
    p.add_argument('--elf', type=Path, default=timedemo.ROOT/'build/wolf.elf')
    p.add_argument('--repeat', type=int, default=2)
    p.add_argument('--view', type=int, choices=(160,214,240,320), default=214)
    p.add_argument('--expect', choices=('clock', 'pictures', 'measure'), default='clock')
    p.add_argument('--deaths', action='store_true', help='observe death states at completed pictures separately from plain timings')
    a = p.parse_args()
    out = timedemo.ROOT/'build/tests'/a.name
    out.mkdir(parents=True, exist_ok=False)
    _, symbols = read(a.elf)
    shutil.copy2(a.elf, out/'wolf.elf')
    reports = []
    lua = r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local active,packets,pending,frames=false,0,0,0
local first,previous,anchor=nil,nil,nil
@DEATH_OBSERVER@
for _,name in ipairs({"a2_config","bus_timing","ram_start","ram_seed"}) do
 local port=manager.machine.ioport.ports[":"..name]
 if port then print("SETTING "..name.." "..port:read()) end
end
s:install_write_tap(0x3e4,0x3e4,'attract-screen',function(_,d)
 if d~=13 or active then return end
 active=true;anchor=s:read_u16(0x1046)
 if s:read_u16(TIMED)~=0 or s:read_u16(WIDTH)~=EXPECTED_WIDTH then
  print('ERROR incorrect automatic-demo mode or view');manager.machine:exit();return
 end
 print(string.format('AUTOMATIC_START %.9f',manager.machine.time:as_double()))
end)
s:install_write_tap(0x3f7,0x3f7,'attract-packet',function(_,d)
 if not active or d~=1 then return end
 packets=packets+1;pending=pending+1
 if first==nil then first=manager.machine.time:as_double();previous=first end
end)
s:install_write_tap(0x3f0,0x3f0,'attract-frame',function(_,d)
 if not active or d~=2 or pending==0 then return end
 local now=manager.machine.time:as_double()
 frames=frames+1
 print(string.format('FRAME %d %d %.9f',frames,packets*4,now-previous))
 print(string.format('PRESENTED %d %d %d',frames,pending,(s:read_u16(0x104c)-s:read_u16(0x1046))&65535))
 @DEATH_FRAME@
 previous=now;pending=0
end)
s:install_write_tap(0x3f5,0x3f5,'attract-end',function(_,d)
 if not active or d~=2 then return end
 if first==nil then print('ERROR no automatic-demo frames')
 else
  print(string.format('PACKETS %d',packets))
  print(string.format('CLOCK_TICKS %d',(s:read_u16(0x1046)-anchor)&65535))
  print(string.format('DONE %d %.9f',frames,previous-first))
  print(string.format('REFRESH %.6f',1/manager.machine.screens[":screen"].frame_period))
 end
 manager.machine:exit()
end)
emu.register_frame_done(function()
 if manager.machine.time:as_double()>@LIMIT@ then
  print('ERROR automatic-demo timeout');manager.machine:exit()
 end
end)
'''
    logic = json.loads((timedemo.ROOT/'build/assets/logic.json').read_text())
    state_ids = logic['states']
    death_observer = memmap.fill(r'''
local shown={}
local function observeDeaths(now)
 local ob=s:read_u16(OBJECTS+42)
 while ob~=0 do
  local state=s:read_u16(@MM:ART_FULL@+ob+16)
  if DEATH_STATES[state] and shown[ob]~=state then
   print(string.format('DEATH_PRESENT %d %d %d %.9f',ob,state,packets,now-first));shown[ob]=state
  end
  ob=s:read_u16(@MM:ART_FULL@+ob+42)
 end
end
''').replace('OBJECTS',str(memmap.OLD_WORLD+logic['layout']['OBJLIST'])).replace('DEATH_STATES',
        '({'+','.join('[%d]=true'%state_ids['s_grddie'+str(n)] for n in range(1,5))+'})')
    lua=lua.replace('@DEATH_OBSERVER@',death_observer if a.deaths else '').replace(
        '@DEATH_FRAME@','observeDeaths(now)' if a.deaths else '')
    for key, name in [('TIMED','timeDemo'),('WIDTH','viewWidth')]:
        lua = re.sub(r'\b'+key+r'\b', str(symbols[name]), lua)
    lua=lua.replace('EXPECTED_WIDTH',str(a.view//2))
    disk = a.disk.resolve(strict=True)
    timedemo.LUA = lua
    task = SimpleNamespace(machine='apple2gsr1',seed=None,pal=False,view=a.view,demo=0,limit=550,
                           disk=disk,disk2=None,drives=2,mame=timedemo.MAME,host_limit=600)
    results = []
    for n in range(a.repeat):
        target = out/f'run{n+1}'
        r = timedemo.run(task, target)
        log = (target/'mame.log').read_text()
        assert '[LUA ERROR]' not in log and 'ERROR ' not in log
        packets = [int(x) for x in re.findall(r'^PACKETS (\d+)$', log, re.M)]
        presented = [(int(n),int(debt)) for n,debt in re.findall(r'^PRESENTED \d+ (\d+) (\d+)$',log,re.M)]
        counts = [n for n,_ in presented]
        clock_ticks = int(re.search(r'^CLOCK_TICKS (\d+)$',log,re.M)[1])
        assert packets == [1055] and len(counts) == r['frames'] and sum(counts) == packets[0]
        if a.expect == 'pictures':
            assert counts == [1]*packets[0], 'not every recorded state was presented'
        elif a.expect == 'clock':
            # The final picture can end before consuming all due time: there
            # are no recorded commands after the demo's death/end packet.
            assert max(debt for _,debt in presented[:-1])<4, 'demo clock fell behind'
            assert clock_ticks==packets[0]*4, 'recorded ticks were dropped or invented'
        results.append(r)
        print(f'run {n+1}: {packets[0]} packets, {r["frames"]} pictures, {1000/r["mean_ms"]:.3f} FPS', flush=True)
    assert all(r['frame_times'] == results[0]['frame_times'] for r in results), 'native repeats differ'
    r = results[0]
    deaths=[];shown={}
    for ob,state,packet,at in re.findall(r'^DEATH_PRESENT (\d+) (\d+) (\d+) ([\d.]+)$',log,re.M):
        ob,state,packet,at=int(ob),int(state),int(packet),float(at)
        if state==state_ids['s_grddie1']:
            shown[ob]=[(state,packet,at)]
        elif ob in shown:
            shown[ob].append((state,packet,at))
            if state==state_ids['s_grddie4']:
                poses=shown.pop(ob)
                deaths.append(dict(actor=(ob-logic['layout']['OBJLIST'])//64,
                    first_packet=poses[0][1],corpse_packet=packet,seconds=at-poses[0][2],
                    animated_poses=len(poses)-1))
    if a.deaths and a.expect=='clock':
        assert len(deaths)>=10 and any(d['first_packet']>=800 for d in deaths), 'missing crowded deaths'
        tolerance=max(x['ns'] for x in r['frame_times'])/1e9+4/70
        assert all(abs(d['seconds']-45/70)<=tolerance for d in deaths), 'death timing at picture completion drifted'
    reports.append(dict(view=a.view,packets=packets[0],pictures=r['frames'],seconds=r['seconds'],
                        fps=1000/r['mean_ms'],mean_ms=r['mean_ms'],
                        worst_ms=max(x['ns'] for x in r['frame_times'])/1e6,
                        clock_ticks=clock_ticks,max_sampled_debt=max(d for _,d in presented),
                        max_active_sampled_debt=max(d for _,d in presented[:-1]),
                        final_sampled_debt=presented[-1][1],
                        max_packets_per_picture=max(counts),observed_deaths=deaths,
                        identical_runs=len(results),disk_sha256=timedemo.sha(disk),settings=r['settings']))
    (out/'result.json').write_text(json.dumps(dict(cases=reports,elf_sha256=timedemo.sha(a.elf),
        mame_sha256=timedemo.sha(timedemo.MAME),expectation=a.expect,actor_observations=a.deaths),indent=2)+'\n')


if __name__ == '__main__':
    main()
