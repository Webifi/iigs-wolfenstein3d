"""Check cached pictures, palette ownership, and every published fade step."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
import screen_ram_guard

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--disk', type=Path, default=ROOT/'build/wolf-hd.po')
    ap.add_argument('--elf', type=Path, default=ROOT/'build/wolf.elf')
    ap.add_argument('--menu', type=Path, default=ROOT/'build/assets/menu.bin')
    ap.add_argument('--check-free-screen-ram', action='store_true')
    ap.add_argument('--mame', type=Path, required=True)
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, syms = read(args.elf)
    observer = memmap.fill(r'''
local f=assert(io.open(@MENU@,'rb'));local raw=f:read('a');f:close()
local active=false
local offset=0
local pictures=0
local views=0
local function black()
 for i=0,511 do assert(mem:read_u8(@MM:SHR_PAL@+i)==0,'picture changes under a lit palette') end
end
local function match(addr,off,n)
 for i=0,n-1 do assert(mem:read_u8(addr+i)==raw:byte(off+i+1),'cached picture differs at '..string.format('%06x',addr+i)) end
end
local function code(a) return not manager.machine:side_effects_disabled() and cpu.state.PB.value==a>>16 and cpu.state.PC.value==a+1 end
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(mem:read_u8(at+i)) end;return table.concat(b)
end
local savedPalette=nil
local fadeExpected=nil
local savedChecks,fadeChecks=0,0
local fadeErrors={}
local function fadeCheck(ok,why)
 if not ok then fadeErrors[#fadeErrors+1]=why;print('FADE_ERROR '..why) end
end
paletteSaveTap=mem:install_read_tap(@SAVE@,@SAVE@,'palette-save-source',function(a,d,m)
 if code(a) then savedPalette=bytes(@MM:SHR_PAL@,512) end
end)
fadePrepareTap=mem:install_read_tap(@STEP@,@STEP@,'fade-prepare',function(a,d,m)
 if not code(a) then return end
 if savedPalette then
  fadeCheck(bytes(@FADE@,512)==savedPalette,'fade saved palette differs from active E1 colors')
  savedPalette=nil;savedChecks=savedChecks+1
 end
 local step=cpu.state.A.value
 assert(step>=0 and step<=16,'fade step out of range')
 fadeExpected={}
 for i=0,255 do
  local src=mem:read_u16(@FADE@+i*2)
  local color=0
  for shift=0,8,4 do
   color=color | (mem:read_u8(@CURVE@+step*16+((src>>shift)&15))<<shift)
  end
  fadeExpected[i]=color
 end
end)
fadePublishTap=mem:install_read_tap(@PUBLISHED@,@PUBLISHED@,'fade-published',function(a,d,m)
 if not code(a) then return end
 assert(fadeExpected,'fade was not prepared')
 for i=0,255 do
  fadeCheck(mem:read_u16(@MM:SHR_PAL@+i*2)==fadeExpected[i],'published fade color differs at '..i)
 end
 fadeExpected=nil;fadeChecks=fadeChecks+1
end)
pictureStartTap=mem:install_read_tap(@START@,@START@,'picture-start',function(a,d,m)
 if not code(a) then return end
 black();active=true
 offset=mem:read_u16(@TABLE@+cpu.state.A.value*8)*512
end)
pictureEndTap=mem:install_read_tap(@END@,@END@,'picture-end',function(a,d,m)
 if not code(a) then return end
 assert(active);black()
 match(@MM:SHR@,offset,32000);match(@MM:SHR_SCB@,offset+32000,200);match(@FADE@,offset+0x7e00,512)
 active=false;pictures=pictures+1
 print('PICTURE_EXACT '..pictures)
end)
picturePaletteTap=mem:install_write_tap(@MM:SHR_PAL@,@MM:SHR_PAL+0x1ff@,'held-colors',function(a,d,m)
 if active then assert(d==0,'palette published before cached picture is complete') end
end)
viewRevealTap=mem:install_read_tap(@REVEAL@,@REVEAL@,'view-reveal',function(a,d,m)
 if not code(a) then return end
 black();views=views+1
 print('VIEW_BLACK '..views)
end)
CALLS={}
CALLS.checked=function()
 if #fadeErrors>0 then print('FADES_FAILED '..#fadeErrors);manager.machine:schedule_exit();return end
 assert(pictures>=2 and views>=1,'missing title/credits or game reveal')
 assert(savedChecks>=3 and fadeChecks>=64,'missing fade coverage')
 if checkFreeScreenRam then checkFreeScreenRam() end
 print('TRANSITIONS_OK '..pictures..' '..views)
 print('FADES_OK '..savedChecks..' '..fadeChecks)
end
''')
    vals=dict(MENU=json.dumps(str(args.menu.resolve())),START=syms['StreamCachedPicture'],
              END=syms['cachedPictureDone'],TABLE=syms['lumpTable'],FADE=syms['fadeBase'],REVEAL=syms['RevealPal'],
              SAVE=syms['PalSave'],STEP=syms['FadeStepCore'],PUBLISHED=syms['fadeDelay'],CURVE=syms['fadeTab'])
    for key,value in vals.items():observer=observer.replace('@'+key+'@',str(value))
    if args.check_free_screen_ram:
        observer += screen_ram_guard.lua(syms)
    (out/'observe.lua').write_text(observer)
    steps=['wait=1','sleep=1','snap=title','wait=12','sleep=1','snap=credits','wait=13','sleep=1',
           'snap=demo','key=J13 Escape','wait=2','sleep=0.5','snap=menu','key=J13 Escape','wait=1',
           'sleep=1','snap=title-return','call=checked','end=']
    run=subprocess.run([sys.executable,'tools/ui_test.py','--name',args.name,'--hd','--disk',str(args.disk),'--seconds','240',
                        '--mame',str(args.mame.resolve()),'--j13','only','--debug',
                        '--steps',';'.join(steps),'--lua',str(out/'observe.lua')],cwd=ROOT,
                       capture_output=True,text=True,timeout=600)
    (out/'driver.log').write_text(run.stdout+run.stderr)
    log=(out/'mame.log').read_text()
    assert run.returncode==0 and 'TIMEOUT' not in log and 'Error in Lua' not in log and '[LUA ERROR]' not in log,log[-3000:]
    counts=re.search(r'^TRANSITIONS_OK (\d+) (\d+)$',log,re.M)
    assert counts,log[-3000:]
    fades=re.search(r'^FADES_OK (\d+) (\d+)$',log,re.M)
    assert fades,log[-3000:]
    if args.check_free_screen_ram:assert 'FREE_SCREEN_RAM_OK 32768' in log
    result=dict(pictures=int(counts[1]),game_reveals=int(counts[2]),differing_bytes=0,
                palette_order_errors=0,machine='apple2gsr1',ramsize='4352K',
                saved_palettes=int(fades[1]),published_fade_steps=int(fades[2]),
                reclaimed_ram_bytes_checked=32768 if args.check_free_screen_ram else 0,
                disk_sha256=hashlib.sha256(args.disk.read_bytes()).hexdigest(),
                elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest())
    (out/'transitions.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
