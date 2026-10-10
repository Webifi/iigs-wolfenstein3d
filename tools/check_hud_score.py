"""Check the score on the status bar after every kind of score change.

The game starts the first floor. At the end of a frame the check writes a score to the logic bank and sets the
HUD dirty flag. At the end of the next frame the 40 status bar rows must equal the picture that tools/reference.py draws from
the game values. The scores cover each carry, each leading blank and a digit that stays.
"""
import memmap
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
from reference import render_hud

ROOT = Path(__file__).resolve().parents[1]
SCORES = [0, 5, 10, 100, 1600, 1699, 1700, 2000, 9999, 10000, 10001, 99999, 100000, 100500, 999999, 123456,
          123457, 123467, 123567, 124567, 134567, 234567, 234567, 20000, 20, 7, 0, 7, 70, 700, 7000, 70000, 700000]
FIELDS = ('score', 'levelIndex', 'lives', 'health', 'ammo', 'weapon', 'keys')

LUA = memmap.fill(r'''
local cases=@CASES@
local frames,step=0,0
local function word(a) return mem:read_u16(a) end
local function dump(k)
 local rows={}
 for i=0,6399 do rows[#rows+1]=string.char(mem:read_u8(@MM:SHR+0x6400@+i)) end
 local f=assert(io.open(@OUT@..'/hud'..k..'.bin','wb'))
 f:write(table.concat(rows));f:close()
end
hudScoreFrame=mem:install_write_tap(0x3f0,0x3f0,'hud-score-frame',function(a,d,m)
 if d~=2 then return end
 frames=frames+1
 if frames<=@WARM@ then return end
 if step>0 then
  dump(step)
  print(string.format('HUD_CASE %d %d %d %d %d %d %d %d',step,word(@SCORE@)+(word(@SCORE@+2)<<16),word(@LEVEL@),word(@LIVES@),word(@HEALTH@),word(@AMMO@),word(@WEAPON@),word(@KEYS@)))
 end
 step=step+1
 if step>#cases then print('HUD_DONE '..#cases);manager.machine:exit();return end
 mem:write_u16(@LSCORE@,cases[step]&0xffff)
 mem:write_u16(@LSCORE@+2,cases[step]>>16)
 mem:write_u16(@DIRTY@,1)
end)
''')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--name', default='hud-score')
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, sym = read(ROOT/'build/wolf.elf')
    logic = {k: int(v, 0)+memmap.OLD_WORLD for k, v in re.findall(r'^(V_score)\s+\.equ\s+(\S+)', (ROOT/'build/gen/logic.inc').read_text(), re.M)}
    values = dict(CASES='{'+','.join(map(str, SCORES))+'}', OUT=json.dumps(str(out)), WARM=30, SCORE=sym['score'], LSCORE=logic['V_score'],
                  DIRTY=sym['hudDirty'], LEVEL=sym['levelIndex'], LIVES=sym['lives'], HEALTH=sym['health'],
                  AMMO=sym['ammo'], WEAPON=sym['weapon'], KEYS=sym['keys'])
    script = LUA
    for key, value in values.items():
        script = script.replace('@'+key+'@', str(value))
    (out/'observe.lua').write_text(script)
    subprocess.run([sys.executable, 'tools/ui_test.py', '--name', args.name, '--hd', '--skip', '--seconds', '120',
                    '--steps', 'sleep=110;end=', '--lua', str(out/'observe.lua')],
                   cwd=ROOT, check=True, timeout=400, stdout=subprocess.DEVNULL)
    log = (out/'mame.log').read_text()
    rows = re.findall(r'^HUD_CASE (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)$', log, re.M)
    if f'HUD_DONE {len(SCORES)}' not in log or len(rows) != len(SCORES):
        raise SystemExit(log[-3000:])
    report = []
    for row in rows:
        step = int(row[0])
        game = dict(zip(FIELDS, map(int, row[1:])))
        assert game['score'] == SCORES[step-1]
        actual = (out/f'hud{step}.bin').read_bytes()
        wanted = render_hud(game)
        differing =[i for i, (a, b) in enumerate(zip(actual, wanted)) if a != b]
        report.append(dict(step=step, game=game, differing_bytes=len(differing), first=differing[:4]))
    failed = [r for r in report if r['differing_bytes']]
    (out/'result.json').write_text(json.dumps(dict(scores=len(SCORES), failed=len(failed), steps=report), indent=2)+'\n')
    print(f'{len(SCORES)} scores, {len(failed)} differ')
    if failed:
        raise SystemExit(json.dumps(failed[:3]))


if __name__ == '__main__':
    main()
