"""Run effects through their actual 65816 entry point on a stock MAME boot.

The test trampoline replaces one frame's clock call, preserves its interface,
and observes GLU traffic. It is injected only by the test, never into the disk.
"""
import memmap
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from elf import read
import test_media
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'build/tests/sound-effects';out.mkdir(parents=True,exist_ok=True)
for name in ('cfg','nvram','state','snap'):(out/name).mkdir(exist_ok=True)
(out/'cfg/apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
_,sym=read(ROOT/'build/wolf.elf')
def long(op,address):return bytes([op])+address.to_bytes(3,'little')
def lda(n):return bytes([0xa9])+struct.pack('<H',n)
code=bytearray([0x08,0xc2,0x30,0x48,0xda,0x5a,0x8b])
steps=[('stop',None),('pistol',24),('lower_digi',18),('equal_digi',26),
       ('same_cached',26),('adlib',31),('lower_adlib',0),('death',9),('off',None)]
for i,(name,sound) in enumerate(steps):
    code+=lda(i)+long(0x8f,memmap.TEST_MARKERS)
    if name=='stop':code+=long(0x22,sym['StopMusic'])+long(0x22,sym['StopEffects'])
    elif name=='off':
        code+=long(0x22,sym['StopEffects'])+lda(0)+long(0x8f,sym['soundVolume'])
        code+=lda(i+1)+long(0x8f,memmap.TEST_MARKERS)+lda(24)+long(0x22,sym['PlaySound'])
    else:code+=lda(sound)+long(0x22,sym['PlaySound'])
code+=lda(len(steps)+1)+long(0x8f,memmap.TEST_MARKERS)
code+=bytes([0xab,0x7a,0xfa,0x68,0x28])+long(0x22,sym['I_GetTime'])+bytes([0x6b])
script=memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local active=false
local stage=-1
local ctl=0
local adr=0
local hi=0
local counts={}
local regs={}
local ram={}
local busy=0
local violations=0
local function audit() if busy&0x80~=0 or cpu.state.P.value&4==0 then violations=violations+1 end end
local function finish()
local f=io.open(OUT..'/traffic.json','w')
local stages={}
for i=0,10 do local q=counts[i] or {0,0,0};stages[#stages+1]=string.format('[%d,%d,%d,%d]',i,q[1],q[2],q[3]) end
local r={};for i=0,255 do r[#r+1]=tostring(regs[i] or -1) end
f:write('{"violations":'..violations..',"stages":['..table.concat(stages,',')..'],"registers":['..table.concat(r,',')..']}');f:close()
for slot=0,1 do
local f=io.open(OUT..'/doc-slot'..slot..'.bin','wb');local b={}
for i=0,8191 do b[#b+1]=string.char(ram[slot*8192+i] or 0) end
f:write(table.concat(b));f:close()
local f=io.open(OUT..'/doc-seen'..slot..'.bin','wb');local b={}
for i=0,8191 do b[#b+1]=ram[slot*8192+i] and '\1' or '\0' end
f:write(table.concat(b));f:close()
local f=io.open(OUT..'/doc-actual'..slot..'.bin','wb');local b={}
for i=0,8191 do b[#b+1]=string.char(manager.machine.devices[':doc'].spaces['rom']:read_u8(slot*8192+i)) end
f:write(table.concat(b));f:close()
end
for tag,device in pairs(manager.machine.devices) do
if tag:find('doc') or tag:find('es5503') then
print('SOUNDDEVICE '..tag)
for name,space in pairs(device.spaces) do print('SOUNDSPACE '..name) end
end end
manager.machine:exit()
end
mark=s:install_write_tap(@MM:TEST_MARKERS@,@MM:TEST_MARKERS@,'sound-stage',function(a,d,m)
stage=d;print('STAGE '..d)
if d==10 then finish() end
end)
tap=s:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDADRH@,'sound-traffic',function(a,d,m)
if a==@MM:SOUNDCTL@ then ctl=d elseif a==@MM:SOUNDADRL@ then adr=d elseif a==@MM:SOUNDADRH@ then hi=d
elseif active and stage>=0 then
audit()
local q=counts[stage] or {0,0,0};counts[stage]=q
if ctl&0x40~=0 then
q[1]=q[1]+1;ram[hi*256+adr]=d
if ctl&0x20~=0 then adr=adr+1;if adr==256 then adr=0;hi=(hi+1)&255 end end
else q[2]=q[2]+1;regs[adr]=d;if ctl&32~=0 then adr=(adr+1)&255 end end
end end)
ctlRead=s:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,'busy-audit',function(a,d,m) busy=d end)
readTap=s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'sound-reads',function(a,d,m)
if active and stage>=0 then audit();local q=counts[stage] or {0,0,0};counts[stage]=q;q[3]=q[3]+1 end
if ctl&32~=0 then adr=(adr+1)&255 end end)
frame=s:install_write_tap(0x3f0,0x3f0,'sound-start',function(a,d,m)
if d==1 and not active then
active=true
local code=CODE
for i=1,#code do s:write_u8(@MM:MENU+0x1c00@+i-1,code[i]) end
s:write_u8(FRAME+1,0);s:write_u8(FRAME+2,0x80);s:write_u8(FRAME+3,0x3f)
end end)
emu.register_frame_done(function()
if not active then s:write_u16(0x3e8,0x5a5a) end
if manager.machine.time:as_double()>420 then print('TIMECAP');manager.machine:exit() end end)
''').replace('OUT',json.dumps(str(out))).replace('CODE','{'+','.join(map(str,code))+'}').replace('FRAME',str(sym['frameLoop']))
lua_guard.write(out/'test.lua', script)
# The trampoline tests playback after boot; all writes stay on private media.
media,_=test_media.prepare(ROOT/'build/wolf-hd.po',out)
live=subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True,check=False).stdout.splitlines()
if any(str(ROOT/'build/tests') in line for line in live):
    raise RuntimeError('A MAME process for this checkout is already running')
cmd=['nice','-n','20',mame_kit.BINARY,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K',*media,'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run','430','-autoboot_delay','0','-autoboot_script',str(out/'test.lua')]
for arg,folder in [('cfg','cfg'),('nvram','nvram'),('state','state'),('snapshot','snap')]:cmd+=['-'+arg+'_directory',str(out/folder)]
with (out/'mame.log').open('w') as log:
    p=subprocess.Popen(cmd,env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1'),stdout=log,stderr=subprocess.STDOUT)
    try:rc=p.wait(timeout=900)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:rc=p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();rc=p.wait(timeout=5)
log=(out/'mame.log').read_text()
if rc or 'STAGE 10' not in log:raise SystemExit(log[-3000:])
t=json.loads((out/'traffic.json').read_text());rows=t['stages']
assert t['violations']==0,t
assert rows[9][1:3]==[0,0] and rows[9][3]==0,rows[9]
assert rows[4][1]==0 and rows[4][2]>0,rows[4]
doc=b''.join((out/f'doc-slot{slot}.bin').read_bytes() for slot in (0,1))
seen=b''.join((out/f'doc-seen{slot}.bin').read_bytes() for slot in (0,1))
actual=b''.join((out/f'doc-actual{slot}.bin').read_bytes() for slot in (0,1))
# The resident effects of the floor reach the DOC while the floor loads, before this test watches the GLU,
# so only the bytes the test saw written are compared.
assert sum(seen)>0 and all(a==b for a,b,s in zip(doc,actual,seen) if s)
for index,sound in [(1,24),(2,18),(3,26),(4,26),(5,31),(6,0),(7,9)]:
    pcm=(ROOT/f'build/sound/effect-{sound:02}.pcm').read_bytes()
    assert rows[index][1] in (0,len(pcm)),(index,sound,rows[index],len(pcm))
    if rows[index][1]:
        assert pcm in doc
t.update(checks=['a repeat of the same sound uploads nothing','zero volume has no GLU access','an upload is the whole one-shot or nothing','the bytes this test saw written match MAME DOC RAM','BUSY polling and IRQ exclusion at every GLU access'],disk_sha256=hashlib.sha256((out/'wolf-hd.po').read_bytes()).hexdigest())
t.update(mame=cmd[3],mame_sha256=hashlib.sha256(Path(cmd[3]).read_bytes()).hexdigest(),
         elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
(ROOT/'docs/evidence/sound/effects-playback.json').write_text(json.dumps(t,indent=2)+'\n')
print('Effects playback: priorities, caches, upload bytes and zero-volume traffic passed')
