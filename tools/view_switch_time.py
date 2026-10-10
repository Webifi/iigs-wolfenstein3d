"""Time a change of view size in stock MAME, from writes to the memory that setView fills.

Two runs boot the hard disk image into the game (the skip latch) and change the size: with the
- and = keys in play (setViewInPlay), and with the view latch $03E1 and an Esc menu exit
(the full redraw that the menus use). Each change reports the frame that holds it:
  tables  from the first write of setView to the end of its tables (FIRST is set)
  screen  from there to the start of the first picture (screenInit, the status bar, the border)
  picture from the start of the first picture to the end of the frame
  pool    bytes written into the ray height pool, banks $30-$33, in that frame
"""
import memmap
import argparse
import re
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from wolfdata import ROOT
from elf import read

PREFIX = ''

LUA = memmap.fill('''
local T, order = {}, {}
local capture=0
local function stamp(label, lo, hi)
  order[#order+1] = label; T[label] = {n=0}
  return mem:install_write_tap(lo, hi, label, function(a, d, m)
    local t = manager.machine.time:as_double()
    local r = T[label]
    if r.n == 0 then r.first = t end
    r.last = t; r.n = r.n + 1
  end)
end
tapCode = stamp("code", @MM:SCALE3@, @MM:SCALE5+0xffff@)
tapView = stamp("view", %(view)d, %(view)d + 1)
tapPool = stamp("pool", @MM:LOGIC_BASE@, @MM:OBJECT_MARKERS+0xfff@)
tapFirst = stamp("first", 0x1044, 0x1045)
tapCast = stamp("cast", 0x3f2, 0x3f2)
tapFrame = mem:install_write_tap(0x3f0, 0x3f0, "frame", function(a, d, m)
  local t = manager.machine.time:as_double()
  if d == 1 then
    for _, k in ipairs(order) do T[k] = {n=0} end
    frameStart = t
  elseif d == 2 and T["view"].n > 0 then
    local parts = {string.format("VS frame %%.6f %%.6f", frameStart or 0, t)}
    for _, k in ipairs(order) do
      local r = T[k]
      if r.n > 0 then parts[#parts+1] = string.format("%%s %%.6f %%d", k, r.first, r.n) end
    end
    print(table.concat(parts, " "))
    local width=mem:read_u16(%(width)d)
    local left=(160-width)//2
    local top=left
    local bad=0
    for y=0,159 do for x=0,159 do
      if y<top or y>=top+width or x<left or x>=left+width then
        if mem:read_u8(@MM:SHR@+y*160+x)~=0 then bad=bad+1 end
      end
    end end
    print(string.format("MARGIN %%d %%d",width*2,bad))
    assert(bad==0,"nonblack view margin")
    capture=capture+1
    local f=io.open("@OUT@/hud-"..capture..".bin","wb")
    for i=0,6399 do f:write(string.char(mem:read_u8(@MM:SHR+0x6400@+i))) end
    f:close()

  end
end)
''')

KEYS = [('2/3 to 3/4','Equals'),('3/4 to full','Equals'),('full to 3/4','Minus'),
        ('3/4 to 2/3','Minus'),('2/3 to half','Minus'),('half to 2/3','Equals')]
LATCH = [('2/3 to half',1),('half to 3/4',3),('3/4 to full',4),('full to 2/3',2),
         ('2/3 to 3/4',3),('3/4 to half',1),('half to full',4),('full to half',1),
         ('half to 2/3',2),('2/3 to full',4),('full to 3/4',3),('3/4 to 2/3',2)]


def run(name, steps, lua):
    name = PREFIX + name
    script = ROOT / 'build/tests' / (name + '.lua')
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(lua.replace("@OUT@",str(ROOT/"build/tests"/name)))
    cmd = [sys.executable, str(ROOT / 'tools/ui_test.py'), '--name', name, '--hd', '--skip', '--seconds', '160',
           '--lua', str(script), '--steps', steps]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    return (ROOT / 'build/tests' / name / 'mame.log').read_text()


def report(title, labels, log):
    print(title)
    rows = re.findall(r'^VS frame (\S+) (\S+)(.*)$', log, re.M)
    assert len(rows)==len(labels),(len(rows),len(labels))
    results=[]
    for label, (start, end, rest) in zip(labels, rows):
        marks = {k: (float(t), int(n)) for k, t, n in re.findall(r'(\w+) (\S+) (\d+)', rest)}
        start, end = float(start), float(end)
        tables = marks['first'][0] - marks['code'][0]
        screen = marks['cast'][0] - marks['first'][0]
        results.append(dict(switch=label,frame_ms=(end-start)*1000,tables_ms=tables*1000,screen_ms=screen*1000,picture_ms=(end-marks['cast'][0])*1000,pool_bytes=marks.get('pool',(0,0))[1]))
        print('  %-12s %4.0f ms  (tables %3.0f, screen %3.0f, picture %3.0f, pool %2d pages)' % (
            label, (end - start) * 1000, tables * 1000, screen * 1000, (end - marks['cast'][0]) * 1000,
            marks['pool'][1] // 256 if 'pool' in marks else 0))

    return results


def check_margins():
    checks={}
    hud_hashes=set()
    for name, count in (('vswitch-keys',len(KEYS)),('vswitch-latch',len(LATCH)+1)):
        name = PREFIX + name
        out=ROOT/'build/tests'/name
        margins=re.findall(r'^MARGIN (\d+) (\d+)$',(out/'mame.log').read_text(),re.M)
        assert len(margins)==count and all(int(bad)==0 for _,bad in margins),margins
        hashes=[hashlib.sha256((out/f'hud-{n}.bin').read_bytes()).hexdigest() for n in range(1,count+1)]
        assert len(set(hashes))==1,'HUD changed during view switch'
        hud_hashes.update(hashes)
        checks[name]=dict(pictures=count,nonblack_margin_bytes=0,hud_sha256=hashes[0])
    assert len(hud_hashes)==1,'HUD differs between key and menu paths'
    return checks


def main():
    global PREFIX
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='', help='prefix capture names to preserve earlier runs')
    PREFIX = parser.parse_args().prefix
    _, symbols = read(ROOT / 'build/wolf.elf')
    lua = LUA % dict(view=symbols['weaponViewIndex'],width=symbols['viewBytes'])
    steps = ['sleep=50'] + ['key=%s;sleep=6' % key for _, key in KEYS]
    keys=report('size keys in play:', [label for label, _ in KEYS], run('vswitch-keys', ';'.join(steps + ['end=']), lua))
    steps = ['sleep=50'] + ['poke=0x3e1,%d;sleep=6' % view for _, view in LATCH]
    steps += ['key=Esc;wait=2;sleep=1;key=Esc;sleep=8', 'end=']
    latch=report('full redraw (the view latch, then an Esc menu exit with no change):',
           [label for label, _ in LATCH] + ['menu exit'], run('vswitch-latch', ';'.join(steps), lua))
    (ROOT/'build/tests'/(PREFIX+'view-switch.json')).write_text(json.dumps(dict(keys=keys,latch=latch,margins=check_margins()),indent=2)+'\n')


if __name__ == '__main__':
    main()
