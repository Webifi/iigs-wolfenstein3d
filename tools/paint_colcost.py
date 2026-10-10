"""Phase A time per column, by class, from the writes of COL ($102E): the time between two writes is the
previous column's preparation. Key = world owners, marks byte this frame, marks byte last frame, weapon state
(0 none, 1 same runs, 2 changed). One run, any build:
  python3 tools/paint_colcost.py NAME DISK --elf ELF [--demos 0] [--views 214]
Writes build/tests/NAME/dD-vV/colcost.json: {frame: {key: [columns, microseconds]}}."""
import memmap
import argparse, json, sys, collections
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
import timedemo
from elf import read
p = argparse.ArgumentParser()
p.add_argument('name'); p.add_argument('disk', type=Path)
p.add_argument('--demos', nargs='+', type=int, default=[0]); p.add_argument('--views', nargs='+', type=int, default=[214])
p.add_argument('--elf', type=Path, required=True)
a = p.parse_args()
_, SYMS = read(a.elf)
a.disk = a.disk.resolve(strict=True)
out = timedemo.ROOT / 'build/tests' / a.name
out.mkdir(parents=True, exist_ok=True)
EXTRA = memmap.fill(r'''
local ccOn, ccPrevT, ccPrevKey, ccFrameStart = false, nil, nil, nil
local ccAgg = {}
local ccFrameRows = {}
s:install_write_tap(0x3f3, 0x3f3, "cc-mark", function(addr, d, m)
  local t = manager.machine.time:as_double()
  if d == 1 then ccOn = true; ccPrevT = nil; ccPrevKey = nil
  elseif d == 2 then
    ccOn = false
  end
end)
s:install_write_tap(0x102e, 0x102e, "cc-col", function(addr, d, m)
  if not ccOn then return end
  local t = manager.machine.time:as_double()
  if ccPrevT and ccPrevKey then
    local e = ccAgg[ccPrevKey]
    if not e then e = {0, 0}; ccAgg[ccPrevKey] = e end
    e[1] = e[1] + 1; e[2] = e[2] + (t - ccPrevT)
  end
  local c = d & 255
  local mask = s:read_u16(@MM:COLUMN_MASKS@ + 2 * c)
  local n = 0; local mm = mask
  while mm ~= 0 do n = n + (mm & 1); mm = mm >> 1 end
  local wt, owt = s:read_u16(@WT@), s:read_u16(@OWT@)
  local np, op = s:read_u16(@MM:WEAPON_RUNS@ + wt + 2 * c), s:read_u16(@MM:WEAPON_RUNS@ + owt + 2 * c)
  local nr, orr = s:read_u8(@MM:WEAPON_RUNS@ + np), s:read_u8(@MM:WEAPON_RUNS@ + op)
  local ws = 0
  if nr ~= 0 or orr ~= 0 then if np == op then ws = 1 else ws = 2 end end
  ccPrevKey = string.format("%d,%02x,%02x,%d", n, s:read_u8(@MM:MARKS@ + c), s:read_u8(@MM:OLD_MARKS@ + c), ws)
  ccPrevT = t
end)
local function ccReport(frame)
  local parts = {}
  for k, e in pairs(ccAgg) do parts[#parts + 1] = string.format("%s=%d:%.0f", k, e[1], e[2] * 1e6) end
  print("CC " .. frame .. " " .. table.concat(parts, " "))
  ccAgg = {}
end
''').replace('@WT@', str(SYMS['weaponMaskTable'])).replace('@OWT@', str(SYMS['oldWeaponMaskTable']))
base = timedemo.LUA
script = base.replace('local first, previous, frames', EXTRA + '\nlocal first, previous, frames')
script = script.replace('frames=frames+1', 'frames=frames+1\n    ccReport(frames)')
assert script != base
timedemo.LUA = script
for view in a.views:
    for demo in a.demos:
        target = out / f'd{demo}-v{view}'
        task = SimpleNamespace(machine='apple2gsr1', seed=None, pal=False, view=view, demo=demo, limit=1500, disk=a.disk, disk2=None, drives=2, mame=timedemo.MAME, host_limit=1800)
        result = timedemo.run(task, target)
        frames = {}
        for line in (target / 'mame.log').read_text().splitlines():
            if line.startswith('CC '):
                f = line.split()
                d = {}
                for item in f[2:]:
                    k, v = item.split('='); n, us = v.split(':'); d[k] = (int(n), float(us))
                frames[int(f[1])] = d
        json.dump(frames, open(target / 'colcost.json', 'w'))
        print('d%d v%d' % (demo, view), len(frames), 'frames', result['seconds'], flush=True)
