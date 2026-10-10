"""Stock MAME play through real keyboard fields and whole-screen snapshots."""
import memmap
from mame_target import ram_size
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import statistics
import shutil
from elf import read
import logic_capture
import test_media
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument('--name',required=True)
ap.add_argument('--scenario',choices=('controls','route','tap','slowtap','turn','walk','guards','guards-still','fight','mouse'),default='controls')
ap.add_argument('--disk',type=Path,default=ROOT/'build/disk1.po')
ap.add_argument('--elf',type=Path,default=ROOT/'build/wolf.elf')
ap.add_argument('--view',type=int,choices=(160,214,240,320),default=214)
ap.add_argument('--plan',type=Path)
ap.add_argument('--end',type=float)
ap.add_argument('--input-origin',type=float)
ap.add_argument('--seed-weapons',action='store_true')
ap.add_argument('--profile-at',type=float)
ap.add_argument('--profile-phase',choices=('paint','frame','cast'),default='paint')
ap.add_argument('--instruction-counts',action='store_true')
ap.add_argument('--analyze',action='store_true')
ap.add_argument('--music-volume',type=int,choices=range(16))
ap.add_argument('--music-song',type=int)
ap.add_argument('--music-unit',type=Path,help='candidate WDM2, WDP2 or WDP3 song bank')
ap.add_argument('--sound-audit',action='store_true')
ap.add_argument('--effects-every',type=float,default=0)
ap.add_argument('--settings-audit',action='store_true')
ap.add_argument('--reinsert-settings-disk',action='store_true')
ap.add_argument('--irq-profile',action='store_true')
ap.add_argument('--irq-collision',action='store_true')
ap.add_argument('--pal',action='store_true')
ap.add_argument('--realtime',action='store_true')
ap.add_argument('--ramsize',default=None, help='default: 4352K on ROM 01, 5M on ROM 03')
ap.add_argument('--machine',default='apple2gsr1',choices=('apple2gsr1','apple2gs'))
args=ap.parse_args()
if args.irq_collision:args.sound_audit=True
if args.instruction_counts and args.profile_at is None:ap.error('--instruction-counts requires --profile-at')
# Frozen image/ELF pairs have copy times, so the build-order guard applies
# to the live Makefile output. Every run still records both content hashes.
if not args.analyze and args.disk.resolve()==ROOT/'build/disk1.po' and args.disk.stat().st_mtime_ns < args.elf.stat().st_mtime_ns:
    ap.error('disk image is older than the linked game; wait for make to finish')
out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
if args.profile_at is not None and not args.analyze:shutil.copyfile(args.elf,out/'profile.elf')
(out/'cfg').mkdir(exist_ok=True);(out/'snap').mkdir(exist_ok=True);(out/'state').mkdir(exist_ok=True)
(out/('cfg/'+args.machine+'.cfg')).write_text('<mameconfig version="10"><system name="%s"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>'%args.machine)
_,symbols=read(args.elf)
disk_sha=hashlib.sha256(args.disk.read_bytes()).hexdigest()
elf_sha=hashlib.sha256(args.elf.read_bytes()).hexdigest()
spawn=None
if args.scenario=='controls':
    plan=[(1,1.2,['Right Arrow']),(2,3,['Right Arrow','f  F']),(3.5,4,['w  W','Right Arrow','f  F']),(4.5,4.7,['Left Arrow','Right Arrow'])]
    snaps=[.5,1.15,1.4,2.5,3.8,5.5];end=6
elif args.scenario=='route':
    plan=[(2,2.7,['w  W']),(3.2,3.35,['Space']),(4,7,['w  W']),(7.5,8.5,['Right Arrow']),(9,11,['f  F']),(11.5,14,['w  W','f  F'])]
    snaps=[1,3.7,5.5,8,10,13];end=15
elif args.scenario in ('tap','slowtap'):
    plan=[(1,1.03,['Right Arrow']),(3,3.5,['Right Arrow']),(5,7,['Right Arrow'])]
    if args.scenario=='slowtap':
        spawn=(9600,2944,0)
        plan=[plan[0]]+[(.5+n*.5,.75+n*.5,['f  F']) for n in range(5)]
    snaps=[.5,1.5,3.7,5.1,7.2,7.7];end=8
    if args.scenario=='slowtap':snaps=[.5,1.1,1.3,1.5,2,2.5];end=3
elif args.scenario=='mouse':
    plan=[(2,2.25,['Mouse Button 0']),(3,3.5,['Mouse Button 1']),(4,4.5,['w  W','Mouse Button 1'])]
    snaps=[.5,1.5,2.5,3.5,4.5,5.5];end=6
else:
    plan={'turn':[(1,6,['Right Arrow'])], 'walk':[(1,2.5,['w  W'])], 'guards':[(1,6,['Right Arrow'])], 'guards-still':[], 'fight':[(.5+n*.5,.75+n*.5,['f  F']) for n in range(8)]}[args.scenario]
    if args.scenario in ('guards','guards-still','fight'):spawn=(9600,2944,0)
    if args.scenario=='walk':spawn=(8832,12544,256)
    snaps=[.5,1.5,2,3,4,6.5];end=7
if args.plan:plan=json.loads(args.plan.read_text());snaps=[];end=args.end or 18
if args.end is not None:end=args.end
left=(160-args.view//2)//2;top=(160-args.view//2)//2;right=left+args.view//2;bottom=top+args.view//2
script=memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
for _,name in ipairs({"a2_config","bus_timing","ram_start","snd_demux"}) do local port=manager.machine.ioport.ports[":"..name];if port then print("SETTING "..name.." "..port:read()) end end
SOUNDTEST
local screen=manager.machine.screens[":screen"]
local plan=PLAN
local snaps=SNAPS
local spawn=SPAWN
local start=nil
local frameStart=nil
local held={}
local last={}
local n=0
local shot=1
local video=0
local previous=nil
local paintFirst=nil
local paintLast=nil
local paintVideo=nil
local lastVideo=nil
local bootshot=1
local bootTimes={5,60,180}
local prof=manager.machine.memory.regions[":zipprof"]
local baseline=nil
local profiled=false
local auditStores=0
local paintStart=nil
local castStart=nil
local changedFirst=nil
local lastPose=nil
local profileRanges={{0x0800,0x08ff},{0x2000,0x5fff},{0x6d80,0x6dff},{0x8fea,0x8fff}}
local function profileSnapshot()
local p={};for _,r in ipairs(profileRanges) do for i=r[1],r[2] do p[i]=prof:read_u64(@MM:ART_BRIGHT+0x100@+i*24+16) end end;return p
end
local function saveProfile(t,origin)
if baseline and not profiled and (paintFirst or CASTONLY) then
local final=profileSnapshot();local f=io.open(OUT..'/profile.txt','w')
for _,r in ipairs(profileRanges) do for i=r[1],r[2] do local dt=final[i]-baseline[i];if dt>0 then f:write(string.format('%06x %d\n',i<0x6000 and i*16 or (i-0x6000)*256,dt)) end end end
f:close();profiled=true;print(string.format('PCSAMPLE %.9f %.9f',origin-start,t-origin))
print(string.format('AUDITSTORES %d',auditStores))
if COUNTS then manager.machine.debugger:command('trace off,:maincpu') end
end
baseline=nil
end
local function field(name)
for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do if f.name==name or ((name=='Option' or name=='Command') and f.name:find(name)) or (#name==1 and f.name:sub(1,1)==name and #f.name<=4) or (name=='Mouse X' and f.name:find('Mouse X')) or (name=='Mouse Y' and f.name:find('Mouse Y')) then return f end end end
error('missing real key '..name)
end
screenTap=s:install_write_tap(@MM:SHR@,@MM:SHR+0x63ff@,"paint-time",function(a,d,m)
local offset=a-@MM:SHR@
local y=offset//160;local x=offset%160
if start and x>=LEFT and x<RIGHT and y>=TOP and y<BOTTOM then
local t=manager.machine.time:as_double()
if baseline then auditStores=auditStores+1 end
paintFirst=paintFirst or t;paintVideo=paintVideo or video
paintLast=t;lastVideo=video
if not changedFirst and s:read_u8(a)~=d then
changedFirst=t
print(string.format('VISIBLE %.9f %d %d %d',t-start,s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004)))
end
end end)
paintTap=s:install_write_tap(0x3f3,0x3f3,"paint",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then paintStart=t
if PROFILE and not WHOLEFRAME and not CASTONLY and start and t-start>=PROFILEAT and not profiled then auditStores=0;baseline=profileSnapshot();if COUNTS then manager.machine.debugger:command('trace '..OUT..'/instructions.trace,:maincpu,noloop') end end
elseif d==2 and paintStart then
print(string.format('PAINTCPU %d %.9f',n+1,t-paintStart))
if not WHOLEFRAME and not CASTONLY then saveProfile(t,paintStart) end
end end)
castTap=s:install_write_tap(0x3f2,0x3f2,"cast-time",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then
castStart=t
if PROFILE and CASTONLY and start and t-start>=PROFILEAT and not profiled then
    auditStores=0;baseline=profileSnapshot()
    if COUNTS then manager.machine.debugger:command('trace '..OUT..'/instructions.trace,:maincpu,noloop') end
end
elseif d==2 and castStart then
print(string.format('CASTCPU %d %.9f',n+1,t-castStart))
if CASTONLY then saveProfile(t,castStart) end
end end)
inputTap=s:install_write_tap(INPUTHEAD,INPUTHEAD+1,"input-queue",function(a,d,m)
if a~=INPUTHEAD or not start then return end
local p=s:read_u16(INPUTHEAD)
print(string.format('ADB %.9f %d %d %d %d',manager.machine.time:as_double()-start,s:read_u16(INPUTRING+p),s:read_u16(INPUTRING+p+2),s:read_u16(INPUTRING+p+4),s:read_u16(INPUTRING+p+6)))
end)
tap=s:install_write_tap(0x3f0,0x3f0,"play",function(a,d,m)
local t=manager.machine.time:as_double()
if d==1 then SOUNDCOST frameStart=t;paintFirst=nil;paintLast=nil;paintVideo=nil;lastVideo=nil;changedFirst=nil
if PROFILE and WHOLEFRAME and start and t-start>=PROFILEAT and not profiled then auditStores=0;baseline=profileSnapshot();if COUNTS then manager.machine.debugger:command('trace '..OUT..'/instructions.trace,:maincpu,noloop') end end
if not start and spawn then s:write_u16(0x1000,spawn[1]);s:write_u16(0x1002,spawn[2]);s:write_u16(0x1004,spawn[3]) end
if not start and VIEW~=214 then s:write_u8(0x3e1,({[160]=1,[214]=2,[240]=3,[320]=4})[VIEW]) end
elseif d==2 then
n=n+1
if not start then if SEEDWEAPONS then s:write_u16(BESTWEAPON,3) end;start=INPUTORIGIN;print(string.format('READY %.9f',t));if PAL then s:write_u8(@MM:LANGSEL@,s:read_u8(@MM:LANGSEL@)|16) end end
print(string.format('FRAME %d %.9f %.9f %d %d %d %d %d %d %d',n,t-start,t-frameStart,s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004),s:read_u16(0x104a),s:read_u16(0x1048),s:read_u16(HEALTH),s:read_u16(LEVELSTATE)))
print(string.format('DROPPED %d',s:read_u16(INPUTDROP)))
if paintFirst then print(string.format('PAINT %d %.9f %d',n,paintLast-paintFirst,lastVideo-paintVideo+1)) end
if WHOLEFRAME then saveProfile(t,frameStart) end
if start and t-start>ENDTIME and frameStart-start>=ENDTIME then print(string.format('DONE %.9f',t-start));manager.machine:exit() end
elseif d==0 and baseline and not profiled then
baseline=nil;if COUNTS then manager.machine.debugger:command('trace off') end
end end)
emu.register_frame_done(function()
local now=manager.machine.time:as_double()
video=video+1
if not start then
s:write_u16(0x3e8,0x5a5a)
if bootTimes[bootshot] and now>=bootTimes[bootshot] then screen:snapshot(string.format('boot%02d.png',bootshot));bootshot=bootshot+1 end
if now>240 then manager.machine:exit() end return end
local t=now-start
local current={}
for row=TOP+10,BOTTOM-10,8 do for x=LEFT,RIGHT-1,3 do current[#current+1]=s:read_u8(@MM:SHR@+row*160+x) end end
if previous then
local changed=0;for i=1,#current do if current[i]~=previous[i] then changed=changed+1 end end
print(string.format('VIDEO %.9f %.9f',t,changed/#current))
end
previous=current
if MOUSETEST then
local function moveMouse(axis,value) local f=field('Mouse '..axis);f:set_value(value);print(string.format('MOUSE %.9f %s %d',t,axis,value)) end
if t>=1 and not held.mx1 then moveMouse('X',12);held.mx1=true end
if t>=1.4 and not held.mx2 then moveMouse('X',20);held.mx2=true end
if t>=1.6 and not held.my1 then moveMouse('Y',20);held.my1=true end
if t>=3.1 and not held.mx3 then moveMouse('X',28);held.mx3=true end
if t>=4.1 and not held.mx4 then moveMouse('X',36);held.mx4=true end
if t>=5.1 and not held.my3 then moveMouse('Y',0);held.my3=true end
if t>=5.5 and not held.my2 then moveMouse('Y',24);held.my2=true end
end
print(string.format('CONTROL %.9f %d %d %d %d %d',t,s:read_u16(WEAPON),s:read_u16(VIEWBYTES),s:read_u16(MOUSEWALK),s:read_u16(MOUSESPEED),s:read_u16(0x104a)))
SETTINGSAUDIT
local pose={s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004)}
if not lastPose or pose[1]~=lastPose[1] or pose[2]~=lastPose[2] or pose[3]~=lastPose[3] then print(string.format('MOTION %.9f %d %d %d',t,pose[1],pose[2],pose[3]));lastPose=pose end
for i,p in ipairs(plan) do
if t>=p[1] and t<p[2] and not held[i] then
for _,k in ipairs(p[3]) do field(k):set_value(1) end
held[i]=true;print(string.format('KEY %.9f down %s',t,table.concat(p[3],'+')))
elseif t>=p[2] and held[i] then
for _,k in ipairs(p[3]) do field(k):set_value(0) end
held[i]=false;plan[i][1]=999;print(string.format('KEY %.9f up %s',t,table.concat(p[3],'+')))
end end
if snaps[shot] and t>=snaps[shot] then
screen:snapshot(string.format('screen%02d.png',shot))
local f=io.open(OUT..string.format('/screen%02d.bin',shot),'wb')
local bytes={};for i=0,31999 do bytes[#bytes+1]=string.char(s:read_u8(@MM:SHR@+i)) end
f:write(table.concat(bytes));f:close()
print(string.format('SCREEN %d %.9f phase %d',shot,t,s:read_u8(0x3f0)))
shot=shot+1
end
-- Finish the current game frame before stopping. Optional resolution modes
-- can paint longer than the old 0.2-second completion margin.
if t>ENDTIME and frameStart-start>=ENDTIME and s:read_u8(0x3f0)~=1 then print(string.format('DONE %.9f',t));io.stdout:flush();manager.machine:exit() end
end)
''')
settings_trace=''
if args.settings_audit:
    values=','.join(f's:read_u16({symbols[k]})' for k in ('soundVolume','musicVolume','musicActive','musicLoaded','settingsSaveStatus'))
    settings_trace=f"print(string.format('AUDIOSETTING %.9f %d %d %d %d %d',t,{values}))\nprint(string.format('AUDIOCURSOR %.9f %d',t,s:read_u16({memmap.MUSIC_BASE+0x20})))"
script=script.replace('SETTINGSAUDIT',settings_trace)
soundtest=''
if args.reinsert_settings_disk:
    script=script.replace('local pose={s:read_u16(0x1000)', "if t>1 and not held.settingsDisk then manager.machine.images[':fdc:2:35dd']:load("+json.dumps(str(args.disk))+");held.settingsDisk=true end\nlocal pose={s:read_u16(0x1000)",1)
if args.music_song is not None or args.music_unit is not None:
    assert not (args.music_song is not None and args.music_unit is not None)
    music_file=args.music_unit or ROOT/f'build/sound/song-{args.music_song:02}.bin'
    assert music_file.exists()
    soundtest+=memmap.fill("""local songInjected=false
songTap=s:install_read_tap(SONGSTART,SONGSTART,'song-select',function(a,d,m)
if not songInjected and cpu.state.PB.value==SONGBANK then songInjected=true;print('SONGINJECT '..manager.machine.time:as_double());local f=io.open(SONGPATH,'rb');local bytes=f:read('a');f:close();for i=1,#bytes do s:write_u8(@MM:MUSIC_BASE@+i-1,bytes:byte(i)) end end
end)
""").replace('SONGSTART',str(symbols['StartMusic'])).replace('SONGBANK',str(symbols['StartMusic']>>16)).replace('SONGPATH',json.dumps(str(music_file)))
if args.music_volume is not None:
    soundtest+="musicVolumeTap=s:install_read_tap(%d,%d,'music-volume',function(a,d,m) if a==%d then return %d else return 0 end end)\n"%(symbols['musicVolume'],symbols['musicVolume']+1,symbols['musicVolume'],args.music_volume)
if args.sound_audit:
    soundtest+=memmap.fill("""local songHeaderPrinted=false
musicWakeTap=s:install_read_tap(WAKE_ADDRESS,WAKE_ADDRESS,'music-wake',function(a,d,m)
if cpu.state.PB.value==WAKE_BANK then
 if not songHeaderPrinted then
 local magic=s:read_u32(@MM:MUSIC_BASE@);local ticks=s:read_u32(@MM:MUSIC_BASE+0xc@);local base=s:read_u16(@MM:MUSIC_BASE+0x18@)
 if magic==0x324d4457 then ticks=s:read_u32(@MM:MUSIC_BASE+0x10@);base=s:read_u8(@MM:MUSIC_BASE+0xc@)*256 end
 print(string.format('SONGHEADER %d %d %d',magic,ticks,base));songHeaderPrinted=true end
 print(string.format('MUSICWAKE %.9f',manager.machine.time:as_double()))
end end)
""").replace('WAKE_BANK',str(symbols['MusicWake']>>16)).replace('WAKE_ADDRESS',str(symbols['MusicWake']))
    soundtest+=memmap.fill('''local soundBase=nil
local function soundCounters()
local p={};local prof=manager.machine.memory.regions[':zipprof']
for _,range in ipairs({{0x800,0x8ff},{0x2000,0x24ff},{0x9de4,0x9dff}}) do for i=range[1],range[2] do p[i]=prof:read_u64(@MM:ART_BRIGHT+0x100@+i*24+16) end end
return p end
local function soundProfileFinish()
if not soundBase then return end
local final=soundCounters();local f=io.open(OUT..'/sound-profile.txt','w')
for i,base in pairs(soundBase) do if final[i]>base then f:write(string.format('%06x %d\\n',i<0x6000 and i*16 or (i-0x6000)*256,final[i]-base)) end end
f:close();soundBase=nil end
local irqStart=nil
local function soundTraceStart()
if irqEntry then return end
soundBase=soundCounters()
irqEntry=s:install_read_tap(IRQSTART,IRQSTART,'irq-cost-start',function(a,d,m) irqStart=manager.machine.time:as_double() end)
irqExit=s:install_read_tap(IRQEND,IRQEND,'irq-cost-end',function(a,d,m)
if irqStart then print(string.format('IRQCOST %.9f %.9f',manager.machine.time:as_double(),manager.machine.time:as_double()-irqStart));irqStart=nil end end)
end
local soundCtl=0;local soundAdr=0;local soundBusy=0;local soundViolations=0
busyTap=s:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,'sound-busy',function(a,d,m) soundBusy=d end)
soundTap=s:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDADRL@,'sound-audit',function(a,d,m)
if a==@MM:SOUNDCTL@ then soundCtl=d elseif a==@MM:SOUNDADRL@ then soundAdr=d else
if soundBusy&128~=0 or cpu.state.P.value&4==0 then soundViolations=soundViolations+1;print('SOUNDVIOLATION '..soundViolations) end
if soundCtl&64==0 then

if soundAdr>=0xa4 and soundAdr<=0xac and d==0 then print(string.format('MUSICNOTE %.9f %d',manager.machine.time:as_double(),soundAdr-0xa4)) end
end
if soundCtl&32~=0 then soundAdr=(soundAdr+1)&255 end
end end)
soundReadTap=s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'sound-read-audit',function(a,d,m)
if soundBusy&128~=0 or cpu.state.P.value&4==0 then soundViolations=soundViolations+1;print('SOUNDVIOLATION '..soundViolations) end
if soundCtl&32~=0 then soundAdr=(soundAdr+1)&255 end
end)
''')
    if args.settings_audit:
        soundtest=soundtest.replace('if soundCtl&64==0 then', "print(string.format('AUDIODATA %.9f %d %d %d',manager.machine.time:as_double(),soundCtl,soundAdr,d))\nif soundCtl&64==0 then")
    soundtest=soundtest.replace('IRQSTART',str(symbols['inputIrq'])).replace('IRQEND',str(symbols['inputIrqEnd']))
if args.irq_profile:
    soundtest+='''local measuredIRQ=nil
irqMeasure=s:install_write_tap(0x3f4,0x3f4,'irq-time',function(a,d,m)
if d==1 then measuredIRQ=manager.machine.time:as_double()
elseif d==2 and measuredIRQ then print(string.format('IRQMEASURE %.9f %.9f',manager.machine.time:as_double(),manager.machine.time:as_double()-measuredIRQ));measuredIRQ=nil end end)
manager.machine.debugger:command('focus :maincpu')
manager.machine.debugger:command('bpset IRQBEGIN,1,{do b@3f4=1;go}')
manager.machine.debugger:command('bpset IRQRETURN,1,{do b@3f4=2;go}')
'''.replace('IRQBEGIN',format(symbols['inputIrq'],'x')).replace('IRQRETURN',format(symbols['inputIrqEnd'],'x'))
if args.effects_every:
    def fx_long(op,address):return bytes([op])+address.to_bytes(3,'little')
    code=bytearray([0x08,0xc2,0x30,0x48,0xda,0x5a,0x8b,0xa9,0,0])+fx_long(0x8f,(memmap.TEST_MARKERS+0x2))
    for effect in (46,38):code+=bytes([0xa9,effect,0])+fx_long(0x22,symbols['PlaySound'])
    code+=bytes([0xa9,1,0])+fx_long(0x8f,(memmap.TEST_MARKERS+0x2))
    code+=bytes([0xab,0x7a,0xfa,0x68,0x28])+fx_long(0x22,symbols['I_GetTime'])+bytes([0x6b])
    soundtest+=memmap.fill('''local nextEffect=10;local effectArmed=false
local function effectStress(t)
if t<nextEffect or effectArmed then return end
nextEffect=nextEffect+PERIOD;effectArmed=true
local code=FXCODE;for i,v in ipairs(code) do s:write_u8(@MM:MENU+0x1e00@+i-1,v) end
s:write_u8(FXFRAME+1,0);s:write_u8(FXFRAME+2,0x82);s:write_u8(FXFRAME+3,0x3f)
print(string.format('EFFECTPAIR %.9f',t))
end
fxStressMarker=s:install_write_tap(@MM:TEST_MARKERS+0x2@,@MM:TEST_MARKERS+0x2@,'stress-marker',function(a,d,m)
if d==0 then print(string.format('EFFECTSTART %.9f %d',manager.machine.time:as_double(),s:read_u16(FXPENDING)+s:read_u16(FXPENDING+2)))
elseif d==1 then for i=0,2 do s:write_u8(FXFRAME+1+i,(FXCLOCK>>(8*i))&255) end;effectArmed=false end end)
''').replace('PERIOD',str(args.effects_every)).replace('FXCODE','{'+','.join(map(str,code))+'}').replace('FXFRAME',str(symbols['frameLoop'])).replace('FXCLOCK',str(symbols['I_GetTime'])).replace('FXPENDING',str(symbols['fxPending']))
    script=script.replace('local t=now-start','local t=now-start;effectStress(t)')
if args.irq_collision:
    def longop(op,address):return bytes([op])+address.to_bytes(3,'little')
    trampoline=bytearray([0x08,0x78,0xc2,0x30,0x48,0xda,0x5a,0x8b,0xa9,46,0])
    trampoline+=longop(0x22,symbols['PlaySound'])+bytes([0xa9,200,0])
    trampoline+=longop(0x22,symbols['StartDamageFlash'])+bytes([0xa2,2,0])
    outer=len(trampoline);trampoline+=bytes([0xa0,255,255]);inner=len(trampoline)
    trampoline+=bytes([0x88,0xd0,253,0xca,0xd0,(outer-len(trampoline)-6)&255])
    trampoline+=bytes([0xa9,1,0])+longop(0x8f,memmap.TEST_MARKERS)
    trampoline+=bytes([0xab,0x7a,0xfa,0x68,0x28])+longop(0x22,symbols['I_GetTime'])+bytes([0x6b])
    soundtest+=memmap.fill('''local collisionInjected=false;local collisionPhase=false;local collisionAddress=0;local collisionSources=0
local function collisionStart()
if collisionInjected then return end;collisionInjected=true
local code=TRAMPOLINE;for i,v in ipairs(code) do s:write_u8(@MM:MENU+0x1c00@+i-1,v) end
s:write_u8(FRAMELOOP+1,0);s:write_u8(FRAMELOOP+2,0x80);s:write_u8(FRAMELOOP+3,0x3f)
end
collisionMark=s:install_write_tap(@MM:TEST_MARKERS@,@MM:TEST_MARKERS@,'collision-marker',function(a,d,m)
if d==1 then collisionPhase=true;s:write_u8(FRAMELOOP+1,CLOCKLOW);s:write_u8(FRAMELOOP+2,CLOCKMID);s:write_u8(FRAMELOOP+3,CLOCKHIGH) end end)
collisionAdr=s:install_write_tap(@MM:SOUNDADRL@,@MM:SOUNDADRL@,'collision-address',function(a,d,m) collisionAddress=d end)
collisionRead=s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'collision-ack',function(a,d,m)
if collisionPhase and collisionAddress==0xe1 and d&128==0 and collisionSources<3 then
collisionSources=collisionSources+1;print(string.format('COLLISION_SOURCE %d %.9f',(d>>1)&31,manager.machine.time:as_double())) end
collisionAddress=(collisionAddress+1)&255 end)
''').replace('TRAMPOLINE','{'+','.join(map(str,trampoline))+'}').replace('FRAMELOOP',str(symbols['frameLoop'])).replace('CLOCKLOW',str(symbols['I_GetTime']&255)).replace('CLOCKMID',str((symbols['I_GetTime']>>8)&255)).replace('CLOCKHIGH',str(symbols['I_GetTime']>>16))
script=script.replace('manager.machine:exit()','SOUNDFINISH manager.machine:exit()').replace('SOUNDFINISH','soundProfileFinish();' if args.sound_audit else '')
script=script.replace('SOUNDTEST',soundtest).replace('SOUNDCOST',('soundTraceStart();' if args.sound_audit else '')+('collisionStart();' if args.irq_collision else ''))
script=script.replace('INPUTORIGIN',str(args.input_origin) if args.input_origin is not None else 't')
if 'LogicFrame' in symbols:
    lc=logic_capture.layout()
    script=script.replace('local s=cpu.spaces["program"]', 'local s=cpu.spaces["program"]\n'+logic_capture.lua())
    script=script.replace('s:write_u16(0x1000,spawn[1]);s:write_u16(0x1002,spawn[2]);s:write_u16(0x1004,spawn[3])',
                          'logicSpawn(spawn[1],spawn[2],spawn[3])')
    symbols.update(bestWeapon=lc['V_bestweapon'])
script=script.replace('SEEDWEAPONS','true' if args.seed_weapons else 'false')
for label,name in [('BESTWEAPON','bestWeapon'),('WEAPON','weapon'),('VIEWBYTES','viewBytes'),('MOUSEWALK','mouseWalk'),('MOUSESPEED','mouseSensitivity')]:script=script.replace(label,str(symbols[name]))
script=script.replace('PLAN','{'+','.join('{%s,%s,{%s}}'%(a,b,','.join(json.dumps(k) for k in keys)) for a,b,keys in plan)+'}').replace('SNAPS','{'+','.join(map(str,snaps))+'}').replace('HEALTH',str(symbols['health'])).replace('LEVELSTATE',str(symbols['levelState'])).replace('PAL','true' if args.pal else 'false').replace('ENDTIME',str(end)).replace('OUT',json.dumps(str(out)))
script=script.replace('PROFILEAT',str(args.profile_at or 0)).replace('PROFILE','true' if args.profile_at is not None else 'false')
script=script.replace('WHOLEFRAME','true' if args.profile_phase=='frame' else 'false').replace('CASTONLY','true' if args.profile_phase=='cast' else 'false')
script=script.replace('COUNTS','true' if args.instruction_counts else 'false')
script=script.replace('MOUSETEST','true' if args.scenario=='mouse' else 'false')
script=script.replace('INPUTHEAD',str(symbols.get('inputHead',0x3e8))).replace('INPUTRING',str(symbols.get('inputRing',0x300))).replace('INPUTDROP',str(symbols['inputDropped'])).replace('VIEW',str(args.view)).replace('SPAWN','{'+','.join(map(str,spawn))+'}' if spawn else 'false')
for key,value in [('LEFT',left),('RIGHT',right),('TOP',top),('BOTTOM',bottom)]:script=script.replace(key,str(value))
if args.scenario in ('tap','slowtap') and 'BuildFineTurn' in symbols:
    script += r'''
local fineFrame,fineCount=-1,0
fineTap=s:install_read_tap(@NEXT@,@NEXT@,"fine-command",function()
 if not start or manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 then return end
 if fineFrame~=n then fineFrame=n;fineCount=0 end
 local count=s:read_u16(@COUNT@)
 if count<=fineCount then return end
 fineCount=count
 print(string.format('FINECOMMAND %.9f %d %d %d',manager.machine.time:as_double()-start,n,s:read_u16(@UNTIL@),s:read_u16(@COMMANDS@+(count-1)*8)))
end)
'''.replace('@NEXT@',str(symbols['buildNext'])).replace('@COUNT@',str(symbols['ticCount'])).replace('@UNTIL@',str(symbols['inputUntil'])).replace('@COMMANDS@',str(symbols['ticCommands']))
lua_guard.write(out/'play.lua', script)
media,swaps=test_media.prepare(args.disk,out)
if swaps:lua_guard.write(out/'play.lua', script+'\n'+swaps)
binary=mame_kit.BINARY
if args.analyze:
    prior=json.loads((out/'result.json').read_text())
    assert prior['disk_sha256']==disk_sha and prior['elf_sha256']==elf_sha,'analysis needs the captured disk/ELF pair'
    provenance={key:prior[key] for key in ('mame','mame_sha256') if key in prior}
else:
    provenance=dict(mame=binary,mame_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
cmd=['nice','-n','20',binary,args.machine,'-rompath',mame_kit.ROMPATH,'-ramsize',args.ramsize or ram_size(args.machine),*media,'-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run',str(max(250,int(end)+250)),'-autoboot_delay','0','-autoboot_script',str(out/'play.lua'),'-cfg_directory',str(out/'cfg'),'-state_directory',str(out/'state'),'-nvram_directory',str(out/'nvram'),'-snapshot_directory',str(out/'snap')]
if args.instruction_counts or args.irq_profile:
    (out/'debug.txt').write_text('go\n')
    cmd+=['-debug','-debugger','none','-debugscript',str(out/'debug.txt')]
env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
if args.realtime:cmd.remove('-nothrottle')
cmd+=['-video','none']
code=0
if not args.analyze:
    if len([line for line in subprocess.run(['pgrep','-fl','(gsdoom|/iigs.app/Contents/MacOS/iigs)'],capture_output=True,text=True).stdout.splitlines() if str(ROOT/'build/tests') in line])>=1:raise SystemExit('A worker MAME process is already running.')
    with (out/'mame.log').open('w') as log:
        p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:code=p.wait(timeout=max(110 if args.irq_profile else 55,int(end/4)+60))
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(p.pid,signal.SIGTERM)
            try:code=p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);code=p.wait(timeout=5)
log=(out/'mame.log').read_text()
rows=[dict(zip(('n','time','seconds','x','y','angle','command','tics','health','levelState'),[int(v) if i not in (1,2) else float(v) for i,v in enumerate(row)])) for row in re.findall(r'^FRAME (\d+) ([\d.]+) ([\d.]+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)',log,re.M)]
done=re.search(r'^DONE ([\d.]+)',log,re.M)
if code or not rows or (float(done[1])<end if done else rows[-1]['time']<end-.2):raise SystemExit(log[-2500:])
def stats(rows):
    times=sorted(r['seconds'] for r in rows)
    return dict(frames=len(times),fps=len(times)/sum(times),mean_ms=1000*statistics.mean(times),p95_ms=1000*times[int((len(times)-1)*.95)],worst_ms=1000*max(times)) if times else None
phases=[(0,1,[])]+plan
if args.scenario=='guards':phases=[(1,6,['Right Arrow'])]
if args.scenario in ('guards-still','fight'):phases=[(.5,4.5,[] if args.scenario=='guards-still' else ['f  F'])]
death=next((r['time'] for r in rows if r['levelState']),None)
if death is not None:
    phases=[(a,min(b,death),keys) for a,b,keys in phases if a<death]
report=dict(**provenance,music_song=args.music_song,music_volume=args.music_volume,sound_violations=len(re.findall(r'^SOUNDVIOLATION',log,re.M)),music_wakes=len(re.findall(r'^MUSICWAKE',log,re.M)),music_notes=len(re.findall(r'^MUSICNOTE',log,re.M)),disk_sha256=disk_sha,elf_sha256=elf_sha,scenario=args.scenario,view=args.view,spawn=spawn,pal=args.pal,all_loop=stats(rows[1:]),phases=[dict(start=a,end=b,keys=keys,loop=stats([r for r in rows[1:] if a<=r['time']<b and not r['levelState']])) for a,b,keys in phases],events=[dict(time=float(t),edge=edge,keys=keys) for t,edge,keys in re.findall(r'^KEY ([\d.]+) (down|up) (.*)',log,re.M)])
ready=re.search(r'^READY ([\d.]+)',log,re.M)
report['cold_boot_seconds']=float(ready[1]) if ready else None
paints={int(n):dict(ms=1000*float(t),video_frames=int(v)) for n,t,v in re.findall(r'^PAINT (\d+) ([\d.]+) (\d+)',log,re.M)}
paintcpu={int(n):1000*float(t) for n,t in re.findall(r'^PAINTCPU (\d+) ([\d.]+)',log,re.M)}
castcpu={int(n):1000*float(t) for n,t in re.findall(r'^CASTCPU (\d+) ([\d.]+)',log,re.M)}
videos=[(float(t),float(c)) for t,c in re.findall(r'^VIDEO ([\d.]+) ([\d.]+)',log,re.M)]
for phase in report['phases']:
    a,b=phase['start'],phase['end']
    selected=[(i,t,c) for i,(t,c) in enumerate(videos) if a<=t<b]
    fractions=[c for i,t,c in selected]
    p=[paints[r['n']] for r in rows if a<=r['time']<b and r['n'] in paints]
    cpu=[paintcpu[r['n']] for r in rows if a<=r['time']<b and r['n'] in paintcpu and r['n'] in paints]
    episodes=sum(c>0 and (i==0 or videos[i-1][1]==0) for i,t,c in selected)
    casts=[castcpu[r['n']] for r in rows if a<=r['time']<b and r['n'] in castcpu and castcpu[r['n']]>1]
    phase['cast_changed_mean_ms']=statistics.mean(casts) if casts else None
    phase['visible']=dict(episodes=episodes,updates_per_second=episodes/(b-a),paint_mean_ms=statistics.mean(r['ms'] for r in p) if p else 0,paint_worst_ms=max((r['ms'] for r in p),default=0),paint_cpu_mean_ms=statistics.mean(cpu) if cpu else None)
report['input_events']=[dict(time=float(t),tic=int(tic),type=int(typ),value=int(v),aux=int(aux)) for t,tic,typ,v,aux in re.findall(r'^ADB ([\d.]+) (\d+) (\d+) (\d+) (\d+)',log,re.M)]
report['motion']=[dict(time=float(t),x=int(x),y=int(y),angle=int(angle)) for t,x,y,angle in re.findall(r'^MOTION ([\d.]+) (\d+) (\d+) (\d+)',log,re.M)]
report['visible_motion']=[dict(time=float(t),x=int(x),y=int(y),angle=int(angle)) for t,x,y,angle in re.findall(r'^VISIBLE ([\d.]+) (\d+) (\d+) (\d+)',log,re.M)]
report['input_dropped']=max(map(int,re.findall(r'^DROPPED (\d+)',log,re.M)),default=0)
report['death_time']=death
if args.scenario in ('tap','slowtap'):
    taps=[]
    control_total=0
    fine_commands=[dict(time=float(t),frame=int(f),tic=int(tic),bits=int(bits)) for t,f,tic,bits in re.findall(r'^FINECOMMAND ([\d.]+) (\d+) (\d+) (\d+)',log,re.M)]
    def angle_units(degrees):
        turns,angle=divmod(degrees,360)
        return turns*1024+round(angle*1024/360)
    for down in (e for e in report['events'] if e['edge']=='down' and e['keys']=='Right Arrow'):
        up=next(e for e in report['events'] if e['edge']=='up' and e['keys']=='Right Arrow' and e['time']>down['time'])
        before=[m for m in report['motion'] if m['time']<=down['time']][-1]
        after=[m for m in report['motion'] if down['time']<m['time']<up['time']+.5]
        sequence=[before]+after
        delta=sum(((a['angle']-b['angle']+512)%1024)-512 for b,a in zip(sequence,sequence[1:]))
        first=next((m for m in after if m['angle']!=before['angle']),None)
        visible=next((m for m in report['visible_motion'] if m['time']>=down['time'] and m['angle']!=before['angle']),None)
        rawdown=next(e for e in report['input_events'] if e['time']>=down['time'] and e['type']==0 and e['value']==60)
        rawup=next(e for e in report['input_events'] if e['time']>=rawdown['time'] and e['type']==0 and e['value']==188)
        ticks=(rawup['tic']-rawdown['tic'])&65535
        first_video=next((t for t,c in videos if visible and t>=visible['time'] and c>0),None)
        # Original ControlMovement carries controlx modulo ANGLESCALE=20.
        old_degrees=-(control_total//20)
        control_tics=max(1,ticks)  # a same-tic press/release still delivers one tap
        if 'BuildFineTurn' in symbols:
            commands=[r for r in fine_commands if down['time']<=r['time']<up['time']+.5 and r['bits']&8]
            assert len(commands)==control_tics, (commands,control_tics)
            keyboard_units=sum((35,35,70,140,0)[r['bits']>>10] for r in commands)
        else:
            keyboard_units=control_tics*35
        control_total+=keyboard_units
        new_degrees=-(control_total//20)
        expected=angle_units(new_degrees)-angle_units(old_degrees)
        taps.append(dict(held_seconds=up['time']-down['time'],held_doc_tics=ticks,control_tics=control_tics,expected_units=expected,angle_units=delta,angle_degrees=delta*360/1024,pose_latency_ms=1000*(first['time']-down['time']) if first else None,first_changed_store_latency_ms=1000*(visible['time']-down['time']) if visible else None,first_video_change_latency_ms=1000*(first_video-down['time']) if first_video else None))
    report['taps']=taps
    report['fine_turn_commands']=fine_commands
if args.profile_at is not None:
    report['profile_frames']=1
    report['profile_phase']=args.profile_phase
    sample=re.search(r'^PCSAMPLE ([\d.]+) ([\d.]+)',log,re.M)
    report['profile_elapsed_ms']=float(sample[2])*1000 if sample else None
(out/'frames.json').write_text(json.dumps(rows,separators=(',',':'))+'\n')
store_counts=re.findall(r'^AUDITSTORES (\d+)',log,re.M)
report['profile_view_writes']=int(store_counts[0]) if store_counts else None
if args.instruction_counts:
    import collections
    counts=collections.Counter();instructions={}
    trace=out/'instructions.trace'
    for line in trace.read_text().splitlines():
        match=re.match(r'^([0-9A-Fa-f]{2}):?([0-9A-Fa-f]{4}):\s+(.*)',line)
        if match:
            pc=int(match[1]+match[2],16);counts[pc]+=1;instructions[pc]=match[3]
    if not counts:raise SystemExit('debugger trace contains no instruction counts')
    (out/'instruction-counts.json').write_text(json.dumps({f'{pc:06x}':dict(count=n,instruction=instructions[pc]) for pc,n in sorted(counts.items())},indent=2)+'\n')
    report['profile_instructions']=sum(counts.values())
    # Retain the small aggregate, not the per-instruction trace.
    import time
    trace.rename(Path.home()/'.Trash'/('wolf-instructions-%d.trace'%time.time_ns()))
report['mame_binary']=binary
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))

if args.scenario in ('tap','slowtap') and any(t['angle_units']!=t['expected_units'] for t in report['taps']):raise SystemExit('held-time turn mismatch')

if args.music_song is not None or args.music_unit is not None:
    assert 'SONGINJECT ' in log, 'selected song was never injected at execution'
    if args.music_volume:
        header=re.search(r'^SONGHEADER (\d+) (\d+) (\d+)',log,re.M)
        hot=music_file.read_bytes()
        if hot[:4] in (b'WDP2', b'WDP3'):
            from doc_render import unpack
            hot,_,_=unpack(hot)
        assert hot[:4]==b'WDM2', 'selected bank is not a supported song'
        wanted=(int.from_bytes(hot[:4],'little'),int.from_bytes(hot[16:20],'little'),hot[12]*256)
        assert header and tuple(map(int,header.groups()))==wanted, 'actual played song differs from requested source'
