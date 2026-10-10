"""Phase shares for one timedemo, matching the views slow-frame method.

A frame runs from one frame-done marker ($3F0 written 2) to the next. Paint,
cast, visibility, and sprite preparation are the game's own markers. Logic/tic
is the recorded demo's player, doors and actors, divided by 4. The HUD
is the UpdateHUD called from the frame loop. Sound IRQ is inputIrq through
rti, taken out of the phase it interrupted, bracketed by debugger breakpoints
on inputIrq and its rti. Other is the remainder, which is PlaySound plus the
frame glue. The run writes the demo request and title-skip latches.
--patch-menu supports frozen images without the title-skip interface by
patching an isolated media copy; it does not modify source files.
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from elf import read
from mame_target import ram_size
import test_media
import logic_observer
import lua_guard
import mame_kit

ROOT = Path(__file__).resolve().parents[1]
MAME = Path(mame_kit.BINARY)
ROMS = mame_kit.ROMPATH

LUA = memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local requested, active = false, false
local frames, origin = 0, nil
local phase, stamp = "gap", 0
local acc = {paint=0, cast=0, logic=0, vis=0, sprites=0, hud=0, irq=0, gap=0}
local inIrq, irqAt = false, 0
local irqFx, irqMus = 0, 0
local irqSawFx = false
local psAt, psBytes, psId, psCount = nil, 0, -1, 0
local ramWrites, irqRam = 0, 0
local ctl = 0
local hudAt, bootNote = nil, 0
local function now() return manager.machine.time:as_double() end
local function add(dt)
  if dt<0 then dt=0 end
  if inIrq then acc.irq=acc.irq+dt
  else acc[phase]=acc[phase]+dt end
end
local function close(t)
  add(t-stamp); stamp=t
end
local function setphase(name)
  local t=now(); close(t); phase=name
end
for _,name in ipairs({"a2_config","bus_timing","ram_start","ram_seed"}) do
  local port=manager.machine.ioport.ports[":"..name]
  if port then print("SETTING "..name.." "..port:read()) end
end
local taps={}
local function tap(kind,a,b,name,fn)
  local h=kind=="w" and s:install_write_tap(a,b,name,fn) or s:install_read_tap(a,b,name,fn)
  taps[#taps+1]=h
end
-- A tap can be dropped when the memory map changes. An address space change notifier would reinstall it at once,
-- but its listener outlives the Lua state and crashes MAME at exit; the frame notifier reinstalls the taps once a frame.
FRAMESUB=emu.add_machine_frame_notifier(function()
  for _,h in ipairs(taps) do h:reinstall() end
end)
tap("w",@MM:SOUNDCTL@,@MM:SOUNDCTL@,"glu-ctl",function(a,d,m) ctl=d&255 end)
tap("w",@MM:SOUNDDATA@,@MM:SOUNDDATA@,"glu-data",function(a,d,m)
  if (ctl&64)==0 then return end
  ramWrites=ramWrites+1
  if inIrq then irqRam=irqRam+1
  elseif psAt then psBytes=psBytes+1 end
end)
tap("w",0x3f4,0x3f4,"irq-bracket",function(a,d,m)
  local t=now()
  if d==1 and not inIrq then
    close(t); inIrq=true; irqAt=t; irqSawFx=false
  elseif d==2 and inIrq then
    local dt=t-irqAt
    acc.irq=acc.irq+dt
    if irqSawFx then irqFx=irqFx+dt else irqMus=irqMus+dt end
    inIrq=false; stamp=t
  end
end)
tap("r",FXREFILL,FXREFILL,"fx-refill",function(a,d,m)
  if inIrq then irqSawFx=true end
end)
tap("r",FXEND,FXEND,"fx-end",function(a,d,m)
  if inIrq then irqSawFx=true end
end)
tap("r",PLAY,PLAY,"play-enter",function(a,d,m)
  if psAt then return end
  psAt=now(); psBytes=0; psId=s:read_u16(SFXEVENT); psCount=psCount+1
end)
tap("r",PLAYRTL,PLAYRTL,"play-leave",function(a,d,m)
  if not psAt then return end
  psAt=nil
end)
tap("r",HUD,HUD,"hud-enter",function(a,d,m)
  if origin and phase=="gap" and not inIrq and hudAt==nil then setphase("hud"); hudAt=true end
end)
tap("r",HUDRET1,HUDRET1,"hud-leave-a",function(a,d,m)
  if hudAt then setphase("gap"); hudAt=nil end
end)
tap("r",HUDRET2,HUDRET2,"hud-leave-b",function(a,d,m)
  if hudAt then setphase("gap"); hudAt=nil end
end)
local function onLogicPhase(d)
  if not origin then return end
  if d==1 then setphase("logic")
  elseif d==3 then setphase("vis")
  elseif d==5 or d==6 then setphase("gap") end
end
@LOGIC_TAPS@
tap("w",0x3f2,0x3f2,"cast-phase",function(a,d,m)
  if not origin then return end
  if d==1 then setphase("cast") elseif d==2 then setphase("sprites") end
end)
tap("w",0x3f3,0x3f3,"paint-phase",function(a,d,m)
  if not origin then return end
  if d==1 then setphase("paint") elseif d==2 then setphase("gap") end
end)
local function report(t)
  close(t)
  hudAt=nil
  local total=t-origin
  local logic=acc.logic
  local other=total-(acc.paint+acc.cast+logic+acc.vis+acc.sprites+acc.hud+acc.irq)
  if other<0 then other=0 end
  print(string.format("SHARE %d %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f %d %d %d %d %.3f %.3f",
    frames+1, total*1000, acc.paint*1000, acc.cast*1000, (logic/4)*1000, acc.vis*1000,
    acc.sprites*1000, acc.hud*1000, acc.irq*1000, other*1000,
    psId, psCount, psBytes, irqRam, irqFx*1000, irqMus*1000))
  io.stdout:flush()
  acc={paint=0, cast=0, logic=0, vis=0, sprites=0, hud=0, irq=0, gap=0}
  irqFx, irqMus, ramWrites, irqRam, psBytes, psCount, psId = 0, 0, 0, 0, 0, 0, -1
  phase="gap"
end
tap("w",0x3f7,0x3f7,"demo-packet",function(a,d,m)
  if active and d==1 and not origin then
    origin=now(); stamp=origin; phase="gap"; hudAt=nil; inIrq=false
    acc={paint=0, cast=0, logic=0, vis=0, sprites=0, hud=0, irq=0, gap=0}
    irqFx, irqMus, ramWrites, irqRam, psBytes, psCount, psId = 0, 0, 0, 0, 0, 0, -1
  end
end)
tap("w",0x3f0,0x3f0,"frame",function(a,d,m)
  if d==1 and not requested then
    requested=true
    s:write_u8(0x3e1,VIEW)
    s:write_u8(0x3e3,1)
    s:write_u8(0x3e2,DEMO+1)
    print(string.format("REQUESTED %.0f", now()))
    io.stdout:flush()
  elseif d==2 and active and origin then
    local t=now()
    report(t); frames=frames+1
    origin=t; stamp=t; phase="gap"
    if frames>=UNTIL then
      print(string.format("DONE %d", frames))
      print(string.format("REFRESH %.6f", 1/manager.machine.screens[":screen"].frame_period))
      manager.machine:exit()
    end
  end
end)
tap("w",0x3f5,0x3f5,"demo-state",function(a,d,m)
  if d==1 then
    active=true
    print(string.format("ACTIVE %.0f", now()))
    io.stdout:flush()
  elseif d==2 and active then
    print(string.format("DONE %d", frames))
    print(string.format("REFRESH %.6f", 1/manager.machine.screens[":screen"].frame_period))
    manager.machine:exit()
  elseif d==3 and requested then
    print("ERROR demo unavailable")
    manager.machine:exit()
  end
end)
manager.machine.debugger:command('focus :maincpu')
manager.machine.debugger:command('bpset @IRQ@,1,{do b@3f4=1;go}')
manager.machine.debugger:command('bpset @IRQEND@,1,{do b@3f4=2;go}')
emu.register_frame_done(function()
  if not requested then s:write_u16(0x3e8,0x5a5a) end
  local t=manager.machine.time:as_double()
  if not origin and t-bootNote>=30 then
    bootNote=t
    print(string.format("BOOT %.0f pc=%02x:%04x skip=%04x f0=%02x f5=%02x e1=%02x e2=%02x e3=%02x site=%02x%02x",
      t, cpu.state.PB.value, cpu.state.PC.value, s:read_u16(0x3e8),
      s:read_u8(0x3f0), s:read_u8(0x3f5), s:read_u8(0x3e1), s:read_u8(0x3e2), s:read_u8(0x3e3),
      s:read_u8(@MM:MENU+0x2725@), s:read_u8(@MM:MENU+0x2726@)))
    io.stdout:flush()
  end
  if t>LIMIT then
    print(string.format("ERROR time limit after %d demo frames at %02x:%04x", frames, cpu.state.PB.value, cpu.state.PC.value))
    manager.machine:exit()
  end
end)
''')


# lda long:UI_SKIP / cmp #$5A5A / bne bootMenu, at $3F8B1E in a raw segment.
MENU_BNE = bytes.fromhex('afe80300c95a5ad015')


def patch_menu_skip(image):
    """NOP MenuBoot's title branch in a private disk copy. Never the source."""
    image = Path(image)
    if image.resolve() == (ROOT / 'build/wolf-hd.po').resolve():
        raise SystemExit('refusing to patch the source disk')
    data = bytearray(image.read_bytes())
    hits = []
    start = 0
    while True:
        found = data.find(MENU_BNE, start)
        if found < 0:
            break
        hits.append(found)
        start = found + 1
    if len(hits) != 1:
        raise SystemExit(f'menu skip signature hits {len(hits)} in {image}')
    off = hits[0]
    if data[off + 7:off + 9] != b'\xd0\x15':
        raise SystemExit(f'menu skip bytes at {off} are not D0 15')
    hdr = 512
    if data[hdr:hdr + 6] != b'WOLFGS':
        raise SystemExit(f'{image} is not a Wolf disk')
    nseg = int.from_bytes(data[hdr + 8:hdr + 10], 'little')
    block = off // 512
    home = None
    for i in range(nseg):
        ent = hdr + 16 + i * 8
        addr = int.from_bytes(data[ent:ent + 3], 'little')
        flags = data[ent + 3]
        first = int.from_bytes(data[ent + 4:ent + 6], 'little')
        count = int.from_bytes(data[ent + 6:ent + 8], 'little')
        if first <= block < first + count:
            home = (i, addr, flags, first, count)
            break
    if home is None:
        raise SystemExit(f'menu skip at {off} is not inside a segment')
    seg, addr, flags, first, count = home
    if flags & 0x3:
        raise SystemExit(f'menu skip is in segment {seg} flags {flags:#x}, not a raw segment')
    data[off + 7:off + 9] = b'\xea\xea'
    image.write_bytes(data)
    ram = addr + (block - first) * 512 + (off % 512)
    print(f'menu skip patched {image.name} off {off} seg {seg} ram {ram:#x}', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('disk', type=Path)
    ap.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf', help='ELF matching the profiled disk, including frozen builds')
    ap.add_argument('--demo', type=int, choices=range(4), default=0)
    ap.add_argument('--view', type=int, choices=(160, 214, 240, 320), default=214)
    ap.add_argument('--until', type=int, default=930)
    ap.add_argument('--limit', type=int, default=500)
    ap.add_argument('--host-limit', type=int, default=420)
    ap.add_argument('--machine', default='apple2gsr1')
    ap.add_argument('--seed', type=int, help='explicit diagnostic RAM pattern; stock startup by default')
    ap.add_argument('--patch-menu', action='store_true', help='old worker fixture: patch only the private media copy')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    disk = args.disk.resolve(strict=True)
    elf = args.elf.resolve(strict=True)
    segments, sym = read(elf)
    def hud_return(start):
        pc=sym[start]
        segment=next(x for x in segments if x['address']<=pc<x['address']+len(x['data']))
        offset=pc-segment['address']
        end=sym['runLogic' if start=='liveFinish' else 'renderFrame']
        body=segment['data'][offset:offset+end-pc]
        call=b'\x20'+(sym['UpdateHUD']&65535).to_bytes(2,'little')
        assert body.count(call)==1,(start,'HUD call not found')
        return pc+body.index(call)+3
    out = args.out or (ROOT / 'build/tests' / f'sfx-share-d{args.demo}-v{args.view}')
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'profile-build.json').write_text(json.dumps(dict(
        disk=str(disk), disk_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(),
        elf=str(elf), elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        demo=args.demo, view=args.view, seed=args.seed, patch_menu=args.patch_menu,
        timing='Traced phase shares are diagnostic; IRQ phase can differ from untraced timedemo.'
    ), indent=2)+'\n')
    cfg = out / 'cfg'
    cfg.mkdir(exist_ok=True)
    ports = [('a2_config', 7, 0, 0), ('bus_timing', 1, 1, 1)]
    if args.seed is not None:ports += [('ram_start', 7, 4, 5), ('ram_seed', 0xffffffff, 0, args.seed)]
    (cfg / (args.machine + '.cfg')).write_text(
        '<mameconfig version="10"><system name="%s"><input>%s</input></system></mameconfig>' %
        (args.machine, ''.join(
            '<port tag=":%s" type="CONFIG" mask="%d" defvalue="%d" value="%d"/>' % p for p in ports)))
    script = (LUA.replace('VIEW', str({160: 1, 214: 2, 240: 3, 320: 4}[args.view]))
              .replace('DEMO', str(args.demo)).replace('LIMIT', str(args.limit))
              .replace('UNTIL', str(args.until))
              .replace('FXREFILL', str(sym['EffectRefill'])).replace('FXEND', str(sym['EffectBufferEnd']))
              .replace('PLAYRTL', str(sym['effectReturn'])).replace('PLAY', str(sym['PlaySound']))
              .replace('SFXEVENT', str(sym['sfxEvent'])).replace('HUDRET1', str(hud_return('liveFinish')))
              .replace('HUDRET2', str(hud_return('runLogic'))).replace('HUD', str(sym['UpdateHUD']))
              .replace('@IRQEND@', format(sym['inputIrqEnd'], 'x'))
              .replace('@IRQ@', format(sym['inputIrq'], 'x')))
    script=script.replace('@LOGIC_TAPS@',logic_observer.taps(sym,'logic','onLogicPhase',handle='soundLogic'))
    lua_guard.write(out / 'run.lua', script)
    media, swaps = test_media.prepare(disk, out)
    copy = out / disk.name
    if args.patch_menu and copy.stat().st_size > 800 * 1024:
        patch_menu_skip(copy)
        record = json.loads((out / 'media.json').read_text())
        for item in record:
            if Path(item['file']).resolve() == copy.resolve():
                item['sha256'] = hashlib.sha256(copy.read_bytes()).hexdigest()
        (out / 'media.json').write_text(json.dumps(record, indent=2) + '\n')
    if swaps:
        lua_guard.write(out / 'run.lua', script + '\n' + swaps)
    (out / 'debug.txt').write_text(
        'focus :maincpu\nbpset %x,1,{do b@3f4=1;go}\nbpset %x,1,{do b@3f4=2;go}\ngo\n'
        % (sym['inputIrq'], sym['inputIrqEnd']))
    cmd = ['nice', '-n', '20', str(MAME), args.machine, '-rompath', ROMS, '-ramsize', ram_size(args.machine),
           *media, '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo',
           '-seconds_to_run', str(args.limit + 20), '-autoboot_delay', '0',
           '-autoboot_script', str(out / 'run.lua'), '-cfg_directory', str(cfg),
           '-state_directory', str(out / 'state'), '-nvram_directory', str(out / 'nvram'),
           '-snapshot_directory', str(out / 'snap'),
           '-debug', '-debugger', 'none', '-debugscript', str(out / 'debug.txt')]
    live = subprocess.run(['pgrep', '-fl', '/iigs.app/Contents/MacOS/iigs'],
                          capture_output=True, text=True, check=False).stdout.splitlines()
    if any(str(ROOT / 'build/tests') in line for line in live):
        raise SystemExit('A MAME process for this checkout is already running')
    (out / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
    with (out / 'mame.log').open('w') as log:
        process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=args.host_limit)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                    process.wait()
    text = (out / 'mame.log').read_text(errors='replace')
    rows = []
    for m in re.finditer(r'^SHARE (\d+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) (-?\d+) (\d+) (\d+) (\d+) ([\d.]+) ([\d.]+)$', text, re.M):
        keys = ('frame', 'total', 'paint', 'cast', 'logic', 'vis', 'sprites', 'hud', 'irq', 'other',
                'sound', 'starts', 'play_bytes', 'irq_bytes', 'irq_fx', 'irq_mus')
        vals = m.groups()
        row = {k: (int(v) if k in ('frame', 'sound', 'starts', 'play_bytes', 'irq_bytes') else float(v))
               for k, v in zip(keys, vals)}
        rows.append(row)
    (out / 'shares.json').write_text(json.dumps(rows, indent=2) + '\n')
    done = re.findall(r'^DONE (\d+)$', text, re.M)
    errors = re.findall(r'^ERROR (.*)$', text, re.M)
    print(f'rows {len(rows)} done {done} errors {errors} exit {process.returncode} log {out/"mame.log"}')
    if errors or not done or process.returncode or 'Lua error' in text:
        raise SystemExit('share run did not finish')


if __name__ == '__main__':
    main()
