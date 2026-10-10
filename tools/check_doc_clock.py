"""Check the 70 Hz game clock of the DOC ramp (src/iigs/doc.s) against emulated time.

The clock oscillator walks a 256-byte ramp (byte 0 holds 255, because 0 halts the oscillator) in free run, and
I_GetTime sums the steps between two reads modulo 256. A real DOC plays all L bytes of a table before it completes a
cycle (the carry out of the 2^(17+R) phase), so the ramp gives exactly one step for each table step and the clock runs at
scan rate x TIMER_FREQ / 2^16. An emulator that wrapped after L-1 bytes would run the clock fast by 1/255.

python3 tools/check_doc_clock.py [--name NAME]

The game boots to the first floor and idles. The check reads tmSteps at the end of one frame after 10 s and at the end of
one frame after 130 s of emulated time and compares the rate with the one that the register values give.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read

ROOT = Path(__file__).resolve().parents[1]
DOC_CLOCK = 28636363 / 32       # A2GS_MASTER_CLOCK / 4 / 8, the clock of the ES5503 in apple2gs.cpp
OSCS, TIMER_FREQ = 32, 174      # doc.s: DOC_OSCS and TIMER_FREQ
EXPECTED = DOC_CLOCK / (OSCS + 2) * TIMER_FREQ / 65536
FIRST, SECOND = 10, 130

LUA = r'''
local first,second=nil,nil
local function steps() return mem:read_u16(@STEPS@)+mem:read_u16(@STEPS@+2)*65536 end
docClockFrame=mem:install_write_tap(0x3f0,0x3f0,'doc-clock-frame',function(a,d,m)
 if d~=2 then return end
 local t=manager.machine.time:as_double()
 if not first and t>=@FIRST@ then first={t,steps()};print(string.format('DOCCLOCK 1 %.9f %d',t,first[2])) end
 if first and not second and t>=@SECOND@ then
  second={t,steps()};print(string.format('DOCCLOCK 2 %.9f %d',t,second[2]));manager.machine:exit()
 end
end)
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--name', default='doc-clock')
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, sym = read(ROOT/'build/wolf.elf')
    script = LUA.replace('@STEPS@', str(sym['tmSteps'])).replace('@FIRST@', str(FIRST)).replace('@SECOND@', str(SECOND))
    (out/'observe.lua').write_text(script)
    subprocess.run([sys.executable, 'tools/ui_test.py', '--name', args.name, '--hd', '--skip', '--seconds', str(SECOND + 60),
                    '--steps', f'sleep={SECOND + 50};end=', '--lua', str(out/'observe.lua')],
                   cwd=ROOT, check=True, timeout=600, stdout=subprocess.DEVNULL)
    log = (out/'mame.log').read_text()
    rows = re.findall(r'^DOCCLOCK (\d) ([\d.]+) (\d+)$', log, re.M)
    if [r[0] for r in rows] != ['1', '2']:
        raise SystemExit(log[-2000:])
    (t1, n1), (t2, n2) = [(float(r[1]), int(r[2])) for r in rows]
    rate = (n2 - n1) / (t2 - t1)
    error = rate / EXPECTED - 1
    result = dict(seconds=t2 - t1, steps=n2 - n1, rate_hz=rate, expected_hz=EXPECTED, error_percent=error*100,
                  if_wrapped_after_L_minus_1_percent=100/255)
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    if abs(error) > 0.0005:
        raise SystemExit('the game clock does not run at the rate of its DOC registers')


if __name__ == '__main__':
    main()
