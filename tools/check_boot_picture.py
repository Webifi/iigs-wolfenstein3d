"""The loading picture: in its colors while the disks load, intact when the game has started, black before the PG-13 page.

Usage: check_boot_picture.py --name NAME [--media hd|one|two]

An observer script runs in stock MAME (tools/ui_test.py). It compares the screen with the aligned build/assets/boot-shared.shr record packed by the disk builder:
 - from the moment the row palettes and palettes 0 and 1 of the screen equal the record (the loader writes them
   first), each video frame is counted when palettes 0 and 1 differ. The time when every row of the picture has its
   pixels (two bytes of each row, every sixth frame) is in the report; The game writes them once while it starts
   (InitFlash in keys.s) and UiBootCells puts them back, so at most one frame may differ;
 - at MenuBoot the pixels of rows 0-190, the row palettes and the 16 palettes equal the record;
 - through the final boot music load, pixels and row palettes stay intact, including transient writes;
 - at PgPage, after BootPicture, every palette and the pixels sampled are black.
The report is build/tests/NAME/boot-picture.json.
"""
import memmap
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from elf import read
import test_media

ROOT = Path(__file__).resolve().parents[1]

OBSERVER = memmap.fill(r'''
local s = mem
local rec = {}
do
  local f = assert(io.open(@RECORD@, "rb"))
  local data = f:read("a")
  f:close()
  for i = 1, #data do rec[i - 1] = data:byte(i) end
end
local PIX, SCB, PAL = @MM:SHR@, @MM:SHR_SCB@, @MM:SHR_PAL@
local function bad(addr, offset, count)
  local n = 0
  for i = 0, count - 1 do
    if s:read_u8(addr + i) ~= rec[offset + i] then n = n + 1 end
  end
  return n
end
local armed, frames, badFrames, firstBad, armedAt = false, 0, 0, nil, nil
local boot, pg, fading = false, false, false
local wrongWrites = 0
bootWrites = mem:install_write_tap(PIX, PIX + 191 * 160 - 1, "boot-picture-writes", function(a, d, m)
  if boot and not fading and d ~= rec[a - PIX] then wrongWrites = wrongWrites + 1 end
end)
bootRows = mem:install_write_tap(SCB, SCB + 199, "boot-row-writes", function(a, d, m)
  if boot and not fading and d ~= rec[32000 + a - SCB] then wrongWrites = wrongWrites + 1 end
end)
bootColors = mem:install_write_tap(PAL, PAL + 511, "boot-palette-writes", function(a, d, m)
  if boot and not fading and d ~= rec[0x7e00 + a - PAL] then wrongWrites = wrongWrites + 1 end
end)
fadeTap = mem:install_read_tap(@FADEOUT@, @FADEOUT@, "boot-fade", function(a, d, m)
  if cpu.state.PC.value ~= a + 1 or not boot or fading then return end
  fading = true
  local empty = 0
  for cell = 0, 37 do
    for y = 193, 197 do
      for x = 44 + cell * 7, 48 + cell * 7 do
        local byte = s:read_u8(PIX + y * 160 + (x // 2))
        local color = x % 2 == 0 and (byte >> 4) or (byte & 15)
        if color ~= 5 then empty = empty + 1 end
      end
    end
  end
  print("BOOT_BAR_UNFILLED_PIXELS " .. empty)
  print(string.format("BOOT_FADE pixels=%d rows=%d palettes=%d wrong_writes=%d",
    bad(PIX, 0, 191 * 160), bad(SCB, 32000, 200), bad(PAL, 0x7e00, 512), wrongWrites))
end)
local whole = false
local function sampled()
  for y = 0, 190 do
    for _, x in ipairs({40, 120}) do
      if s:read_u8(PIX + y * 160 + x) ~= rec[y * 160 + x] then return false end
    end
  end
  return true
end
emu.register_frame_done(function()
  if boot then return end
  local now = manager.machine.time:as_double()
  if armed and not whole and frames % 6 == 0 and sampled() then
    whole = true
    print(string.format("PICTURE_WHOLE %.3f", now))
  end
  local p01 = bad(PAL, 0x7e00, 64)
  if not armed then
    if p01 == 0 and bad(SCB, 32000, 200) == 0 then
      armed = true; armedAt = now
      print(string.format("PICTURE_COLORS %.3f", now))
    end
    return
  end
  frames = frames + 1
  if p01 ~= 0 then
    badFrames = badFrames + 1
    if not firstBad then firstBad = now end
  end
end)
bootTap = mem:install_read_tap(@MENUBOOT@, @MENUBOOT@, "menuboot", function(a, d, m)
  if cpu.state.PC.value ~= a + 1 or boot then return end
  boot = true
  print(string.format("MENUBOOT %.3f frames=%d bad_frames=%d", manager.machine.time:as_double(), frames, badFrames))
  print("PIXELS_BAD " .. bad(PIX, 0, 191 * 160))
  print("SCB_BAD " .. bad(SCB, 32000, 200))
  print("PALETTES_BAD " .. bad(PAL, 0x7e00, 512))
end)
pgTap = mem:install_read_tap(@PGPAGE@, @PGPAGE@, "pgpage", function(a, d, m)
  if cpu.state.PC.value ~= a + 1 or pg then return end
  pg = true
  local lit, pixels = 0, 0
  for i = 0, 511 do if s:read_u8(PAL + i) ~= 0 then lit = lit + 1 end end
  for y = 0, 199, 3 do for x = 0, 159, 3 do if s:read_u8(PIX + y * 160 + x) ~= 0 then pixels = pixels + 1 end end end
  print(string.format("BLACK_AT_PGPAGE %.3f palette_bytes=%d pixels=%d", manager.machine.time:as_double(), lit, pixels))
  manager.machine:exit()
end)
''')

KEEPER = r'''
local s = mem
local keeperDisk1 = @DISK1@
local needDisk1 = false
needTap = mem:install_read_tap(@NEEDWAIT@, @NEEDWAIT@, "need-wait", function(a, d, m)
  if cpu.state.PC.value == a + 1 and not pg then needDisk1 = true end
end)
foundTap = mem:install_read_tap(@NEEDDONE@, @NEEDDONE@, "need-done", function(a, d, m)
  if cpu.state.PC.value == a + 1 then needDisk1 = false end
end)
emu.register_frame_done(function()
  if not needDisk1 then return end
  local drive = manager.machine.images[":fdc:2:35dd"]
  if not drive.exists then drive:load(keeperDisk1); print("BOOT_DISK1") end
end)
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--media', choices=('hd', 'one', 'two'), default='hd')
    ap.add_argument('--mame', type=Path, help='emulator binary, including a J13-capable kit')
    ap.add_argument('--j13', choices=('off', 'only', 'both'), default='off')
    ap.add_argument('--record', type=Path, default=ROOT/'build/assets/boot-shared.shr')
    args = ap.parse_args()
    out = ROOT / 'build/tests' / args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT / 'build/wolf.elf')
    script = OBSERVER
    for token, value in (('RECORD', json.dumps(str(args.record.resolve()))), ('MENUBOOT', symbols['MenuBoot']),
                         ('PGPAGE', symbols['PgPage']), ('FADEOUT', symbols['FadeOut'])):
        script = script.replace('@' + token + '@', str(value))
    command = [sys.executable, 'tools/ui_test.py', '--name', args.name, '--j13', args.j13]
    if args.mame:
        command += ['--mame', str(args.mame)]
    if args.media == 'hd':
        seconds = 90
        command.append('--hd')
    else:
        # The loader asks for disk 2 or 3 while it loads, and the front end asks for disk 1 after it.
        _, swaps = test_media.prepare(ROOT / 'build/disk1.po', out, drives=1 if args.media == 'one' else 2)
        script += '\n' + KEEPER.replace('@DISK1@', json.dumps(str(out / 'disk1.po'))) \
            .replace('@NEEDWAIT@', str(symbols['needWait'])).replace('@NEEDDONE@', str(symbols['needDone']))
        script += '\nlocal s = mem\n' + swaps
        seconds = 420
        if args.media == 'two':
            command += ['--disk2', str(out / 'disk2.po')]
    (out / 'observe.lua').write_text(script)
    command += ['--seconds', str(seconds), '--steps', 'sleep=%d;end=' % (seconds - 1), '--lua', str(out / 'observe.lua')]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=seconds * 2 + 150)
    (out / "driver.log").write_text(run.stdout + run.stderr)
    if run.returncode:
        raise SystemExit((run.stdout + run.stderr)[-2500:])
    log = (out / 'mame.log').read_text()
    colors = re.search(r'^PICTURE_COLORS ([\d.]+)$', log, re.M)
    whole = re.search(r'^PICTURE_WHOLE ([\d.]+)$', log, re.M)
    boot = re.search(r'^MENUBOOT ([\d.]+) frames=(\d+) bad_frames=(\d+)$', log, re.M)
    black = re.search(r'^BLACK_AT_PGPAGE ([\d.]+) palette_bytes=(\d+) pixels=(\d+)$', log, re.M)
    assert colors, 'the screen never held the palettes and the row palettes of the picture'
    assert whole, 'the picture was never whole on the screen'
    assert boot and black, 'no MenuBoot or no PgPage seen'
    fade = re.search(r'^BOOT_FADE pixels=(\d+) rows=(\d+) palettes=(\d+) wrong_writes=(\d+)$', log, re.M)
    assert fade, 'the boot fade was not seen'
    bar = re.search(r'^BOOT_BAR_UNFILLED_PIXELS (\d+)$', log, re.M)
    assert bar and int(bar[1]) == 0, 'the boot bar did not fill every cell before fading'
    counts = {k: int(re.search(r'^%s (\d+)$' % k, log, re.M).group(1)) for k in ('PIXELS_BAD', 'SCB_BAD', 'PALETTES_BAD')}
    report = dict(media=args.media, j13=args.j13, colors_from=float(colors.group(1)), whole_at=float(whole.group(1)),
                  menuboot_at=float(boot.group(1)),
                  frames_with_the_picture=int(boot.group(2)), frames_with_wrong_palettes_0_and_1=int(boot.group(3)),
                  pixels_bad=counts['PIXELS_BAD'], row_palettes_bad=counts['SCB_BAD'], palettes_bad=counts['PALETTES_BAD'],
                  black_at=float(black.group(1)), black_palette_bytes=int(black.group(2)), black_pixels=int(black.group(3)),
                  record_sha256=hashlib.sha256(args.record.read_bytes()).hexdigest(),
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((ROOT/('build/wolf-hd.po' if args.media=='hd' else 'build/disk1.po')).read_bytes()).hexdigest())
    report['final_load'] = dict(zip(('pixels_bad', 'row_palettes_bad', 'palettes_bad', 'wrong_writes'), map(int, fade.groups())))
    (out / 'boot-picture.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    failures = []
    if report['frames_with_wrong_palettes_0_and_1'] > 1:
        failures.append('palettes 0 and 1 were wrong in %d frames' % report['frames_with_wrong_palettes_0_and_1'])
    if report['pixels_bad'] or report['row_palettes_bad'] or report['palettes_bad']:
        failures.append('the screen differs from the record at MenuBoot')
    if any(report['final_load'].values()):
        failures.append('the final load overwrites the visible boot picture')
    if report['black_palette_bytes'] or report['black_pixels']:
        failures.append('the screen is not black at PgPage')
    if failures:
        raise SystemExit('FAILED: ' + '; '.join(failures))
    print('boot picture ok')


if __name__ == '__main__':
    main()
