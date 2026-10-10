"""Exercise sampled attacks, hardware loops, table sizes and high music voices."""
import memmap
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from doc_song import encode_song
from elf import read
from wolfaudio import DOC_RATE
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/tests/doc-sampled-voices';OUT.mkdir(parents=True,exist_ok=True)
for name in ('cfg','nvram','state','snap'):(OUT/name).mkdir(exist_ok=True)
(OUT/'cfg/apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
_,sym=read(ROOT/'build/wolf.elf')
assert sym['copyLength']<(memmap.SOUND_CODE+0x1300)
pcm=(ROOT/'build/sound/effect-24.pcm').read_bytes()
samples=pcm[:1023]+b'\0'+pcm[1024:2048]+bytes([128])*(180*256-2048)
assert len(samples)==180*256 and 0 not in samples[1024:]
fc=round(7000*16384/DOC_RATE)
commands=[]
for voice,page,level in [(14,0x40,100),(15,0x44,100),(27,0x40,80)]:
    commands += [(0xa0+voice,3),(voice,fc&255),(0x20+voice,fc>>8),
                 (0x80+voice,page),(0xc0+voice,0x17),(0x40+voice,level)]
commands += [(0xaf,1),(0xae,6),(0xbb,0x12)]
fixture,_=encode_song([(0,commands),(700,[])],samples,700)
(OUT/'fixture.bin').write_bytes(fixture)

def long(op,address):return bytes([op])+address.to_bytes(3,'little')
def lda(value):return bytes([0xa9])+struct.pack('<H',value)
def mark(value):return lda(value)+long(0x8f,memmap.TEST_MARKERS)
def call(label):return long(0x22,sym[label])
def wrap(body):return bytes([0x08,0x78,0xc2,0x30,0x48,0xda,0x5a,0x8b])+body+bytes([0xab,0x7a,0xfa,0x68,0x28])+call('I_GetTime')+bytes([0x6b])
first=wrap(call('StopMusic')+mark(1)+lda(0)+long(0x8f,sym['musicLoaded'])+lda(15)+long(0x8f,sym['musicVolume'])+call('StartMusic')+mark(2))
body=mark(3)
index=0
for stage,regs in [(None,[0xae,0xaf,0xbb,0x4e,0x4f,0x5b]),(6,[0x4e,0x4f,0x5b]),(0,[0xae,0xaf,0xbb])]:
    if stage is not None:body+=bytes([0xc2,0x20])+lda(stage)+call('SetMusicVolume')
    body+=bytes([0xe2,0x20])
    for reg in regs:
        body+=bytes([0xa2])+struct.pack('<H',reg)+bytes([0x20])+struct.pack('<H',sym['readRegister']&65535)+long(0x8f,(memmap.TEST_MARKERS+0x10)+index)
        index+=1
body+=bytes([0xc2,0x20])+mark(4)
second=wrap(body)
script=memmap.fill(r'''
local cpu=manager.machine.devices[':maincpu'];local s=cpu.spaces.program
local start=nil;local armed=false;local second=false;local busy=0;local violations=0
local function target(address) for i=0,2 do s:write_u8(FRAME+1+i,(address>>(8*i))&255) end end
local function put(address,bytes) for i,v in ipairs(bytes) do s:write_u8(address+i-1,v) end end
local function finish()
local values={};for i=0,11 do values[#values+1]=s:read_u8(@MM:TEST_MARKERS+0x10@+i) end
local doc=manager.machine.devices[':doc'].spaces.rom;local bytes={}
for i=0,180*256-1 do bytes[#bytes+1]=string.char(doc:read_u8(0x4000+i)) end
local f=io.open(OUT..'/doc.bin','wb');f:write(table.concat(bytes));f:close()
local f=io.open(OUT..'/result.json','w');f:write('{"registers":['..table.concat(values,',')..'],"violations":'..violations..'}');f:close()
manager.machine:exit()
end
ctl=s:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,'busy',function(a,d,m) busy=d end)
local function audit(a,d,m) if busy&128~=0 or cpu.state.P.value&4==0 then violations=violations+1 end end
reads=s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'doc-read',audit)
writes=s:install_write_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'doc-write',audit)
marker=s:install_write_tap(@MM:TEST_MARKERS@,@MM:TEST_MARKERS@,'sample-stage',function(a,d,m)
if d==1 then local f=io.open(OUT..'/fixture.bin','rb');local data=f:read('a');f:close();for i=1,#data do s:write_u8(@MM:MUSIC_BASE@+i-1,data:byte(i)) end
elseif d==2 then start=manager.machine.time:as_double();target(CLOCK)
elseif d==4 then finish() end end)
frame=s:install_write_tap(0x3f0,0x3f0,'sample-start',function(a,d,m)
if d==1 and not armed then armed=true;put(@MM:SOUND_CODE+0x1300@,FIRST);put(@MM:SOUND_CODE+0x1400@,SECOND);target(@MM:SOUND_CODE+0x1300@) end end)
emu.register_frame_done(function()
local t=manager.machine.time:as_double()
if start and t-start>.4 and not second then second=true;target(@MM:SOUND_CODE+0x1400@) end
if t>240 then print('TIMEOUT');manager.machine:exit() end end)
''')
for label,value in [('OUT',json.dumps(str(OUT))),('FRAME',str(sym['frameLoop'])),('CLOCK',str(sym['I_GetTime'])),('FIRST','{'+','.join(map(str,first))+'}'),('SECOND','{'+','.join(map(str,second))+'}')]:script=script.replace(label,value)
lua_guard.write(OUT/'test.lua', script)
cmd=['nice','-n','20',mame_kit.BINARY,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K','-flop3',str(ROOT/'build/disk1.po'),'-flop4',str(ROOT/'build/disk2.po'),'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run','250','-autoboot_delay','0','-autoboot_script',str(OUT/'test.lua')]
for arg,folder in [('cfg','cfg'),('nvram','nvram'),('state','state'),('snapshot','snap')]:cmd+=['-'+arg+'_directory',str(OUT/folder)]
with (OUT/'mame.log').open('w') as log:
    p=subprocess.Popen(cmd,env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1'),stdout=log,stderr=subprocess.STDOUT)
    try:rc=p.wait(timeout=65)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:rc=p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();rc=p.wait(timeout=5)
assert rc==0,(OUT/'mame.log').read_text()[-2000:]
r=json.loads((OUT/'result.json').read_text());v=r['registers']
assert v[:3]==[7,0,0x13],v
assert v[3:9]==[100,100,80,40,40,32],v
assert v[9:]==[3,3,3] and r['violations']==0,r
assert (OUT/'doc.bin').read_bytes()==samples
r.update(checks=['1024-byte sampled attack swaps into a free-running 1024-byte loop','voice 27 one-shot and output-channel bits','master volume updates voices above the IMF range','off stops both attack/loop voices and voice 27','DOC RAM matches the full sampled wave image','all DOC reads and writes obey BUSY and IRQ exclusion'])
r.update(mame=cmd[3],mame_sha256=hashlib.sha256(Path(cmd[3]).read_bytes()).hexdigest(),
         disk_sha256=hashlib.sha256((ROOT/'build/disk1.po').read_bytes()).hexdigest(),
         elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
(ROOT/'docs/evidence/sound/sampled-voices.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r,indent=2))
