"""Drive the front end in stock MAME with real ADB key fields and take whole
screen snapshots.

Steps run in order, separated by ';':
  wait=N        wait until the menu code reports screen N in $03E4
  sleep=S       wait S emulated seconds
  key=NAME      press and release a key (Return, Esc, Down, Up, Left, Right,
                Space, Minus, Equals, or one letter)
  hold=NAME,S   hold a key for S seconds
  snap=FILE     whole MAME screen to build/tests/NAME/FILE.png
  poke=A,V      write byte V at address A (decimal or 0x hex)
  poke16=A,V    write the 16 bit word V at address A
  mark=NAME     print MARK and the emulated time (tools/wait_times.py pairs it with the events it logs)
  call=NAME     run CALLS[NAME]; returning false waits and retries next frame
  waitframes=N  wait until the game has finished N more frames (FRAMEADDR, set by the --lua script)
  waitmem=A,V   wait until byte A equals V
  peek=A,N      print N bytes from address A
  eject=N       unload the 3.5-inch drive N (3 or 4)
  insert=N,F    load the disk image F (a path) into drive N
  status=N      print whether drive N holds a disk
  pc=           print the program counter and the stack pointer
  trace=N       print PC and S at each of the next N video frames
  end=          stop (the run also stops at the time limit)
"""
from mame_target import ram_size
import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path
import floor_capture
import lua_guard
import mame_kit
import test_media

ROOT = Path(__file__).resolve().parents[1]
MAME = mame_kit.BINARY
KEYS = {'Return': 'Return', 'Esc': 'Esc', 'Down': 'Down Arrow', 'Up': 'Up Arrow', 'Left': 'Left Arrow',
        'Right': 'Right Arrow', 'Space': 'Space', 'Tab': 'Tab', 'Delete': 'Backspace',
        'Control': 'Control', 'Shift': 'Shift', 'Option': 'Option / Solid Apple',
        'Minus': '-  _', 'Equals': '=  +'}

ap = argparse.ArgumentParser()
ap.add_argument('--name', required=True)
ap.add_argument('--mame', type=Path, default=MAME)
ap.add_argument('--j13', choices=('off','only','both'), default='off')
ap.add_argument('--accelerator', type=int, default=0, choices=range(8))
ap.add_argument('--card',choices=('zip','tw'),default='zip')
ap.add_argument('--cache',type=int,choices=(8,16,32,64),default=32)
ap.add_argument('--steps', required=True)
ap.add_argument('--disk', type=Path)
ap.add_argument('--disk2', type=Path)
ap.add_argument('--seconds', type=int, default=120, help='emulated seconds limit')
ap.add_argument('--machine', default='apple2gsr1', choices=('apple2gsr1', 'apple2gs', 'apple2gs1as', 'apple2gsas'))
ap.add_argument('--ramsize', default=None, help='default: 4352K on ROM 01, 5M on ROM 03')
ap.add_argument('--hd', action='store_true', help='boot build/wolf-hd.po from a CFFA card in slot 7, no floppy')
ap.add_argument('--skip', action='store_true', help='set the latch that skips the title and menu at start')
ap.add_argument('--debug', action='store_true', help='enable headless debugger for explicit observer traces')
ap.add_argument('--audio', action='store_true', help='record the emulated audio to audio.wav; MAME stays silent (-sound none)')
ap.add_argument('--check-floor', type=int, choices=range(60), help='verify native floor assets at its first completed game frame')
ap.add_argument('--lua', type=Path, help='append an explicit observer or test fixture script')
args = ap.parse_args()
MAME = args.mame
j13_config = {"off":0,"only":3,"both":1}[args.j13]
if args.ramsize is None:
    args.ramsize = '14M' if args.machine.endswith('as') else '5M' if args.machine=='apple2gs' else '4352K'
if args.disk is None:
    source = ROOT / ('build/wolf-hd.po' if args.hd else 'build/disk1.po')
    if source.stat().st_mtime_ns < (ROOT/'build/wolf.elf').stat().st_mtime_ns:
        raise SystemExit('disk image is older than the linked game; wait for make to finish')

out = ROOT / 'build/tests' / args.name
out.mkdir(parents=True, exist_ok=True)
for d in ('cfg', 'snap', 'state', 'nvram'):
    (out / d).mkdir(exist_ok=True)
(out / 'cfg' / f'{args.machine}.cfg').write_text(
    f'<mameconfig version="10"><system name="{args.machine}"><input>'
    f'<port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="{args.accelerator}"/>'
    f'<port tag=":j13_config" type="CONFIG" mask="1" defvalue="0" value="{j13_config & 1}"/>'
    f'<port tag=":j13_config" type="CONFIG" mask="2" defvalue="0" value="{j13_config & 2}"/>'
    f'<port tag=":bus_timing" type="CONFIG" mask="6" defvalue="6" value="{(8,16,32,64).index(args.cache)*2}"/>'
    f'<port tag=":bus_timing" type="CONFIG" mask="1024" defvalue="0" value="{1024 if args.card=="tw" else 0}"/>'
    f'<port tag=":bus_timing" type="CONFIG" mask="2048" defvalue="0" value="{2048 if args.card=="tw" and args.cache==32 else 0}"/></input></system></mameconfig>')


def lua_key(name):
    field = KEYS.get(name, f'{name.lower()}  {name.upper()}' if len(name) == 1 else name)
    return field


steps = []
for item in filter(None, (s.strip() for s in args.steps.split(';'))):
    kind, _, arg = item.partition('=')
    if kind == 'key':
        steps.append(('key', lua_key(arg), 0.12))
    elif kind == 'hold':
        name, secs = arg.split(',')
        steps.append(('key', lua_key(name), float(secs)))
    elif kind == 'wait':
        steps.append(('wait', int(arg)))
    elif kind == 'sleep':
        steps.append(('sleep', float(arg)))
    elif kind == 'snap':
        steps.append(('snap', arg))
    elif kind == 'poke':
        a, v = arg.split(',')
        steps.append(('poke', int(a, 0), int(v, 0)))
    elif kind == 'poke16':
        a, v = arg.split(',')
        steps.append(('poke16', int(a, 0), int(v, 0)))
    elif kind == 'mark':
        steps.append(('mark', arg))
    elif kind == 'call':
        steps.append(('call', arg))
    elif kind == 'waitframes':
        steps.append(('waitframes', int(arg)))
    elif kind == 'waitmem':
        a,v=arg.split(',')
        steps.append(('waitmem',int(a,0),int(v,0)))
    elif kind == 'peek':
        a, n = arg.split(',')
        steps.append(('peek', int(a, 0), int(n, 0)))
    elif kind == 'eject':
        steps.append(('eject', int(arg)))
    elif kind == 'status':
        steps.append(('status', int(arg)))
    elif kind == 'insert':
        n, f = arg.split(',', 1)
        steps.append(('insert', int(n), f))
    elif kind == 'pc':
        steps.append(('pc',))
    elif kind == 'trace':
        steps.append(('trace', int(arg)))
    elif kind == 'end':
        steps.append(('end',))
    else:
        raise SystemExit('unknown step ' + item)


def lua_step(s):
    if s[0] == 'key':
        return '{k="key",f=%r,d=%s}' % (s[1], s[2])
    if s[0] == 'waitmem':
        return '{k="waitmem",a=%d,v=%d}' % (s[1],s[2])
    if s[0] == 'wait':
        return '{k="wait",n=%d}' % s[1]
    if s[0] == 'sleep':
        return '{k="sleep",d=%s}' % s[1]
    if s[0] == 'snap':
        return '{k="snap",f=%r}' % s[1]
    if s[0] == 'poke':
        return '{k="poke",a=%d,v=%d}' % (s[1], s[2])
    if s[0] == 'poke16':
        return '{k="poke16",a=%d,v=%d}' % (s[1], s[2])
    if s[0] == 'mark':
        return '{k="mark",n=%r}' % s[1]
    if s[0] == 'call':
        return '{k="call",n=%r}' % s[1]
    if s[0] == 'waitframes':
        return '{k="waitframes",n=%d}' % s[1]
    if s[0] == 'peek':
        return '{k="peek",a=%d,n=%d}' % (s[1], s[2])
    if s[0] == 'eject':
        return '{k="eject",t=":fdc:%d:35dd"}' % (s[1] - 1)
    if s[0] == 'status':
        return '{k="status",t=":fdc:%d:35dd"}' % (s[1] - 1)
    if s[0] == 'insert':
        return '{k="insert",t=":fdc:%d:35dd",f=%r}' % (s[1] - 1, s[2])
    if s[0] == 'pc':
        return '{k="pc"}'
    if s[0] == 'trace':
        return '{k="trace",n=%d}' % s[1]
    return '{k="end"}'


lua = r'''
local cpu=manager.machine.devices[":maincpu"]
local mem=cpu.spaces["program"]
local screen=manager.machine.screens[":screen"]
CALLS=CALLS or {}
local steps={%s}
local idx=1
local stepStart=nil
local held=nil
local function field(name)
  for _,p in pairs(manager.machine.ioport.ports) do for _,f in pairs(p.fields) do if f.name==name then return f end end end
  error("missing key "..name)
end
local function now() return manager.machine.time:as_double() end
emu.register_frame_done(function()
  local t=now()
  if %s and t<5000 then mem:write_u16(0x3e8,0x5a5a) end
  if t>%d then
    print(string.format("TIMEOUT at step %%d screen %%d PC %%06x",idx,mem:read_u8(0x3e4),cpu.state.PC.value))
    screen:snapshot('timeout.png');manager.machine:exit();return
  end
  -- keep the test latch that skips the front end clear: this run wants it
  local s=steps[idx]
  if not s then manager.machine:exit() return end
  if not stepStart then stepStart=t end
  if s.k=="wait" then
    if mem:read_u8(0x3e4)==s.n then print(string.format("WAIT %%d ok at %%.3f",s.n,t)); idx=idx+1; stepStart=nil end
  elseif s.k=="waitmem" then
    if mem:read_u8(s.a)==s.v then print(string.format("WAITMEM %%x=%%d at %%.3f",s.a,s.v,t));idx=idx+1;stepStart=nil end
  elseif s.k=="sleep" then
    if t-stepStart>=s.d then idx=idx+1; stepStart=nil end
  elseif s.k=="key" then
    if not held then field(s.f):set_value(1); held=true
    elseif t-stepStart>=s.d then field(s.f):set_value(0); held=nil; idx=idx+1; stepStart=nil end
  elseif s.k=="snap" then
    screen:snapshot(s.f..".png"); print(string.format("SNAP %%s at %%.3f",s.f,t)); idx=idx+1; stepStart=nil
  elseif s.k=="poke" then
    mem:write_u8(s.a,s.v); idx=idx+1; stepStart=nil
  elseif s.k=="poke16" then
    mem:write_u16(s.a,s.v); idx=idx+1; stepStart=nil
  elseif s.k=="mark" then
    print(string.format("MARK %%.4f %%s",t,s.n)); idx=idx+1; stepStart=nil
  elseif s.k=="call" then
    if CALLS[s.n]()~=false then idx=idx+1; stepStart=nil end
  elseif s.k=="waitframes" then
    local f=mem:read_u16(FRAMEADDR)
    if not s.f0 then s.f0=f end
    if ((f-s.f0)&65535)>=s.n then idx=idx+1; stepStart=nil end
  elseif s.k=="peek" then
    local b={}; for i=0,s.n-1 do b[#b+1]=string.format("%%02x",mem:read_u8(s.a+i)) end
    print(string.format("PEEK %%x: %%s",s.a,table.concat(b," "))); idx=idx+1; stepStart=nil
  elseif s.k=="trace" then
    local st=cpu.state
    print(string.format("T %%.3f PC %%06x DB=%%02x S=%%04x D=%%04x A=%%04x P=%%02x", t, st.PC.value, st.DB.value, st.S.value, st.D.value, st.A.value, st.P.value))
    s.n=s.n-1; if s.n<=0 then idx=idx+1; stepStart=nil end
  elseif s.k=="eject" then
    manager.machine.images[s.t]:unload(); print("EJECT "..s.t); idx=idx+1; stepStart=nil
  elseif s.k=="status" then
    local im=manager.machine.images[s.t]; print("DRIVE "..s.t.." exists="..tostring(im.exists).." file="..tostring(im.filename)); idx=idx+1; stepStart=nil
  elseif s.k=="insert" then
    local r=manager.machine.images[s.t]:load(s.f); print("INSERT "..s.t.." "..tostring(r)); idx=idx+1; stepStart=nil
  elseif s.k=="pc" then
    local st=cpu.state
    print(string.format("PC %%06x PB=%%02x DB=%%02x S=%%04x D=%%04x A=%%04x X=%%04x Y=%%04x P=%%02x", st.PC.value, st.PB.value, st.DB.value, st.S.value, st.D.value, st.A.value, st.X.value, st.Y.value, st.P.value)); idx=idx+1; stepStart=nil
  elseif s.k=="end" then manager.machine:exit() end
end)
''' % (',\n'.join(lua_step(s) for s in steps), 'true' if args.skip else 'false', args.seconds)
if args.check_floor is not None:
    lua = lua.replace('local screen=', 'local s=mem\n'+floor_capture.lua(out, floor=args.check_floor, trigger=0x3f0, value=2)+'\nlocal screen=', 1)
if args.lua:
    lua += '\n' + args.lua.read_text()
lua_guard.write(out / 'ui.lua', lua)
disk = out / ('wolf-hd.po' if args.hd else 'disk1.po')   # the run writes saves here, not to the build
if args.hd:
    source_disk = (args.disk or ROOT/'build/wolf-hd.po').resolve()
    media_out = out/'media' if source_disk.parent == out.resolve() else out
    media_out.mkdir(exist_ok=True)
    media, _ = test_media.prepare(source_disk, media_out, args.disk2)
else:
    shutil.copyfile(args.disk or ROOT/'build/disk1.po', disk)
    media = ['-flop3', str(disk)]
cmd = ['nice', '-n', '20', MAME, args.machine, '-rompath', mame_kit.ROMPATH,
       '-ramsize', args.ramsize or ram_size(args.machine)] + media + ['-video', 'none', '-sound', 'none', '-nothrottle',
       '-skip_gameinfo', '-seconds_to_run', str(args.seconds + 5), '-autoboot_delay', '0',
       '-autoboot_script', str(out / 'ui.lua'), '-cfg_directory', str(out / 'cfg'), '-state_directory', str(out / 'state'),
       '-nvram_directory', str(out / 'nvram'), '-snapshot_directory', str(out / 'snap')]
if args.debug:
    cmd += ['-debug', '-debugger', 'none']
if args.disk2 and not args.hd:
    cmd += ['-flop4', str(args.disk2)]
if args.audio:
    cmd += ['-wavwrite', str(out / 'audio.wav')]
env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
with (out / 'mame.log').open('w') as log:
    p = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        p.wait(timeout=args.seconds * 2 + 120)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        print('killed after the wall clock limit')
log_text = (out / 'mame.log').read_text()
print(log_text[-2500:])
if p.returncode or 'TIMEOUT at step' in log_text:
    raise SystemExit('UI route did not complete')
if args.check_floor is not None and re.findall(r'^ASSETS_DONE (\d+)(?: \d+)?$',log_text,re.M) != ['0']:
    raise SystemExit('Native floor assets did not match')
snaps = sorted((out / 'snap').glob('*.png'))
print('snapshots:', [str(s) for s in snaps])
