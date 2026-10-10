"""Keep approved LOADING glyphs and their background visible through floor I/O.

The native 160-by-3 progress line is at (80,109). Verify exact aligned ink slots
before and throughout the read, unchanged background and footer colors outside
that line, and monotonic visible progress. Disk prompts are
excluded while replacing the sign. Media and key routes use the actual UI.
"""
import memmap
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from elf import read
import test_media
from check_boot_picture import KEEPER

ROOT = Path(__file__).resolve().parents[1]

OBSERVER = memmap.fill(r'''
local s=mem
FRAMEADDR=@FRAMECOUNT@
local PIX,SCB,PAL=@MM:SHR@,@MM:SHR_SCB@,@MM:SHR_PAL@
local expected=@GLYPHS@
local reading,entryAt,frames,errors,backgroundErrors,skipped=false,0,0,0,0,0
local firstBar,lastBar,entrySign=0,0,false
local barRegressions,entryGlyphErrors=0,0
local firstMismatch="none"
local background={}
local modal,modalClosed=false,nil
local function now() return manager.machine.time:as_double() end
local menuReady=0
menuStartTap=mem:install_read_tap(@LISTRUN@,@LISTRUN@,'loading-menu-start',function(a,d,m)
 if cpu.state.PC.value==a+1 then menuReady=0 end
end)
menuReadyTap=mem:install_read_tap(@LISTKEY@,@LISTKEY@,'loading-menu-ready',function(a,d,m)
 if cpu.state.PC.value==a+1 then menuReady=s:read_u8(@MM:UI_SCREEN@) end
end)
CALLS.loadingMenuReady=function()
 if menuReady~=0 and menuReady==s:read_u8(@MM:UI_SCREEN@) then menuReady=0;return true end
 return false
end
local function color(x,y)
 local b=s:read_u8(PIX+y*160+(x//2))
 local c=x%2==0 and (b>>4) or (b&15)
 return s:read_u16(PAL+(s:read_u8(SCB+y)&15)*32+c*2)
end
local function ink(x,y)
 local b=s:read_u8(PIX+y*160+(x//2))
 return x%2==0 and (b>>4) or (b&15)
end
local function signUp()
 if s:read_u16(@BUSY@)~=1 or s:read_u16(@KIND@)~=0 then return false end
 for _,p in ipairs(expected) do if ink(p[1],p[2])~=p[3] then return false end end
 return true
end
local function bar()
 local n=0
 for x=80,239 do
  if ink(x,109)~=1 or ink(x,110)~=1 or ink(x,111)~=1 then break end
  n=n+1
 end
 return n
end
local function promptUp()
 if s:read_u16(@BUSY@)==1 and s:read_u16(@KIND@)==2 then return true end
 for _,base in ipairs({@MM:DISK_PROMPT_00@,@MM:DISK_PROMPT@}) do
  local text=""
  for i=0,12 do text=text..string.char(s:read_u8(base+i)&127) end
  if text:match("^INSERT DISK %d$") then return true end
 end
 return false
end
modalStart=mem:install_read_tap(@SHOW@,@SHOW@,'prompt-start',function(a,d,m)
 if cpu.state.PC.value==a+1 and cpu.state.A.value==2 then modal=true;modalClosed=nil end
end)
modalDone=mem:install_read_tap(@DONE@,@DONE@,'prompt-done',function(a,d,m)
 if cpu.state.PC.value==a+1 and modal then modalClosed=now() end
end)
emu.register_frame_done(function()
 if not reading or s:read_u16(@LOADKEEP@)==0 then return end
 if modal then
  if signUp() then modal=false
  elseif not modalClosed or now()-modalClosed<=1.5 then skipped=skipped+1;return
  else modal=false end
 end
 if promptUp() then skipped=skipped+1;return end
 frames=frames+1
 if not signUp() then errors=errors+1 end
 for _,p in ipairs(background) do
  if color(p[1],p[2])~=p[3] then backgroundErrors=backgroundErrors+1;break end
 end
 local current=bar()
 if current<lastBar then barRegressions=barRegressions+1 end
 lastBar=current
 if frames==1 or frames==120 or frames==240 then screen:snapshot('read-'..frames..'.png') end
end)
entryTap=mem:install_read_tap(@LOADFLOOR@,@LOADFLOOR@,'floor-entry',function(a,d,m)
 if cpu.state.PC.value~=a+1 or (cpu.state.A.value&0x2000)==0 then return end
 reading=true;entryAt=now();frames=0;errors=0;backgroundErrors=0;skipped=0
 entrySign=signUp();firstBar=bar();lastBar=firstBar;background={}
 barRegressions=0;entryGlyphErrors=0;firstMismatch="none"
 local misses={}
 for _,p in ipairs(expected) do if ink(p[1],p[2])~=p[3] then misses[#misses+1]=string.format('%d,%d:%x/%x',p[1],p[2],ink(p[1],p[2]),p[3]) end end
 entryGlyphErrors=#misses;firstMismatch=misses[1] or 'none'
 print('GLYPH_MISMATCH '..table.concat(misses,' '))
 local b={};for i=0,32767 do b[#b+1]=string.char(s:read_u8(PIX+i)) end
 local f=assert(io.open(@RAW@,'wb'));f:write(table.concat(b));f:close()

 -- The dimmed picture stays intact, including footer rows: no boot strip.
 for y=0,199,2 do for x=0,319,8 do
  if not(y>=109 and y<=111 and x>=80 and x<=239) then
   background[#background+1]={x,y,color(x,y)}
  end
 end end
 screen:snapshot('read-entry.png')
end)
loadedTap=mem:install_read_tap(@LOADED@,@LOADED@,'floor-loaded',function(a,d,m)
 if cpu.state.PC.value~=a+1 or not reading then return end
 reading=false;local current=bar();if current<lastBar then barRegressions=barRegressions+1 end;lastBar=current;screen:snapshot('read-end.png')
 print(string.format('FLOOR_READ seconds=%.3f frames=%d glyph_errors=%d background_errors=%d skipped=%d bar_first=%d bar_last=%d sign_at_entry=%s prompt_completed=%s bar_regressions=%d entry_glyph_errors=%d first_glyph_mismatch=%s',now()-entryAt,frames,errors,backgroundErrors,skipped,firstBar,lastBar,tostring(entrySign),tostring(not modal),barRegressions,entryGlyphErrors,firstMismatch))
end)
''')



def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--elf', type=Path, default=ROOT/'build/wolf.elf')
    ap.add_argument('--disk', type=Path)
    ap.add_argument('--media', choices=('hd', 'one', 'two'), default='hd')
    ap.add_argument('--baseline', action='store_true', help='check the former hard-edged overlay for paired captures')
    ap.add_argument('--old-floor', type=int, default=5, choices=range(1, 10), help='the floor that the game believes to be in memory')
    args = ap.parse_args()
    out = ROOT / 'build/tests' / args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(args.elf)
    from loading_glyphs import pixels, assembly
    glyphs = pixels()
    if args.baseline:
        sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
        from render import Face,Screen,blank
        from shared_gray import INK, OVERLAY_INK
        face=Face('BlackOpsOne-Regular.ttf',ROOT/'build/frontend/native',size=6)
        expected=Screen(blank(320,200,0x333));face.draw(expected,'LOADING',135,87)
        glyphs=[[x,y,OVERLAY_INK[INK[c&15]]] for y,row in enumerate(expected.rows)
                for x,c in enumerate(row) if c!=0x333]
    else:
        assert (ROOT/'src/iigs/loading_sign.inc').read_text() == assembly(), 'loading asset is stale'
    script=OBSERVER.replace('@RAW@',json.dumps(str(out/'read-entry.shr'))).replace('@GLYPHS@','{'+','.join('{%d,%d,%d}'%tuple(p) for p in glyphs)+'}')
    for token, value in (('LOADKEEP', symbols['loadKeep']), ('LOADFLOOR', symbols['LoadFloorData']),
                         ('LOADED', symbols['demoFloorLoaded']), ('FRAMECOUNT', symbols['frameCount']),
                         ('BUSY',symbols['busyShown']), ('KIND',symbols['busyKind']),
                         ('LISTRUN',symbols['ListRun']), ('LISTKEY',symbols['listKey']),
                         ('SHOW',symbols['BusyShow']), ('DONE',symbols['needDone'])):
        script = script.replace('@' + token + '@', str(value))
    # New Game, the game believes that floor 5 is in memory, New Game again (the Y key answers the question about the
    # game that runs): LoadFloorAssets reads floor 0 from the disk.
    steps = ['wait=1;sleep=4', 'key=Esc', 'wait=2', 'sleep=6', 'key=Return', 'wait=15', 'sleep=2', 'key=Return', 'wait=3', 'sleep=2', 'key=Return',
             'waitframes=4', 'sleep=3', 'poke16=%d,%d' % (symbols['levelIndex'], args.old_floor), 'key=Esc', 'wait=2', 'sleep=6',
             'key=Return', 'wait=15', 'sleep=2', 'key=Return', 'wait=3', 'sleep=2', 'key=Return', 'sleep=1', 'key=Y', 'waitframes=4', 'sleep=3', 'end=']
    if 'EpisodeSelect' in symbols:
        steps = [part for step in steps for part in (['wait=19', 'sleep=2', 'key=Return', step]
                 if step == 'wait=15' else [step])]
    # Screen IDs are published before the list finishes drawing. Wait for
    # its input loop so a cold registered page cannot discard the key.
    steps = [part for step in steps for part in (['call=loadingMenuReady', step]
             if step == 'key=Return' else [step])]
    command = [sys.executable, 'tools/ui_test.py', '--name', args.name]
    if args.disk:command += ['--disk',str(args.disk)]
    if args.media == 'hd':
        seconds = 200
        command.append('--hd')
    else:
        _, swaps = test_media.prepare(args.disk or ROOT / 'build/disk1.po', out, drives=1 if args.media == 'one' else 2)
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
    reads = re.findall(r'^FLOOR_READ (.*)$', log, re.M)
    assert reads, 'no floor read with the screen kept was seen'
    report = []
    for line in reads:
        report.append(dict(item.split('=',1) for item in line.split(' ')))
    (out / 'floor-read-sign.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    failures = []
    for n, r in enumerate(report, 1):
        if int(r['frames']) < 60:
            failures.append('read %d: only %s frames were counted' % (n, r['frames']))
        for key in ('glyph_errors','background_errors','bar_regressions'):
            if int(r[key]):failures.append('read %d: %s=%s'%(n,key,r[key]))
        if r['prompt_completed']!='true':failures.append('read %d: prompt never restored loading sign'%n)
        if r['sign_at_entry']!='true':failures.append('read %d: sign missing before floor call'%n)
        if int(r['bar_last'])<=int(r['bar_first']) or int(r['bar_last'])>160:
            failures.append('read %d: progress line absent, stationary or out of bounds'%n)
    if failures:
        raise SystemExit('FAILED: ' + '; '.join(failures))
    print('floor read sign ok')


if __name__ == '__main__':
    main()
