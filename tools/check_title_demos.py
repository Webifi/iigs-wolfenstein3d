"""Observe the real title cycle and its nonblocking floppy floor probes."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
import floor_capture
import test_media
import music_capture

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument('--name', required=True)
ap.add_argument('--floppy', action='store_true', help='only disk 1 is present; missing floors must be skipped')
args = ap.parse_args()
out = ROOT / 'build/tests' / args.name
out.mkdir(parents=True, exist_ok=True)
_, symbols = read(ROOT / 'build/wolf.elf')
expected = [0, 0] if args.floppy else [0, 1, 2, 3, 0]
observer = memmap.fill(r'''
local seen=0
local started=false
titleTap=mem:install_write_tap(0x3e4,0x3e4,"title-cycle",function(a,d,m)
 if d~=13 then return end
 started=true;seen=seen+1
 if seen==1 then
  local banks={}
  for i=0,8 do banks[#banks+1]=string.format("%02x",mem:read_u8(0x7e14+i)) end
  print("TITLE_RAM "..table.concat(banks,""))
 end
 print(string.format("TITLE_DEMO %.9f %d %d",manager.machine.time:as_double(),
       mem:read_u16(DEMONUMBER),mem:read_u16(FLOOR)))
 if seen==COUNT then manager.machine:exit() end
end)
probeTap=mem:install_read_tap(@PROBE@,@PROBE@,"title-probe",function(a,d,m)
 if started then print("TITLE_PROBE "..(cpu.state.A.value&32767)) end
end)
emu.register_frame_done(function()
 if not started then return end
 for _,base in ipairs({@MM:DISK_PROMPT_00@,@MM:DISK_PROMPT@}) do
  local prompt=""
  for i=0,12 do prompt=prompt..string.char(mem:read_u8(base+i)&127) end
  if prompt:match("^INSERT DISK %d$") then print("TITLE_BLOCKED "..prompt);manager.machine:exit() end
 end
end)
''')
for token, value in [('DEMONUMBER', symbols['demoNumber']), ('FLOOR', symbols['levelIndex']),
                     ('@PROBE@', symbols['ProbeFloorData']), ('COUNT', len(expected))]:
    observer = observer.replace(token, str(value))
observer += music_capture.lua()
(out / 'observe.lua').write_text(observer)
if args.floppy:
    assets = floor_capture.lua(out, floor=0, trigger=0x3e4, value=13)
    assets = assets.replace(' or assetsChecked', '').replace('  assetsChecked=true', '')
    observer = 'local s=mem\n' + assets + '\n' + observer
    # Boot may need disk 2 for resident sound. Once the front end opens,
    # only disk 1 remains available; a title demo must never prompt.
    _, boot_swaps = test_media.prepare(ROOT / 'build/disk1.po', out, drives=1)
    boot_swaps = boot_swaps.replace('emu.register_frame_done(function()',
                                   'emu.register_frame_done(function()\n if titleBootDone then return end', 1)
    observer += '''
local s=mem
local titleBootDone=false
local titleNeedsDisk1=false
bootDisk1Tap=mem:install_read_tap(@READYDISK1@,@READYDISK1@,"boot-menu-disk",function(a,d,m)
 if cpu.state.PB.value==0x3f and not titleBootDone then titleNeedsDisk1=true end
end)
emu.register_frame_done(function()
 local page=mem:read_u8(0x3e4)
 if page==14 or page==1 then titleBootDone=true end
 if titleNeedsDisk1 and not titleBootDone then
  local drive=manager.machine.images[":fdc:2:35dd"]
  if not drive.exists then drive:load(@DISK1@);print("BOOT_MENU_DISK1") end
 end
end)
''' + boot_swaps
    # The floppy must finish ejecting before the test inserts disk 1.
    observer = observer.replace('@READYDISK1@', str(symbols['needWait']))
    observer = observer.replace('@DISK1@', json.dumps(str(out / 'disk1.po')))
    (out / 'observe.lua').write_text(observer)
command = [sys.executable, 'tools/ui_test.py', '--name', args.name, '--seconds', '1400',
           '--steps', 'sleep=1399;end=', '--lua', str(out / 'observe.lua')]
if not args.floppy:
    command.append('--hd')
subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
log = (out / 'mame.log').read_text()
visits = [dict(seconds=float(t), demo=int(d), floor=int(f))
          for t, d, f in re.findall(r'^TITLE_DEMO ([\d.]+) (\d+) (\d+)$', log, re.M)]
probes = list(map(int, re.findall(r'^TITLE_PROBE (\d+)$', log, re.M)))
assert 'TITLE_BLOCKED' not in log, 'title loop asked for a missing disk'
assert [r['demo'] for r in visits] == expected, visits
assert all(r['floor'] == 2*r['demo'] for r in visits), visits
assert set(probes) >= ({2, 4, 6} if args.floppy else {0, 2, 4, 6}), probes
ram = re.findall(r'^TITLE_RAM ([0-9a-f]+)$', log, re.M)
assert ram == ['ffffffffffffffff03'], ram
if args.floppy:
    assert re.findall(r'^ASSETS_DONE (\d+)$', log, re.M) == ['0', '0'], 'floor assets changed across skipped probes'
song_events = music_capture.events(log)
assert [e['song'] for e in song_events] == ([7,3,7,3] if args.floppy else [7,3,7,9,7,3,7,9,7,3]), song_events
disk = ROOT / ('build/disk1.po' if args.floppy else 'build/wolf-hd.po')
report = dict(disk_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(),
              elf_sha256=hashlib.sha256((ROOT / 'build/wolf.elf').read_bytes()).hexdigest(),
              floppy=args.floppy, visits=visits, probes=probes, blocking_prompts=0,
              song_starts=song_events, glu_violations=0,
              required_ram_bank_bits=ram[0], assets_before_and_after=args.floppy)
(out / 'title-check.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
