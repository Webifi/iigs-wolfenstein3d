"""Compare complete stock frames using the retained engine's demo inputs.

The registered fixture replaces only the cold demo loader with RTL and puts
the retained recording in its packet buffer before starting. Gameplay code,
art, source maps, sound and every timed frame are the actual selected builds.
The result compares whole builds; differing art fits or music are not isolated.
"""
import memmap
import argparse
import json
import re
from pathlib import Path
import struct
from types import SimpleNamespace

from elf import read
import timedemo


PIXELS = memmap.fill(r'''
local picture,history={},{}
local painting=false
local pixelStarted=false
local pixelFile=assert(io.open(@PIXELS@,'wb'))
pixelStartTap=s:install_write_tap(0x3f7,0x3f7,'registered-capture-start',function(a,d,m)
 if active and d==1 and not pixelStarted then history={};pixelStarted=true end
end)
pixelWriteTap=s:install_write_tap(@MM:SHR@,@MM:SHR+0x7cff@,'registered-pixels',function(a,d,m)
 local i=a-@MM:SHR@
 local v=d&255
 if painting then
  if not history[i] then history[i]={old=picture[i],values={}} end
  local values=history[i].values
  values[#values+1]=v
 end
 picture[i]=v
end)
pixelPaintTap=s:install_write_tap(0x3f3,0x3f3,'registered-paint',function(a,d,m)
 if d==1 then painting=true elseif d==2 then painting=false end
end)
local function capturePicture(frame)
 local exposed,wrong=0,0
 for i,h in pairs(history) do
  local seenExposed,seenWrong=false,false
  for _,v in ipairs(h.values) do
   if v~=picture[i] then
    seenExposed=true
    if v~=h.old then seenWrong=true end
   end
  end
  if seenExposed then exposed=exposed+1 end
  if seenWrong then wrong=wrong+1 end
 end
 print(string.format('PIXELS %d %d %d',frame,exposed,wrong))
 local values={}
 for i=0,31999 do
  local value=assert(picture[i],'uninitialized screen byte '..i)
  values[#values+1]=string.char(value)
 end
 pixelFile:write(table.concat(values))
 history={}
end
pixelStop=emu.add_machine_stop_notifier(function() pixelFile:close() end)
''')


def retained_packets(script, symbols, path, demo, count, floor):
    """Replace the cold recording source, leaving timed gameplay untouched."""
    fixture = memmap.fill('''
    local f=assert(io.open(@PATH@,'rb'));local bytes=f:read('*a');f:close()
    for i=1,#bytes do s:write_u8(@MM:DEMOS+0x30@+i-1,bytes:byte(i)) end
    s:write_u16(@MM:DEMOS@+@DEMO@*6,0x8030)
    s:write_u16(@MM:DEMOS+0x2@+@DEMO@*6,@COUNT@)
    s:write_u16(@MM:DEMOS+0x4@+@DEMO@*6,@FLOOR@)
    s:write_u8(@LOAD@,0x6b)
''')
    for key, value in dict(PATH=json.dumps(str(path)), DEMO=demo, COUNT=count,
                           FLOOR=floor, LOAD=symbols['LoadDemoAssets']).items():
        fixture = fixture.replace('@'+key+'@', str(value))
    assert script.count('requested=true') == 1
    return script.replace('requested=true', 'requested=true\n'+fixture, 1)


def command_bank_checks(symbols):
    """Read-only native assertions for cached owners after transparent columns."""
    script = '\ncommandBankTaps={}\n'
    for i, name in enumerate(('fastRun', 'lightRun', 'runLoop', 'soloLoop'), 1):
        pc = symbols[name]
        script += f'''
commandBankTaps[{i}]=s:install_read_tap({pc},{pc},'command-bank-{name}',function(a,d,m)
 if not active or manager.machine:side_effects_disabled() or cpu.state.PC.value~=a+1 then return end
 local rec=s:read_u16(0x10fa)
 if rec<2048 then
  local expected=s:read_u8({symbols['ownerInfo']+12}+rec)
  local actual=s:read_u8(0x1070)
  if actual~=expected then
   print(string.format('ERROR command bank {name} frame %d column %d record %d actual %02x expected %02x',frames+1,s:read_u16(0x102e),rec,actual,expected))
   manager.machine:exit()
  end
 end
end)
'''
    return script


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--name', default='registered-performance')
    p.add_argument('--views', type=int, nargs='+', default=[214, 320])
    p.add_argument('--demos', type=int, nargs='+', default=[0, 1, 2, 3])
    p.add_argument('--check-commands', action='store_true',
                   help='diagnostic: assert each cached sprite command bank while drawing')
    p.add_argument('--compare-pixels', action='store_true',
                   help='require identical floor color mappings, pixels and clean transient writes')
    a = p.parse_args()
    root = timedemo.ROOT
    baseline = a.baseline.resolve()
    directory = (baseline/'assets/demos.bin').read_bytes()
    out = root/'build/tests'/a.name
    out.mkdir(parents=True, exist_ok=False)
    _, symbols = read(root/'build/wolf.elf')
    original = timedemo.LUA
    reports = []
    for demo in a.demos:
        start, count, floor = struct.unpack_from('<3H', directory, demo*6)
        assert (baseline/f'levels/{floor}/map.bin').read_bytes() == (root/f'build/levels/{floor}/map.bin').read_bytes()
        if a.compare_pixels:
            palettes = [json.loads((path/f'palettes/{floor}.json').read_text())
                        for path in (baseline, root/'build')]
            assert all(palettes[0][k] == palettes[1][k] for k in ('palette','wall_lights','sprite_lights')), 'Pixel comparison requires identical color mappings'
        packet = directory[start-0x8000:start-0x8000+count*3]
        assert len(packet) == count*3 and len(packet) <= 0x2fd0
        packet_file = out/f'demo-{demo}.bin'
        packet_file.write_bytes(packet)
        for view in a.views:
            results = []
            for candidate in (False, True):
                folder = out/f'd{demo}-v{view}'/('registered' if candidate else 'retained')
                timedemo.LUA = original
                if candidate:
                    timedemo.LUA = retained_packets(original, symbols, packet_file, demo, count, floor)
                    if a.check_commands:
                        timedemo.LUA += command_bank_checks(symbols)
                if a.compare_pixels:
                    capture = PIXELS.replace('@PIXELS@', json.dumps(str(folder/'frames.pixels')))
                    timedemo.LUA = timedemo.LUA.replace('local first, previous, frames', capture+'\nlocal first, previous, frames')
                    timedemo.LUA = timedemo.LUA.replace('frames=frames+1', 'frames=frames+1\n    capturePicture(frames)')
                disk = root/'build/wolf-hd.po' if candidate else baseline/'wolf-hd.po'
                task = SimpleNamespace(machine='apple2gsr1', seed=None, pal=False, view=view,
                                       demo=demo, limit=1200, disk=disk, disk2=None, drives=2,
                                       mame=timedemo.MAME, host_limit=600)
                result = timedemo.run(task, folder)
                (folder/'result.json').write_text(json.dumps(result, indent=2)+'\n')
                results.append(result)
            before, after = results
            assert before['frames'] == after['frames'], ('frame counts differ', demo, view, before['frames'], after['frames'])
            old = [r['ns']/1e9 for r in before['frame_times']]
            new = [r['ns']/1e9 for r in after['frame_times']]
            # Keep the same crowded frames instead of choosing a new top set.
            slow = sorted(range(len(old)), key=lambda i:old[i], reverse=True)[:20]
            report = dict(demo=demo, view=view, frames=before['frames'],
                          retained_seconds=before['seconds'], registered_seconds=after['seconds'],
                          delta_percent=100*(after['seconds']/before['seconds']-1),
                          same_slow20_retained_ms=sum(old[i] for i in slow)*50,
                          same_slow20_registered_ms=sum(new[i] for i in slow)*50,
                          maximum_frame_delta_ms=max(n-o for n,o in zip(new,old))*1000)
            reports.append(report)
            if a.compare_pixels:
                from frame_capture import capture_index, compact_capture
                paths = [out/f'd{demo}-v{view}'/kind/'frames.pixels' for kind in ('retained','registered')]
                indices = [capture_index(path) for path in paths]
                differences = [i for i,(x,y) in enumerate(zip(indices[0]['frame_sha256'],indices[1]['frame_sha256']),1) if x!=y]
                checks = [re.findall(r'^PIXELS (\d+) (\d+) (\d+)$', (path.parent/'mame.log').read_text(), re.M) for path in paths]
                assert all(len(rows)==before['frames'] for rows in checks)
                report['different_pixel_frames'] = differences
                report['transient_bytes'] = [dict(exposed=sum(int(r[1]) for r in rows),wrong=sum(int(r[2]) for r in rows)) for rows in checks]
                report['pixel_sha256'] = [index['sha256'] for index in indices]
            (out/'summary.json').write_text(json.dumps(dict(cases=reports,
                comparison='complete builds, matched retained demo packets and map bytes',
                command_bank_assertions=a.check_commands,
                candidate_elf_sha256=timedemo.sha(root/'build/wolf.elf'),
                baseline_elf_sha256=timedemo.sha(baseline/'wolf.elf')), indent=2)+'\n')
            print(json.dumps(report), flush=True)
            if a.compare_pixels:
                assert not differences, 'Native pictures differ; raw captures retained'
                assert not any(row['exposed'] or row['wrong'] for row in report['transient_bytes']), 'Transient paint writes differ; raw captures retained'
                for path in paths: compact_capture(path)
    timedemo.LUA = original


if __name__ == '__main__':
    main()
