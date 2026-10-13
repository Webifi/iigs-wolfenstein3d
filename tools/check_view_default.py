"""The first view size from the hidden speed test (src/iigs/viewdef.s), in MAME.

Each case boots a private copy of build/wolf-hd.po with one WOLF.SETTINGS block and one CPU model, and an
observer script prints VD lines: the test (time, flags, counts, kind, size), the screen sum before and
after it, the time of MenuBoot, LoadSettings, the PG-13 page and the start of the title song, and the view
the game holds at the end. A case can press keys (steps), then the tool reads the settings block back from
the disk copy.

Models: stock (apple2gsr1, 4352K), stock-rom3 (apple2gs, 5M), zip16 (16 MHz ZipGS, 32 KB cache), twgs14
(14 MHz TransWarp GS), twgs14-rom3, the slower cards zip7, zip8, zip12, twgs7 and twgs10, which show the
margin of the limit, and native16 (fast RAM with no wait).

MAME is the kit named in tools/mame_kit.py. The script starts with the guard of tools/lua_guard.py, which keeps and
removes every tap at machine stop. A case also fails on a MAME exit code other than 0 and on a new crash report with
the process id of its MAME.

  check_view_default.py --list
  check_view_default.py [--only CASE ...] [--elf build/wolf.elf] [--disk build/wolf-hd.po] [--prefix vd]
  check_view_default.py --only fresh-stock --count-only    (no expectations: for a build without the test)

Needs a finished build. Runs one MAME process at a time. build/tests/PREFIX-CASE has the logs and the disk copy;
build/tests/PREFIX-view-default.json lists the numbers.
"""
import memmap
import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

from elf import read
import lua_guard
import mame_kit

REPORTS = Path.home() / 'Library/Logs/DiagnosticReports'   # where macOS writes the crash reports of MAME

ROOT = Path(__file__).resolve().parents[1]
MAME = mame_kit.BINARY
ROMS = mame_kit.ROMPATH
SETTINGS_IN = 0x7c00            # frontend.inc
S_VIEW, S_SHADE, S_KEYS, S_SUM = 12, 13, 32, 8
S_PAINT, S_WALLS = 29, 58
NOTSET = 255
KEYS = {'Return': 'Return', 'Esc': 'Esc', 'Down': 'Down Arrow', 'Up': 'Up Arrow', 'Left': 'Left Arrow',
        'Right': 'Right Arrow', 'Space': 'Space', 'Minus': '-  _', 'Equals': '=  +',
        'F2': 'F2', 'Home': 'Home', 'A': 'a  A'}

# (tag, mask, default, value) lines of the MAME cfg: a2_config is the CPU type, bus_timing the cache and the card.
MODELS = {
    'stock': [('a2_config', 7, 0, 0)],
    'zip16': [('a2_config', 7, 0, 7), ('bus_timing', 6, 6, 4)],
    'twgs14': [('a2_config', 7, 0, 7), ('bus_timing', 6, 6, 4), ('bus_timing', 1024, 0, 1024),
               ('bus_timing', 2048, 0, 2048), ('bus_timing', 458752, 0, 196608), ('twgs_rom', 1, 0, 1)],
    'stock-rom3': [('a2_config', 7, 0, 0)],
    'twgs14-rom3': [('a2_config', 7, 0, 7), ('bus_timing', 6, 6, 4), ('bus_timing', 1024, 0, 1024),
                    ('bus_timing', 2048, 0, 2048), ('bus_timing', 458752, 0, 196608), ('twgs_rom', 1, 0, 1)],
    'native16': [('a2_config', 7, 0, 7), ('bus_timing', 6, 6, 4), ('bus_timing', 8192, 0, 8192)],   # 16 MHz fast RAM with no wait (not a real card)
    # the slower cards, for the margin of the limit
    'zip7': [('a2_config', 7, 0, 1), ('bus_timing', 6, 6, 0)],                      # 7 MHz ZipGS, 8 KB
    'zip8': [('a2_config', 7, 0, 3), ('bus_timing', 6, 6, 2)],                      # 8 MHz ZipGS, 16 KB
    'zip12': [('a2_config', 7, 0, 5), ('bus_timing', 6, 6, 4)],                     # 12 MHz ZipGS, 32 KB
    'twgs7': [('a2_config', 7, 0, 1), ('bus_timing', 1024, 0, 1024), ('twgs_rom', 1, 0, 1)],   # 7 MHz TransWarp GS, 8 KB
    'twgs14noirq': [('a2_config', 7, 0, 7), ('bus_timing', 6, 6, 4), ('bus_timing', 1024, 0, 1024),
                    ('bus_timing', 2048, 0, 2048), ('bus_timing', 4096, 0, 4096), ('bus_timing', 458752, 0, 196608),
                    ('twgs_rom', 1, 0, 1)],                                   # 14 MHz, IRQ slowdown off
    'twgs10': [('a2_config', 7, 0, 7), ('bus_timing', 1024, 0, 1024), ('bus_timing', 458752, 0, 327680),
               ('twgs_rom', 1, 0, 1)],                                              # 10 MHz TransWarp GS, 8 KB
}

# ROM 03 models: the machine and the RAM size (the others are apple2gsr1 with 4352K)
MACHINES = {'stock-rom3': ('apple2gs', '5M'), 'twgs14-rom3': ('apple2gs', '5M')}

# Options (screen 7) from the main menu (screen 2): Save Game is off before a game, so Options is two rows down.
# Display & Sound (screen17): View Size2, Depth Shading3; root Options Save Settings3.
TO_OPTIONS = ['wait=1', 'sleep=1', 'key=Esc', 'wait=2', 'sleep=1', 'key=Down', 'sleep=0.3', 'key=Down', 'sleep=0.3',
              'key=Return', 'wait=7', 'key=Return', 'wait=17', 'sleep=1', 'snap=options']
SAVE_ROOT = ['key=Esc', 'wait=7'] + ['key=Down', 'sleep=0.3'] * 3
SAVE = ['sleep=0.5', 'snap=before-save', 'key=Return', 'sleep=8', 'snap=after-save']
# Start a new game, then wait for completed frames before changing view.
NEW_GAME = ['wait=1', 'sleep=1', 'key=Esc', 'wait=2', 'sleep=1', 'key=Return', 'wait=15', 'sleep=0.5', 'key=Return', 'wait=3', 'sleep=0.5', 'key=Return',
            'wait=0', 'waitframes=2']
# F2 opens Save Game independently of the remembered main-menu row.
SAVE_GAME = ['key=F2', 'wait=4', 'sleep=1', 'key=Home', 'snap=slots',
             'key=Return', 'sleep=1', 'key=A', 'key=Return', 'sleep=12', 'snap=after-save', 'end=']
FLOWS = {
    # a key goes down while the test runs (an ADB interrupt inside the loops); nothing else is pressed
    'inject': [],
    # Start the probe with I set to exercise the emulator's interrupt-related speed policy.
    'seiflag': [],
    # a game saved with no size picked: the size stays not set
    'savegame': NEW_GAME + SAVE_GAME,
    # the = key in play (3/4), then a game saved: the size is stored
    'savegamekeys': NEW_GAME + ['key=Equals', 'waitframes=2'] + SAVE_GAME,
    # a size picked: Full (two Right keys from 2/3), then Save Settings
    'pick': TO_OPTIONS + ['key=Down', 'sleep=0.3', 'key=Down', 'sleep=0.3', 'key=Right', 'sleep=0.3', 'key=Right',
                          'sleep=0.5', 'snap=picked'] + SAVE_ROOT + SAVE + ['end='],
    # a size picked on a fast machine: Two Thirds (one Left key from 3/4), then Save Settings
    'pickdown': TO_OPTIONS + ['key=Down', 'sleep=0.3', 'key=Down', 'sleep=0.3', 'key=Left',
                              'sleep=0.5', 'snap=picked'] + SAVE_ROOT + SAVE + ['end='],
    # depth shading changed, no size: Save Settings must keep the size not set
    'shade': TO_OPTIONS + ['key=Down', 'sleep=0.3'] * 3 + ['key=Right', 'sleep=0.5', 'snap=shade'] +
             SAVE_ROOT + SAVE + ['end='],
}

# name: (model, settings, flow, the case whose disk it boots, what must hold). The test must run (ran) when the
# settings name no size. size: what the test chose, view: weaponViewIndex at the end, disk: S_VIEW and S_SHADE of the
# settings block on the disk copy after the run (None: not a settings block of the game).
CASES = {
    'fresh-stock': ('stock', 'fresh', None, None, dict(ran=True, size=1, view=2)),
    'fresh-stock-rom3': ('stock-rom3', 'fresh', None, None, dict(ran=True, size=1, view=2)),
    'fresh-zip16': ('zip16', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'fresh-twgs14': ('twgs14', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    # The probe enables CPU IRQs even with I set on entry, restoring caller
    # flags afterward. The card's own configuration stays unchanged.
    'seiflag-twgs14': ('twgs14', 'fresh', 'seiflag', None, dict(ran=True, size=2, view=4, sei=True)),
    'seiflag-twgs14noirq': ('twgs14noirq', 'fresh', 'seiflag', None, dict(ran=True, size=2, view=4, sei=True)),
    'seiflag-zip16': ('zip16', 'fresh', 'seiflag', None, dict(ran=True, size=2, view=4, sei=True)),
    'inject-stock': ('stock', 'fresh', 'inject', None, dict(ran=True, size=1, view=2)),
    'inject-zip16': ('zip16', 'fresh', 'inject', None, dict(ran=True, size=2, view=4)),
    'fresh-native16': ('native16', 'fresh', None, None, dict(ran=True, size=3, view=6)),
    'fresh-zip7': ('zip7', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'fresh-zip8': ('zip8', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'fresh-zip12': ('zip12', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    # The 7 MHz band chooses 3/4; 10 MHz has A about equal to B and chooses full.
    'fresh-twgs7': ('twgs7', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'fresh-twgs10': ('twgs10', 'fresh', None, None, dict(ran=True, size=3, view=6)),
    'fresh-twgs14-rom3': ('twgs14-rom3', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'fresh-twgs14noirq': ('twgs14noirq', 'fresh', None, None, dict(ran=True, size=2, view=4)),
    'bad-stock': ('stock', 'bad', None, None, dict(ran=True, size=1, view=2)),
    'set-full-stock': ('stock', 3, None, None, dict(ran=False, view=6)),
    'set-half-stock': ('stock', 0, None, None, dict(ran=False, view=0)),
    'set-twothirds-zip16': ('zip16', 1, None, None, dict(ran=False, view=2)),
    'set-threequarters-twgs14': ('twgs14', 2, None, None, dict(ran=False, view=4)),
    'shade-stock': ('stock', 'fresh', 'shade', None, dict(ran=True, size=1, view=2, disk=(NOTSET, 0))),
    'shade-again-stock': ('stock', 'disk', None, 'shade-stock', dict(ran=True, size=1, view=2, shade=0)),
    'pick-stock': ('stock', 'fresh', 'pick', None, dict(ran=True, size=1, view=6, disk=(3, 1))),
    'pick-again-stock': ('stock', 'disk', None, 'pick-stock', dict(ran=True, size=1, view=6, shade=1)),
    'savegame-stock': ('stock', 'fresh', 'savegame', None, dict(ran=True, size=1, view=2, disk=(NOTSET, 1))),
    'savegame-again-stock': ('stock', 'disk', None, 'savegame-stock', dict(ran=True, size=1, view=2, shade=1)),
    'savegamekeys-stock': ('stock', 'fresh', 'savegamekeys', None, dict(ran=True, size=1, view=4, disk=(2, 1))),
    'savegamekeys-again-stock': ('stock', 'disk', None, 'savegamekeys-stock', dict(ran=True, size=1, view=4)),
    'pick-zip16': ('zip16', 'fresh', 'pickdown', None, dict(ran=True, size=2, view=2, disk=(1, 1))),
    'pick-again-zip16': ('zip16', 'disk', None, 'pick-zip16', dict(ran=True, size=2, view=2)),
}

OBSERVER = memmap.fill(r'''
local cpu = manager.machine.devices[":maincpu"]
local mem = cpu.spaces["program"]
local screen = manager.machine.screens[":screen"]
local S = @SYMS@
local steps = {@STEPS@}
local limit = @LIMIT@
local idx, stepStart, held = 1, nil, nil
local completedFrames = 0
mem:install_write_tap(0x3f0, 0x3f0, "vd-frames", function(o,d,m)
  if d == 2 then completedFrames = completedFrames + 1 end
end)
local musicAt, finished, booted, entered = nil, false, false, false
local inject, injectAt, injectKey = @INJECT@, nil, nil
local setI = @SETI@
local probeActive, stackMin, firmwareBefore = false, 65535, {}
local measuredA, measuredB = false, false
local cardWrites = 0
mem:install_write_tap(0xbc0000, 0xbcffff, "vd-card-writes", function(o,d,m)
  if probeActive then cardWrites = cardWrites + 1 end
end)
mem:install_write_tap(0x1200, 0x1fff, "vd-stack", function(o,d,m)
  if probeActive then stackMin = math.min(stackMin, o) end
end)
local function firmwareSum()
  local h = 0
  for a = 0xa00, 0xaff do h = (h * 33 + mem:read_u8(a)) & 0xffffffff end
  return h
end
print(string.format("VD_CONFIG cpu=%d bus=%d", manager.machine.ioport.ports[":a2_config"]:read(),
  manager.machine.ioport.ports[":bus_timing"]:read()))
local function now() return manager.machine.time:as_double() end
local function sum()
  local h = 0
  for a = @MM:SHR@, @MM:SHR_PAL+0x1ff@ do h = (h * 33 + mem:read_u8(a)) & 0xffffffff end
  return h
end
local function field(name)
  for _, p in pairs(manager.machine.ioport.ports) do for _, f in pairs(p.fields) do if f.name == name then return f end end end
  error("missing key " .. name)
end
local function exec(name, fn)
  local a = S[name]
  if not a then return end
  mem:install_read_tap(a, a, "vd-" .. name, function(addr, d, m)
    if cpu.state.PC.value == addr + 1 then fn() end
  end)
end
local function display(label)
  local painting = mem:read_u16(S.bufferOn)
  print(string.format("VD_%s view=%d sview=%d paint=%d spaint=%d walls=%d swalls=%d frames=%d width=%d wallpath=%d", label,
    mem:read_u16(S.weaponViewIndex), mem:read_u8(@SVIEW@), painting, mem:read_u8(@SVIEW@ + 17), mem:read_u16(S.wallPaintOn), mem:read_u8(@SVIEW@ + 46), completedFrames, mem:read_u16(S.viewWidth)*2,
    mem:read_u16(S.tightDispatch+1) == (S.wallPaintBridge & 65535) and 1 or 0))
end
local function final(why)
  if finished then return end
  finished = true
  local view = S.weaponViewIndex and mem:read_u16(S.weaponViewIndex) or -1
  local shade = S.columnLight and mem:read_u16(S.columnLight) or -1
  print(string.format("VD_FINAL t=%.4f why=%s view=%d sview=%d shade=%d", now(), why, view, mem:read_u8(@SVIEW@), shade))
  display("DISPLAY")
  manager.machine:exit()
end
exec("MenuBoot", function() booted = true; print(string.format("VD_MENUBOOT t=%.4f", now())) end)
exec("LoadSettings", function() print(string.format("VD_LOADSETTINGS t=%.4f", now())) end)
exec("PgPage", function() print(string.format("VD_PGPAGE t=%.4f", now())) end)
exec("ViewDefault", function()
  local st = cpu.state
  entered = true
  if setI then st.P.value = st.P.value | 4 end   -- an experiment: the test with the I flag set
  probeActive = true
  for a = 0xa00, 0xaff do firmwareBefore[a] = mem:read_u8(a) end
  print(string.format("VD_ENTRY t=%.4f P=0x%02x DB=0x%02x D=0x%04x S=0x%04x dp=0x%08x tw=0x%02x sum=0x%08x music=%d", now(), st.P.value, st.DB.value,
    st.D.value, st.S.value, firmwareSum(), mem:read_u8(0xbc0000), sum(), mem:read_u16(S.musicActive)))
  local returnPC = (mem:read_u16(st.S.value+1) + 1) & 65535
  returnPC = returnPC | (mem:read_u8(st.S.value+3) << 16)
  mem:install_read_tap(returnPC, returnPC, "vd-restored", function(o,d,m)
    if probeActive and st.PC.value == o+1 then
      local changed = 0
      for a = 0xa00, 0xaff do if firmwareBefore[a] ~= mem:read_u8(a) then changed = changed + 1 end end
      print(string.format("VD_RESTORED P=0x%02x DB=0x%02x D=0x%04x S=0x%04x dp=0x%08x tw=0x%02x stackmin=0x%04x dpbad=%d cardwrites=%d", st.P.value, st.DB.value,
        st.D.value, st.S.value-3, firmwareSum(), mem:read_u8(0xbc0000), stackMin, changed, cardWrites))
      probeActive = false
    end
  end)
end)
exec("vtBatchA", function()
  if not measuredA then
    print(string.format("VD_MEASURING tw=0x%02x P=0x%02x", mem:read_u8(0xbc0000), cpu.state.P.value))
    measuredA = true
  end
end)
exec("vtBatchB", function()
  if not measuredB then
    print(string.format("VD_MEASUREB tw=0x%02x P=0x%02x", mem:read_u8(0xbc0000), cpu.state.P.value))
    measuredB = true
  end
end)
if S.viewTestSize then
  mem:install_write_tap(S.viewTestSize + 1, S.viewTestSize + 1, "vd-exit", function(o, d, m)
    if not entered then return end   -- (the loader writes these bytes too)
    local size = (d & 0xff) * 256 + mem:read_u8(S.viewTestSize)
    print(string.format("VD_EXIT t=%.4f A=%d B=%d kind=%d size=%d sum=0x%08x music=%d", now(), mem:read_u16(S.viewTestA),
      mem:read_u16(S.viewTestB), mem:read_u16(S.viewTestKind), size, sum(), mem:read_u16(S.musicActive)))
  end)
end
emu.register_frame_done(function()
  local t = now()
  if finished then return end
  if inject and entered and not injectAt then   -- a key goes down while the test runs: an ADB interrupt
    injectKey = field(inject); injectKey:set_value(1); injectAt = t
    print(string.format("VD_INJECT t=%.4f", t))
  elseif injectAt and injectKey and t - injectAt >= 0.1 then
    injectKey:set_value(0); injectKey = nil
  end
  if t > limit then print("VD_TIMEOUT"); final("timeout"); return end
  if booted and not musicAt and mem:read_u16(S.musicActive) ~= 0 then   -- (before MenuBoot the RAM is not set yet)
    musicAt = t
    print(string.format("VD_MUSIC t=%.4f", t))
    display("BOOT")
  end
  local s = steps[idx]
  if not s then
    if musicAt and t - musicAt > 1.5 then final("music") end
    return
  end
  if not stepStart then stepStart = t end
  if s.k == "wait" then
    if mem:read_u8(0x3e4) == s.n then print(string.format("VD_WAIT %d t=%.4f", s.n, t)); idx = idx + 1; stepStart = nil end
  elseif s.k == "waitframes" then
    s.start = s.start or completedFrames
    if completedFrames - s.start >= s.n then idx = idx + 1; stepStart = nil end
  elseif s.k == "sleep" then
    if t - stepStart >= s.d then idx = idx + 1; stepStart = nil end
  elseif s.k == "key" then
    if not held then field(s.f):set_value(1); held = true
    elseif t - stepStart >= 0.12 then field(s.f):set_value(0); held = nil; idx = idx + 1; stepStart = nil end
  elseif s.k == "snap" then
    screen:snapshot(s.f .. ".png"); idx = idx + 1; stepStart = nil
  elseif s.k == "end" then
    final("steps")
  end
end)
''')


def cfg_xml(machine, model):
    ports = ''.join('<port tag=":%s" type="CONFIG" mask="%d" defvalue="%d" value="%d" />' % p for p in MODELS[model])
    return f'<mameconfig version="10"><system name="{machine}"><input>{ports}</input></system></mameconfig>'


def settings_block(view, symbols=None, good=True, paint=0, walls=2):
    """A valid WOLF.SETTINGS block (bytes 8-9 the sum of 12-495) with the view byte view."""
    block = bytearray(512)
    block[:8] = b'WOLFSET\x02'
    block[S_VIEW:S_VIEW + 4] = bytes((view, 1, 1, 5))
    block[S_KEYS:S_KEYS + 26] = bytes((0x0d, 0x3e, 0x01, 0x3d, 0x3b, 0x3c, 0x00, 0x02, 0x2b, 0x2f,
                                       0x31, 0x0e, 0x03, 0x36, 0x7e, 0x70, 0x3a, 0x37, 0x38, 0x39,
                                       0x5b, 0x57, 0x56, 0x58, 0x59, 0x5c))
    block[30] = 1
    block[S_PAINT] = paint
    block[S_WALLS] = walls
    struct.pack_into('<H', block, S_SUM, (sum(block[12:496]) + (0 if good else 1)) & 0xffff)
    return bytes(block)


def settings_offset(disk):
    data = disk.read_bytes()
    block = struct.unpack_from('<H', data, 512 + 436)[0]   # HDR_SETTINGS of the header in block 1
    assert 0 < block < len(data) // 512
    return block * 512


def steps_lua(steps):
    out = []
    for item in steps:
        kind, _, arg = item.partition('=')
        if kind == 'key':
            out.append('{k="key",f=%r}' % KEYS[arg])
        elif kind == 'waitframes':
            out.append('{k="waitframes",n=%d}' % int(arg))
        elif kind == 'wait':
            out.append('{k="wait",n=%d}' % int(arg))
        elif kind == 'sleep':
            out.append('{k="sleep",d=%s}' % arg)
        elif kind == 'snap':
            out.append('{k="snap",f=%r}' % arg)
        elif kind == 'end':
            out.append('{k="end"}')
        else:
            raise SystemExit('unknown step ' + item)
    return ',\n'.join(out)


def crash_reports():
    """The names of the iigs crash reports now in the folder of macOS."""
    return {p.name for p in REPORTS.glob('iigs-*.ips')}


def report_pid(name):
    """The process id inside one crash report (None when the file does not parse)."""
    try:
        return json.loads((REPORTS / name).read_text().partition('\n')[2]).get('pid')
    except (OSError, ValueError):
        return None


def run_case(prefix, name, args):
    model, settings, flow, from_case, _ = CASES[name]
    out = ROOT / 'build/tests' / f'{prefix}-{name}'
    out.mkdir(parents=True, exist_ok=True)
    for d in ('cfg', 'snap', 'state', 'nvram'):
        (out / d).mkdir(exist_ok=True)
    machine, ram = MACHINES.get(model, ('apple2gsr1', '4352K'))
    (out / 'cfg' / f'{machine}.cfg').write_text(cfg_xml(machine, model))
    disk = out / 'wolf-hd.po'
    if settings == 'disk':
        shutil.copyfile(ROOT / 'build/tests' / f'{prefix}-{from_case}' / 'wolf-hd.po', disk)
    else:
        shutil.copyfile(args.disk, disk)
        if settings == 'bad':
            at = settings_offset(disk)
            data = bytearray(disk.read_bytes())
            data[at:at + 512] = settings_block(3, good=False)
            disk.write_bytes(data)
        elif settings != 'fresh':
            at = settings_offset(disk)
            data = bytearray(disk.read_bytes())
            data[at:at + 512] = settings_block(**settings) if isinstance(settings, dict) else settings_block(settings)
            disk.write_bytes(data)
    _, symbols = read(args.elf)
    want = ('MenuBoot', 'LoadSettings', 'PgPage', 'ViewDefault', 'vtBatchA', 'vtBatchB', 'viewTestA', 'viewTestB', 'viewTestKind',
            'viewTestSize', 'weaponViewIndex', 'musicActive', 'columnLight', 'wallPaintOn', 'bufferOn', 'viewWidth', 'tightDispatch', 'wallPaintBridge')
    syms = '{' + ','.join('%s=%d' % (k, symbols[k]) for k in want if k in symbols) + '}'
    steps = args.steps.split(';') if args.steps else FLOWS[flow] if flow else []
    limit = (args.seconds * 2 if flow else args.seconds) * (1 if model == 'stock' else 2)
    lua = OBSERVER.replace('@SVIEW@', str(SETTINGS_IN + S_VIEW)).replace('@SETI@', 'true' if flow == 'seiflag' else 'false').replace('@INJECT@', ('%r' % KEYS['Space']) if flow == 'inject' else 'nil').replace('@SYMS@', syms).replace('@STEPS@', steps_lua(steps)).replace('@LIMIT@', str(limit))
    lua_guard.write(out / 'view.lua', lua)
    cmd = ['nice', '-n', '20', MAME, machine, '-rompath', ROMS, '-ramsize', ram, '-sl7', 'cffa3000',
           '-hard1', str(disk), '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo',
           '-seconds_to_run', str(limit + 5), '-autoboot_delay', '0', '-autoboot_script', str(out / 'view.lua'),
           '-cfg_directory', str(out / 'cfg'), '-state_directory', str(out / 'state'),
           '-nvram_directory', str(out / 'nvram'), '-snapshot_directory', str(out / 'snap')]
    live = [l for l in subprocess.run(['pgrep', '-fl', '/iigs.app/Contents/MacOS/iigs'], capture_output=True,
                                      text=True).stdout.splitlines() if str(ROOT / 'build/tests') in l]
    if live:
        raise SystemExit('my MAME process is already running')
    env = dict(__import__('os').environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1')
    began = time.time()
    reports_before = crash_reports()
    with (out / 'mame.log').open('w') as log:
        p = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=limit * 4 + 300)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            print('killed after the wall clock limit')
    text = (out / 'mame.log').read_text()
    result = parse(text)
    result['wall_seconds'] = round(time.time() - began, 1)
    result['mame_exit'] = p.returncode
    result['mame_pid'] = p.pid
    new_reports = sorted(crash_reports() - reports_before)
    result['own_crash_reports'] = [r for r in new_reports if report_pid(r) == p.pid]
    result['other_new_crash_reports'] = [r for r in new_reports if r not in result['own_crash_reports']]
    data = disk.read_bytes()
    at = settings_offset(disk)
    result['disk_sview'] = data[at + S_VIEW] if data[at:at + 7] == b'WOLFSET' else None
    result['disk_shade'] = data[at + S_SHADE] if data[at:at + 7] == b'WOLFSET' else None
    result['disk_paint'] = data[at + S_PAINT] if data[at:at + 7] == b'WOLFSET' else None
    result['disk_walls'] = data[at + S_WALLS] if data[at:at + 7] == b'WOLFSET' else None
    result['disk_checksum_valid'] = struct.unpack_from('<H', data, at + S_SUM)[0] == sum(data[at+12:at+496]) & 0xffff
    result['config_xml'] = cfg_xml(machine, model)
    result['command'] = cmd
    result['model'], result['case'] = model, name
    return result


def parse(text):
    """The VD lines of the log as {name: {field: number or text}}; a later line of one name wins."""
    r = {}
    for line in text.splitlines():
        m = re.match(r'VD_([A-Z]+)(?: \d+)? (.*)', line)
        if not m or m.group(1) == 'WAIT':
            continue
        fields = {}
        for k, v in re.findall(r'(\w+)=(\S+)', m.group(2)):
            if v.startswith('0x'):
                fields[k] = int(v, 16)
            elif re.fullmatch(r'-?\d+', v):
                fields[k] = int(v)
            elif re.fullmatch(r'-?\d+\.\d+', v):
                fields[k] = float(v)
            else:
                fields[k] = v
        r[m.group(1).lower()] = fields
    return r


def check(r, name, count_only):
    """The failures of a case: a list of texts."""
    want = CASES[name][4]
    bad = []
    if r.get('mame_exit') != 0:
        bad.append('MAME exit code %s, not 0' % r.get('mame_exit'))
    if r.get('own_crash_reports'):
        bad.append('MAME crash reports: %s' % ', '.join(r['own_crash_reports']))
    if 'final' not in r:
        return bad + ['no VD_FINAL: the run did not finish']
    if count_only:
        return bad
    ran = 'entry' in r
    if ran != want['ran']:
        bad.append('the test %s' % ('did not run' if want['ran'] else 'ran: a size in the settings must win'))
    if ran:
        e, x = r['entry'], r['exit']
        if bool(e['P'] & 4) != want.get('sei', False):
            bad.append('the I flag is %s at the test' % ('set' if e['P'] & 4 else 'clear'))
        if e['sum'] != x['sum']:
            bad.append('the screen changed during the test')
        if x['t'] > r.get('pgpage', {}).get('t', 1e9):
            bad.append('the test ended after the PG-13 page began')
        if x['t'] > r.get('music', {}).get('t', 1e9):
            bad.append('the test ended after the title song began')
        if e['music']:
            bad.append('the song played at the test')
        if x['size'] != want['size']:
            bad.append('the test chose %d, not %d' % (x['size'], want['size']))
    if r['final']['view'] != want['view']:
        bad.append('the view is %d, not %d' % (r['final']['view'], want['view']))
    if 'shade' in want and r['final']['shade'] != want['shade']:
        bad.append('the depth shading is %d, not %d: the file was not read' % (r['final']['shade'], want['shade']))
    if 'disk' in want and (r['disk_sview'], r['disk_shade']) != want['disk']:
        bad.append('the disk has S_VIEW %s and S_SHADE %s, not %s' % (r['disk_sview'], r['disk_shade'], want['disk']))
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', nargs='+')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--prefix', default='vd')
    ap.add_argument('--elf', type=Path, default=ROOT / 'build/wolf.elf')
    ap.add_argument('--disk', type=Path, default=ROOT / 'build/wolf-hd.po')
    ap.add_argument('--seconds', type=int, default=75, help='emulated seconds limit of a stock run (2x for the others)')
    ap.add_argument('--steps', help='steps of the key flow, separated by ; (a debug run)')
    ap.add_argument('--count-only', action='store_true', help='print the numbers, check nothing')
    args = ap.parse_args()
    if args.list:
        for name, (model, settings, flow, from_case, want) in CASES.items():
            print(f'{name:28} {model:7} settings={settings} flow={flow} from={from_case} {want}')
        return
    names = args.only or list(CASES)
    results, failed = {}, 0
    for name in names:
        r = run_case(args.prefix, name, args)
        bad = check(r, name, args.count_only)
        r['failures'] = bad
        results[name] = r
        print(name, json.dumps({k: v for k, v in r.items() if k not in ('case',)}, sort_keys=True))
        for line in bad:
            print('  FAIL', line)
        failed += bool(bad)
        (ROOT / 'build/tests' / f'{args.prefix}-view-default.json').write_text(json.dumps(results, indent=1, sort_keys=True))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
