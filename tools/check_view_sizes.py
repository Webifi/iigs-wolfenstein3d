"""The - and = keys and the View Size row of Options reach half, two thirds, three quarters and full size.

Boots the hard disk image into the game (the skip latch), then reads weaponViewIndex
(0 half, 2 two thirds, 4 three quarters, 6 full) after each action.
"""
import re
import subprocess
import sys
from wolfdata import ROOT
from elf import read

_, symbols = read(ROOT / 'build/wolf.elf')
address = symbols['weaponViewIndex']
ask = 'peek=0x%x,1' % address
# (what the test does, steps, the size expected after it)
CASES = [
    ('start', [], 2),
    ('Options Right', ['key=Esc', 'wait=2', 'sleep=1', 'key=Down', 'key=Down', 'key=Down', 'key=Return', 'wait=7', 'key=Return', 'wait=17',
                       'sleep=1', 'key=Down', 'key=Down', 'key=Right'], 4),
    ('Options Right again', ['key=Right'], 6),
    ('Options at full', ['key=Right'], 6),
    ('Options Left to 3/4', ['key=Left'], 4),
    ('Options Left', ['key=Left'], 2),
    ('Options Left again', ['key=Left'], 0),
    ('Esc back to the game', ['key=Esc', 'wait=7', 'key=Esc', 'wait=2', 'sleep=1', 'key=Esc', 'sleep=6'], 0),
    ('= key', ['key=Equals', 'sleep=3'], 2),
    ('= key again', ['key=Equals', 'sleep=3'], 4),
    ('= key to full', ['key=Equals', 'sleep=3'], 6),
    ('= key at full', ['key=Equals', 'sleep=3'], 6),
    ('- key to 3/4', ['key=Minus', 'sleep=3'], 4),
    ('- key', ['key=Minus', 'sleep=3'], 2),
    ('- key again', ['key=Minus', 'sleep=3'], 0),
    ('- key at half', ['key=Minus', 'sleep=3'], 0),
]
steps = ['sleep=50']
for _, actions, _ in CASES:
    steps += actions + ['sleep=0.3',ask]
steps.append('end=')
subprocess.run([sys.executable, str(ROOT / 'tools/ui_test.py'), '--name', 'check-view-sizes', '--hd', '--skip',
                '--seconds', '200', '--steps', ';'.join(steps)], check=True, cwd=ROOT,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
log = (ROOT / 'build/tests/check-view-sizes/mame.log').read_text()
seen = [int(v, 16) for v in re.findall(r'^PEEK [0-9a-f]+: ([0-9a-f]{2})', log, re.M)]
bad = 0
for (name, _, want), got in zip(CASES, seen):
    print('%-22s size %d %s' % (name, got, 'ok' if got == want else 'WRONG, expected %d' % want))
    bad += got != want
if len(seen) != len(CASES):
    print('only %d of %d readings' % (len(seen), len(CASES)))
    bad += 1
sys.exit(1 if bad else 0)
