"""Real ADB walk, hit provenance and death lifecycle on a bounded stock boot."""
import memmap
from mame_target import ram_size
import argparse, hashlib, json, os, re, signal, subprocess
from pathlib import Path
from elf import read
import logic_capture
import music_capture
import test_media
import lua_guard
import mame_kit
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--machine',default='apple2gsr1');ap.add_argument('--seconds',type=float,default=12);ap.add_argument('--standing',action='store_true');ap.add_argument('--disk',type=Path);ap.add_argument('--guards',action='store_true');ap.add_argument('--game-over',action='store_true');ap.add_argument('--flash-timing',action='store_true');ap.add_argument('--pickup',action='store_true');ap.add_argument('--flash-rows',action='store_true');ap.add_argument('--view',type=int,choices=(160,214,240,320),default=214);args=ap.parse_args()
r=args.root;disk=args.disk or r/'build/disk1.po';out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
(out/'cfg').mkdir(exist_ok=True)
(out/'cfg'/f'{args.machine}.cfg').write_text(f'<mameconfig version="10"><system name="{args.machine}"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
_,sym=read(r/'build/wolf.elf')
plan=[] if args.standing else [[.5,1.5,['w  W']],[1.7,1.85,['Space']],[2,3.2,['w  W']],[3.5,4.23,['Right Arrow']],[4.5,6,['w  W']],[6.2,6.35,['Space']],[6.5,8,['w  W']],[8.5,9.23,['Right Arrow']],[9.5,11,['w  W']]]
if args.pickup:plan=[[.5,1.5,['w  W']]]
if args.flash_rows:plan=[[1.2,1.25,['p  P']]]
script=memmap.fill(r'''
local s=manager.machine.devices[':maincpu'].spaces['program']
local fade={writes=0,pixels=0}
local start=nil;local last=nil;local held={};local plan=PLAN;local hits={};local frames={};local death={};local flashes={};local bonuses={};local irqs={};local flashstates={};local flashrequests={}
local function field(name)
for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do if f.name==name then return f end end end
error('missing ADB key '..name)
end
local function objects()
local a={};for i=0,s:read_u16(SYM.objectBytes)//32-1 do local o={};for k=0,15 do o[#o+1]=s:read_u16(0x10000+i*32+k*2) end;a[#a+1]=o end;return a
end
local function viewHash()
local top,bottom,left,bytes=s:read_u16(SYM.viewTop),s:read_u16(SYM.viewBottom),s:read_u16(SYM.viewLeft),s:read_u16(SYM.viewBytes)
local h=0
for row=top,bottom-1 do for x=left,left+bytes-1 do h=(h*31+s:read_u8(@MM:SHR@+row*160+x))%4294967291 end end
return h
end
local function palette(p)
local a={};for i=0,15 do a[#a+1]=s:read_u16(@MM:SHR_PAL@+p*32+i*2) end;return table.concat(a,',')
end
local function statusPalettes()
local a={};for p=1,12 do a[#a+1]=palette(p) end;return table.concat(a,';')
end
local function fadeSample(t)
local phase=DEATHPHASE
if phase==2 and not fade.start_time then fade.start_time=t;fade.start_clock=s:read_u16(SYM.deathClock);fade.start_hash=viewHash();fade.hud_start=statusPalettes() end
if phase>=3 and fade.start_time and not fade.end_time then
fade.end_time=t;fade.end_clock=s:read_u16(SYM.deathClock);fade.end_hash=viewHash();fade.hud_end=statusPalettes()
local bad=0
for p=0,15 do if p<1 or p>12 then for i=0,15 do if s:read_u16(@MM:SHR_PAL@+p*32+i*2)~=0xa00 then bad=bad+1 end end end end
fade.not_red=bad
end
end
local function array(base,n,word) local a={};for i=0,n-1 do a[#a+1]=word and s:read_u16(base+i*2) or s:read_u8(base+i) end;return a end
local function dumpJSON(v)
if type(v)=='table' then local a={};local isarray=#v>0;for k,x in pairs(v) do a[#a+1]=(isarray and '' or string.format('%q:',k))..dumpJSON(x) end;return (isarray and '[' or '{')..table.concat(a,',')..(isarray and ']' or '}') elseif type(v)=='boolean' then return v and 'true' or 'false' elseif type(v)=='string' then return string.format('%q',v) else return tostring(v) end
end
local function snapshot()
return {time=manager.machine.time:as_double()-start,health=s:read_u16(SYM.health),lives=s:read_u16(SYM.lives),state=s:read_u16(SYM.levelState),deathphase=DEATHPHASE,target=DEATHTARGET,x=s:read_u16(0x1000),y=s:read_u16(0x1002),angle=s:read_u16(0x1004),pwall=s:read_u16(SYM.pwallState),frame=s:read_u16(SYM.frameCount)}
end
hitTap=s:install_write_tap(SYM.health,SYM.health,'hits',function(a,d,m)
if not start then return end
local old=s:read_u16(SYM.health);local new=(old&0xff00)|(d&255)
if new>=old then return end
local h=snapshot();local actor=s:read_u16(0x10b0);h.actor=actor//32;h.object=array(0x10000+actor,16,true);h.damage=s:read_u16(0x10c0);h.newhealth=new;h.random=s:read_u16(SYM.randomIndex);h.projected=s:read_u8(0x1b800+actor//32)==s:read_u16(SYM.projectionStamp)
h.projections={};for i=0,s:read_u16(0x107c)-1 do h.projections[#h.projections+1]=array(0x14800+i*16,8,true) end
h.map=array(0xd0000,4096,false);h.doors=array(SYM.doorPosition,s:read_u16(SYM.doorBytes)//2,true);hits[#hits+1]=h
print(string.format('HIT %.3f actor %d at %d,%d damage %d health %d->%d projected %s',h.time,h.actor,h.object[1],h.object[2],h.damage,old,new,tostring(h.projected)))
end)
frameTap=s:install_write_tap(0x3f0,0x3f0,'room-walk',function(a,d,m)
if d==1 and not start then s:write_u8(0x3e1,VIEWLATCH) end
if d==1 and not start and PICKUP then s:write_u16(0x1000,8064);s:write_u16(0x1002,13184);s:write_u16(0x1004,512);s:write_u16(SYM.health,50) end
if d==1 and not start and GUARDS then s:write_u16(0x1000,9600);s:write_u16(0x1002,2944);s:write_u16(0x1004,0) end
if d==2 then if not start then start=manager.machine.time:as_double();if GAMEOVER then s:write_u16(SYM.lives,0) end;print('READY '..start) end;local f=snapshot();fadeSample(f.time);f.ids={};for i=0,s:read_u16(0x107c)-1 do f.ids[#f.ids+1]=s:read_u16(0x14808+i*16)//32 end;for _,h in ipairs(hits) do if h.frame==f.frame-1 then h.drawn=false;for _,id in ipairs(f.ids) do if h.actor==id then h.drawn=true end end end end;frames[#frames+1]=f end
end)
settledTap=s:install_read_tap(SYM.deathSettled,SYM.deathSettled,'death-settled',function(a,d,m)
if fade.over then return end
local top,bottom,left,bytes=s:read_u16(SYM.viewTop),s:read_u16(SYM.viewBottom),s:read_u16(SYM.viewLeft),s:read_u16(SYM.viewBytes);local other=0
for row=top,bottom-1 do for x=left,left+bytes-1 do if s:read_u8(@MM:SHR@+row*160+x)~=0x22 then other=other+1 end end end
fade.over={other_pixels=other,red=s:read_u16(@MM:SHR_PAL@+4),white=s:read_u16(@MM:SHR_PAL@+2),}
end)
fadeTap=s:install_write_tap(@MM:SHR_PAL@,@MM:SHR_PAL+0x1ff@,'death-fade',function(a,d,m)
local pc=manager.machine.devices[':maincpu'].state.PC.value
if pc>=SYM.DeathFadeStart and pc<SYM.deathCodeEnd then fade.writes=fade.writes+1 end
end)
fadePixelTap=s:install_write_tap(@MM:SHR@,@MM:SHR+0x7cff@,'death-pixels',function(a,d,m)
if DEATHPHASE~=2 then return end
local offset=a-@MM:SHR@;local row=offset//160;local x=offset%160;local left=s:read_u16(SYM.viewLeft)
if fade.start_time and row>=s:read_u16(SYM.viewTop) and row<s:read_u16(SYM.viewBottom) and x>=left and x<left+s:read_u16(SYM.viewBytes) then fade.pixels=fade.pixels+1;if not fade.first_pixel then fade.first_pixel={time=manager.machine.time:as_double()-start,address=a,pc=manager.machine.devices[':maincpu'].state.PC.value} end end
end)
FLASHCHECK
DEBUGSETUP
emu.register_frame_done(function()
if not start then s:write_u16(0x3e8,0x5a5a) return end
local t=manager.machine.time:as_double()-start
FLASHSAMPLE
for i,p in ipairs(plan) do if t>=p[1] and t<p[2] and not held[i] then for _,k in ipairs(p[3]) do field(k):set_value(1) end;held[i]=true
elseif t>=p[2] and held[i] then for _,k in ipairs(p[3]) do field(k):set_value(0) end;held[i]=false;p[1]=999 end end
local state=s:read_u16(SYM.levelState)
if state~=last then local f=snapshot();death[#death+1]=f;last=state;print('STATE '..dumpJSON(f))
end
if t>=ENDTIME then
DEBUGDUMP
local f=io.open(OUT..'/walk.json','w');f:write(dumpJSON({hits=hits,fade=fade,frames=frames,death=death,final=snapshot(),objects=objects(),flashes=flashes,bonuses=bonuses,irqs=irqs,flashstates=flashstates,flashrequests=flashrequests}));f:close();print('DONE '..t);manager.machine:exit()
end
end)
''')
required=('DeathFadeStart','deathCodeEnd','deathSettled','deathClock','viewTop','viewBottom','viewLeft','viewBytes','objectBytes','health','lives','levelState','pwallState','frameCount','randomIndex','projectionStamp','doorPosition','doorBytes')
if 'LogicFrame' in sym:
 lc=logic_capture.layout()
 sym.update(health=lc['V_health'],lives=lc['V_lives'],pwallState=lc['V_pwallstate'],randomIndex=lc['V_rndindex'])
 required=tuple(k for k in required if k!='objectBytes')
 script=script.replace('local start=nil',logic_capture.lua()+'\nlocal start=nil',1)
 script=script.replace('local a={};for i=0,s:read_u16(SYM.objectBytes)//32-1 do local o={};for k=0,15 do o[#o+1]=s:read_u16(0x10000+i*32+k*2) end;a[#a+1]=o end;return a','return logicObjects()')
 script=script.replace('local actor=s:read_u16(0x10b0);h.actor=actor//32;h.object=array(0x10000+actor,16,true);h.damage=s:read_u16(0x10c0)',
                       'local actor=s:read_u16(LC.V_lastattacker);h.actor=400+(actor-(LC.OBJLIST&65535))//64;h.object=logicObjects()[h.actor+1];h.damage=s:read_u16(0x1152)')
 script=script.replace('0x1b800+actor//32','0x1b800+h.actor')
 script=script.replace('s:write_u16(0x1000,8064);s:write_u16(0x1002,13184);s:write_u16(0x1004,512)', 'logicSpawn(8064,13184,512)')
 script=script.replace('s:write_u16(0x1000,9600);s:write_u16(0x1002,2944);s:write_u16(0x1004,0)', 'logicSpawn(9600,2944,0)')
 script=script.replace("h.map=array(0xd0000,4096,false);", "h.map=array(0xd0000,4096,false);h.logicmap=array(LC.TILEMAP,4096,false);h.logicdoors=array(LC.DOORPOS,s:read_u16(LC.V_doornum),true);h.exact=true;")
 script=script.replace('x=s:read_u16(0x1000),y=s:read_u16(0x1002),angle=s:read_u16(0x1004)',
                       'x=s:read_u16(LC.OBJLIST+LC.O_X+1),y=s:read_u16(LC.OBJLIST+LC.O_Y+1),angle=s:read_u16(0x1004)')
flashcheck=memmap.fill(r'''
local irq=nil;local docaddr=0
docAddrTap=s:install_write_tap(@MM:SOUNDADRL@,@MM:SOUNDADRL@,'doc-address',function(a,d,m) docaddr=d&255 end)
irqStartTap=s:install_write_tap(0x3f4,0x3f4,'irq-marker',function(a,d,m)
if d==1 and start then irq={time=manager.machine.time:as_double()-start,damage=s:read_u16(SYM.damageCount),bonus=s:read_u16(SYM.bonusCount),reads=0,bytes=0,alarm_reads=0} end
if d==2 and irq then
irq.ms=(manager.machine.time:as_double()-start-irq.time)*1000
if irq.first then
irq.copy_ms=(irq.last-irq.first)*1000;irq.tint=s:read_u16(SYM.flashTint);irq.level=s:read_u16(SYM.levelIndex);irq.tic=s:read_u16(SYM.flashTime);irq.palette={};irq.palette_mismatches=0;irq.row_palette_mismatches=0
local base=@MM:TINTS@+s:read_u16(SYM.levelIndex)*320+irq.tint*32
for i=0,31 do local c=s:read_u8(@MM:SHR_PAL@+i);irq.palette[#irq.palette+1]=c;if c~=s:read_u8(base+i) then irq.palette_mismatches=irq.palette_mismatches+1 end end
local status=@MM:TINTS@+3200+irq.tint*384
for i=0,383 do local c=s:read_u8(@MM:SHR_PAL+0x20@+i);irq.palette[#irq.palette+1]=c;if c~=s:read_u8(status+i) then irq.palette_mismatches=irq.palette_mismatches+1 end end
flashes[#flashes+1]=irq
end
irqs[#irqs+1]=irq;irq=nil
end
end)
docReadTap=s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'irq-doc',function(a,d,m) if irq then irq.reads=irq.reads+1;if docaddr==0xe0 then irq.alarm_reads=irq.alarm_reads+1 end end end)
paletteTap=s:install_write_tap(@MM:SHR_PAL@,@MM:SHR_PAL+0x19f@,'flash-palette',function(a,d,m)
if irq then local t=manager.machine.time:as_double()-start;irq.first=irq.first or t;irq.last=t;irq.bytes=irq.bytes+1 end
end)
damageTap=s:install_write_tap(SYM.damageCount,SYM.damageCount,'damage-request',function(a,d,m)
if start and (d&255)>s:read_u16(SYM.damageCount) then flashrequests[#flashrequests+1]={kind='red',time=manager.machine.time:as_double()-start,count=d&255,tic=s:read_u16(SYM.flashTime)} end
end)
bonusTap=s:install_write_tap(SYM.bonusCount,SYM.bonusCount,'bonus-request',function(a,d,m)
if start and (d&255)==18 then local b={kind='white',time=manager.machine.time:as_double()-start,count=18,tic=s:read_u16(SYM.flashTime)};bonuses[#bonuses+1]=b;flashrequests[#flashrequests+1]=b end
end)
''')
if 'flashTint' in sym:
 required+=('inputIrq','inputIrqEnd','damageCount','bonusCount','flashTint','flashTime','levelIndex')
 script=script.replace('FLASHCHECK',flashcheck)
 script=script.replace('FLASHSAMPLE',memmap.fill(r'''local dc=s:read_u16(SYM.damageCount);local bc=s:read_u16(SYM.bonusCount);local tint=s:read_u16(SYM.flashTint);local color=s:read_u16(@MM:SHR_PAL@);local prev=flashstates[#flashstates]
if not prev or dc~=prev.damage or bc~=prev.bonus or tint~=prev.tint or color~=prev.color then flashstates[#flashstates+1]={time=t,damage=dc,bonus=bc,tint=tint,color=color} end'''))
else:script=script.replace('FLASHCHECK','').replace('FLASHSAMPLE','')
script=script.replace('VIEWLATCH',str({160:1,214:2,240:3,320:4}[args.view]))
script=script.replace('DEATHPHASE', 's:read_u16('+str(sym['deathPhase'])+')' if 'deathPhase' in sym else '0').replace('DEATHTARGET','s:read_u16('+str(sym['deathTarget'])+')' if 'deathTarget' in sym else '0').replace('PICKUP','true' if args.pickup else 'false').replace('GUARDS','true' if args.guards else 'false').replace('GAMEOVER','true' if args.game_over else 'false')
script=script.replace('DEBUGDUMP',"local c=manager.machine.debugger.consolelog;local f=io.open(OUT..'/debug-console.txt','w');for i=1,#c do f:write((c[i] or '')..string.char(10)) end;f:close()" if args.flash_timing else '')
script=script.replace('DEBUGSETUP',r'''manager.machine.debugger:command('focus :maincpu')
manager.machine.debugger:command('bpset '..string.format('%x',SYM.inputIrq)..',1,{do b@3f4=1;go}')
manager.machine.debugger:command('bpset '..string.format('%x',SYM.inputIrqEnd)..',1,{do b@3f4=2;go}')''' if args.flash_timing else '')
script=script.replace('SYM','{'+','.join(k+'='+str(sym[k]) for k in required)+'}').replace('PLAN', '{'+','.join('{%s,%s,{%s}}'%(a,b,','.join(json.dumps(k) for k in keys)) for a,b,keys in plan)+'}').replace('ENDTIME',str(args.seconds)).replace('OUT',json.dumps(str(out)))
for k in sorted(required,key=len,reverse=True):script=script.replace('{'+','.join(n+'='+str(sym[n]) for n in required)+'}.'+k,str(sym[k]))
if args.game_over:
 script+='\nlocal cpu=manager.machine.devices[\":maincpu\"];local mem=s\n'+music_capture.lua()
 script+='''
local rosterAt=nil;local scoreAccepted=false
emu.register_frame_done(function()
 local t=manager.machine.time:as_double()
 if s:read_u16(%d)==23 and not rosterAt then rosterAt=t end
 if rosterAt and not scoreAccepted and t-rosterAt>=2 then
  field("Return"):set_value(1);scoreAccepted=true
 elseif scoreAccepted and t-rosterAt>=2.2 then field("Return"):set_value(0) end
end)
''' % sym['currentSong']
lua_guard.write(out/'walk.lua', script)
media,swaps=test_media.prepare(disk,out)
if swaps:lua_guard.write(out/'walk.lua', script+'\n'+swaps)
binary=mame_kit.BINARY
cmd=['nice','-n','20',binary,args.machine,'-rompath',mame_kit.ROMPATH,'-ramsize',ram_size(args.machine),*media,'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run','250','-autoboot_delay','0','-autoboot_script',str(out/'walk.lua'),'-cfg_directory',str(out/'cfg'),'-nvram_directory',str(out/'nvram'),'-state_directory',str(out/'state')]
cmd+=['-snapshot_directory',str(out/'snap')]
if args.flash_timing:
 (out/'debug.txt').write_text('focus :maincpu\nbpset %x,1,{do b@3f4=1;go}\nbpset %x,1,{do b@3f4=2;go}\ngo\n'%(sym['inputIrq'],sym['inputIrqEnd']))
 cmd+=['-debug','-debugger','none','-debugscript',str(out/'debug.txt')]
if len([x for x in subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout.splitlines() if str(ROOT/'build/tests') in x])>=1:raise SystemExit('A worker MAME process is already running')
with (out/'mame.log').open('w') as log:
 p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1'),start_new_session=True)
 try:code=p.wait(timeout=180)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGTERM)
  try:code=p.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);code=p.wait(timeout=5)
log=(out/'mame.log').read_text()
if code or 'DONE ' not in log:raise SystemExit(log[-1500:])
data=json.loads((out/'walk.json').read_text());data['disk_sha256']=hashlib.sha256(disk.read_bytes()).hexdigest();data['elf_sha256']=hashlib.sha256((r/'build/wolf.elf').read_bytes()).hexdigest();data['plan']=plan;data['view']=args.view
if args.game_over:
 data['song_starts']=music_capture.events(log)
 assert [x['song'] for x in data['song_starts']][:3]==[3,23,7],data['song_starts']
 data['glu_violations']=0
(out/'walk.json').write_text(json.dumps(data,separators=(',',':'))+'\n')
print('\n'.join(x for x in log.splitlines() if x.startswith(('HIT','STATE','DONE'))))
