"""Play an original demo on the stock IIgs model and compare every frame's
game state with the wolfsim.py model of the source. Non-shootable actors have
no consumer for derived aim/depth fields, so those two fields are excluded.
Shared wall-cast builds check stable gameplay and fresh combat projections,
while reporting the accepted visibility/activation differences separately.
Visibility itself is checked by the wall/neighborhood and picture fixtures.

Prints the first differing frame and field, or the demo's end state.
"""
from mame_target import ram_size
import argparse
from collections import Counter
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from elf import read
import wolfsim
import floor_capture
import test_media
import demo_capture
import memmap
from memmap import projections
import logic_observer
import lua_guard
import mame_kit

ROOT = Path(__file__).resolve().parents[1]
MAME = mame_kit.BINARY
ROMS = mame_kit.ROMPATH

PLAYER_FIELDS = ('x', 'y', 'angle', 'tilex', 'tiley', 'area')
GAME_FIELDS = ('health', 'ammo', 'score', 'lives', 'keys', 'weapon', 'bestweapon', 'killcount',
               'secretcount', 'treasurecount', 'rndindex', 'playstate')
ACTOR_FIELDS = ('x', 'y', 'tilex', 'tiley', 'dir', 'hp', 'flags', 'active', 'ticcount', 'state', 'distance',
                'centered', 'transx')
ACTOR_GAME_FIELDS = ACTOR_FIELDS[:-2]  # non-shootable actors have no aim/depth consumer

LUA = memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local L=@MM:ART_FULL@
local layout=@LAYOUT@
local fields=@FIELDS@
local vars=@VARS@
local states=@STATES@
local demo=@DEMO@
local timedemo=@TIMEDEMO@
local started=false
local lastrnd=0
local frames=0
local postFile=@POSTS@ and io.open("@OUT@/ray-posts.bin","wb") or nil
local spriteFile=@POSTS@ and io.open("@OUT@/sprite-posts.bin","wb") or nil
local function savePosts()
  if not postFile then return end
  local bytes={}
  for _,base in ipairs({@POSTADDRS@}) do
    for col=0,s:read_u16(@VIEWADDR@)-1 do
      local v=s:read_u16(base+col*2)
      bytes[#bytes+1]=string.char(v&255,v>>8)
    end
  end
  postFile:write(table.concat(bytes))
  local count=s:read_u16(0x107c)
  bytes={string.char(count&255,count>>8)}
  for i=0,count-1 do for j=0,6 do
    local v=s:read_u16(@RECORDS@+i*16+j*2)
    bytes[#bytes+1]=string.char(v&255,v>>8)
  end end
  spriteFile:write(table.concat(bytes))
end
local paintInFile=@POSTS@ and io.open("@OUT@/paint-inputs.bin","wb") or nil
paintInTap=s:install_write_tap(0x3f3,0x3f3,"paint-inputs",function(a,d,m)
  if d~=1 or not paintInFile or not started or s:read_u8(0x3f5)~=1 then return end
  local count=s:read_u16(0x107c)
  local bytes={string.char(count&255,count>>8)}
  local function span(base,len) for i=0,len-1 do bytes[#bytes+1]=string.char(s:read_u8(base+i)) end end
  span(@MM:MARKS@,320);span(@MM:COLUMN_MASKS@,320);span(@ORDER@,count*2);span(@MM:SILHOUETTES@,count*2)
  paintInFile:write(table.concat(bytes))
end)
local function u16(a) return s:read_u16(L+a) end
local function s16(a) local v=s:read_u16(L+a); if v>=0x8000 then v=v-0x10000 end; return v end
local function s32(a) local v=s:read_u16(L+a)+s:read_u16(L+a+2)*65536; if v>=0x80000000 then v=v-0x100000000 end; return v end
local function var(n) return u16(vars[n]) end
local rngCallLog={}
rngCallerTap=s:install_read_tap(@RND@,@RND@,"rng-caller",function(a,d,m)
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~=@RNDBANK@ then return end
  local index=(var("rndindex")+1)&255
  rngCallLog[index]=s:read_u16((cpu.state.S.value+1)&65535)
end)
local function rngCaller(index)
  local caller=assert(rngCallLog[index],"RNG call was not observed")
  if @RNG_LEGACY@ then assert(caller==u16(layout.RNGLOG+index*2),"RNG observer differs from legacy log") end
  return caller
end
@REGION_TAPS@
local function dump()
  local p=layout.OBJLIST
  local o={}
  o[#o+1]=string.format('"frame":%d,"x":%d,"y":%d,"angle":%d,"tilex":%d,"tiley":%d,"area":%d',
    var("framecount"),s32(p+fields.O_X),s32(p+fields.O_Y),u16(p+fields.O_ANGLE),u16(p+fields.O_TILEX),u16(p+fields.O_TILEY),u16(p+fields.O_AREA))
  o[#o+1]=string.format('"health":%d,"ammo":%d,"score":%d,"lives":%d,"keys":%d,"weapon":%d,"bestweapon":%d,"killcount":%d,"secretcount":%d,"treasurecount":%d,"rndindex":%d,"playstate":%d',
    s16(vars.health),var("ammo"),var("score")+var("score_hi")*65536,s16(vars.lives),var("keys"),var("weapon"),var("bestweapon"),var("killcount"),var("secretcount"),var("treasurecount"),var("rndindex"),var("playstate"))
  local doors={}
  for i=0,var("doornum")-1 do doors[#doors+1]=tostring(u16(layout.DOORPOS+i*2)) end
  o[#o+1]='"doors":['..table.concat(doors,',')..']'
  o[#o+1]=string.format('"pwall":[%d,%d,%d]',var("pwallstate"),var("pwallx"),var("pwally"))
  local actors={}
  local a=u16(p+fields.O_NEXT)
  while a~=0 do
    actors[#actors+1]=string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d,"%s",%d,%d,%d]',
      s32(a+fields.O_X),s32(a+fields.O_Y),u16(a+fields.O_TILEX),u16(a+fields.O_TILEY),u16(a+fields.O_DIR),s16(a+fields.O_HP),
      u16(a+fields.O_FLAGS),u16(a+fields.O_ACTIVE),s16(a+fields.O_TICS),states[u16(a+fields.O_STATE)] or tostring(u16(a+fields.O_STATE)),s32(a+fields.O_DIST),
      u16(a+fields.O_VIEWX),s32(a+fields.O_TRANSX))
    a=u16(a+fields.O_NEXT)
  end
  o[#o+1]='"actors":['..table.concat(actors,',')..']'
  local calls={}
  local r=var("rndindex")
  while lastrnd~=r do lastrnd=(lastrnd+1)%256; calls[#calls+1]=tostring(rngCaller(lastrnd)) end
  o[#o+1]='"rngcalls":['..table.concat(calls,',')..']'
  print('STATE {'..table.concat(o,',')..'}')
end
local prof=manager.machine.memory.regions[":zipprof"]
local profA,profB=@PROFA@,@PROFB@
local base=nil
local profileRanges={{0x0800,0x08ff},{0x2000,0x5fff},{0x6d80,0x6dff},{0x8fea,0x8fff},{0x9de6,0x9eff}}
local function snap() local t={};for _,r in ipairs(profileRanges) do for k=r[1],r[2] do t[k]=prof:read_u64(@MM:ART_BRIGHT+0x100@+k*24+16) end end;return t end
local t0,tc,tc2,tp=0,0,0,0
local traceFrame=@TRACE@
local traceWhole=@TRACEWHOLE@
local traceBase=nil
local function saveBins(before)
  local final=snap();local f=io.open("@OUT@/profile.txt","w")
  for k,v in pairs(final) do local dt=v-before[k];if dt>0 then f:write(string.format("%06x %d\n",k<0x6000 and k*16 or (k-0x6000)*256,dt)) end end
  f:close()
end
phaseTap=s:install_write_tap(0x3f2,0x3f2,"phase",function(a,d,m)
  if d==1 then
    tc=manager.machine.time:as_double()
    if not traceWhole and started and s:read_u8(0x3f5)==1 and frames+1==traceFrame then
      traceBase=snap();manager.machine.debugger:command('trace @OUT@/instructions.trace,:maincpu,noloop@TRACEACTION@')
    end
  else
    tc2=manager.machine.time:as_double()
    if traceBase and not traceWhole then
      manager.machine.debugger:command('trace off,:maincpu');saveBins(traceBase);traceBase=nil
      print(string.format('CASTPROFILE %d %.9f',frames+1,tc2-tc))
    end
  end
end)
local phaseT={0,0,0,0,0,0};local lastPhase=0;local lastT=0
local function onLogicPhase(d)
  local t=manager.machine.time:as_double()
  if lastPhase>0 and lastPhase<5 then phaseT[lastPhase]=phaseT[lastPhase]+(t-lastT) end
  if frames>=200 and frames<204 then print(string.format('PH %d->%d %.6f',lastPhase,d,t-lastT)) end
  lastPhase=d;lastT=t
end
@LOGIC_TAPS@
paintTap=s:install_write_tap(0x3f3,0x3f3,"paint",function(a,d,m)
  if d==1 then tp=manager.machine.time:as_double() end
end)
frameTap=s:install_write_tap(0x3f0,0x3f0,"frame",function(a,d,m)
  if d==1 then
    t0=manager.machine.time:as_double()
    if traceWhole and started and s:read_u8(0x3f5)==1 and frames+1==traceFrame then
      traceBase=snap();manager.machine.debugger:command('trace @OUT@/instructions.trace,:maincpu,noloop@TRACEACTION@')
    end
  elseif d==2 and traceWhole and traceBase then
    manager.machine.debugger:command('trace off,:maincpu');saveBins(traceBase);traceBase=nil
    print(string.format('FRAMEPROFILE %d %.9f',frames+1,manager.machine.time:as_double()-t0))
  end
  if d==2 and started then local t=manager.machine.time:as_double(); print(string.format('TIME %.6f cast %.6f sprites %.6f paint %.6f',tc-t0,tc2-tc,tp-tc2,t-tp)) end
  if d==1 and not started then
    started=true
    if @PAL@ then s:write_u8(@MM:LANGSEL@,s:read_u8(@MM:LANGSEL@)|0x10) end
    local f=io.open("@LEVEL@","rb")
    if f then
      local data=f:read("*a"); f:close()
      assert(#data==0x10000, "logic bank must contain 65536 bytes")
      for i=0,0xffff do s:write_u8(L+i,data:byte(i+1)) end
      s:write_u16(@LEVELINDEX@, u16(layout.LEVELBLOCK+0x10))
    end
    s:write_u8(0x3e1,@VIEWLATCH@)
    s:write_u8(0x3e3,timedemo)
    s:write_u8(0x3e2,demo+1)
  elseif d==2 and started and s:read_u8(0x3f5)==1 then
    dump()
    savePosts()
    frames=frames+1
    if frames==profA then base=snap() end
    if frames==profB and base then
      local now=snap()
      local f=io.open("@OUT@/profile.txt","w")
      for k,v in pairs(now) do local dv=v-base[k]; if dv>0 then f:write(string.format("%06x %d\n",k<0x6000 and k*16 or (k-0x6000)*256,dv)) end end
      f:close()
    end
  end
end)
demoTap=s:install_write_tap(0x3f5,0x3f5,"demo",function(a,d,m)
  if d==2 then if postFile then postFile:close() end;print(string.format('LOGICPHASES doors %.3f actors %.3f rays %.3f marks %.3f',phaseT[1]*1000/frames,phaseT[2]*1000/frames,phaseT[3]*1000/frames,phaseT[4]*1000/frames)); regionReport(); print('DEMOEND '..frames); print(string.format('REFRESH %.6f',1/manager.machine.screens[":screen"].frame_period)); manager.machine:exit()
  elseif d==3 then print('DEMOFLOOR'); manager.machine:exit() end
end)
emu.register_frame_done(function()
  if not started then s:write_u16(0x3e8,0x5a5a) end
  if manager.machine.time:as_double()>@LIMIT@ then print('TIMEOUT '..frames..string.format(' pc=%02x:%04x A=%04x X=%04x Y=%04x D=%04x DB=%02x bank=%02x',cpu.state.PB.value,cpu.state.PC.value,cpu.state.A.value,cpu.state.X.value,cpu.state.Y.value,cpu.state.D.value,cpu.state.DB.value,s:read_u8(0x54))); manager.machine:exit() end
end)
''')


def lua_table(d):
    return '{' + ','.join('%s=%d' % (k, v) for k, v in d.items()) + '}'


def level_file(demo):
    """The demo's floor bank when the disk holds another floor (test only)."""
    mapon = wolfsim.demo_chunks()[demo]['mapon']
    loaded = json.loads((ROOT / 'build/assets/logic.json').read_text())['floor']
    return ROOT / 'build/levels' / str(mapon) / 'logic.bin' if mapon != loaded else ROOT / 'build/none'


def run_mame(demo, name, limit, machine='apple2gsr1', profile=(0, 0), logic_only=False, disk=None, check_assets=False, drives=2, pal=False, seed=None, trace_frame=0, ray_posts=False, capture_frames=(), elf=None, view=214, trace_scope="cast", trace_action=''):
    disk=Path(disk or ROOT/'build/disk1.po')
    elf=Path(elf or ROOT/'build/wolf.elf')
    if disk.resolve()==ROOT/'build/disk1.po' and disk.stat().st_mtime_ns < elf.stat().st_mtime_ns:
        raise SystemExit('disk image is older than the linked game; wait for make to finish')
    out = ROOT / 'build/tests' / name
    (out / 'cfg').mkdir(parents=True, exist_ok=True)
    ram_config = '' if seed is None else (
        '<port tag=":ram_start" type="CONFIG" mask="7" defvalue="4" value="5"/>'
        f'<port tag=":ram_seed" type="CONFIG" mask="4294967295" defvalue="0" value="{seed}"/>')
    (out / 'cfg' / f'{machine}.cfg').write_text(
        f'<mameconfig version="10"><system name="{machine}"><input>'
        '<port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/>'
        + ram_config +
        '</input></system></mameconfig>')
    logic = json.loads((ROOT / 'build/assets/logic.json').read_text())
    _, symbols = read(elf)
    vars_ = {name: logic['layout']['VARS'] + 2 * i for i, name in enumerate(logic['vars'])}
    states = '{' + ','.join('[%d]="%s"' % (a, n) for n, a in logic['states'].items()) + '}'
    script = (LUA.replace('@LAYOUT@', lua_table(logic['layout'])).replace('@FIELDS@', lua_table(logic['fields']))
              .replace('@VARS@', lua_table(vars_)).replace('@STATES@', states).replace('@DEMO@', str(demo))
              .replace('@TIMEDEMO@', '1').replace('@LIMIT@', str(limit))
              .replace('@RND@', str(symbols['Rnd'])).replace('@RNDBANK@', str(symbols['Rnd']>>16))
              .replace('@RNG_LEGACY@', 'true' if 'rngValue' not in symbols else 'false')
              .replace('@VIEWLATCH@', str({160:1,214:2,240:3,320:4}[view]))
              .replace('@TRACEACTION@', (',{'+trace_action+'}') if trace_action else '').replace('@POSTS@', 'true' if ray_posts else 'false').replace('@POSTADDRS@', ','.join(str(symbols[k]) for k in ('heightIndex','hitPlane','sourceAddr','sourceBank'))).replace('@VIEWADDR@', str(symbols['viewWidth']))
              .replace('@TRACE@', str(trace_frame)).replace('@TRACEWHOLE@', 'true' if trace_scope == 'frame' else 'false')
              .replace('@PAL@', 'true' if pal else 'false')
              .replace('@PROFA@', str(profile[0])).replace('@PROFB@', str(profile[1]))
              .replace('@OUT@', str(out))
              .replace('@LEVEL@', str(level_file(demo) if logic_only else ROOT / 'build/none'))
              .replace('@LEVELINDEX@', str(symbols['levelIndex'])))
    script=script.replace('@RECORDS@',str(projections(symbols)[0])).replace('@ORDER@',str(projections(symbols)[1]))
    script=script.replace('@LOGIC_TAPS@',logic_observer.taps(symbols,'logic','onLogicPhase'))
    script += logic_observer.short_move_tap(symbols)
    script += logic_observer.actor_pointer_taps(symbols)
    region_taps='local function regionReport() end\n'
    if 'InitLineRegions' in symbols:
        region_taps=memmap.fill(r'''
local regionReads={0,0,0}
regionReadObservers={}
for _,spec in ipairs({{REGIONCALL,1},{REGIONCLEAR,2},{REGIONFALLBACK,3}}) do
  local address,index=spec[1],spec[2]
  regionReadObservers[#regionReadObservers+1]=s:install_read_tap(address,address,"region-coverage-"..index,function(a,d,m)
    if not started or manager.machine:side_effects_disabled() or cpu.state.PB.value~=13 or s:read_u8(0x3f5)~=1 then return end
    regionReads[index]=regionReads[index]+1
  end)
end
local function regionReport() print(string.format("REGION_LOOKUPS %d %d %d",regionReads[1],regionReads[2],regionReads[3])) end
regionSetupObserver=s:install_read_tap(REGIONSETUP,REGIONSETUP,"region-setup",function(a,d,m)
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 then return end
  local expected={};for cell=0,4095 do expected[cell]=0 end
  local count=u16(layout.ROOMRECTS)
  for id=1,count do
    local base=L+layout.ROOMRECTS+2+(id-1)*4
    for x=s:read_u8(base),s:read_u8(base+1) do for y=s:read_u8(base+2),s:read_u8(base+3) do
      local cell=x*64+y;assert(expected[cell]==0,"overlapping line regions");expected[cell]=id
    end end
  end
  local cells=0
  for cell=0,4095 do
    assert(s:read_u8(@MM:SHAREWARE_LINEIDS@+cell)==expected[cell],"region ID was not initialized")
    if expected[cell]~=0 then assert(s:read_u8(L+layout.TILEMAP+cell)==0,"region contains a wall");cells=cells+1 end
  end
  for id=0,255 do assert(s:read_u16(@MM:ART_FULL+0x3edac@+id*2)==0,"region count was not initialized") end
  print(string.format("REGION_TABLE %d %d %d",var("mapon"),count,cells))
end)
regionChangeObserver=s:install_read_tap(REGIONSTORED,REGIONSTORED,"region-change",function(a,d,m)
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~=13 then return end
  local id=s:read_u8(@MM:SHAREWARE_LINEIDS@+cpu.state.X.value)
  if id==0 then return end
  local count=0
  for cell=0,4095 do if s:read_u8(@MM:SHAREWARE_LINEIDS@+cell)==id and s:read_u8(L+layout.TILEMAP+cell)~=0 then count=count+1 end end
  assert(s:read_u16(@MM:ART_FULL+0x3edac@+id*2)==count,"region occupancy count differs from the map")
  print(string.format("REGION_CHANGE %d %d",id,count))
end)
''').replace('REGIONSETUP',str(symbols['InitRayTextureDirectory'])).replace('REGIONSTORED',str(symbols['tileStored'])).replace('REGIONCALL',str(symbols['CheckLine'])).replace('REGIONCLEAR',str(symbols['lineRegionClear'])).replace('REGIONFALLBACK',str(symbols['lineRegionFallback']))
    script=script.replace('@REGION_TAPS@',region_taps)
    if capture_frames:
        script=script.replace('local function dump()',demo_capture.lua(symbols,capture_frames,out)+'\nlocal function dump()',1)
        script=script.replace('    savePosts()','    savePosts()\n    capturePicture(frames+1)',1)
    if check_assets:
        script=script.replace(memmap.fill('local L=@MM:ART_FULL@'), floor_capture.lua(out, demo)+memmap.fill('\nlocal L=@MM:ART_FULL@'))
    media,swaps=test_media.prepare(disk or ROOT/'build/disk1.po',out,drives=drives)
    lua_guard.write(out / 'demo.lua', script+'\n'+swaps)
    cmd = ['nice', '-n', '20', MAME, machine, '-rompath', ROMS, '-ramsize', ram_size(machine),
           *media, '-video', 'none', '-sound', 'none', '-nothrottle',
           '-skip_gameinfo', '-seconds_to_run', str(int(limit) + 30), '-autoboot_delay', '0',
           '-autoboot_script', str(out / 'demo.lua'), '-cfg_directory', str(out / 'cfg'),
           '-state_directory', str(out / 'state'), '-nvram_directory', str(out / 'nvram'), '-snapshot_directory', str(out / 'snap')]
    if trace_frame:
        (out / 'debug.txt').write_text('go\n')
        cmd += ['-debug', '-debugger', 'none', '-debugscript', str(out / 'debug.txt')]
        shutil.copyfile(elf, out / 'profile.elf')
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
    live = [l for l in subprocess.run(['pgrep', '-fl', '/iigs.app/Contents/MacOS/iigs'], capture_output=True,
                                      text=True).stdout.splitlines() if str(ROOT / 'build/tests') in l]
    if len(live) >= 1:
        raise SystemExit('A worker MAME process is already running.')
    with (out / 'mame.log').open('w') as log:
        p = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=600)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    if p.returncode:
        raise RuntimeError('MAME exited with code %d; see %s' % (p.returncode, out / 'mame.log'))
    text = (out / 'mame.log').read_text()
    refresh = re.findall(r'^REFRESH ([\d.]+)$', text, re.M)
    if len(refresh) != 1 or abs(float(refresh[0]) - (50 if pal else 60)) > 1:
        raise RuntimeError('Requested video refresh was not applied; see '+str(out/'mame.log'))
    if check_assets and re.findall(r'^ASSETS_DONE (\d+)$',text,re.M)!=['0']:
        raise RuntimeError('Native floor assets did not match; see '+str(out/'mame.log'))
    if trace_frame:
        import collections
        import time
        counts = collections.Counter()
        instructions = {}
        trace = out / 'instructions.trace'
        for line in trace.read_text().splitlines():
            match = re.search(r'(?<![0-9A-Fa-f])([0-9A-Fa-f]{2}):?([0-9A-Fa-f]{4}):\s+(.*)', line)
            if match:
                pc = int(match[1] + match[2], 16)
                counts[pc] += 1
                instructions[pc] = match[3]
        if not counts:
            raise RuntimeError('Requested frame has no instruction trace')
        (out / 'instruction-counts.json').write_text(json.dumps({f'{pc:06x}': dict(count=n, instruction=instructions[pc]) for pc, n in sorted(counts.items())}, indent=2) + '\n')
        sample = re.search(r'^(?:CAST|FRAME)PROFILE (\d+) ([\d.]+)', text, re.M)
        (out / 'result.json').write_text(json.dumps(dict(view=view, frame=trace_frame, profile_scope=trace_scope, **{trace_scope+'_ms':float(sample[2])*1000}), indent=2)+'\n')
        if not trace_action:
            trace.rename(Path.home() / '.Trash' / ('wolf-demo-instructions-%d.trace' % time.time_ns()))
    if capture_frames:
        p=out/'result.json'
        result=json.loads(p.read_text()) if p.exists() else {}
        result.update(demo_capture.metadata(symbols))
        p.write_text(json.dumps(result,indent=2)+'\n')
    rows = [json.loads(m) for m in re.findall(r'^STATE (.*)$', text, re.M)]
    end = re.findall(r'^(DEMOEND|DEMOFLOOR|TIMEOUT).*$', text, re.M)
    return rows, (end[-1] if end else text[-800:])


def oracle_rows(demo, width=240, every=1, shared_visibility=False):
    d = wolfsim.demo_chunks()[demo]
    game = wolfsim.Game(d['mapon'], viewwidth=width)
    game.ray_columns = list(range(4, width, 8))
    data = d['data']
    rows = []
    for n in range(0, len(data) - len(data) % 3, 3):
        b = data[n]
        cx = data[n + 1] - 256 if data[n + 1] > 127 else data[n + 1]
        cy = data[n + 2] - 256 if data[n + 2] > 127 else data[n + 2]
        if n + 3 == len(data):
            game.playstate = wolfsim.EX_COMPLETED
        game.play_frame(b, cx, cy)
        snap = game.snapshot()
        p = game.player
        snap['area'] = p.areanumber
        obs = []
        ob = game.player.next
        while ob is not None:
            obs.append(ob)
            ob = ob.next
        snap['actors'] = [[a['x'], a['y'], a['tilex'], a['tiley'], a['dir'], a['hp'], a['flags'], a['active'],
                           a['ticcount'], a['state'], a['distance'],
                           int(abs(o.viewx - game.centerx) < game.shootdelta), o.transx]
                          for a, o in zip(snap['actors'], obs)]
        if shared_visibility:
            # Derive combat projection independently even when the old sparse
            # fan did not see this actor. Preserve the model's cached fields.
            projected = []
            for ob in obs:
                if not ob.flags & wolfsim.FL_SHOOTABLE:
                    projected.append(None)
                    continue
                saved = ob.transx, ob.transy, ob.viewx, ob.viewheight
                game.transform_actor(ob)
                projected.append((int(abs(ob.viewx-game.centerx) < game.shootdelta), ob.transx))
                ob.transx, ob.transy, ob.viewx, ob.viewheight = saved
            snap['_projected'] = projected
        snap['pwall'] = list(snap['pwall'])
        rows.append(snap)
        if game.playstate:
            break
    return rows


def compare(native, model, shared_visibility=False, visibility_changes=None):
    for n, (a, b) in enumerate(zip(native, model)):
        diffs = []
        for f in PLAYER_FIELDS + GAME_FIELDS:
            if a.get(f) != b.get(f):
                diffs.append((f, a.get(f), b.get(f)))
        if a['doors'] != b['doors']:
            diffs.append(('doors', a['doors'], b['doors']))
        if a['pwall'] != b['pwall']:
            diffs.append(('pwall', a['pwall'], b['pwall']))
        if len(a['actors']) != len(b['actors']):
            diffs.append(('actor count', len(a['actors']), len(b['actors'])))
        for i, (x, y) in enumerate(zip(a['actors'], b['actors'])):
            # Shared-cast visibility replaces the old sparse fan. Keep its
            # differences explicit, and still check every other flag bit,
            # motion/state/combat field and live shootable projection.
            fields = ACTOR_FIELDS if (x[6] | y[6]) & wolfsim.FL_SHOOTABLE else ACTOR_GAME_FIELDS
            for index, (f, u, v) in enumerate(zip(fields, x, y)):
                if shared_visibility:
                    if f == 'flags':
                        if (u ^ v) & wolfsim.FL_VISABLE and visibility_changes is not None:
                            key = 'visibility_added' if u & wolfsim.FL_VISABLE else 'visibility_removed'
                            visibility_changes[key] = visibility_changes.get(key, 0) + 1
                        u &= ~wolfsim.FL_VISABLE
                        v &= ~wolfsim.FL_VISABLE
                    elif f == 'active' and u in (0, 1) and v in (0, 1):
                        if u != v and visibility_changes is not None:
                            visibility_changes[f] = visibility_changes.get(f, 0) + 1
                        continue
                    elif f in ('centered', 'transx'):
                        if x[6] & wolfsim.FL_SHOOTABLE and x[6] & wolfsim.FL_VISABLE:
                            v = b['_projected'][i][index - 11]
                        else:
                            continue  # hidden/corpse aim and depth have no consumer
                if u != v:
                    diffs.append(('actor %d %s' % (i, f), u, v))
        if diffs:
            return n + 1, diffs
    return None, []


def audit_shared_visibility(native, model):
    """Keep gameplay failures distinct from the retired sparse-fan oracle.

    This does not prove the changed visibility/activation/projection fields.
    Their native neighborhood and picture checks remain separate acceptance
    requirements. The existing strict comparator, including live shootable projection checks, remains required.
    """
    changes, first_changes, faults = Counter(), {}, Counter()
    first_fault = None

    def record(key, frame, unexpected=False):
        nonlocal first_fault
        changes[key] += 1
        first_changes.setdefault(key, frame)
        if unexpected:
            faults[key] += 1
            if first_fault is None:
                first_fault = dict(frame=frame, field=key)

    if len(native) != len(model):
        record('frame_count', min(len(native), len(model)) + 1, True)
    for frame, (a, b) in enumerate(zip(native, model), 1):
        for field in ('frame',) + PLAYER_FIELDS + GAME_FIELDS + ('doors', 'pwall'):
            if a.get(field) != b.get(field):
                record(field, frame, True)
        if len(a['actors']) != len(b['actors']):
            record('actor_count', frame, True)
        for x, y in zip(a['actors'], b['actors']):
            if len(x) != len(ACTOR_FIELDS) or len(y) != len(ACTOR_FIELDS):
                record('actor_record_size', frame, True)
            for field, u, v in zip(ACTOR_FIELDS, x, y):
                if u == v:
                    continue
                if field == 'flags':
                    if (u ^ v) & wolfsim.FL_VISABLE:
                        record('actor_visibility', frame)
                    if (u ^ v) & ~wolfsim.FL_VISABLE:
                        record('actor_other_flags', frame, True)
                else:
                    allowed = field in ('centered', 'transx') or (field == 'active' and u in (0, 1) and v in (0, 1))
                    record('actor_' + field, frame, not allowed)
    return dict(native_frames=len(native), model_frames=len(model),
                differences=dict(changes), first_changes=first_changes,
                unexpected=dict(faults), first_fault=first_fault,
                contract='Only VIS bit 8, active 0/1 and cached centered/transx are recorded separately. '
                         'Every other flag bit, actor motion/state/combat, player/game, doors/pushwalls '
                         'and RNG index remain checked. Changed fields need independent native '
                         'visibility/neighborhood and picture validation; this audit does not prove them.')


def report_profile(out, frames):
    _, syms = read(ROOT / 'build/wolf.elf')
    table = sorted((v, k) for k, v in syms.items() if 0x8000 <= v < 0x9000 or 0x20000 <= v < 0x60000 or 0xd8000 <= v < 0xe0000 or memmap.OLD_RAY_CODE <= v < memmap.LOGIC_BASE)
    import bisect
    keys = [v for v, k in table]
    total = {}
    for line in (out / 'profile.txt').read_text().splitlines():
        a, t = line.split()
        a = int(a, 16)
        i = bisect.bisect_right(keys, a) - 1
        name = table[i][1] if i >= 0 else hex(a)
        total[name] = total.get(name, 0) + int(t) * 66 / 15120000 / frames
    for name, ms in sorted(total.items(), key=lambda kv: -kv[1])[:40]:
        print('%-28s %8.3f ms' % (name, ms))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('demo', type=int, choices=range(4))
    ap.add_argument('--name')
    ap.add_argument('--recheck', type=Path, help='recheck a retained native capture without launching MAME')
    ap.add_argument('--disk', type=Path)
    ap.add_argument('--elf', type=Path)
    ap.add_argument('--view', type=int, choices=(160,214,240,320), default=214)
    ap.add_argument('--drives', type=int, choices=(1,2), default=2)
    ap.add_argument('--machine', choices=('apple2gsr1', 'apple2gs'), default='apple2gsr1')
    ap.add_argument('--pal', action='store_true')
    ap.add_argument('--seed', type=int, help='explicit diagnostic RAM pattern seed; default keeps stock startup')
    ap.add_argument('--check-assets', action='store_true')
    ap.add_argument('--limit', type=float, default=400)
    ap.add_argument('--profile', nargs=2, type=int, default=(0, 0), metavar=('FROM', 'TO'))
    ap.add_argument('--capture-frames', nargs='+', type=int, default=(), help='save selected native pictures and ray arrays for reference checks')
    ap.add_argument('--ray-posts', action='store_true', help='save all prepared ray arrays and sprite projections for byte comparison')
    ap.add_argument('--trace-frame', type=int, default=0, help='count and profile the cast of one demo frame; diagnostic, not timing acceptance')
    ap.add_argument('--trace-scope', choices=('cast','frame'), default='cast')
    ap.add_argument('--trace-action', default='', help='debugger action run at every traced instruction, e.g. tracelog "COL=%%04X ",w@2e')
    ap.add_argument('--logic-only', action='store_true', help='inject another floor for logic debugging; not a disk playback or picture check')
    ap.add_argument('--shared-visibility', action='store_true', help='audit gameplay against the old fan, logging changed VIS/activation/projection separately; requires independent visibility and picture checks')
    args = ap.parse_args()
    if args.trace_frame and args.profile[1]:
        ap.error('--trace-frame and --profile use the same profile output; run separately')
    if args.seed is not None and not 0 <= args.seed <= 0xffffffff:
        ap.error('seed must fit 32 bits')
    if args.logic_only:
        print('DIAGNOSTIC: host-injected logic floor; art and disk loading are not validated.', flush=True)
    if args.recheck:
        text = (args.recheck / 'mame.log').read_text()
        assert '[LUA ERROR]' not in text, 'retained capture has Lua errors'
        if args.check_assets:
            assert 'ASSETS_DONE 0' in text, 'retained asset checks did not pass'
        native = [json.loads(line[6:]) for line in text.splitlines() if line.startswith('STATE ')]
        ends = re.findall(r'^(DEMOEND|DEMOFLOOR|TIMEOUT).*$', text, re.M)
        end = ends[-1] if ends else 'missing end'
    else:
        native, end = run_mame(args.demo, args.name or 'demo%d-check' % args.demo, args.limit,
                               machine=args.machine, profile=args.profile, logic_only=args.logic_only, disk=args.disk,
                               check_assets=args.check_assets, drives=args.drives, pal=args.pal, seed=args.seed, trace_frame=args.trace_frame, ray_posts=args.ray_posts, capture_frames=args.capture_frames, elf=args.elf, view=args.view, trace_scope=args.trace_scope, trace_action=args.trace_action)
    if args.profile[1]:
        report_profile(ROOT / 'build/tests' / (args.name or 'demo%d-check' % args.demo), args.profile[1] - args.profile[0])
    shared_visibility = 'CastLogicView' in read(args.elf or ROOT / 'build/wolf.elf')[1]
    model = oracle_rows(args.demo, shared_visibility=shared_visibility)
    visibility_changes = {}
    print('native frames', len(native), 'model frames', len(model), 'end', end)
    frame, diffs = compare(native, model, shared_visibility, visibility_changes)
    if shared_visibility:
        print('SHARED_VISIBILITY ' + json.dumps(visibility_changes, sort_keys=True))
    if args.shared_visibility:
        audit = audit_shared_visibility(native, model)
        destination = ROOT / 'build/tests' / (args.name or 'demo%d-check' % args.demo) / 'shared-visibility-audit.json'
        destination.write_text(json.dumps(audit, indent=2) + '\n')
        print('SHARED VISIBILITY AUDIT', json.dumps(audit))
        if audit['first_fault'] and not frame:
            frame, diffs = audit['first_fault']['frame'], list(audit['unexpected'].items())
    if frame:
        print('first difference at frame', frame)
        for d in diffs[:20]:
            print('  ', d)
        raise SystemExit(1)
    if len(native) != len(model) or end != 'DEMOEND':
        print('incomplete playback or frame counts differ')
        raise SystemExit(1)
    last = native[-1]
    print(json.dumps({k: last[k] for k in PLAYER_FIELDS + GAME_FIELDS}))


if __name__ == '__main__':
    main()
