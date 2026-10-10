"""Bounded stock MAME cold boot; keep only timings and selected final frames."""
from mame_target import ram_size
import argparse
import json
import hashlib
import os
import pathlib
import re
import subprocess
from elf import read
import logic_capture
import memmap
from memmap import projections
import test_media
import lua_guard
import mame_kit

ROOT=pathlib.Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument('--machine',default='apple2gsr1',choices=('apple2gsr1','apple2gs'))
ap.add_argument('--demo',type=int,choices=range(4))
ap.add_argument('--disk',type=pathlib.Path,default=ROOT/'build/disk1.po')
ap.add_argument('--elf',type=pathlib.Path,default=ROOT/'build/wolf.elf',help='linked symbols matching the disk under test')
ap.add_argument('--drives',type=int,choices=(1,2),default=2)
ap.add_argument('--limit',type=int,default=140)
ap.add_argument('--host-limit',type=int,default=300)
ap.add_argument('--frames',type=int,default=20)
ap.add_argument('--ramsize',default=None, help='default: 4352K on ROM 01, 5M on ROM 03')
ap.add_argument('--name',default='stage1-start')
ap.add_argument('--keys',default='')
ap.add_argument('--command',type=int,default=0)
ap.add_argument('--key-steps',default='',help='frame:keys pairs for keyboard events')
ap.add_argument('--latch-steps',default='',help='frame:latch pairs written to $3E1 at the start of that frame')
ap.add_argument('--command-steps',default='',help='frame:command pairs, held until the next pair')
ap.add_argument('--spawn',nargs=3,type=int,metavar=('X','Y','ANGLE'))
ap.add_argument('--pal',action='store_true')
ap.add_argument('--profile',action='store_true')
ap.add_argument('--check-assets',action='store_true',help='read back the current floor art before its first frame')
ap.add_argument('--death-frame',type=int,help='diagnostic: set the source death result before this frame')
ap.add_argument('--capture-frames',nargs='+',type=int)
ap.add_argument('--view',type=int,default=214,choices=(160,214,240,320))
ap.add_argument('--depth-shading',type=int,choices=(0,1),help='set the native depth-light option before the first frame')
ap.add_argument('--pixel-probe',nargs=2,type=int,metavar=('BYTE_X','ROW'))
ap.add_argument('--column-directory-fixture',action='store_true',help='exercise the lighting column-directory adapter with existing art addresses')
args=ap.parse_args()
if args.ramsize is None:args.ramsize='5M' if args.machine=='apple2gs' else '4352K'
if args.spawn and not (0 <= args.spawn[0] < 64*256 and 0 <= args.spawn[1] < 64*256 and 0 <= args.spawn[2] < 1024):
    ap.error("spawn must be inside the 64 by 64 map with angle 0..1023")
key_steps={2:args.keys} if args.keys else {}
for pair in filter(None,args.key_steps.split(',')):
    frame,key=pair.split(':',1);frame=int(frame)
    if not 1<=frame<=args.frames:ap.error('invalid keyboard frame')
    key_steps[frame]=key
latches={}
for pair in filter(None,args.latch_steps.split(',')):
    frame,latch=map(int,pair.split(':'))
    if not 1<=frame<=args.frames or not 1<=latch<=4:ap.error('invalid view latch')
    latches[frame]=latch
steps={1:0,2:args.command}
for pair in filter(None,args.command_steps.split(',')):
    frame,command=map(int,pair.split(':'))
    if not 1<=frame<=args.frames or not 0<=command<=255:ap.error('invalid command step')
    steps[frame]=command
if args.disk.stat().st_mtime_ns < args.elf.stat().st_mtime_ns:
    ap.error('disk image is older than the linked game; wait for make to finish')
disk_sha=hashlib.sha256(args.disk.read_bytes()).hexdigest()
captures=set(args.capture_frames or (1,args.frames))
if len(captures)>8 or any(n<1 or n>args.frames for n in captures):
    ap.error('capture at most eight selected frames within the run')
out=ROOT/'build/tests'/args.name
out.mkdir(parents=True,exist_ok=True)
(out/'cfg').mkdir(exist_ok=True);(out/'state').mkdir(exist_ok=True)
(out/'cfg'/f'{args.machine}.cfg').write_text(f'<mameconfig version="10"><system name="{args.machine}"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
script=memmap.fill('''local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
for _,name in ipairs({"a2_config","bus_timing","ram_start","snd_demux"}) do local port=manager.machine.ioport.ports[":"..name];if port then print("SETTING "..name.." "..port:read()) end end
local start=nil
local n=0
local ready=false
local phaseStart=nil
local castTime=nil
local prof=manager.machine.memory.regions[":zipprof"]
local baseline=nil
local frameWorldTics=0
local frameWorldLead=0
local framePlayerTics=0
local frameHasWorld=false
local doorAddress=DOORADDR
local doorCountAddress=DOORCOUNTADDR
local worldCountAddress=COUNTADDR
local gameFields=GAMEFIELDS
local steps=STEPS
local command=0
local spawn=SPAWN
local keySteps=KEYEVENTS
local latchSteps=@@LATCH@@
local captures=CAPTURES
local viewAddress=VIEWADDR
local heightAddress=HEIGHTADDR
local sourceAddress=SOURCEADDR
local bankAddress=BANKADDR
local planeAddress=PLANEADDR
local function gameState()
local fields={}
for _,field in ipairs(gameFields) do
local value=field[1]=='score' and s:read_u32(field[2]) or s:read_u16(field[2])
fields[#fields+1]='"'..field[1]..'":'..value
end
return '{'..table.concat(fields,',')..'}'
end
local function snapshot()
local t={}
for i=0x2000,0x5fff do t[i]=prof:read_u64(@MM:ART_BRIGHT+0x100@+i*24+16) end
return t
end
PROBE
phase_tap=s:install_write_tap(0x3f2,0x3f2,"phase",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then phaseStart=t elseif d==2 and phaseStart then castTime=t-phaseStart end
end)
scene_tap=s:install_write_tap(0x3f0,0x3f0,"scene",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then
ready=true; start=t
framePlayerTics=s:read_u16(0x1048)
frameWorldLead=s:read_u16(0x1044)~=0 and 0 or s:read_u16(WORLDLEAD)
frameHasWorld=s:read_u16(LEVELSTATE)==0
if n==0 then
if PAL then s:write_u8(@MM:LANGSEL@,s:read_u8(@MM:LANGSEL@)|0x10) end
if spawn then s:write_u16(0x1000,spawn[1]);s:write_u16(0x1002,spawn[2]);s:write_u16(0x1004,spawn[3]) end
end
if PROFILE and n==1 then baseline=snapshot() end
if n==0 and VIEW~=214 then s:write_u8(0x3e1,({[160]=1,[214]=2,[240]=3,[320]=4})[VIEW]) end
if latchSteps[n+1] then s:write_u8(0x3e1,latchSteps[n+1]) end
if steps[n+1] then command=steps[n+1] end
s:write_u8(0x3e0,command)
if keySteps[n+1] then emu.keypost(keySteps[n+1]) end
elseif d==2 and start~=nil then
frameWorldTics=frameHasWorld and framePlayerTics-frameWorldLead+s:read_u16(WORLDLEAD) or 0
n=n+1
print(string.format("FRAME %d %.9f",n,t-start)); io.stdout:flush()
print(string.format("COLW %d %d",n,s:read_u16(viewAddress)))
print(string.format("POSE %d %d %d %d",n,s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004)))
print('LOGIC '..n..' '..s:read_u16(0x1048)..' '..command..' '..frameWorldTics..' '..gameState())
if castTime then print(string.format("CAST %d %.9f",n,castTime)) end
if captures[n] then
manager.machine.screens[":screen"]:snapshot('screen'..n..'.png')
local f=io.open(OUT.."/frame"..n..".bin","wb")
local bytes={}
for row=0,159 do for x=0,159 do bytes[#bytes+1]=string.char(s:read_u8(@MM:SHR@+row*160+x)) end end
f:write(table.concat(bytes)); f:close()
local f=io.open(OUT.."/hud"..n..".bin","wb")
local bytes={}
for i=25600,31999 do bytes[#bytes+1]=string.char(s:read_u8(@MM:SHR@+i)) end
f:write(table.concat(bytes));f:close()
local f=io.open(OUT.."/map"..n..".bin","wb")
local bytes={}
for i=0,4095 do bytes[#bytes+1]=string.char(s:read_u8(@MM:MAP@+i)) end
f:write(table.concat(bytes));f:close()
local doors={}
for i=0,s:read_u16(doorCountAddress)//2-1 do doors[#doors+1]=tostring(s:read_u16(doorAddress+i*2)) end
local st=io.open(OUT.."/state"..n..".json","w")
st:write(string.format('{"x":%d,"y":%d,"angle":%d,"view_width":%d,"doc_ticks":%d,"emulated_time":%.9f,"refresh_hz":%.6f,"doors":[%s],"game":%s,"actor_flags":%s}',s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004),s:read_u16(viewAddress),s:read_u16(0x104c),t,1/manager.machine.screens[":screen"].frame_period,table.concat(doors,","),gameState(),actorVisibility()));st:close()
local f=io.open(OUT.."/objects"..n..".json","w")
local objects={}
for i=0,s:read_u16(worldCountAddress)-1 do
local fields={}
for j=0,15 do fields[#fields+1]=tostring(s:read_u16(@MM:OBJECT_RECORDS@+i*32+j*2)) end
objects[#objects+1]="["..table.concat(fields,",").."]"
end
local visible={}
for i=0,s:read_u16(0x107c)-1 do
local fields={}
for j=0,6 do fields[#fields+1]=tostring(s:read_u16(@RECORDS@+i*16+j*2)) end
visible[#visible+1]="["..table.concat(fields,",").."]"
end
f:write('{"objects":['..table.concat(objects,",")..'],"visible":['..table.concat(visible,",")..']}');f:close()
local posts={}
for col=0,s:read_u16(viewAddress)-1 do
posts[#posts+1]=string.format('[%d,%d,%d,%d]',s:read_u16(heightAddress+col*2),s:read_u16(sourceAddress+col*2),(BANKSTRIDE==2 and s:read_u16(bankAddress+col*2) or s:read_u8(bankAddress+col)),s:read_u16(planeAddress+col*2))
end
local f=io.open(OUT.."/posts"..n..".json","w")
f:write('['..table.concat(posts,",")..']');f:close()
end
if n>=FRAMES then
if PROFILE and baseline then
local final=snapshot(); local f=io.open(OUT.."/profile.txt","w")
for i=0x2000,0x5fff do
local delta=final[i]-baseline[i]
if delta>0 then f:write(string.format("%06x %d\\n",i*16,delta)) end
end
f:close()
end
manager.machine:exit()
end
end end)
emu.register_frame_done(function()
local t=manager.machine.time:as_double()
if not ready then s:write_u16(0x3e8,0x5a5a) end
if t>140 then print("TIMEOUT ready="..tostring(ready).." pc="..string.format("%02x:%04x",cpu.state.PB.value,cpu.state.PC.value)); manager.machine:exit() end
end)
''')
probe=''
if args.pixel_probe:
    x,y=args.pixel_probe
    if not 0<=x<160 or not 0<=y<160:ap.error('probe outside view RAM')
    address=memmap.SHR+y*160+x
    probe=memmap.fill('''probeTap=s:install_write_tap(ADDRESS,ADDRESS,"pixel-probe",function(a,d,m)
if n~=0 then return end
local l=s:read_u32(0x103a)&0xffffff;local r=s:read_u32(0x103e)&0xffffff
local row=s:read_u16(0x108a);local lb=s:read_u16(0x10de);local rb=s:read_u16(0x10e0)
local lt=s:read_u8(@MM:WALL_CAST@+lb+row)*2+(row&1);local rt=s:read_u8(@MM:WALL_CAST@+rb+row)*2+(row&1)
print(string.format('PIXELPROBE %d col %d row %d ptr %06x %06x tex %d %d color %d %d',d,s:read_u16(0x102e),row,l,r,lt,rt,s:read_u8(l+lt),s:read_u8(r+rt)))
if s:read_u16(0x102e)>0 then
local dump={};for i=0,11 do dump[#dump+1]=tostring(s:read_u16(PROBELEFT+i*2)) end
print('LEFTSPANS '..table.concat(dump,','))
print(string.format('ENDTABLE %d %d',s:read_u8(@MM:ART_MID+0x61d32@),s:read_u8(@MM:ART_MID+0x61d3a@)))
end
end)''').replace('ADDRESS',str(address))
script=script.replace('PROBE',probe)
elf_segments,symbols=read(args.elf)
script=script.replace("@RECORDS@",str(projections(symbols)[0]))
if args.depth_shading is not None:
    script=script.replace('if n==0 then\nif PAL',
        'if n==0 then\ns:write_u16(%d,%d);s:write_u16(%d,65535)\nif PAL' %
        (symbols['columnLight'],args.depth_shading,symbols['heightView']))
exact_logic='LogicFrame' in symbols
if exact_logic:
    script=script.replace('local start=nil',logic_capture.lua()+logic_capture.actor_visibility_lua(symbols)+'\nlocal start=nil',1)
    script=script.replace('frameWorldLead=s:read_u16(0x1044)~=0 and 0 or s:read_u16(WORLDLEAD)','frameWorldLead=0')
    script=script.replace('framePlayerTics-frameWorldLead+s:read_u16(WORLDLEAD)','framePlayerTics')
    script=script.replace('if spawn then s:write_u16(0x1000,spawn[1]);s:write_u16(0x1002,spawn[2]);s:write_u16(0x1004,spawn[3]) end',
                          'if spawn then logicSpawn(spawn[1],spawn[2],spawn[3]) end')
    script=script.replace(memmap.fill('for i=0,s:read_u16(worldCountAddress)-1 do\nlocal fields={}\nfor j=0,15 do fields[#fields+1]=tostring(s:read_u16(@MM:OBJECT_RECORDS@+i*32+j*2)) end\nobjects[#objects+1]="["..table.concat(fields,",").."]"\nend'),
                          'for _,fields in ipairs(logicObjects()) do objects[#objects+1]="["..table.concat(fields,",").."]" end')
if not exact_logic:script=script.replace('local start=nil','local function actorVisibility() return "false" end\nlocal start=nil',1)
if args.death_frame:
    if not exact_logic or not 1<=args.death_frame<=args.frames:ap.error('death frame requires the exact logic and a frame in this run')
    script=script.replace('if steps[n+1] then',"if n+1==%d then s:write_u16(LC.V_health,0);s:write_u16(LC.V_events,s:read_u16(LC.V_events)|3);s:write_u16(LC.V_playstate,2);s:write_u16(LC.V_killerobj,s:read_u16(LC.OBJLIST+LC.O_NEXT)) end\nif steps[n+1] then"%args.death_frame)
script=script.replace('PROBELEFT',str(symbols.get('trueLeftSpans',0))).replace('WORLDLEAD',str(symbols.get('worldLead',0))).replace('LEVELSTATE',str(symbols['levelState']))
meta=json.loads((ROOT/'build/assets/map.json').read_text())
world=json.loads((ROOT/'build/assets/world.json').read_text())
game_names=('objectCount','health','ammo','keys','lives','score','randomIndex','killCount','weapon','chosenWeapon','bestWeapon','weaponFrame','attackActive','attackPhase','attackTicks','fireHeld','levelState','levelIndex','secretCount','pwallState','pwallPosition','pwallCell','pwallStep','pwallTile')
if exact_logic:
    game_names=('health','ammo','keys','lives','score','killCount','weapon','chosenWeapon','bestWeapon','weaponFrame','levelState','levelIndex','pwallPosition','deathPhase')
if not args.death_frame:game_names=tuple(n for n in game_names if n!='deathPhase')
game_names+=tuple(name for name in ('flowPhase','nextFloor') if name in symbols)
game_fields='{'+','.join('{'+json.dumps(name)+','+str(symbols[name])+'}' for name in game_names)+'}'
script=re.sub(r'\bCOUNTADDR\b',str(symbols.get('objectCount',0)),script).replace('GAMEFIELDS',game_fields).replace('STEPS','{'+','.join('[%d]=%d'%pair for pair in sorted(steps.items()))+'}')
if args.column_directory_fixture:
    assert 'WOLF_PREPARED 1' in (ROOT/'build/gen/picture_config.inc').read_text()
    code_limit=next(segment['address']+segment['size'] for segment in elf_segments if segment['address']==memmap.SW_SEG_CODE)
    stub=code_limit-32
    code_end=max(int(last,16) for last in re.findall(r'^(?:code|gamecode)\s+[0-9a-f]+-([0-9a-f]+)',(ROOT/'build/wolf.lst').read_text(),re.M))
    assert code_end<stub and stub+11<code_limit
    fixture=memmap.fill('''local directoryCheck=nil
local function installDirectoryFixture()
local pages=PAGES
local overwritten={}
for i=0,#pages*256-1 do overwritten[i]=s:read_u8(@MM:COLUMN_DIR@+i) end
local offsets={}
for i,page in ipairs(pages) do
local offset=(i-1)*256;offsets[page]=offset
for u=0,63 do
s:write_u16(@MM:COLUMN_DIR@+offset+u*4,s:read_u16(@MM:OLD_WALL_COLUMNS@+page*256+u*4))
s:write_u16(@MM:COLUMN_DIR+0x2@+offset+u*4,s:read_u16(@MM:ART_STAGE+0x38002@+page*256+u*4)&255)
end
end
local expected={}
for page=0,105 do
local offset=offsets[page] or 0;s:write_u16(TEXBASE+page*2,offset)
for u=0,63 do
expected[page*256+u*4]=s:read_u16(@MM:COLUMN_DIR@+offset+u*4)
expected[page*256+u*4+2]=s:read_u16(@MM:COLUMN_DIR+0x2@+offset+u*4)|(page*256)
end
end
for u=0,63 do s:write_u16(TEXOFFSETS+u*2,u*4) end
local original={};for i=0,4 do original[i+1]=s:read_u8(CASTFRAME+i) end
local code={0x20,INITDIR&255,(INITDIR>>8)&255,table.unpack(original)}
code[#code+1]=0x4c;code[#code+1]=(CASTFRAME+5)&255;code[#code+1]=((CASTFRAME+5)>>8)&255
for i,b in ipairs(code) do s:write_u8(STUB+i-1,b) end
s:write_u8(CASTFRAME,0x4c);s:write_u16(CASTFRAME+1,STUB&65535)
directoryCheck=function()
local count=0;local bad=0
for offset,value in pairs(expected) do count=count+1;if s:read_u16(@MM:ART_STAGE+0x38000@+offset)~=value then bad=bad+1 end end
for i=0,#pages*256-1 do s:write_u8(@MM:COLUMN_DIR@+i,overwritten[i]) end
for i,b in ipairs(original) do s:write_u8(CASTFRAME+i-1,b) end
print(string.format('DIRECTORYCHECK %d %d %d',count,bad,#pages*256));io.stdout:flush()
end
end
''')
    for token,value in {'PAGES':'{'+','.join(map(str,meta['textures']))+'}','TEXBASE':symbols['texBase'],'TEXOFFSETS':symbols['texOffsets'],'CASTFRAME':symbols['castFrame'],'INITDIR':symbols['InitRayTextureDirectory'],'STUB':stub}.items():fixture=fixture.replace(token,str(value))
    script=script.replace('phase_tap=s:',fixture+'phase_tap=s:',1)
    script=script.replace('castTime=t-phaseStart end','castTime=t-phaseStart;if directoryCheck then directoryCheck();directoryCheck=nil end end',1)
    script=script.replace('if n==0 then\nif PAL','if n==0 then\ninstallDirectoryFixture()\nif PAL',1)
script=script.replace('BANKSTRIDE','2' if 'WOLF_PREPARED 1' in (ROOT/'build/gen/picture_config.inc').read_text() else '1')
script=script.replace('CAPTURES','{'+','.join('[%d]=true'%n for n in sorted(captures))+'}').replace('WORLDCOUNT',str(len(world['objects']))).replace('HEIGHTADDR',str(symbols['heightIndex'])).replace('SOURCEADDR',str(symbols['sourceAddr'])).replace('BANKADDR',str(symbols['sourceBank'])).replace('PLANEADDR',str(symbols['hitPlane'])).replace('VIEWADDR',str(symbols['viewWidth'])).replace('KEYEVENTS','{'+','.join('[%d]=%s'%(frame,json.dumps(key)) for frame,key in sorted(key_steps.items()))+'}').replace('@@LATCH@@','{'+','.join('[%d]=%d'%pair for pair in sorted(latches.items()))+'}').replace('DOORADDR',str(symbols['doorPosition'])).replace('DOORCOUNTADDR',str(symbols['doorBytes'])).replace('SPAWN','{'+','.join(map(str,args.spawn))+'}' if args.spawn else 'false').replace('PAL','true' if args.pal else 'false').replace('PROFILE','true' if args.profile else 'false').replace('FRAMES',str(args.frames)).replace('COMMAND',str(args.command)).replace('VIEW',str(args.view));script=re.sub(r'\bOUT\b',lambda _:json.dumps(str(out)),script)
if args.demo is not None:
    if not exact_logic:ap.error('demo capture requires the exact logic build')
    script=script.replace('local start=nil','local demoRequested=false\nlocal start=nil',1)
    script=script.replace('ready=true; start=t','ready=true; start=t\nif not demoRequested then demoRequested=true; s:write_u8(0x3e3,1); s:write_u8(0x3e2,%d) end'%(args.demo+1))
script=script.replace('if t>140 then','if t>%d then'%args.limit)
media,swaps=test_media.prepare(args.disk,out,drives=args.drives)
if args.check_assets:
    import floor_capture
    from buildconfig import config
    script += floor_capture.lua(out, floor=config()['floor']-1, trigger=0x3f0, value=1)
lua_guard.write(out/'scene.lua', script+'\n'+swaps)
cmd=['nice','-n','20',mame_kit.BINARY,args.machine,'-rompath',mame_kit.ROMPATH,'-ramsize',args.ramsize or ram_size(args.machine),*media,'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run',str(args.limit+10),'-autoboot_delay','0','-autoboot_script',str(out/'scene.lua'),'-cfg_directory',str(out/'cfg'),'-state_directory',str(out/'state'),'-nvram_directory',str(out/'nvram'),'-snapshot_directory',str(out)]
env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
live=[line for line in subprocess.run(['pgrep','-fl','(gsdoom|/iigs.app/Contents/MacOS/iigs)'],capture_output=True,text=True).stdout.splitlines() if str(ROOT/'build/tests') in line]
if len(live)>=1:raise SystemExit('A worker MAME process is already running; this test did not start.')
with (out/'mame.log').open('w') as log:
    p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
    try: code=p.wait(timeout=args.host_limit)
    except subprocess.TimeoutExpired:
        p.terminate()
        try: code=p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill(); code=p.wait(timeout=5)
log=(out/'mame.log').read_text()
logic=[dict(frame=int(n),tics=int(tics),command=int(command),world_tics=int(world_tics),game=json.loads(game)) for n,tics,command,world_tics,game in re.findall(r'^LOGIC (\d+) (\d+) (\d+) (\d+) (.*)',log,re.M)]
(out/'logic.json').write_text(json.dumps(logic,separators=(',',':'))+'\n')
timings=[float(t) for t in re.findall(r'^FRAME \d+ ([\d.]+)',log,re.M)]
if code or len(timings)!=args.frames:
    raise SystemExit(log[-2500:])
if args.check_assets and not re.search(r'^ASSETS_DONE 0(?: |$)', log, re.M):
    raise SystemExit('Native asset readback failed; see '+str(out/'mame.log'))
moving=timings[1:]
casts=[float(t) for t in re.findall(r'^CAST \d+ ([\d.]+)',log,re.M)][1:]
result=dict(demo=args.demo,disk_sha256=disk_sha,elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),keys=args.keys,key_steps=args.key_steps,command_steps=args.command_steps,view=args.view,pal=args.pal,spawn=args.spawn,cast_ms=1000*sum(casts)/len(casts) if casts else None,model=mame_kit.NAME+' stock bus bit 0x001',machine=args.machine,frames=args.frames,command=args.command,mean_ms=1000*sum(moving)/len(moving) if moving else None,fps=len(moving)/sum(moving) if moving else None,worst_ms=1000*max(moving) if moving else None,first_ms=timings[0]*1000)
result['depth_shading']=args.depth_shading
ray_mode=(ROOT/'build/gen/ray_mode.inc').read_text()
result['unwrapped_rays']='sameMaterial' in symbols
result['material_lookup']='resolveRayMaterial' in symbols
result['material_guard_texels']=0
result['coarse_material']='nearbyMaterial' in symbols
result['vector_weights']='weightedSpanVector' in symbols
result['split_span']='prepareSplitSpan' in symbols
result['mixed_span']='prepareMixedSpan' in symbols
result['weighted_span']='fillWeightedSpan' in symbols
result['weighted_rays']='weightedRay' in symbols
result['plane_rays']='planeRay' in symbols
result['push_planes']='pushPlane' in symbols
result['door_planes']='movingWallPlane' in symbols
result['span_fill']='fillRaySpan' in symbols
result['mame_binary']=cmd[3]
result['rays']='exact' if 'WOLF_EXACT_RAYS 1' in ray_mode else 'thirtytwo' if 'WOLF_RAY_STRIDE 32' in ray_mode else 'sixteenth' if 'WOLF_RAY_STRIDE 16' in ray_mode else 'eighth' if 'WOLF_RAY_STRIDE 8' in ray_mode else 'quarter' if 'WOLF_QUARTER_RAYS 1' in ray_mode else 'half'
if args.column_directory_fixture:
    checks=re.search(r'^DIRECTORYCHECK (\d+) (\d+) (\d+)',log,re.M)
    if not checks or int(checks[2]):raise SystemExit('native column-directory fixture failed')
    result['column_directory_fixture']=dict(checked_words=int(checks[1]),differing_words=int(checks[2]),restored_art_bytes=int(checks[3]))
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
