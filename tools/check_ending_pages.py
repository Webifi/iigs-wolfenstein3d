"""The victory page and the ending pages: each one is on the screen in a few seconds, and every pixel is as the lump says.

Usage: check_ending_pages.py --name NAME [--media hd|one|two]

The test starts a game, ends the episode through the victory state (the same fixture as tools/wait_times.py), and presses
Return at the victory page and at the first ending page. An observer script runs in stock MAME (tools/ui_test.py). It times
each VictoryShow and EndShow call, from its entry to the end of EpisodeEnd, and dumps the screen memory at that moment
(32,768 bytes from $E1:2000: pixels, row palettes, palettes).
The expected pictures are the lumps of build/assets/menu.bin (tools/art_lumps.py). An ending page is the whole record. The
victory page is the 160 rows of its record with the digits that the game draws: the test sets 15 seconds on each of the 8
floors, so the time is 02:00, and the ratios 80, 40 and 100; each digit goes through the table of the palette of its row. Rows
160-199 (the status bar) are not compared; the row palettes 0-159 and the palettes 0, 13, 14 and 15 are. Each call must take
less than LIMIT seconds. The report is build/tests/NAME/ending-pages.json.
"""
import memmap
import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

from elf import read
import logic_capture
import test_media
from check_boot_picture import KEEPER

ROOT = Path(__file__).resolve().parents[1]
DUMP_BYTES = 32768                      # pixels, row palettes, palettes
LIMIT = 1.0

OBSERVER = memmap.fill(r'''
local s = mem
@LOGIC@
FRAMEADDR = @FRAMECOUNT@                  -- the step waitframes of ui_test.py counts the frames of the game here
local pg = false
CALLS = CALLS or {}
CALLS.victory = function()
  for i = 0, 7 do
    s:write_u16(@RATIOS@ + i * 8, 80)
    s:write_u16(@RATIOS@ + i * 8 + 2, 40)
    s:write_u16(@RATIOS@ + i * 8 + 4, 100)
    s:write_u16(@RATIOS@ + i * 8 + 6, 15)
  end
  s:write_u16(LC.V_playstate, 6)
end
local started, shown = nil, 0
startTaps = {}
for _, entry in ipairs({@VICTORYSHOW@, @ENDSHOW@}) do
  startTaps[#startTaps + 1] = mem:install_read_tap(entry, entry, "show" .. entry, function(a, d, m)
    if cpu.state.PC.value ~= a + 1 then return end
    started = manager.machine.time:as_double()
  end)
end
doneTap = mem:install_read_tap(@EPOUT@, @EPOUT@, "epout", function(a, d, m)
  if cpu.state.PC.value ~= a + 1 or not started then return end
  local took = manager.machine.time:as_double() - started
  started = nil
  local parts = {}
  for i = 0, @DUMP@ - 1 do parts[#parts + 1] = string.char(s:read_u8(@MM:SHR@ + i)) end
  local f = assert(io.open(@PATH@ .. "/page-" .. shown .. ".bin", "wb"))
  f:write(table.concat(parts))
  f:close()
  print(string.format("ENDING_PAGE %d %.4f", shown, took))
  shown = shown + 1
end)
''')


def lumps():
    """The page lumps of menu.bin: {name: bytes}."""
    names = {m.group(1): int(m.group(2)) for m in re.finditer(r'^LUMP_(\w+)\s+\.equ\s+(\d+)', (ROOT / 'build/gen/menu.inc').read_text(), re.M)}
    raw = (ROOT / 'build/assets/menu.bin').read_bytes()
    out = {}
    for name in ('VICTORY', 'END1', 'END2'):
        first, count, _, size = struct.unpack_from('<HHHH', raw, 8 + 8 * names[name])
        out[name] = raw[first * 512:(first + count) * 512]
    return out


def model_victory(rec):
    """The 160 rows of the victory page with the digits of the test: 15 seconds on each of the 8 floors, so 02:00, and the
    ratios 80, 40 and 100."""
    screen = bytearray(rec[:25600])
    tables = rec[25600:25600 + 256]
    glyphs = rec[25600 + 256:25600 + 256 + 1280]
    scb = rec[32000:32160]

    def digit(d, x, y):
        for row in range(16):
            table = tables[scb[y + row] * 16:scb[y + row] * 16 + 16]
            for col in range(8):
                b = glyphs[d * 128 + row * 8 + col]
                screen[(y + row) * 160 + x // 2 + col] = table[b >> 4] << 4 | table[b & 15]
    for x, d in ((112, 0), (128, 2), (152, 0), (168, 0)):
        digit(d, x, 64)
    for y, value in zip((112, 128, 144), (80, 40, 100)):
        for k, ch in enumerate(str(value)):
            digit(int(ch), 240 - 16 * len(str(value)) + 16 * k, y)
    return bytes(screen)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--media', choices=('hd', 'one', 'two'), default='hd')
    args = ap.parse_args()
    out = ROOT / 'build/tests' / args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT / 'build/wolf.elf')
    script = OBSERVER.replace('@LOGIC@', 'local s = mem\n' + logic_capture.lua())
    for token, value in (('FRAMECOUNT', symbols['frameCount']), ('ENDSHOW', symbols['EndShow']), ('VICTORYSHOW', symbols['VictoryShow']), ('RATIOS', symbols['ratioTable']),
                         ('EPOUT', symbols['epOut']), ('DUMP', DUMP_BYTES), ('PATH', json.dumps(str(out)))):
        script = script.replace('@' + token + '@', str(value))
    # A floppy reads the song of the victory page first: its steps wait longer. Early keys are lost, never counted.
    settle, gap = (12, 8) if args.media == 'hd' else (60, 20)
    steps = ['wait=1', 'sleep=4', 'key=Return', 'wait=2', 'sleep=6', 'key=Return', 'wait=15', 'sleep=2', 'key=Return', 'wait=3', 'sleep=2', 'key=Return',
             'waitframes=4', 'sleep=3', 'call=victory', 'sleep=%d' % settle, 'key=Return', 'sleep=%d' % gap, 'key=Return',
             'sleep=%d' % gap, 'end=']
    command = [sys.executable, 'tools/ui_test.py', '--name', args.name]
    if args.media == 'hd':
        seconds = 200
        command.append('--hd')
    else:
        _, swaps = test_media.prepare(ROOT / 'build/disk1.po', out, drives=1 if args.media == 'one' else 2)
        script += '\n' + KEEPER.replace('@DISK1@', json.dumps(str(out / 'disk1.po'))) \
            .replace('@NEEDWAIT@', str(symbols['needWait'])).replace('@NEEDDONE@', str(symbols['needDone']))
        script += '\nlocal s = mem\n' + swaps
        seconds = 900
        if args.media == 'two':
            command += ['--disk2', str(out / 'disk2.po')]
    (out / 'observe.lua').write_text(script)
    command += ['--seconds', str(seconds), '--steps', ';'.join(steps), '--lua', str(out / 'observe.lua')]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=seconds * 2 + 150)
    (out / 'driver.log').write_text(run.stdout + run.stderr)
    if run.returncode:
        raise SystemExit((run.stdout + run.stderr)[-2500:])
    log = (out / 'mame.log').read_text()
    if 'TIMEOUT at step' in log or re.search(r'Lua error', log, re.I):
        raise SystemExit(log[-2500:])
    took = [float(t) for _, t in re.findall(r'^ENDING_PAGE (\d+) ([\d.]+)$', log, re.M)]
    assert len(took) == 3, 'the victory page and two ending pages were expected, %d seen' % len(took)
    pages = lumps()
    report, failures = [], []
    for page, name in enumerate(('VICTORY', 'END1', 'END2')):
        dump = (out / ('page-%d.bin' % page)).read_bytes()
        rec = pages[name]
        if name == 'VICTORY':
            expected = model_victory(rec)
            checked = list(range(25600)) + [32000 + y for y in range(160)] + [32256 + 32 * p + i for p in (0, 13, 14, 15) for i in range(32)]
            want = expected + bytes(6400) + rec[32000:32768]
        else:
            checked = list(range(32768))
            want = rec
        wrong = [i for i in checked if dump[i] != want[i]]
        report.append(dict(page=name, seconds=took[page], wrong_bytes=len(wrong), first_wrong=wrong[0] if wrong else None))
        if took[page] >= LIMIT:
            failures.append('%s took %.2f seconds' % (name, took[page]))
        if wrong:
            failures.append('%s: %d bytes differ from the lump, the first at %d' % (name, len(wrong), wrong[0]))
    (out / 'ending-pages.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit('FAILED: ' + '; '.join(failures))
    print('ending pages ok')


if __name__ == '__main__':
    main()
