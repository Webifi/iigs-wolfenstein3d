"""Bytes that a frame's paint writes twice to the screen with a wrong value in between.

The screen is shown while it is painted, so a byte that holds a value that is neither its old
value nor its final value for a while is a visible flaw that no end-of-frame picture check can
see. Every write that reaches the view while the paint runs (the game's $03F3 markers; a store to bank $01 counts
while SHR shadowing is on) is timed; a byte
written more than once is wrong between two writes when the value it holds is not the one it
ends with (the review's definition) and, strictly, not the one it had before the frame either.

The expected number of wrong 2-pixel spots per frame is the summed time that bytes spend wrong
divided by the refresh period: one raster pass sees a byte that is wrong for t seconds with
probability t / (1/60 s).

Usage: python3 tools/paint_twice.py NAME DISK ELF [--demos 0 1 2 3] [--views 214 320]
Writes build/tests/NAME/summary.json and prints one line per case. One MAME at a time, headless.
Run paint_write_compare.py after the pair completes. A successful comparison
retains hashes and removes raw streams by default; --keep-captures overrides it.
"""
import memmap
import argparse, json, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import timedemo

p = argparse.ArgumentParser()
p.add_argument('name')
p.add_argument('disk', type=Path)
p.add_argument('elf', type=Path)
p.add_argument('--views', nargs='+', type=int, default=[214, 320])
p.add_argument('--demos', nargs='+', type=int, default=[0, 1, 2, 3])
p.add_argument('--frames-json', action='store_true', help='keep the per-frame rows in the summary')
p.add_argument('--capture-writes', action='store_true', help='capture pixels from write taps, without timing-perturbing screen reads')
a = p.parse_args()
a.disk = a.disk.resolve(strict=True)
a.elf = a.elf.resolve(strict=True)
if a.disk.stat().st_mtime_ns < a.elf.stat().st_mtime_ns:
    raise SystemExit('Disk predates ELF: finish the build or use a preserved matching pair')
out = timedemo.ROOT / 'build/tests' / a.name
out.mkdir(parents=True, exist_ok=True)

# The tap is installed before the demo starts; the guard prelude of the test tools removes it at stop.
EXTRA = memmap.fill(r'''
local twiceOn, twiceLast, twiceIv, twiceOld = false, {}, {}, {}
local twiceCases = {}
local function twiceReport(frame)
  local multi, expoBytes, expoUs, wrongBytes, wrongUs = 0, 0, 0, 0, 0
  for addr, iv in pairs(twiceIv) do
    multi = multi + 1
    local final = twiceLast[addr][2]
    local e, w = 0, 0
    for _, x in ipairs(iv) do
      if x[3] ~= final then
        e = e + (x[2] - x[1])
        if x[3] ~= twiceOld[addr] then w = w + (x[2] - x[1]) end
      end
    end
    if e > 0 then expoBytes = expoBytes + 1; expoUs = expoUs + math.floor(e * 1e6 + 0.5) end
    if w > 0 then wrongBytes = wrongBytes + 1; wrongUs = wrongUs + math.floor(w * 1e6 + 0.5) end
  end
  print(string.format("TWICE %d %d %d %d %d %d", frame, multi, expoBytes, expoUs, wrongBytes, wrongUs))
  twiceLast, twiceIv, twiceOld = {}, {}, {}
end
s:install_write_tap(0x3f3, 0x3f3, "paint-phase", function(addr, d, m)
  if d == 1 then twiceOn = true elseif d == 2 then twiceOn = false end
end)
local function twiceWrite(addr, d)
  local tw = manager.machine.time:as_double()
  local v = d & 255
  local w = twiceLast[addr]
  if w == nil then
    twiceLast[addr] = {tw, v}
    twiceOld[addr] = s:read_u8(addr)
  else
    local iv = twiceIv[addr]
    if iv == nil then iv = {}; twiceIv[addr] = iv end
    iv[#iv + 1] = {w[1], tw, w[2]}
    w[1] = tw; w[2] = v
  end
end
s:install_write_tap(@MM:SHR@, @MM:SHR+0x7cff@, "screen", function(addr, d, m)
  if twiceOn then twiceWrite(addr, d) end
end)
-- A store to bank $01 reaches the screen only while SHR shadowing is on (bit 3 of $C035 clear);
-- otherwise it fills the mirror and shows nothing. The screen byte is the same offset in $E1.
s:install_write_tap(@MM:WALL_COLUMNS@, @MM:SHR_SHADOW+0x7cff@, "mirror", function(addr, d, m)
  if twiceOn and (s:read_u8(@MM:SHADOW@) & 8) == 0 then twiceWrite(@MM:BANK_E1@ | (addr & 0xffff), d) end
end)
''')
base = timedemo.LUA
if a.capture_writes:
    # Observe bus writes only. Reading the screen from a Lua callback marks
    # a slow cycle in this machine model and changes the next CPU access.
    EXTRA = EXTRA.replace('local twiceOn,', memmap.fill('''local screenBytes, screenKnown = {}, {}
local shadowReg = 255
local pixelFile = nil
s:install_write_tap(@MM:SHADOW@, @MM:SHADOW@, "shadow-state", function(addr,d,m) shadowReg=d end)
s:install_write_tap(@MM:SHADOW_00@, @MM:SHADOW_00@, "shadow-state-bank0", function(addr,d,m) shadowReg=d end)
local function screenWrite(addr,d)
  screenBytes[addr-@MM:SHR@]=d & 255
  screenKnown[addr-@MM:SHR@]=true
end
local function captureWrites()
  if pixelFile == nil then pixelFile=assert(io.open(@PIXELS@,"wb")) end
  local parts={}
  for i=0,31999 do
    assert(screenKnown[i], "screen byte was never initialized: "..i)
    parts[#parts+1]=string.char(screenBytes[i])
  end
  pixelFile:write(table.concat(parts))
end
emu.add_machine_stop_notifier(function() if pixelFile then pixelFile:close();pixelFile=nil end end)
local twiceOn,'''))
    EXTRA = EXTRA.replace('twiceOld[addr] = s:read_u8(addr)', memmap.fill('twiceOld[addr] = screenBytes[addr-@MM:SHR@]'))
    EXTRA = EXTRA.replace('if twiceOn then twiceWrite(addr, d) end', 'if twiceOn then twiceWrite(addr, d) end;screenWrite(addr,d)')
    EXTRA = EXTRA.replace(memmap.fill('if twiceOn and (s:read_u8(@MM:SHADOW@) & 8) == 0 then twiceWrite(@MM:BANK_E1@ | (addr & 0xffff), d) end'),
                          memmap.fill('if (shadowReg & 8) == 0 then local dest=@MM:BANK_E1@ | (addr & 0xffff);if twiceOn then twiceWrite(dest,d) end;screenWrite(dest,d) end'))
script = base.replace('local first, previous, frames', EXTRA + '\nlocal first, previous, frames')
script = script.replace('frames=frames+1', 'frames=frames+1\n    twiceReport(frames)')
if a.capture_writes:
    script = script.replace('twiceReport(frames)', 'twiceReport(frames);captureWrites()')
assert script != base and 'twiceReport(frames)' in script
timedemo.LUA = script

summary = dict(disk=str(a.disk), elf=str(a.elf), disk_sha256=timedemo.sha(a.disk),
               elf_sha256=timedemo.sha(a.elf), mame_sha256=timedemo.sha(timedemo.MAME),
               capture_writes=a.capture_writes, cases=[])
for view in a.views:
    for demo in a.demos:
        target = out / f'd{demo}-v{view}'
        if a.capture_writes:
            timedemo.LUA = script.replace('@PIXELS@', json.dumps(str(target / 'frames.pixels')))
        task = SimpleNamespace(machine='apple2gsr1', seed=None, pal=False, view=view, demo=demo, limit=1500,
                               disk=a.disk, disk2=None, drives=2, mame=timedemo.MAME, host_limit=1800)
        result = timedemo.run(task, target)
        rows = []
        for line in (target / 'mame.log').read_text().splitlines():
            if line.startswith('TWICE '):
                f = line.split()
                rows.append(dict(frame=int(f[1]), multi=int(f[2]), exposed_bytes=int(f[3]), exposed_us=int(f[4]),
                                 wrong_bytes=int(f[5]), wrong_us=int(f[6])))
        n = len(rows)
        if n != result['frames']:
            raise SystemExit(f'd{demo} v{view}: {n} twice rows for {result["frames"]} frames')
        period = 1e6 / 60.0
        case = dict(demo=demo, view=view, frames=n,
                    multi_written_bytes=sum(r['multi'] for r in rows),
                    exposed_bytes=sum(r['exposed_bytes'] for r in rows),
                    exposed_frames=sum(1 for r in rows if r['exposed_bytes']),
                    expected_spots_per_frame=sum(r['exposed_us'] for r in rows) / period / n,
                    expected_spots_worst_frame=max(r['exposed_us'] for r in rows) / period,
                    worst_frame=max(rows, key=lambda r: r['exposed_us'])['frame'],
                    wrong_bytes=sum(r['wrong_bytes'] for r in rows),
                    wrong_spots_per_frame=sum(r['wrong_us'] for r in rows) / period / n,
                    seconds=result['seconds'])
        case['top20_mean_ms'] = sum(sorted((r['ns'] for r in result['frame_times']), reverse=True)[:20]) / 20e6
        if a.frames_json:
            case['rows'] = rows
        summary['cases'].append(case)
        print('d%d v%d: %d frames, multi-written %d, wrong between writes %d bytes in %d frames, '
              'expected spots %.3f per frame (worst frame %d: %.2f); strictly wrong %d bytes' % (
                  demo, view, n, case['multi_written_bytes'], case['exposed_bytes'], case['exposed_frames'],
                  case['expected_spots_per_frame'], case['worst_frame'], case['expected_spots_worst_frame'],
                  case['wrong_bytes']), flush=True)
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(out / 'summary.json')
if any(c['exposed_bytes'] or c['wrong_bytes'] for c in summary['cases']):
    raise SystemExit('Paint showed wrong bytes between writes')
