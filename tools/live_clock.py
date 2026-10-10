"""Bounded stock live-play clock and guard-death check through real input keys.

The initial fixture puts the player in E1M1's guard room with a machine gun,
99 rounds and 100 health, easy difficulty, RNG index 0 and the front guard
at one hit point. It measures a 20-second combat and walking route driven by
real keyboard fields. If that route misses wall-stop coverage, an unmeasured
suffix places the player beside a clear static wall and holds forward for
at most two seconds. The measured prefix and its world state are unchanged.
The player's health is set back to 100 whenever it falls under 30, so that a guard's hit
never ends the route: the check is about time, and a death changes the clock by design.
"""
import argparse
import collections
import shutil
import time
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
import logic_capture
import logic_observer
from wolf_source import states

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument('--view', type=int, choices=(160, 214, 240, 320), required=True)
ap.add_argument('--name', required=True)
ap.add_argument('--measure', action='store_true', help='retain results even when a small MAXTICS falls behind')
ap.add_argument('--profile-at', type=float, nargs='+', default=[], help='trace one complete live frame after each route time')
ap.add_argument('--analyze', action='store_true', help='analyze the retained log without running MAME')
ap.add_argument('--disk', type=Path, help='private media to boot instead of the current build')
ap.add_argument('--normal-boot', action='store_true', help='load saved settings through the real menu')
ap.add_argument('--mame', type=Path)
ap.add_argument('--j13', action='store_true', help='normal boot and real J13 keys for the combat route')
args = ap.parse_args()
if args.j13:
    args.normal_boot = True
out = ROOT / 'build/tests' / args.name
out.mkdir(parents=True, exist_ok=True)
_, sym = read(ROOT / 'build/wolf.elf')
logic = json.loads((ROOT / 'build/assets/logic.json').read_text())
state_ids = logic['states']
death_tics = sum(row[2] for name, row in states() if name in ('s_grddie1', 's_grddie2', 's_grddie3'))
script = 'local s=mem\n' + logic_capture.lua() + r'''
local prof=manager.machine.memory.regions[":zipprof"]
local traceTimes={PROFILETIMES}
local traceIndex=1
local traceBase=nil
local traceTime=0
local traceRanges={{0x0800,0x08ff},{0x2000,0x5fff},{0x6d80,0x6dff},{0x9de6,0x9eff}}
local function snapshotProfile()
 local v={};for _,r in ipairs(traceRanges) do for k=r[1],r[2] do v[k]=prof:read_u64(0x200100+k*24+16) end end;return v
end
local function beginProfile(t)
 if traceTimes[traceIndex] and t>=traceTimes[traceIndex] and not traceBase then
  traceBase=snapshotProfile();traceTime=t
  manager.machine.debugger:command('trace PROFILEOUT/instructions-'..traceIndex..'.trace,:maincpu,noloop')
 end
end
local function endProfile(t)
 if not traceBase then return end
 manager.machine.debugger:command('trace off,:maincpu')
 local v=snapshotProfile();local f=io.open('PROFILEOUT/profile-'..traceIndex..'.txt','w')
 for _,r in ipairs(traceRanges) do for k=r[1],r[2] do
  local dt=v[k]-traceBase[k]
  if dt>0 then f:write(string.format('%06x %d\n',k<0x6000 and k*16 or (k-0x6000)*256,dt)) end
 end end
 f:close();print(string.format('LIVEPROFILE %d %.9f %.9f',traceIndex,traceTime,t-traceTime))
 traceBase=nil;traceIndex=traceIndex+1
end
local begun=false
local configured=nil
local start=0
local ticks=0
local worldTicks=0
local idleDoorTicks=0
local queueSeconds=0
local worldSeconds=0
local playerSeconds=0
local queueStart=nil
local worldStart=nil
local playerStart=nil
local simulationSeconds=0
local docAt=0
local frameTicks=0
local frameTime=0
local frames={}
local deaths={}
local dying={}
local actorTics={}
local shownDeaths={}
local deathStates=DEATHSTATES
local held={}
local prior=nil
local tunnel=0
local blockedWall=0
local blockedDoor=0
local largestPass=0
local markerErrors=0
local mirrorChecks=0
local mirrorErrors=0
local coverageStart=nil
local routeIdleTics=nil
@PUBLISH_TAPS@
local plan={{0.05,4,"f  F"},{4.5,5.5,"w  W"},{6,6.5,"Right Arrow"},
 {7,8,"w  W"},{8.5,10,"Right Arrow"},{10.5,12,"w  W"},{12.5,18.5,"s  S"}}
local function finishCheck(t)
 print(string.format("COLLISIONS %d %d %d %d",tunnel,blockedWall,blockedDoor,largestPass))
 print("ACTOR_MARKERS "..markerErrors)
 print(string.format("WORLD_MIRRORS %d %d",mirrorChecks,mirrorErrors))
 print("IDLE_DOOR_TICS "..(routeIdleTics or idleDoorTicks))
 if coverageStart then print(string.format("WALL_COVERAGE_DONE %.9f",t-coverageStart)) end
 print("CLOCK_DONE");manager.machine:exit()
end
local function addWallCoverage(t)
 for x=1,62 do for y=1,62 do
  local cell=x*64+y
  local wall=s:read_u8(LC.TILEMAP+cell+64)
  local area=s:read_u8(LC.MAP0+y*64+x)
  local clear=true
  for dx=-1,1 do for dy=-1,1 do
   if s:read_u16(LC.ACTORAT+((x+dx)*64+y+dy)*2)>=0x3000 then clear=false end
  end end
  if clear and s:read_u8(LC.TILEMAP+cell)==0 and s:read_u16(LC.ACTORAT+cell*2)==0 and wall>0 and wall<64 and area>=107 and area<144 then
   routeIdleTics=idleDoorTicks;coverageStart=t
   logicSpawn(x*256+128,y*256+128,0);prior=nil;mirrorReady=false
   print(string.format("WALL_COVERAGE_START %d %d",x,y));return
  end
 end end
 error("no clear static-wall fixture")
end
local function key(n)
 for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do
  if f.name==n then return f end
 end end
 error("missing key "..n)
end
docSample=s:install_write_tap(0x104c,0x104c,"doc-sample",function(a,d,m)
 docAt=manager.machine.time:as_double()
end)
local function onQueuePhase(d)
 local t=manager.machine.time:as_double()
 if d==1 then queueStart=t elseif queueStart then queueSeconds=queueSeconds+t-queueStart;queueStart=nil end
end
@QUEUE_TAPS@
local function onWorldPhase(d)
 if not begun then return end
 if d==2 then
  local cpu=manager.machine.devices[":maincpu"]
  assert(s:read_u16(LC.BASE+0x3ca82)==65535 and s:read_u16(LC.V_pwallstate)==0,"skipped active door system")
  local count=s:read_u16(cpu.state.D.value+0xe6)
  assert(count>0 and count<=64,"invalid idle door tic count")
  idleDoorTicks=idleDoorTicks+count;worldTicks=worldTicks+count
 elseif d==1 then worldTicks=worldTicks+s:read_u16(LC.V_tics) end
end
@WORLD_TAPS@
actorPhase=s:install_read_tap(ACTORWORK,ACTORWORK,"actor-tic",function(a,d,m)
 local cpu=manager.machine.devices[":maincpu"]
 if not begun or coverageStart or manager.machine:side_effects_disabled() or cpu.state.PB.value~=0x0d then return end
 local base=LC.BASE+cpu.state.X.value
 if base==LC.OBJLIST then return end
 local id=(base-LC.OBJLIST)//64
 local at=actorTics[id] or 0
 local t=manager.machine.time:as_double()-start
 local state=s:read_u16(base+LC.O_STATE)
 if state==DIE1 and not dying[id] then dying[id]={tic=at,time=t,spent=15-s:read_u16(base+LC.O_TICS)}
 elseif state==DEAD and dying[id] then
  print(string.format("DEATH %d %d %.9f",id,at-dying[id].tic+dying[id].spent,t-dying[id].time))
  dying[id]=nil
 end
 actorTics[id]=at+s:read_u16(LC.V_tics)
end)
local function onLivePhase(d)
 local now=manager.machine.time:as_double()
 if d==7 then worldStart=now
 elseif d==8 and worldStart then worldSeconds=worldSeconds+now-worldStart;worldStart=nil
 elseif d==1 then playerStart=now
 elseif d==6 and playerStart then playerSeconds=playerSeconds+now-playerStart;playerStart=nil
 elseif d==3 then simulationSeconds=now-frameTime end
 if not begun or d~=1 then return end
 local t=now-start
 local x=s:read_u32(LC.OBJLIST+LC.O_X)
 local y=s:read_u32(LC.OBJLIST+LC.O_Y)
 local function blocking(tx,ty)
  local cell=tx*64+ty
  local tile=s:read_u8(LC.TILEMAP+cell)
  if tile~=0 and tile<128 then return "wall" end
  if tile>=128 and tile<192 and s:read_u16(LC.ACTORAT+cell*2)~=0 then return "door" end
 end
 if prior then
  local dx=x-prior.x;local dy=y-prior.y
  if math.abs(dx)>0xafff or math.abs(dy)>0xafff or blocking(x>>16,y>>16) then tunnel=tunnel+1 end
  if dx==0 and dy==0 and (s:read_u16(0x104a)&3)~=0 then
   local angle=s:read_u16(LC.OBJLIST+LC.O_ANGLE)*math.pi/180
   local sign=(s:read_u16(0x104a)&1)~=0 and 1 or -1
   local ax=math.floor(math.cos(angle)*sign+0.5)
   local ay=math.floor(-math.sin(angle)*sign+0.5)
   local what=blocking((x>>16)+ax,(y>>16)+ay)
   if what=="wall" then blockedWall=blockedWall+1 elseif what=="door" then blockedDoor=blockedDoor+1 end
  end
 end
 prior={x=x,y=y}
 largestPass=math.max(largestPass,s:read_u16(LC.V_tics))
 ticks=ticks+s:read_u16(LC.V_tics)
end
@LOGIC_TAPS@
clockFrame=s:install_write_tap(0x3f0,0x3f0,"live-frame",function(a,d,m)
 local t=manager.machine.time:as_double()
 if d==1 then
  if not configured then s:write_u8(0x3e1,VIEWLATCH);configured=t end
  if begun then beginProfile(t-start) end
  frameTicks=ticks;frameTime=t;queueSeconds=0;worldSeconds=0;playerSeconds=0;simulationSeconds=0
 elseif d==2 then
  if begun then endProfile(t-start) end
  if not begun then
   if not configured or t-configured<5 then return end
   logicSpawn(9600,2944,0)
   s:write_u16(LC.V_health,100)
   s:write_u16(LC.V_difficulty,0)
   s:write_u16(LC.V_rndindex,0)
   local ob=s:read_u16(LC.OBJLIST+LC.O_NEXT)
   while ob~=0 do
    local base=LC.BASE+ob
    if s:read_u16(base+LC.O_TILEX)==39 and s:read_u16(base+LC.O_TILEY)==11 then s:write_u16(base+LC.O_HP,1) end
    ob=s:read_u16(base+LC.O_NEXT)
   end
   s:write_u16(LC.V_ammo,99)
   for _,a in ipairs({LC.V_weapon,LC.V_bestweapon,LC.V_chosenweapon}) do s:write_u16(a,2) end
   begun=true;start=t;ticks=0;worldTicks=0;idleDoorTicks=0;print("CLOCK_START "..t)
   return
  end
  if coverageStart then
   if blockedWall>0 or t-coverageStart>=2 then finishCheck(t) end
   return
  end
  if s:read_u16(LC.V_health)<30 then s:write_u16(LC.V_health,100) end -- a hit from a guard must not end the route; the route checks time and stops
  local doc=s:read_u16(0x104c)
  local frontier=s:read_u16(0x1046)
  local debt=(doc-frontier)&65535
  if debt>32767 then debt=debt-65536 end
  local ob=s:read_u16(LC.OBJLIST+LC.O_NEXT)
  while ob~=0 do
   local base=LC.BASE+ob
   local state=s:read_u16(base+LC.O_STATE)
   if deathStates[state] and shownDeaths[ob]~=state then
    print(string.format('DEATH_PRESENT %d %d %.9f',ob,state,t-start));shownDeaths[ob]=state
   end
   local cell=s:read_u16(base+LC.O_X+2)*64+s:read_u16(base+LC.O_Y+2)
   if s:read_u16(base+LC.O_MARKED)~=cell then markerErrors=markerErrors+1 end
   ob=s:read_u16(base+LC.O_NEXT)
  end
  print(string.format("CLOCK %.9f %d %d %d %d %.9f %d %d %d %d %d %.9f %.9f %.9f %.9f %.9f %d",t-start,ticks,doc,frontier,debt,t-frameTime,
    s:read_u16(LC.OBJLIST+LC.O_X+1),s:read_u16(LC.OBJLIST+LC.O_Y+1),s:read_u16(LC.V_health),s:read_u16(INPUTDROP),worldTicks,docAt-start,simulationSeconds,queueSeconds,worldSeconds,playerSeconds,s:read_u16(WORLDFRONTIER)))
  if t-start>=20 then
   if blockedWall==0 then addWallCoverage(t) else finishCheck(t) end
  end
 end
end)
emu.register_frame_done(function()
 if not begun then return end
 local t=manager.machine.time:as_double()-start
 local want={}
 if coverageStart then want["w  W"]=true
 else for _,p in ipairs(plan) do if t>=p[1] and t<p[2] then want[p[3]]=true end end end
 for n,_ in pairs(want) do if not held[n] then key(n):set_value(1) end end
 for n,_ in pairs(held) do if not want[n] then key(n):set_value(0) end end
 held=want
end)
'''
script = (script.replace('PROFILETIMES', ','.join(map(str,args.profile_at)))
          .replace('DEATHSTATES', '{'+','.join('[%d]=true'%state_ids['s_grddie'+str(n)] for n in range(1,5))+'}')
          .replace('PROFILEOUT', str(out))
          .replace('DIE1', str(state_ids['s_grddie1']))
          .replace('DEAD', str(state_ids['s_grddie4']))
          .replace('VIEWLATCH', str({160: 1, 214: 2, 240: 3, 320: 4}[args.view]))
          .replace('INPUTDROP', str(sym['inputDropped']))
          .replace('WORLDFRONTIER', str(sym['worldAt']))
          .replace('ACTORWORK', str(sym.get('actorOneTic',sym.get('marksKept',sym['actorRuns'])))))
for kind,handle,function in [('queue','queuePhase','onQueuePhase'),('world','worldPhase','onWorldPhase'),('logic','livePhase','onLivePhase')]:
    script=script.replace('@'+kind.upper()+'_TAPS@',logic_observer.taps(sym,kind,function,handle=handle))
script += logic_observer.short_move_tap(sym)
script += logic_observer.actor_pointer_taps(sym)
publish_taps=''
if 'LogicWorldPublish' in sym:
    lc=logic_capture.layout()
    pairs=[(0x1000,lc['OBJLIST']+lc['O_X']+1),(0x1002,lc['OBJLIST']+lc['O_Y']+1)]
    pairs += [(sym[mirror],lc['V_'+field]) for mirror,field in
              [('ammo','ammo'),('keys','keys'),('lives','lives'),('score','score'),
               ('weapon','weapon'),('chosenWeapon','chosenweapon'),('bestWeapon','bestweapon'),
               ('weaponFrame','weaponframe'),('killCount','killcount'),('faceFrame','faceframe')]]
    pairs.append((sym['score']+2,lc['V_score_hi']))
    publish_taps=r'''
local mirrorReady=false
local mirrorPairs={PAIRS}
fullPublishObserver=s:install_read_tap(FULLPUB,FULLPUB,"full-publish",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==2 and begun then mirrorReady=true end
end)
worldPublishObserver=s:install_read_tap(WORLDPUB,WORLDPUB,"world-publish",function(a,d,m)
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 or not mirrorReady then return end
 mirrorChecks=mirrorChecks+1
 for _,pair in ipairs(mirrorPairs) do
  if s:read_u16(pair[1])~=s:read_u16(pair[2]) then
   mirrorErrors=mirrorErrors+1
   if mirrorErrors<8 then print("MIRROR_DRIFT "..pair[1]) end
  end
 end
 if s:read_u16(0x1004)~=s:read_u16(LC.DEG1024+s:read_u16(LC.OBJLIST+LC.O_ANGLE)*2) then mirrorErrors=mirrorErrors+1 end
end)
'''.replace('PAIRS',','.join('{%d,%d}'%pair for pair in pairs)).replace('FULLPUB',str(sym['LogicPublish'])).replace('WORLDPUB',str(sym['LogicWorldPublish']))
script=script.replace('@PUBLISH_TAPS@',publish_taps)
if args.j13:
    for old,new in [('w  W','J13 W'),('s  S','J13 S'),('f  F','J13 F'),('Right Arrow','J13 Right')]:
        script=script.replace('"'+old+'"','"'+new+'"')
    script=script.replace('print("CLOCK_DONE");',
        'print("J13_LIVE "..s:read_u16(%d).." "..s:read_u16(%d).." "..s:read_u16(%d));print("CLOCK_DONE");' %
        (sym['j13Mode'],sym['j13Matrix'],sym['j13Timeouts']))
observer = out / 'observer.lua'
observer.write_text(script)
if not args.analyze:
    boot='wait=1;sleep=1;key=Esc;wait=2;sleep=1;key=Home;key=Return;wait=15;sleep=1;key=Return;wait=3;sleep=1;key=Return;wait=0;'
    if args.j13: boot=boot.replace('key=Esc','key=J13 Escape',1)
    subprocess.run([sys.executable, str(ROOT/'tools/ui_test.py'), '--name', args.name,
                    '--hd', '--debug', '--seconds', '220', '--steps', (boot if args.normal_boot else '')+'sleep=215;end=',
                    '--lua', str(observer)]+([] if args.normal_boot else ['--skip'])+
                    (['--disk',str(args.disk)] if args.disk else [])+
                    (['--mame',str(args.mame)] if args.mame else [])+
                    (['--j13','both'] if args.j13 else []), check=True, stdout=subprocess.DEVNULL)
log = (out/'mame.log').read_text()
if args.profile_at and not args.analyze:
    shutil.copyfile(ROOT/'build/wolf.elf',out/'profile.elf')
    for number,at,elapsed in re.findall(r'^LIVEPROFILE (\d+) ([\d.]+) ([\d.]+)',log,re.M):
        trace=out/f'instructions-{number}.trace'
        counts=collections.Counter();instructions={}
        with trace.open() as stream:
            for line in stream:
                match=re.match(r'^([0-9A-Fa-f]{2}):?([0-9A-Fa-f]{4}):\s+(.*)',line)
                if match:
                    pc=int(match[1]+match[2],16);counts[pc]+=1;instructions[pc]=match[3]
        assert counts,'empty live instruction trace'
        (out/f'instruction-counts-{number}.json').write_text(json.dumps({f'{pc:06x}':dict(count=n,instruction=instructions[pc]) for pc,n in sorted(counts.items())},indent=2)+'\n')
        (out/f'profile-{number}.json').write_text(json.dumps(dict(at=float(at),frame_ms=float(elapsed)*1000)))
        trace.rename(Path.home()/'.Trash'/f'wolf-live-{time.time_ns()}.trace')
    assert len(re.findall(r'^LIVEPROFILE ',log,re.M))==len(args.profile_at),'missing live profile'

rows = []
for line in re.findall(r'^CLOCK (.*)$', log, re.M):
    values = line.split()
    rows.append(dict(zip(('seconds','ticks','doc','frontier','debt','frame_seconds','x','y','health','dropped','world_tics','doc_seconds','simulation_seconds','queue_seconds','world_seconds','player_seconds','world_frontier'),
                         [float(v) if i in (0,5,11,12,13,14,15) else int(v) for i,v in enumerate(values)])))
deaths = [dict(actor=int(a), counted_tics=int(n), seconds=float(t))
          for a,n,t in re.findall(r'^DEATH (\d+) (\d+) ([\d.]+)$', log, re.M)]
presented_deaths=[]
shown={}
for ob,state,at in re.findall(r'^DEATH_PRESENT (\d+) (\d+) ([\d.]+)$',log,re.M):
    ob,state,at=int(ob),int(state),float(at)
    if state==state_ids['s_grddie1']:
        shown[ob]=[(state,at)]
    elif ob in shown:
        shown[ob].append((state,at))
        if state==state_ids['s_grddie4']:
            poses=shown.pop(ob)
            presented_deaths.append(dict(actor=(ob-logic['layout']['OBJLIST'])//64,
                seconds=poses[-1][1]-poses[0][1],
                pose_seconds=[b[1]-a[1] for a,b in zip(poses,poses[1:])],
                animated_poses=len(poses)-1))
collision_match=re.search(r'^COLLISIONS (\d+) (\d+) (\d+) (\d+)$',log,re.M)
collisions=dict(zip(('tunnel_events','wall_stops','closed_door_stops','max_pass_tics'), map(int,collision_match.groups()))) if collision_match else {}
marker_match=re.search(r'^ACTOR_MARKERS (\d+)$',log,re.M)
marker_errors=int(marker_match[1]) if marker_match else None
mirror_match=re.search(r'^WORLD_MIRRORS (\d+) (\d+)$',log,re.M)
mirror_checks,mirror_errors=map(int,mirror_match.groups()) if mirror_match else (None,None)
idle_match=re.search(r'^IDLE_DOOR_TICS (\d+)$',log,re.M)
idle_tics=int(idle_match[1]) if idle_match else None
coverage_start=re.search(r'^WALL_COVERAGE_START (\d+) (\d+)$',log,re.M)
coverage_end=re.search(r'^WALL_COVERAGE_DONE ([\d.]+)$',log,re.M)
wall_coverage=dict(used=bool(coverage_start),measured=False)
if coverage_start:
    wall_coverage.update(tile=list(map(int,coverage_start.groups())),seconds=float(coverage_end[1]) if coverage_end else None)
failures = []
if args.j13 and re.findall(r'^J13_LIVE (\d+ \d+ \d+)$',log,re.M)!=['2 1 0']:
    failures.append('J13 mode, matrix or timeout failed during live combat')
if coverage_start and not coverage_end:failures.append('supplemental wall check did not finish')
if 'worldDoorsIdle' in sym and idle_tics is None and not args.analyze:failures.append('idle door observer missing')
if 'CLOCK_DONE' not in log or len(rows)<2:
    raise SystemExit('live clock route did not finish')
# Compare settled frame boundaries; one picture's presentation latency is
# inherent, but no elapsed DOC tic may disappear at a slow frame.
settled = [r for r in rows if r['seconds']>=1]
first,last = settled[0],settled[-1]
doc_elapsed = (last['doc']-first['doc'])&65535
game_elapsed = last['ticks']-first['ticks']
ratio = game_elapsed/doc_elapsed
frame_start_elapsed = last['doc_seconds']-first['doc_seconds']
world_elapsed = last['world_tics']-first['world_tics']
doc_hz = doc_elapsed/frame_start_elapsed
worst_frame = max(r['frame_seconds'] for r in rows)
frontier_elapsed = (last['frontier']-first['frontier'])&65535
if game_elapsed!=frontier_elapsed: failures.append('player tics differ from consumed DOC tics')
if 'world_frontier' in first:
    world_frontier_elapsed = (last['world_frontier']-first['world_frontier'])&65535
    if world_elapsed!=world_frontier_elapsed: failures.append('world tics differ from scheduled DOC tics')
if abs(world_elapsed/doc_elapsed-1)>.03: failures.append('world/DOC drift exceeds 3%')
if abs(ratio-1)>.03: failures.append('game/DOC drift exceeds 3%')
if abs(game_elapsed/frame_start_elapsed/70-1)>.03: failures.append('game/real-time drift exceeds 3%')
if max(r['debt'] for r in settled)>2: failures.append('unconsumed DOC debt')
if not deaths: failures.append('no guard completed its death')
if any(d['counted_tics']!=death_tics for d in deaths): failures.append('guard death state duration')
if any(abs(d['seconds']-death_tics/doc_hz)>worst_frame for d in deaths):
    failures.append('guard death wall time exceeds one picture of quantization')
if last['dropped']: failures.append('input events dropped')
if collisions.get('tunnel_events',1): failures.append('movement crossed a blocking tile or exceeded the safe step')
if collisions.get('max_pass_tics',2)!=1: failures.append('unsafe logic pass size')
if mirror_errors: failures.append('world batch changed a retained view/status mirror')
if 'LogicWorldPublish' in sym and not args.analyze and not mirror_checks: failures.append('world mirror check missing')
if marker_errors: failures.append('actor render cell differs from its final position')
if marker_errors is None and not args.analyze: failures.append('actor render cell check missing')
if not collisions.get('wall_stops') or not collisions.get('closed_door_stops'): failures.append('checks did not exercise both wall and closed-door stops')
if (first['x'],first['y'])==(last['x'],last['y']): failures.append('walking route did not move')
options=dict((name,int(value)) for name,value in re.findall(r'#define (TICSTEP|MAXTICS) (\d+)', (ROOT/'build/gen/tics.inc').read_text()))
input_source = 'J13' if args.j13 else 'ADB'
report = dict(view=args.view, build_options=options, world_tics=world_elapsed, idle_door_tics=idle_tics, world_doc_ratio=world_elapsed/doc_elapsed, input_source=input_source, fixture=f'guard room; easy difficulty; RNG 0; front guard HP 1; machine gun, ammo 99, health 100; real {input_source} route, 20 seconds, final retreat 12.5-18.5 seconds',
              disk_sha256=hashlib.sha256((args.disk or ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),
              elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
              game_tics=game_elapsed, doc_tics=doc_elapsed, ratio=ratio,
              doc_sample_seconds=frame_start_elapsed, doc_hz=doc_hz,
              mean_simulation_ms=1000*sum(r['simulation_seconds'] for r in settled)/len(settled),
              mean_queue_ms=1000*sum(r['queue_seconds'] for r in settled)/len(settled),
              mean_world_ms=1000*sum(r['world_seconds'] for r in settled)/len(settled),
              mean_player_or_whole_tic_ms=1000*sum(r['player_seconds'] for r in settled)/len(settled),
              game_real_time_ratio=game_elapsed/frame_start_elapsed/70,
              max_catchup_tics=max(b['ticks']-a['ticks'] for a,b in zip(rows,rows[1:])),
              max_debt=max(r['debt'] for r in settled),
              worst_frame_ms=worst_frame*1000,
              collisions=collisions, supplemental_wall_coverage=wall_coverage, actor_marker_errors=marker_errors, world_mirror_checks=mirror_checks, world_mirror_errors=mirror_errors, expected_guard_death_tics=death_tics, expected_guard_death_seconds=death_tics/70, deaths=deaths, presented_deaths=presented_deaths, final=last, failures=failures)
(out/'clock.json').write_text(json.dumps(report,indent=2)+'\n')
(out/'clock-frames.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(report,indent=2))
if failures and not args.measure: raise SystemExit('live clock check failed')
