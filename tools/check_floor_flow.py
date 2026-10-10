"""Native exits and saved stats, with private checkpoints and explicit pose fixtures.

Starting poses and isolated counts are injected. A stat-only loader fixture
bypasses the later world restore; check_saved_world.py tests complete saves. Space/Return are
real ADB input; the elevator, bonus, shared disk reader and new world are native.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

from elf import read
from floor_check import checkpoint, checkpoint_lua
import floor_capture
import music_capture
import test_media
import memmap

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = memmap.fill(r'''
local s=mem
local v=@VARS@
local poses=@POSES@
local stage=0
local acting=false
local pressed,releaseAt=nil,0
local tallySeen={}
local titleAt=nil
local seenPages={}
local lastBj=nil
local shownBj={}
local completedPage,victorySeen=-1,false
local lastProgress,lastReport=0,0
local artChecks=@ARTCHECKS@
local function u32(a) return s:read_u16(a)+s:read_u16(a+2)*65536 end
local function put32(a,n) s:write_u16(a,n&65535);s:write_u16(a+2,n>>16) end
local function pixel(x,y)
 local b=s:read_u8(@MM:SHR@+y*160+x//2)
 return x%2==0 and b>>4 or b&15
end
local function checkPicture(name,rows)
 local c=artChecks[name]
 for _,p in ipairs(c.points) do
  assert(pixel(p[1],p[2])==p[3],string.format("wrong ending picture pixel %s at %d,%d: %d, not %d",name,p[1],p[2],pixel(p[1],p[2]),p[3]))
 end
 for y=0,rows-1 do assert(s:read_u8(@MM:SHR_SCB@+y)==c.scb[y+1],string.format("wrong ending palette row %d: %d, not %d",y,s:read_u8(@MM:SHR_SCB@+y),c.scb[y+1])) end
 print('FLOW_PICTURE '..name)
end
local tallyAt={}
local function dumpTally(stage)
 local parts={}
 for i=0,25599 do parts[#parts+1]=string.char(s:read_u8(@MM:SHR@+i)) end
 for y=0,159 do parts[#parts+1]=string.char(s:read_u8(@MM:SHR_SCB@+y)) end
 for i=0,511 do parts[#parts+1]=string.char(s:read_u8(@MM:SHR_PAL@+i)) end
 local f=assert(io.open(@OUT@.."/tally-"..stage..".bin","wb"))
 f:write(table.concat(parts)) f:close()
end
local function bjHash()
 local h=0
 for row=19,102 do for x=11,48 do h=(h*31+s:read_u8(@MM:SHR@+row*160+x))%4294967291 end end
 return h
end
local breathe={}
local function press(key)
 field(key):set_value(1);pressed=key;releaseAt=now()+0.15
end
local function stats(tag)
 print(string.format('FLOW_STATS {"tag":"%s","floor":%d,"score":%d,"oldscore":%d,"extra":%d,"lives":%d,"health":%d,"ammo":%d,"weapon":%d,"keys":%d,"kills":%d,"treasure":%d,"song":%d}',
 tag,s:read_u16(@FLOOR@),u32(v.score),u32(v.oldscore),u32(v.nextextra),s:read_u16(v.lives),s:read_u16(v.health),s:read_u16(v.ammo),s:read_u16(v.weapon),s:read_u16(v.keys),s:read_u16(v.killcount),s:read_u16(v.treasurecount),s:read_u16(@SONG@)))
end
flowFrameTap=s:install_write_tap(0x3f0,0x3f0,"flow-fixture",function(a,d,m)
 if d~=2 or s:read_u8(0x3e4)~=0 then return end
 lastProgress=now()
 if s:read_u16(@STATE@)==0 and not acting then
  stats(stage==0 and "saved" or "entered")
  stage=stage+1
  if not poses[stage] then
   print('FLOW_DONE');screen:snapshot('next-floor.png');manager.machine:exit();return
  end
  local p=poses[stage]
  assert(s:read_u16(@FLOOR@)==p[1],"unexpected loaded floor")
  put32(@PX@,p[2]*256);put32(@PY@,p[3]*256)
  s:write_u16(@TX@,p[2]>>8);s:write_u16(@TY@,p[3]>>8)
  s:write_u16(@ANGLE@,p[4]);s:write_u16(@NEXTACTOR@,0)
  s:write_u16(v.lastobj,@PLAYER@&65535)
  for i=0,4095 do
   local a=@ACTORAT@+i*2
   if s:read_u16(a)>=(@PLAYER@&65535) then s:write_u16(a,0) end
  end
  for a=@SIGHT_ROWS@,@SIGHT_VISIBLE@,2 do s:write_u16(a,0) end
  if @VICTORY@ then
   for i=0,7 do
    s:write_u16(@RATIOS@+i*8,80);s:write_u16(@RATIOS@+i*8+2,40)
    s:write_u16(@RATIOS@+i*8+4,100);s:write_u16(@RATIOS@+i*8+6,15)
   end
  end
  s:write_u16(v.killcount,4);s:write_u16(v.killtotal,4)
  s:write_u16(v.secretcount,0);s:write_u16(v.secrettotal,2)
  s:write_u16(v.treasurecount,1);s:write_u16(v.treasuretotal,2)
  acting=true;press(@VICTORY@ and "Up Arrow" or "Space")
 elseif s:read_u16(@FLOW@)==3 and not tallySeen[stage] then
  tallySeen[stage]=true
  print(string.format('FLOW_TALLY {"floor":%d,"bonus":%d,"seconds":%d,"score":%d,"next":%d,"song":%d}',s:read_u16(@FLOOR@),u32(@BONUS@),s:read_u16(@SECONDS@),u32(v.score),s:read_u16(@NEXT@),s:read_u16(@SONG@)))
  screen:snapshot('tally-'..stage..'.png')
  dumpTally(stage)
  tallyAt[stage]=now()
  breathe[stage]={}
 elseif s:read_u16(@FLOW@)==4 then acting=false end
 if @VICTORY@ and acting then
  local ob=s:read_u16(@NEXTACTOR@)
  if ob~=0 then
   local state=s:read_u16(@WORLD@+ob+16)
   local shape=s:read_u16(@WORLD@+state+2)
   if state~=lastBj then
    print(string.format('FLOW_BJ %d %d %d %d %d',state,shape,s:read_u32(@WORLD@+ob),s:read_u32(@WORLD@+ob+4),s:read_u16(@BJYELL@)))
    lastBj=state
   end
   local id=(400+(ob-(@PLAYER@&65535))//64)*32
   for i=0,s:read_u16(@SPCOUNT@)-1 do
    if s:read_u16(@SPR_RECORDS@+8+i*16)==id and not shownBj[shape] then
     shownBj[shape]=true;print('FLOW_BJ_VISIBLE '..shape);screen:snapshot('bj-'..shape..'.png')
    end
   end
  end
 end
end)
if @VICTORY@ then
 yellTap=s:install_read_tap(@PLAYSOUND@,@PLAYSOUND@,"victory-yell",function(a,d,m)
  if cpu.state.PB.value==0x3d and cpu.state.A.value==72 then
   assert(s:read_u16(@FX_VOLUME@)>0,"victory effects are muted")
   print('FLOW_YELL_PLAY '..now())
  end
 end)
 yellActiveTap=s:install_write_tap(@FX_ACTIVE@,@FX_ACTIVE@+3,"victory-yell-active",function(a,d,m)
  if d==1 and s:read_u16(@EFFECT_ID@)==72 then print('FLOW_YELL_ACTIVE '..now()) end
 end)
 pageTap=s:install_read_tap(@EP_OUT@,@EP_OUT@,"ending-page-ready",function(a,d,m)
  if cpu.state.PB.value==2 then
   local h=s:read_u16(@HOLD@)
   completedPage=h*100+(h==2 and s:read_u16(@FLOWSTEP@) or 0)
  end
 end)
end
emu.register_frame_done(function()
 if acting and now()-lastProgress>20 and now()-lastReport>30 then
  lastReport=now()
  local r=cpu.state
  print(string.format('FLOW_WAIT %.3f PC=%02x:%04x A=%04x X=%04x Y=%04x D=%04x P=%02x',now(),r.PB.value,r.PC.value&65535,r.A.value,r.X.value,r.Y.value,r.D.value,r.P.value))
 end
 if pressed and now()>=releaseAt then field(pressed):set_value(0);pressed=nil;releaseAt=now()+0.3 end
 if pressed or now()<releaseAt then return end
 if @VICTORY@ and stage>0 and s:read_u8(0x3e4)==1 and s:read_u16(@SONG@)==7 then
  titleAt=titleAt or now()
  if now()-titleAt>=1 then print('FLOW_DONE');screen:snapshot('title-again.png');manager.machine:exit() end
 elseif @VICTORY@ and not victorySeen and completedPage==100 and s:read_u16(@SONG@)==24 and s:read_u16(@HOLD@)==1 then
  checkPicture('victory',160)
  victorySeen=true
  print(string.format('FLOW_VICTORY %d %d %d %d %d',s:read_u16(@VICKILL@),s:read_u16(@VICSECRET@),s:read_u16(@VICTREAS@),s:read_u16(@VICMIN@),s:read_u16(@VICSEC@)))
  screen:snapshot('victory.png');press("Return")
 elseif @VICTORY@ and s:read_u16(@SONG@)==24 and s:read_u16(@HOLD@)==2 then
  local page=s:read_u16(@FLOWSTEP@)
  if page<2 and completedPage==200+page and not seenPages[page] then
   checkPicture('ending'..page,200)
   seenPages[page]=true;print('FLOW_ENDPAGE '..page);screen:snapshot('ending-'..page..'.png');press("Return")
  end
 elseif acting and s:read_u16(@FLOW@)==3 and tallySeen[stage] then
  -- BJ breathes every 35 tics: his hash every 0.1 second for 1.7 seconds shows both pictures
  local b=breathe[stage]
  local t=now()-tallyAt[stage]
  if #b<17 and t>=#b*0.1 then b[#b+1]=bjHash() end
  if #b==17 then print('FLOW_BREATHE '..table.concat(b,',')) b[#b+1]=0 press("Return") end
 end
end)
''')


def tally_diff(path, tally, secret):
    """The bytes of the 160 rows of a tally screen (pixels, row palettes, palettes 0, 13 and 14) that differ from the model of
    tools/tally_model.py; BJ may be in either of his two poses."""
    import tally_model
    dump = path.read_bytes()
    best = None
    for pose in (0, 1):
        px, scb, pals = tally_model.screen(tally, secret, pose)
        got_pals = dump[25760:25760 + 32] + dump[25760 + 32 * 13:25760 + 32 * 15]
        wrong = [i for i in range(25600) if dump[i] != px[i]] + [25600 + y for y in range(160) if dump[25600 + y] != scb[y]] \
            + [25760 + i for i in range(96) if got_pals[i] != pals[i]]
        if best is None or len(wrong) < len(best):
            best = wrong
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--media', choices=('hd', 'one', 'two'), default='hd')
    ap.add_argument('--route', choices=('normal', 'secret', 'victory'), default='secret')
    ap.add_argument('--name')
    ap.add_argument('--disk', type=Path, help='source HD image or disk 1; always copied before testing')
    ap.add_argument('--loading-check', action='store_true', help='audit every display write during elevator loading')
    ap.add_argument('--mame', type=Path)
    ap.add_argument('--j13', choices=('off', 'only', 'both'), default='off')
    args = ap.parse_args()
    if args.loading_check and args.route == 'victory':
        ap.error('--loading-check requires an elevator route (normal or secret)')
    name = args.name or 'floor-flow-'+args.route+'-'+args.media
    out = ROOT/'build/tests'/name
    out.mkdir(parents=True, exist_ok=True)
    _, sym = read(ROOT/'build/wolf.elf')
    logic = json.loads((ROOT/'build/assets/logic.json').read_text())
    layout, fields = logic['layout'], logic['fields']
    world = memmap.world(sym)
    variables = {n: world+layout['VARS']+2*i for i, n in enumerate(logic['vars'])}
    first = 8 if args.route == 'victory' else 0
    src = args.disk or ROOT/('build/wolf-hd.po' if args.media == 'hd' else 'build/disk1.po')
    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    prepared = checkpoint(src, out, first)
    data = bytearray(prepared.read_bytes())
    block = struct.unpack_from('<H', data, 512+436)[0]
    settings = bytearray(data[block*512:(block+1)*512])
    values = (1, 2, first, 7, 80, 40, 3, 3, 3, 12345, 0, 40000, 0, 4, 1)
    struct.pack_into('<16H', settings, 232, *values, sum(values)&65535)
    struct.pack_into('<H', settings, 8, sum(settings[12:496])&65535)
    data = bytearray(src.read_bytes())
    block = struct.unpack_from('<H', data, 512+436)[0]
    data[block*512:(block+1)*512] = settings
    prepared.write_bytes(data)
    poses = {'normal': [(0, 6528, 12160, 0)],
             'secret': [(0, 2688, 13184, 180), (9, 11648, 2944, 180)],
             'victory': [(8, 8832, 2068, 90)]}[args.route]
    script = FIXTURE.replace('@VARS@', '{'+','.join('[%s]=%d' % (json.dumps(n), a) for n, a in variables.items())+'}')
    script = script.replace('@POSES@', '{'+','.join('{'+','.join(map(str, p))+'}' for p in poses)+'}')
    script = script.replace('@VICTORY@', 'true' if args.route == 'victory' else 'false')
    checks = json.loads((ROOT/'build/assets/pages-check.json').read_text())
    script = script.replace('@ARTCHECKS@', '{'+','.join(
        k+'={points={'+','.join('{'+','.join(map(str,p))+'}' for p in c['points'])+'},scb={'+','.join(map(str,c['scb']))+'}}' for k,c in checks.items())+'}')
    script = script.replace('@OUT@', json.dumps(str(out)))
    tokens = {k: sym[n] for k, n in [('FLOOR','levelIndex'),('SONG','currentSong'),('STATE','levelState'),('FLOW','flowPhase'),('BONUS','tallyBonus'),('SECONDS','tallySec'),('NEXT','nextFloor'),('HOLD','holdScreen'),('RATIOS','ratioTable'),('FLOWSTEP','flowStep'),('BJYELL','bjYell'),('VICKILL','vicKill'),('VICSECRET','vicSecret'),('VICTREAS','vicTreas'),('VICMIN','vicMin'),('VICSEC','vicTime'),('PLAYSOUND','PlaySound')]}
    tokens.update(WORLD=world, SIGHT_ROWS=sym['SIGHT_ROWS'], SIGHT_VISIBLE=sym['SIGHT_VISIBLE'],
                  SPR_RECORDS=memmap.projections(sym)[0])
    tokens['PLAYER'] = world+layout['OBJLIST']
    tokens['ACTORAT'] = world+layout['ACTORAT']
    tokens['EP_OUT'] = sym['epOut']
    tokens.update(FX_VOLUME=sym['soundVolume'],FX_ACTIVE=sym['fxActive'],EFFECT_ID=sym['effectId'])
    tokens['SPCOUNT'] = 0x1000+memmap.SP_COUNT
    for token, field_ in [('PX','O_X'),('PY','O_Y'),('TX','O_TILEX'),('TY','O_TILEY'),('ANGLE','O_ANGLE'),('NEXTACTOR','O_NEXT')]:
        tokens[token] = world+layout['OBJLIST']+fields[field_]
    for token, address in tokens.items():
        script = script.replace('@'+token+'@', str(address))
    assert '@' not in script
    if args.j13 == 'only':
        for key in ('Space', 'Return', 'Up Arrow'):
            script = script.replace('"'+key+'"', '"J13 '+key.removesuffix(' Arrow')+'"')
    script += checkpoint_lua() + music_capture.lua() + music_capture.art_lua()
    if args.loading_check:
        import floor_loading_capture
        script += floor_loading_capture.lua(sym, out)
    checked_floors = {'normal': [0,1], 'secret': [0,9,1], 'victory': [8]}[args.route]
    for floor in checked_floors:
        folder=out/f'assets-floor{floor}'
        folder.mkdir(exist_ok=True)
        capture=floor_capture.lua(folder, floor=floor, trigger=0x3f0, value=2)
        capture=capture.replace('assetTap=', f'assetTapFloor{floor}=')
        capture=capture.replace('  if d~=', '  if s:read_u8(0x3e4)~=0 then return end\n  if d~=')
        script += '\nlocal s=mem\n'+capture
    media_args = ['--hd']
    if args.media != 'hd':
        _, swaps = test_media.prepare(src, out, drives=1 if args.media == 'one' else 2)
        script += '\n'+swaps
        script += '''
local menuDisk=false
menuDiskTap=mem:install_read_tap(%d,%d,"menu-disk",function(a,d,m) if cpu.state.PB.value==0x3f then menuDisk=true end end)
menuFoundTap=mem:install_read_tap(%d,%d,"menu-found",function(a,d,m) if cpu.state.PB.value==0x3f then menuDisk=false end end)
emu.register_frame_done(function()
 if menuDisk then
  local drive=manager.machine.images[":fdc:2:35dd"]
  if not drive.exists then drive:load(%s);print("MENU_DISK1") end
 end
end)
''' % (sym['needWait'], sym['needWait'], sym['needDone'], sym['needDone'], json.dumps(str(out/'disk1.po')))
        media_args = ['--disk2', str(out/'disk2.po')] if args.media == 'two' else []
    (out/'observe.lua').write_text(script)
    steps = 'wait=1;sleep=1;key=Esc;wait=2;sleep=0.4;key=Down;key=Return;wait=4;sleep=0.4;key=Return;wait=0;sleep=799;end='
    if args.j13 == 'only':
        for key in ('Esc', 'Down', 'Return'):
            steps = steps.replace('key='+key, 'key=J13 '+('Escape' if key == 'Esc' else key))
    input_args = ['--j13', args.j13]
    if args.mame:
        input_args += ['--mame', str(args.mame)]
    if args.loading_check:
        input_args += ['--debug']
    proc = subprocess.run([sys.executable, 'tools/ui_test.py', '--name', name, '--disk', str(prepared),
                           '--seconds', '800', '--steps', steps, '--lua', str(out/'observe.lua'), *media_args, *input_args],
                          cwd=ROOT, capture_output=True, text=True, timeout=1750)
    (out/'driver.log').write_text(proc.stdout+proc.stderr)
    log = (out/'mame.log').read_text()
    assert not re.search(r'Lua error|LUA ERROR', log, re.I), log[-3000:]
    assert proc.returncode == 0 and 'FLOW_DONE' in log, log[-3000:]
    stats = [json.loads(s) for s in re.findall(r'^FLOW_STATS (.*)$', log, re.M)]
    tallies = [json.loads(s) for s in re.findall(r'^FLOW_TALLY (.*)$', log, re.M)]
    assert stats[0] == dict(tag='saved', floor=first, score=12345, oldscore=12345, extra=40000,
                           lives=7, health=80, ammo=40, weapon=3, keys=0, kills=4, treasure=1,
                           song=(2 if first == 8 else 3)), stats[0]
    score = 12345
    for tally, entered in zip(tallies, stats[1:]):
        bonus = 15000 if tally['floor'] == 9 else max(0,90-tally['seconds'])*500+10000
        score += bonus
        assert tally['bonus'] == bonus and tally['score'] == score and tally['song'] == 16, tally
        assert entered['score'] == entered['oldscore'] == score and entered['floor'] == tally['next'], entered
        assert (entered['health'], entered['ammo'], entered['weapon'], entered['keys']) == (80,40,3,0), entered
        assert entered['lives'] == 7+score//40000 and entered['extra'] == (1+score//40000)*40000, entered
    if args.route != 'victory':
        assert len(tallies) == len(poses) and len(stats) == len(poses)+1, (stats, tallies)
        assert stats[-1]['floor'] == 1
    for row in re.findall(r'^FLOW_BREATHE (\S+)$', log, re.M):
        # the copy of a picture takes a frame or two: a hash that comes once or twice is a picture half drawn
        counts = {h: row.split(',').count(h) for h in set(row.split(','))}
        assert sum(1 for c in counts.values() if c >= 3) == 2, ('BJ does not breathe between his two pictures', row)
    assert len(re.findall(r'^FLOW_BREATHE', log, re.M)) == len(tallies), 'a tally without breathing'
    for stage, tally in enumerate(tallies, 1):
        wrong = tally_diff(out / ('tally-%d.bin' % stage), tally, secret=tally['floor'] == 9)
        assert not wrong, ('tally %d: %d bytes differ from the model, the first at %d' % (stage, len(wrong), wrong[0]))
    songs = music_capture.events(log)
    art = music_capture.art_events(log)
    for event in art:
        if event['active']:
            assert event['interrupts_enabled'] and event['music_wakes'] > 0, event
    assert 16 in [s['song'] for s in songs] or args.route == 'victory'
    if args.route == 'victory':
        assert 'FLOW_VICTORY 80 40 100 2 0' in log and [s['song'] for s in songs][-2:] == [24,7], songs
        assert re.findall(r'^FLOW_ENDPAGE (\d+)$',log,re.M) == ['0','1']
        assert 'FLOW_YELL_PLAY' in log
        assert 'FLOW_YELL_ACTIVE' in log
        assert 'FLOW_BJ_VISIBLE' in log
        assert re.findall(r'^FLOW_PICTURE (\w+)$',log,re.M) == ['victory','ending0','ending1']
    assert re.findall(r'^ASSETS_DONE (\d+)(?: \d+)?$', log, re.M) == ['0']*len(checked_floors), log[-3000:]
    assert hashlib.sha256(src.read_bytes()).hexdigest() == source_hash
    loading = floor_loading_capture.check(log) if args.loading_check else None
    result = dict(route=args.route, media=args.media, disk_sha256=source_hash,
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  checkpoint_sha256=hashlib.sha256(prepared.read_bytes()).hexdigest(),
                  j13=args.j13, loading=loading,
                  stats=stats, tallies=tallies, songs=songs, art=art, glu_violations=0,
                  method=__doc__, asset_differences=0,
                  bj_states=[list(map(int,r.split())) for r in re.findall(r'^FLOW_BJ (.*)$',log,re.M)],
                  bj_visible=list(map(int,re.findall(r'^FLOW_BJ_VISIBLE (\d+)$',log,re.M))),
                  yell_started='FLOW_YELL_PLAY' in log,
                  yell_active='FLOW_YELL_ACTIVE' in log,
                  ending_pages=list(map(int,re.findall(r'^FLOW_ENDPAGE (\d+)$',log,re.M))))
    (out/'flow-check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
