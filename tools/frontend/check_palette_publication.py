"""Passive palette/fade and loading publication trace on the current image."""
import json
from pathlib import Path
import re
import hashlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import memmap
from elf import read

name = sys.argv[1]
out = ROOT/'build/tests'/name
out.mkdir(parents=True, exist_ok=True)
_, symbols = read(ROOT/'build/wolf.elf')
shutil.copy2(ROOT/'build/wolf.elf',out/'wolf.elf')
lua = memmap.fill(r'''
local target=OUT
local shadow={}
for i=0,32767 do shadow[i]=0 end
local phase, serial, busy = nil,0,nil
local busyNumber, restored = 0,0
local lightness, curve = {}, {}
for value=0,15 do
 local encoded=value/15
 local linear=encoded<=0.04045 and encoded/12.92 or ((encoded+0.055)/1.055)^2.4
 lightness[value]=linear>216/24389 and 116*linear^(1/3)-16 or linear*24389/27
end
for step=0,16 do
 curve[step]={}
 for value=0,15 do
  local target=lightness[value]*step/16
  local best,error=0,math.huge
  for shade=0,value do
   local difference=math.abs(lightness[shade]-target)
   if difference<error then best,error=shade,difference end
  end
  curve[step][value]=best
 end
end
local function whole()
 local b={};for i=0,31999 do b[#b+1]=string.char(shadow[i]) end
 for i=32000,32199 do b[#b+1]=string.char(shadow[i]) end
 for i=32256,32767 do b[#b+1]=string.char(shadow[i]) end
 return table.concat(b)
end
local writes=assert(io.open(target..'/palette-writes.tsv','w'))
local function dump(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(shadow[i]) end
 local f=assert(io.open(target..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
end
local function tap(a,name,fn)
 mem:install_read_tap(a,a,name,function(ad,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(ad>>16) and cpu.state.PC.value==ad+1 then fn() end
 end)
end
mem:install_write_tap(@MM:SHR@,@MM:SHR_PAL+0x1ff@,'display-writes',function(ad,d,m)
 shadow[ad-@MM:SHR@]=d
 if ad>=@MM:SHR_PAL@ then
  writes:write(string.format('%.9f\t%x\t%d\t%x\t%.9f\n',now(),ad,d,cpu.state.PC.value,screen:time_until_pos(0)))
  if phase then phase.count=phase.count+1;if screen:time_until_pos(216) < screen:time_until_pos(16) then phase.visible=phase.visible+1 end;phase.first=phase.first or now();phase.last=now() end
  if busy then busy.colors=busy.colors+1 end
 elseif busy and ad<@MM:SHR_SCB@ then
  local pos=ad-@MM:SHR@;local y=pos//160;local x=pos%160
  if not(y>=83 and y<117 and x>=35 and x<125) then busy.outside=busy.outside+1 end
 elseif busy then busy.scbs=busy.scbs+1 end
end)
tap(FADE,'fade-begin',function()
 serial=serial+1
 phase={number=serial,level=cpu.state.A.value,screen=mem:read_u8(0x3e4),start=now(),count=0,visible=0,target={}}
 for i=0,255 do phase.target[i]=mem:read_u16(BASE+2*i) end
 print(string.format('FADE_START %d %d %d %.9f',serial,phase.screen,phase.level,now()))
end)
tap(DELAY,'fade-colors-done',function()
 if not phase then return end
 local wrong=0
 for i=0,255 do
  local old=phase.target[i];local expected=0
  for _,shift in ipairs({0,4,8}) do expected=expected|(curve[phase.level][(old>>shift)&15]<<shift) end
  local got=shadow[32256+i*2]|(shadow[32257+i*2]<<8)
  if got~=expected then wrong=wrong+1;if wrong<=4 then print(string.format('FADE_ERROR %d %d %03x %03x',serial,i,got,expected)) end end
 end
 print(string.format('FADE_DONE %d %d %d %.9f %.9f %.9f %d',serial,phase.count,wrong,now()-phase.start,phase.first or 0,phase.last or 0,phase.visible));assert(phase.visible==0,'fade palette spilled into visible rows');assert(wrong==0)
 if phase.screen==1 then dump(string.format('title-fade-%03d-%02d',serial,phase.level)) end
 phase=nil
end)
tap(SHOW,'busy-enter',function()
 if mem:read_u16(BOOT)==0 then return end
 if not busy then busyNumber=busyNumber+1;busy={start=now(),colors=0,scbs=0,outside=0,dark=mem:read_u16(BLACK),before=whole()};dump('busy-'..busyNumber..'-before') end
end)
tap(READY,'busy-visible',function()
 if not busy then return end
 print(string.format('BUSY_READY %.9f %d %d %d %d',now()-busy.start,busy.colors,busy.scbs,busy.outside,busy.dark));dump('busy-'..busyNumber..'-ready');if busy.dark==0 then assert(busy.colors==0 and busy.scbs==0 and busy.outside==0,'loading changed its background') end
end)
tap(FORGET,'busy-forgotten',function()
 if busy then print(string.format('BUSY_END %.9f %d %d %d',now()-busy.start,busy.colors,busy.scbs,busy.outside));dump('busy-end');busy=nil end
end)
tap(HIDE_DONE,'busy-restored',function()
 if busy and busy.dark==0 then
  local exact=whole()==busy.before
  print('BUSY_RESTORED '..tostring(exact));if exact then restored=restored+1 end
  dump('busy-'..busyNumber..'-restored');busy=nil
 end
end)
CALLS.done=function() writes:flush();print('PALETTE_OBSERVER_DONE') end
emu.add_machine_stop_notifier(function() writes:close() end)
''')
for key, symbol in {'FADE':'FadeStepCore','BASE':'fadeBase','DELAY':'fadeDelay','SHOW':'BusyShow',
                    'HIDE_DONE':'hideDone','BLACK':'screenBlack','READY':'busySuppressed','FORGET':'BusyForget','BOOT':'bootComplete'}.items():
    lua=re.sub(r'\b'+key+r'\b',str(symbols[symbol]),lua)
lua=lua.replace('OUT',json.dumps(str(out)))
(out/'observe.lua').write_text(lua)
steps='wait=1;sleep=2;snap=title;wait=12;wait=6;wait=13;sleep=1;call=done;end='
if len(sys.argv)>2 and sys.argv[2].startswith('save'):
    steps='wait=1;sleep=1;key=Esc;wait=2;sleep=1;key=Return;wait=15;sleep=1;key=Return;wait=3;sleep=1;key=Return;wait=0;sleep=1;key=F8;wait=4;sleep=1;key=Return;sleep=1;key=w;key=o;key=l;key=f;key=Return;sleep=5;key=Esc;wait=2;key=Esc;wait=0;sleep=1;key=F8;sleep=4;wait=0;key=F9;sleep=4;wait=0;call=done;end='

args=[sys.executable,'tools/ui_test.py','--name',name,'--hd','--debug','--seconds','360','--lua',str(out/'observe.lua'),'--steps',steps]
if len(sys.argv)>2 and sys.argv[2]=='save-floppy':
    args.remove('--hd');args+=['--disk2',str(ROOT/'build/disk2.po')]
r=subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
(out/'driver.log').write_text(r.stdout+r.stderr)
print(r.stdout+r.stderr)
log=(out/'mame.log').read_text()
assert r.returncode==0 and 'PALETTE_OBSERVER_DONE' in log and '[LUA ERROR]' not in log
rows=re.findall(r'^FADE_DONE (\d+) (\d+) (\d+) ([\d.]+) ([\d.]+) ([\d.]+) (\d+)$',log,re.M)
assert rows and all(int(r[1])==512 and int(r[2])==0 and int(r[6])==0 for r in rows), 'palette publication or ramp failed'
assert 'BUSY_RESTORED false' not in log
ready=re.findall(r'^BUSY_READY ([\d.]+) (\d+) (\d+) (\d+) (\d+)$',log,re.M)
assert all(all(int(n)==0 for n in r[1:4]) for r in ready if int(r[4])==0)
if len(sys.argv)>2 and sys.argv[2].startswith('save'):
    assert any(int(r[4])==0 for r in ready)
    if sys.argv[2]=='save-floppy': assert 'BUSY_RESTORED true' in log
print('\n'.join(line for line in log.splitlines() if line.startswith(('FADE_', 'BUSY_')))[-16000:])

report=dict(fade_steps=len(rows),fade_wrong_colors=0,fade_active_picture_writes=0,
            palette_copy_ms=[(float(r[5])-float(r[4]))*1000 for r in rows],
            busy=[dict(seconds=float(r[0]),palette_bytes=int(r[1]),scb_bytes=int(r[2]),outside_pixel_writes=int(r[3]),black=bool(int(r[4]))) for r in ready],
            restored_overlays=log.count('BUSY_RESTORED true'),
            elf_sha256=hashlib.sha256((out/'wolf.elf').read_bytes()).hexdigest(),
            media_sha256=hashlib.sha256((out/('wolf-hd.po' if '--hd' in args else 'disk1.po')).read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
