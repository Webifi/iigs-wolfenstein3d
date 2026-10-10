"""Trace real ADB keyboard/mouse commands and each native player tic.

Each segment starts at the same clear 25-tile E1M1 corridor. Only the initial
pose is placed by the fixture; actors are unlinked and their occupancy removed
to isolate input from combat. Original walls, doors and statics remain. Movement
goes through the real input ports.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from elf import read
import logic_capture
import logic_observer
from wolfdata import ROOT


LUA = r'''
local s=mem
@LOGIC@
local SYM=@SYMBOLS@
local plans={
 {name="key_walk",first=1,last=4.5,key="Up Arrow"},
 {name="key_turn",first=6,last=9.5,key="Right Arrow"},
 {name="mouse_walk",first=11,last=14.5,axis="Y",rate=-980},
 {name="mouse_turn",first=16,last=19.5,axis="X",rate=1960},
 {name="key_run",first=21,last=22.75,key="Up Arrow",shift=true},
 {name="key_run_turn",first=24,last=27.5,key="Right Arrow",shift=true}}
local start,configured=nil,nil
local frame,serial,frameTics=0,0,0
local pending=nil
local commands={}
local recorded=0
local phase="idle"
local held={}
local lastFrame=0
local mouseValue={X=0,Y=0}
local function signed(v) if v>=32768 then return v-65536 else return v end end
local function field(name)
 for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do
  if f.name==name then return f end
 end end
 error("missing input "..name)
end
local function position()
 return {x=s:read_u32(LC.OBJLIST+LC.O_X),y=s:read_u32(LC.OBJLIST+LC.O_Y),
  angle=s:read_u16(LC.OBJLIST+LC.O_ANGLE),frac=signed(s:read_u16(LC.V_anglefrac))}
end
local function poseJson(p)
 return string.format('{"x":%d,"y":%d,"angle":%d,"frac":%d}',p.x,p.y,p.angle,p.frac)
end
inputEvent=s:install_write_tap(SYM.inputHead+1,SYM.inputHead+1,"input-event",function(a,d,m)
 if not start then return end
 local head=(d<<8)|s:read_u8(SYM.inputHead)
 local p=SYM.inputRing+((head-8)&1023)
 print(string.format('INPUT_EVENT {"time":%.9f,"frame":%d,"stamp":%d,"type":%d,"value":%d,"aux":%d}',
  manager.machine.time:as_double()-start,frame,s:read_u16(p),s:read_u16(p+2),s:read_u16(p+4),s:read_u16(p+6)))
end)
local function commandMade()
 if not start or cpu.state.PB.value~=2 then return end
 local count=s:read_u16(SYM.ticCount)
 if count<=recorded then return end
 assert(count==recorded+1,"command observer missed a slot")
 recorded=count
 local p=SYM.ticCommands+(count-1)*8
 serial=serial+1;commands[count-1]=serial
 print(string.format('INPUT_COMMAND {"id":%d,"time":%.9f,"frame":%d,"slot":%d,"until":%d,"made":%d,"held":%d,"bits":%d,"mouse_x":%d,"mouse_y":%d,"head":%d,"limit":%d,"tail":%d,"interval_credit":%d,"move_budget":%d}',
  serial,manager.machine.time:as_double()-start,frame,count-1,s:read_u16(SYM.inputUntil),s:read_u16(SYM.lastMadeTic),
  s:read_u16(SYM.heldCommand),s:read_u16(p),signed(s:read_u16(p+2)),signed(s:read_u16(p+4)),
  s:read_u16(SYM.inputHead),s:read_u16(SYM.inputLimit),s:read_u16(SYM.inputTail),
  s:read_u16(SYM.inputIntervalTics),s:read_u16(SYM.inputMoveBudget)))
end
commandTap=s:install_read_tap(SYM.buildNext,SYM.buildNext,"command-made",commandMade)
thrustTap=s:install_read_tap(SYM.Thrust,SYM.Thrust,"requested-thrust",function(a,d,m)
 if pending and cpu.state.PB.value==0x0d then
  pending.requested=pending.requested+s:read_u32(0x1100+@SPEED@)
  pending.calls=pending.calls+1
 end
end)
clipTap=s:install_read_tap(SYM.speedReady,SYM.speedReady,"limited-thrust",function(a,d,m)
 if pending and cpu.state.PB.value==0x0d then pending.limited=pending.limited+s:read_u16(0x1100+@SPEED@) end
end)
local function onPlayerTic(d)
 if not start then return end
 if d==1 then
  local slot=s:read_u16(SYM.ticRead)//8
  pending={before=position(),id=commands[slot] or 0,slot=slot,time=manager.machine.time:as_double()-start,
   bits=s:read_u16(0x104a),x=signed(s:read_u16(LC.V_controlx)),y=signed(s:read_u16(LC.V_controly)),
   tics=s:read_u16(LC.V_tics),requested=0,limited=0,calls=0,phase=phase}
 elseif d==6 and pending then
  local p=pending;local after=position();frameTics=frameTics+1
  print(string.format('INPUT_TIC {"id":%d,"time":%.9f,"frame":%d,"phase":"%s","slot":%d,"bits":%d,"controlx":%d,"controly":%d,"tics":%d,"requested":%d,"limited":%d,"thrust_calls":%d,"before":%s,"after":%s}',
   p.id,p.time,frame,p.phase,p.slot,p.bits,p.x,p.y,p.tics,p.requested,p.limited,p.calls,poseJson(p.before),poseJson(after)))
  pending=nil
 end
end
@LOGIC_TAPS@
frameTap=s:install_write_tap(0x3f0,0x3f0,"input-frame",function(a,d,m)
 local now=manager.machine.time:as_double()
 if d==1 then
  if not configured then s:write_u8(0x3e1,@VIEW@);configured=now end
  if start then frame=frame+1;frameTics=0;lastFrame=now;recorded=0;commands={} end
 elseif d==2 then
  if not start then
   if not configured or now-configured<5 then return end
   s:write_u16(LC.OBJLIST+LC.O_NEXT,0)
   s:write_u16(LC.V_lastobj,LC.OBJLIST&65535)
   for p=@SIGHT_ROWS@,@SIGHT_ROWS@+128,2 do s:write_u16(p,0) end
   for i=0,4095 do
    local p=LC.ACTORAT+i*2
    if s:read_u16(p)>=(LC.OBJLIST&65535) then s:write_u16(p,0) end
   end
   start=now;logicSpawn(896,12160,256);s:write_u16(LC.V_anglefrac,0)
   print('INPUT_READY '..now)
  else
   print(string.format('INPUT_FRAME {"time":%.9f,"frame":%d,"seconds":%.9f,"phase":"%s","tics":%d,"doc":%d,"played":%d,"until":%d,"held":%d,"dropped":%d,"pose":%s}',
    now-start,frame,now-lastFrame,phase,frameTics,s:read_u16(0x104c),s:read_u16(0x1046),s:read_u16(SYM.inputUntil),s:read_u16(SYM.heldCommand),s:read_u16(SYM.inputDropped),poseJson(position())))
   if now-start>29 then print('INPUT_DONE');manager.machine:exit() end
  end
  local t=now-start
  for _,p in ipairs(plans) do
   if not p.placed and t>=p.first-0.65 then
    logicSpawn(896,12160,256);s:write_u16(LC.V_anglefrac,0);p.placed=true
   end
  end
 end
end)
emu.register_frame_done(function()
 if not start then return end
 local t=manager.machine.time:as_double()-start
 local want={};phase="idle"
 for _,p in ipairs(plans) do
  if t>=p.first and t<p.last then
   phase=p.name
   if p.key then want[p.key]=true;if p.shift then want['Shift']=true end end
   if p.axis then
    if not p.mouseBase then p.mouseBase=mouseValue[p.axis] end
    local value=(p.mouseBase+math.floor((t-p.first)*p.rate))&255
    field('Mouse '..p.axis):set_value(value);mouseValue[p.axis]=value
   end
  end
 end
 for key,_ in pairs(want) do if not held[key] then field(key):set_value(1);print(string.format('INPUT_PORT {"time":%.9f,"key":"%s","down":true}',t,key)) end end
 for key,_ in pairs(held) do if not want[key] then field(key):set_value(0);print(string.format('INPUT_PORT {"time":%.9f,"key":"%s","down":false}',t,key)) end end
 held=want
end)
'''


SHORT_PLANS = '''local plans={
 {name="right_50ms",first=1,last=1.05,key="Right Arrow"},
 {name="right_100ms",first=4,last=4.10,key="Right Arrow"},
 {name="right_200ms",first=7,last=7.20,key="Right Arrow"},
 {name="right_500ms",first=10,last=10.50,key="Right Arrow"},
 {name="left_100ms",first=13,last=13.10,key="Left Arrow"},
 {name="run_right_200ms",first=16,last=16.20,key="Right Arrow",shift=true},
 {name="right_1000ms",first=19,last=20,key="Right Arrow"},
 {name="left_150ms",first=23,last=23.15,key="Left Arrow"}}
'''


def verify(data, fine=False, short=False):
    commands = {r['id']: r for r in data['command']}
    assert len(commands) == len(data['tic'])
    assert len({r['id'] for r in data['tic']}) == len(commands)
    assert [r['id'] for r in data['tic']] == list(commands)
    assert all((b['until'] - a['until']) & 65535 == 1
               for a, b in zip(data['command'], data['command'][1:]))
    assert all(r['doc'] == r['played'] and r['dropped'] == 0 for r in data['frame'])
    events = [e for e in data['event'] if e['type'] == 0]
    held, at, checks = set(), 0, {}
    bindings = {62: 1, 59: 4, 60: 8, 56: 128}
    turn_frames, last_frame = 0, None
    fine_commands = []
    for row in data['tic']:
        command = commands[row['id']]
        until = command['until']
        while at < len(events) and (until - events[at]['stamp']) & 65535 < 32768:
            raw = events[at]['value']
            if raw & 128:
                held.discard(raw & 127)
            else:
                held.add(raw)
            at += 1
        expected = 0
        for raw in held:
            expected |= bindings[raw]
        assert row['tics'] == 1 and command['bits'] == row['bits'] == expected, (row, command, held)
        assert row['requested'] == row['limited'], row
        first = False
        if not expected & 12:
            turn_frames = 0
        elif command['frame'] != last_frame or turn_frames == 0:
            turn_frames = min(4, turn_frames+1)
            first = True
        last_frame = command['frame']
        mode = (turn_frames if first else 4) if fine and 0 < turn_frames < 4 else 0
        assert command['fine'] == row['fine'] == mode, (command, mode)
        if not expected & 13:
            continue
        run = bool(expected & 128)
        turn = bool(expected & 12)
        rate = 70 if run else 35
        if turn and fine and turn_frames < 4:
            rate = (0, 35, 70, 140)[turn_frames] if first else 0
            fine_commands.append(dict(id=row['id'], frame=row['frame'], stage=turn_frames, units=rate))
        if turn and expected & 4:
            rate = -rate
        name = ('key_run' if run else 'key') + ('_turn' if turn else '_walk')
        if turn and expected & 4:
            name += '_left'
        if run and not turn:
            name = 'key_run'
        before, after = row['before'], row['after']
        dx, dy = after['x']-before['x'], after['y']-before['y']
        angle = (before['angle']-after['angle']+180) % 360-180
        turn_units = angle*20+after['frac']-before['frac']
        assert (row['controlx'], row['controly']) == ((rate, 0) if turn else (0, -rate)), row
        assert (dx, dy, turn_units) == ((0, 0, rate) if turn else (0, -(rate*150-1), 0)), row
        check = checks.setdefault(name, dict(tics=0, first_doc_tic=until, control_units=rate,
                                            distance_per_tic=0 if turn else rate*150-1,
                                            turn_units_per_tic=rate if turn else 0, spans=[]))
        # Shift-up can leave one normal-speed tic before the movement key's up.
        spans = check['spans']
        if not spans or row['id'] != spans[-1]['last_command'] + 1:
            spans.append(dict(first_doc_tic=until, last_doc_tic=until, tics=0,
                              first_command=row['id'], last_command=row['id']))
        span = spans[-1]
        span['tics'] += 1
        span['last_doc_tic'] = until
        span['last_command'] = row['id']
        check['tics'] += 1
        check['last_doc_tic'] = until
    assert checks if short else len(checks) == 4
    for row in checks.values():
        assert sum(span['tics'] for span in row['spans']) == row['tics']
        for span in row['spans']:
            assert ((span['last_doc_tic'] - span['first_doc_tic']) & 65535) + 1 == span['tics']
            assert span['last_command'] - span['first_command'] + 1 == span['tics']
    return dict(keyboard=checks, commands=len(commands), frames=len(data['frame']),
                fine_turns=fine, fine_commands=fine_commands,
                skipped_commands=0, unexpected_controls=0, clipped_thrusts=0,
                incorrect_moves=0, incorrect_turns=0, sampled_doc_debt=0, dropped_events=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--view', type=int, choices=(160, 214, 240, 320), required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--analyze', action='store_true')
    ap.add_argument('--short-turns', action='store_true', help='50–1000 ms turn taps and short presses')
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT/'build/wolf.elf')
    names = ('inputHead','inputRing','ticCount','ticCommands','inputUntil','lastMadeTic',
             'heldCommand','inputLimit','inputTail','inputIntervalTics','inputMoveBudget',
             'Thrust','speedReady','ticRead','inputDropped','buildNext')
    dp = (ROOT/'src/iigs/logic_dp.inc').read_text()
    speed = int(re.search(r'L_SPEED\s+\.equ\s+(0x[0-9a-f]+)', dp)[1], 16)
    lua = re.sub(r'local plans=\{.*?(?=local start,configured)', SHORT_PLANS, LUA, flags=re.S) if args.short_turns else LUA
    script = (lua.replace('@LOGIC@', logic_capture.lua())
              .replace('@SYMBOLS@','{'+','.join(f'{n}={symbols[n]}' for n in names)+'}')
              .replace('@SPEED@',str(speed))
              .replace('@SIGHT_ROWS@',str(int(re.search(r'SIGHT_ROWS\s+\.equ\s+(0x[0-9a-f]+)', (ROOT/'src/iigs/sight.inc').read_text())[1],16)))
              .replace('@VIEW@',str((160,214,240,320).index(args.view)+1)))
    script=script.replace('@LOGIC_TAPS@',logic_observer.taps(symbols,'logic','onPlayerTic',handle='playerTap'))
    (out/'observe.lua').write_text(script)
    if not args.analyze:
        subprocess.run([sys.executable,'tools/ui_test.py','--name',args.name,'--hd','--skip',
                        '--seconds','180','--steps','sleep=179;end=',
                        '--lua',str(out/'observe.lua')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    disk=(ROOT/'build/wolf-hd.po').read_bytes()
    disk_sha = hashlib.sha256(disk).hexdigest()
    elf_sha = hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest()
    if args.analyze:
        previous = json.loads((out/'input-tics.json').read_text())
        assert previous['disk_sha256'] == disk_sha and previous['elf_sha256'] == elf_sha, 'analysis needs the captured disk/ELF pair'
    log=(out/'mame.log').read_text()
    assert 'INPUT_DONE' in log and 'Lua error' not in log, log[-2500:]
    data={kind.lower():[json.loads(row) for row in re.findall(r'^INPUT_'+kind+r' (\{.*\})$',log,re.M)]
          for kind in ('EVENT','COMMAND','TIC','FRAME','PORT')}
    for row in data['command']+data['tic']:
        row['raw_bits']=row['bits']
        row['fine']=(row['bits']>>10)&7
        row['bits'] &= 1023
    checks=verify(data, fine='BuildFineTurn' in symbols, short=args.short_turns)
    summary={}
    phases=sorted({r['phase'] for r in data['tic']}) if args.short_turns else ('key_walk','key_turn','mouse_walk','mouse_turn','key_run','key_run_turn')
    for phase in phases:
        rows=[r for r in data['tic'] if r['phase']==phase]
        summary[phase]=dict(tics=len(rows), controls=dict(collections.Counter(
            f"{r['controlx']},{r['controly']}" for r in rows)),
            moves=dict(collections.Counter(f"{r['after']['x']-r['before']['x']},{r['after']['y']-r['before']['y']}" for r in rows)),
            turns=dict(collections.Counter(str((r['before']['angle']-r['after']['angle']+180)%360-180) for r in rows)),
            clipped=sum(r['requested']!=r['limited'] for r in rows))
    result=dict(view=args.view,build_id='%08X'%struct.unpack_from('<I',disk,944)[0],
                disk_sha256=disk_sha, elf_sha256=elf_sha,
                machine='apple2gsr1',ramsize='4352K',fixture='original corridor, actors unlinked and actor occupancy cleared',checks=checks,summary=summary,**data)
    (out/'input-tics.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(checks,indent=2))
    print('Evidence:',out/'input-tics.json')


if __name__ == '__main__':
    main()
