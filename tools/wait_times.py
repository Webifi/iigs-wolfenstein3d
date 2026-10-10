"""Time the waits of the player in stock MAME: boot, menus, New Game, saves, loads, restart after death.

Usage: wait_times.py CONFIG SCENARIO [--name NAME]
  CONFIG    hd (the hard disk image), two (the floppy set in two drives), one (the floppy set in one drive)
  SCENARIO  boot, menu, options, game, floors, flow, demos, quit or bench

A run starts MAME with tools/ui_test.py and a recorder script (--lua). The recorder logs lines "EV time kind
values" for what the player can see: the screen id of the menu code ($03E4), the frames of the game, the
screen going black or coming back, the busy sign, the strip of the loader (its text and bar in rows 191 to 199),
the drive images and the INSERT DISK prompts, and each time one of the routines in EXECS starts. The steps put
"MARK time name" lines at the moment of each key. A wait runs from its mark to the first sign that the player
can act again: a game frame, or the menu reading keys.
On one drive the harness changes the disks by itself; each change costs the player the time to take a disk out
and put another in, which is not counted: the time from the prompt to the insert is left out of every wait.
"""
import memmap
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from elf import read
import logic_capture
import test_media

ROOT = Path(__file__).resolve().parents[1]

EXECS = ['MenuBoot', 'BootPicture', 'PgPage', 'TitleScreens', 'PlayTitleDemo', 'PollKey', 'NeedHomeDisk', 'BusyShow',
         'BusyHide', 'UiStartGame', 'UiStartSavedFloor', 'RestartLevel', 'ApplyLevel', 'LogicSetupLevel',
         'DeathReveal', 'DoQuit', 'UiQuitRom', 'MenuOpen', 'UiLeave', 'LoadFloorData', 'WriteSettings',
         'setView', 'LoadFloorAssets', 'PlayDemoStart', 'PlayDemoStop', 'DemoAbort', 'StartDemo',
         'StartDemoPrompt', 'StartMusic', 'InitSound', 'ShowNote', 'ReadBlocks', 'UiBlock', 'UiEject', 'LogicNewGame', 'UiDemoStart',
         'CacheFloorMusic', 'FloorMusic', 'SelectMusic', 'StartFloor', 'EnterFloor', 'TallyOpen', 'EpisodeEnd', 'MenuReturnTitle',
         'ExpandMusic', 'ExpandMusicBlocks', 'ScaleMusicVolume']

RECORDER = memmap.fill(r'''
local s = mem
%(logic)s
SYM = %(sym)s
FRAMEADDR = SYM.frameCount
local EXECS = %(execs)s
local SNAPS = %(snaps)s
local pendingSnaps = {}
local function now() return manager.machine.time:as_double() end
local function ev(kind, ...)
  local a = {...}
  for i = 1, #a do a[i] = tostring(a[i]) end
  print(string.format("EV %%.4f %%s %%s", now(), kind, table.concat(a, " ")))
end
local logAllUntil = 0
local last = {id = -1, fr = -1, ls = -1, li = -1, dm = -1, busy = -1, vis = -1, blank = -1, strip = -1, br = -1, prompt = 0, frT = -1, pollT = -1}
for name, addr in pairs(EXECS) do
  local h = mem:install_read_tap(addr, addr, "x-" .. name, function(a, d, m)
    if cpu.state.PC.value ~= a + 1 then return end
    local t = now()
    if name == "PollKey" then
      local gap = t - last.pollT
      last.pollT = t
      if gap > 0.2 then ev("x", name, string.format("gap=%%.3f", gap)) end
      return
    end
    if SNAPS[name] then
      SNAPN = (SNAPN or 0) + 1
      for _, delay in ipairs(SNAPS[name]) do pendingSnaps[#pendingSnaps + 1] = {t = t + delay, name = string.format("%%s-%%02d-%%s", name, SNAPN, delay)} end
    end
    if name == "setView" or name == "UiLeave" then logAllUntil = t + 2 end
    if name == "BusyShow" then ev("x", name, "kind=" .. (cpu.state.A.value & 255)) else ev("x", name) end
  end)
  EXECTAPS = EXECTAPS or {}
  EXECTAPS[#EXECTAPS + 1] = h
end
local function sumPalette(p)
  local n = 0
  for i = 0, 15 do
    local w = mem:read_u16(@MM:SHR_PAL@ + p * 32 + i * 2)
    n = n + (w & 15) + ((w >> 4) & 15) + ((w >> 8) & 15)
  end
  return n
end
local function stripUp()
  -- the strip of the loader (loader.s): rows 191-199 take palette 15, and the bar has a cell at byte 23 of row 195
  -- (the title pictures have the same row palettes, with black pixels)
  if (mem:read_u8(@MM:SHR_SCB@ + 195) & 15) ~= 15 then return 0 end
  if mem:read_u8(@MM:SHR@ + 195 * 160 + 23) == 0 then return 0 end
  return sumPalette(15) > 0 and 1 or 0
end
local function signUp()
  -- the box of the sign (ui_disk.s dlBusy): red border rows 78-79 and 116-117 over bytes 40-119, black inside above the text
  for _, row in ipairs({78, 79, 116, 117}) do
    for col = 40, 119, 7 do
      if mem:read_u8(@MM:SHR@ + row * 160 + col) ~= 0x22 then return 0 end
    end
  end
  for _, col in ipairs({44, 70, 100}) do
    if mem:read_u8(@MM:SHR@ + 81 * 160 + col) ~= 0 then return 0 end
  end
  return 1
end
local function pixelsLit()
  local n = 0
  for _, row in ipairs({6, 22, 40, 58, 76, 94, 112, 130, 150, 170, 185}) do
    for _, col in ipairs({12, 40, 66, 92, 118, 146}) do
      if mem:read_u8(@MM:SHR@ + row * 160 + col) ~= 0 then n = n + 1 end
    end
  end
  return n
end
local driveName = {}
local function swapText()
  for _, base in ipairs({@MM:DISK_PROMPT_00@, @MM:DISK_PROMPT@}) do
    local text = ""
    for i = 0, 12 do text = text .. string.char(mem:read_u8(base + i) & 127) end
    local n = tonumber(text:match("^INSERT DISK (%%d)$"))
    if n then return n end
  end
  return 0
end
emu.register_frame_done(function()
  local t = now()
  for i = #pendingSnaps, 1, -1 do
    if t >= pendingSnaps[i].t then screen:snapshot(pendingSnaps[i].name .. ".png"); ev("snap", pendingSnaps[i].name); table.remove(pendingSnaps, i) end
  end
  local id = mem:read_u8(0x3e4)
  if id ~= last.id then ev("id", id); last.id = id end
  local fr = mem:read_u16(SYM.frameCount)
  if fr ~= last.fr then
    if t - last.frT > 0.2 then ev("fr", fr, string.format("gap=%%.3f", t - last.frT)) elseif t < logAllUntil then ev("fr", fr, "") end
    last.fr = fr; last.frT = t
  end
  local ls, li, dm = mem:read_u16(SYM.levelState), mem:read_u16(SYM.levelIndex), mem:read_u16(SYM.demoMode)
  if ls ~= last.ls or li ~= last.li or dm ~= last.dm then ev("st", "level=" .. li, "state=" .. ls, "demo=" .. dm); last.ls, last.li, last.dm = ls, li, dm end
  local busy = mem:read_u16(SYM.busyShown)
  if busy ~= last.busy then ev("sign", busy); last.busy = busy end
  local vis = signUp()
  if vis ~= last.vis then ev("signvis", vis); last.vis = vis end
  local strip = stripUp()
  if strip ~= last.strip then ev("strip", strip); last.strip = strip end
  local br = sumPalette(0) + sumPalette(8)
  local blank = (br == 0 or pixelsLit() == 0) and 1 or 0
  if blank ~= last.blank then ev("blank", blank); last.blank = blank end
  if br ~= last.br then if (br == 0) ~= (last.br == 0) or math.abs(br - last.br) > 40 then ev("br", br) end; last.br = br end
  local p = swapText()
  if p ~= last.prompt then ev("prompt", p); last.prompt = p end
  for tag, img in pairs(manager.machine.images) do
    if tag:find("35dd") then
      local name = img.exists and (img.filename or "?"):match("([^/]*)$") or "none"
      if driveName[tag] ~= name then ev("drive", tag:match("fdc:(%%d)"), name); driveName[tag] = name end
    end
  end
end)
CALLS = CALLS or {}
CALLS.die = function()
  s:write_u16(LC.V_health, 0)
  s:write_u16(LC.V_events, s:read_u16(LC.V_events) | 3)
  s:write_u16(LC.V_playstate, 2)
  s:write_u16(LC.V_killerobj, s:read_u16(LC.OBJLIST + LC.O_NEXT))
  ev("call", "die")
end
CALLS.elevator = function() s:write_u16(LC.V_playstate, 3); ev("call", "elevator") end
CALLS.victory = function() s:write_u16(LC.V_playstate, 6); ev("call", "victory") end
for n = 0, 9 do
  CALLS["floor" .. n] = function() s:write_u16(SYM.levelIndex, n); ev("call", "floor" .. n) end
end
''')

# The disk keeper: when the front end asks for disk 1 (the sign of kind 2), put it in the empty drive.
KEEPER = r'''
local keeperDisk1 = %(disk1)s
local needDisk1 = false
KEEPTAPS = {}
KEEPTAPS[1] = mem:install_read_tap(%(busyshow)d, %(busyshow)d, "keeper-sign", function(a, d, m)
  if cpu.state.PC.value ~= a + 1 then return end
  if (cpu.state.A.value & 255) == 2 then needDisk1 = true end
end)
KEEPTAPS[2] = mem:install_read_tap(%(busyhide)d, %(busyhide)d, "keeper-hide", function(a, d, m)
  if cpu.state.PC.value == a + 1 then needDisk1 = false end
end)
emu.register_frame_done(function()
  if not needDisk1 then return end
  local drive = manager.machine.images[":fdc:2:35dd"]
  if not drive.exists then drive:load(keeperDisk1); print(string.format("EV %%.4f insert disk1", now())) end
end)
'''


def build_lua(symbols, media_swap, disk1, with_keeper, snaps):
    names = ['frameCount', 'levelState', 'levelIndex', 'demoMode', 'busyShown']
    sym = '{' + ','.join('%s=%d' % (n, symbols[n]) for n in names) + '}'
    execs = '{' + ','.join('%s=%d' % (n, symbols[n]) for n in EXECS if n in symbols) + '}'
    lua = (media_swap + '\n' if media_swap else '') + RECORDER % dict(
        logic=logic_capture.lua(), sym=sym, execs=execs,
        snaps='{' + ','.join('%s={%s}' % (k, ','.join(str(d) for d in v)) for k, v in snaps.items()) + '}')
    if with_keeper:
        lua += KEEPER % dict(disk1=json.dumps(str(disk1)), busyshow=symbols['BusyShow'], busyhide=symbols['BusyHide'])
    return lua


# ---------------------------------------------------------------------------------------------- scenarios
def keys(*names):
    return ';'.join('key=%s' % n for n in names)


TITLE = 'wait=1;sleep=4'                      # the title page: its first seconds flush the keys


def scenario_boot(config):
    return [TITLE, 'end='], {'hd': 90, 'two': 330, 'one': 420}[config]


def scenario_menu(config):
    # the title to the menu, then the screens of the menu and back (no game running)
    steps = [TITLE,
             'mark=title-to-menu', 'key=Return', 'wait=2', 'sleep=6',
             keys('Down', 'Down'), 'sleep=1', 'mark=open-options', 'key=Return', 'wait=7', 'sleep=4',
             'mark=close-options', 'key=Esc', 'wait=2', 'sleep=6',
             'key=Down', 'sleep=1', 'mark=open-read-this', 'key=Return', 'sleep=6',
             'mark=close-read-this', 'key=Esc', 'sleep=5',
             'key=Down', 'sleep=1', 'mark=open-scores', 'key=Return', 'wait=6', 'sleep=4',
             'mark=close-scores', 'key=Esc', 'sleep=5',
             keys('Up', 'Up', 'Up'), 'sleep=1', 'mark=open-load', 'key=Return', 'wait=4', 'sleep=4',
             'mark=close-load', 'key=Esc', 'sleep=5',
             'end=']
    return steps, {'hd': 160, 'two': 440, 'one': 540}[config]


def scenario_game(config):
    # New Game, play, the view keys, the menu in play, a death and its restart, a save and a load, the quit
    steps = [TITLE,
             'key=Return', 'wait=2', 'sleep=6',
             'mark=new-game', 'key=Return', 'wait=3', 'sleep=2',
             'mark=start-game', 'key=Return', 'waitframes=4', 'sleep=3',
             'mark=view-smaller', 'key=Minus', 'waitframes=3', 'sleep=2',
             'mark=view-larger', 'key=Equals', 'waitframes=3', 'sleep=2',
             'mark=menu-open', 'key=Esc', 'wait=2', 'sleep=6',
             'mark=menu-close', 'key=Esc', 'waitframes=4', 'sleep=2',
             'call=die', 'sleep=14', 'waitframes=4', 'sleep=2',
             'mark=menu-open-2', 'key=Esc', 'wait=2', 'sleep=6',
             keys('Down', 'Down'), 'sleep=1', 'mark=open-save', 'key=Return', 'wait=4', 'sleep=3',
             'mark=save', 'key=Return', 'sleep=10',
             'mark=save-to-menu', 'key=Esc', 'wait=2', 'sleep=6',
             'key=Up', 'sleep=1', 'mark=open-load', 'key=Return', 'wait=4', 'sleep=4',
             'mark=load', 'key=Return', 'waitframes=4', 'sleep=3',
             'mark=menu-open-3', 'key=Esc', 'wait=2', 'sleep=6',
             'end=']
    return steps, {'hd': 300, 'two': 680, 'one': 800}[config]


def scenario_floors(config):
    # A saved game for each floor, then a load of each (the game does not change floors by itself yet). The menu
    # has 8 slots: floors 1-8 go to slots 1-8, then floors 9 and 10 overwrite slots 1 and 2. The menu cursor stays
    # on the last item: Save Game after the first save, Load Game after the first load.
    steps = [TITLE, 'key=Return', 'wait=2', 'sleep=6', 'key=Return', 'wait=3', 'sleep=2', 'key=Return', 'waitframes=4', 'sleep=3']
    for n in range(8):
        steps += ['call=floor%d' % n, 'key=Esc', 'wait=2', 'sleep=6']
        steps += [keys('Down', 'Down'), 'sleep=1'] if n == 0 else []
        steps += ['key=Return', 'wait=4', 'sleep=2'] + (['key=Down'] if n else [])
        steps += ['mark=save-floor-%d' % (n + 1), 'key=Return', 'sleep=8', 'key=Esc', 'wait=2', 'sleep=6', 'key=Esc', 'waitframes=4', 'sleep=2']
    for n in range(8):
        steps += ['key=Esc', 'wait=2', 'sleep=6'] + (['key=Up', 'sleep=1'] if n == 0 else [])
        steps += ['key=Return', 'wait=4', 'sleep=2'] + (['key=Down'] if n else [])
        steps += ['mark=load-floor-%d' % (n + 1), 'key=Return', 'waitframes=6', 'sleep=3']
    for n in (8, 9):
        steps += ['call=floor%d' % n, 'key=Esc', 'wait=2', 'sleep=6']
        steps += ['key=Down', 'sleep=1'] if n == 8 else []
        steps += ['key=Return', 'wait=4', 'sleep=2', 'key=Down', 'key=Return', 'sleep=1', 'key=Y', 'sleep=8', 'key=Esc', 'wait=2', 'sleep=6', 'key=Esc', 'waitframes=4', 'sleep=2']
    steps += ['key=Esc', 'wait=2', 'sleep=6', 'key=Up', 'sleep=1', 'key=Return', 'wait=4', 'sleep=2', 'key=Up', 'sleep=1']
    steps += ['mark=load-floor-9', 'key=Return', 'waitframes=6', 'sleep=3']
    steps += ['key=Esc', 'wait=2', 'sleep=6', 'key=Return', 'wait=4', 'sleep=2', 'key=Down', 'mark=load-floor-10', 'key=Return', 'waitframes=6', 'sleep=3', 'end=']
    return steps, {'hd': 1300, 'two': 3900, 'one': 4500}[config]


def scenario_demos(config):
    return [TITLE, 'sleep=1380', 'end='], {'hd': 1500, 'two': 1700, 'one': 1700}[config]


def scenario_bench(config):
    # Options, Benchmark: the demo starts, a few seconds of it run, Esc stops it
    steps = [TITLE,
             'key=Return', 'wait=2', 'sleep=6',
             keys('Down', 'Down'), 'sleep=1', 'key=Return', 'wait=7', 'sleep=4',
             keys(*['Down'] * 7), 'sleep=1', 'mark=bench-start', 'key=Return', 'waitframes=4', 'sleep=8',
             'mark=bench-stop', 'key=Esc', 'sleep=6',
             'end=']
    return steps, {'hd': 130, 'two': 420, 'one': 520}[config]


def scenario_options(config):
    # Options: the Controls screen, then Save Settings (a change first, so that the row lights)
    steps = [TITLE,
             'key=Return', 'wait=2', 'sleep=6',
             keys('Down', 'Down'), 'sleep=1', 'key=Return', 'wait=7', 'sleep=4',
             keys(*['Down'] * 6), 'sleep=1', 'mark=open-controls', 'key=Return', 'sleep=6',
             'mark=close-controls', 'key=Esc', 'sleep=5',
             keys('Up', 'Up', 'Up'), 'sleep=1', 'key=Left', 'sleep=1',
             keys(*['Down'] * 5), 'sleep=1', 'mark=save-settings', 'key=Return', 'sleep=8',
             'end=']
    return steps, {'hd': 130, 'two': 420, 'one': 520}[config]


def scenario_flow(config):
    # New Game, a fake exit through the elevator, the tally and the next floor, then a fake end of the episode:
    # the victory page, the two ending pages and the way back to the title
    steps = [TITLE,
             'key=Return', 'wait=2', 'sleep=6',
             'key=Return', 'wait=3', 'sleep=2',
             'key=Return', 'waitframes=4', 'sleep=3',
             'mark=elevator', 'call=elevator', 'sleep=25',
             'mark=tally-continue', 'key=Return', 'waitframes=6', 'sleep=6',
             'mark=victory', 'call=victory', 'sleep=12',
             'mark=episode-end', 'key=Return', 'sleep=8',
             'mark=ending-page-2', 'key=Return', 'sleep=8',
             'mark=back-to-title', 'key=Return', 'sleep=30',
             'end=']
    return steps, {'hd': 330, 'two': 760, 'one': 900}[config]


def scenario_quit(config):
    steps = [TITLE, 'key=Return', 'wait=2', 'sleep=6', 'key=Up', 'sleep=1', 'key=Return', 'sleep=3',
             'mark=confirm-quit', 'key=Y', 'sleep=8', 'end=']
    return steps, {'hd': 120, 'two': 400, 'one': 500}[config]


SCENARIOS = dict(boot=scenario_boot, menu=scenario_menu, game=scenario_game, floors=scenario_floors, demos=scenario_demos,
                 quit=scenario_quit, bench=scenario_bench, options=scenario_options, flow=scenario_flow)


# ---------------------------------------------------------------------------------------------- the report
def parse(log):
    events = []
    for line in log.splitlines():
        m = re.match(r'^(EV|MARK) (\d+\.\d+) (\S+)\s*(.*)$', line)
        if m:
            events.append((float(m.group(2)), m.group(3) if m.group(1) == 'EV' else 'mark', m.group(4) if m.group(1) == 'EV' else m.group(3)))
    return events


def prompt_time(events, a, b):
    """The seconds between a and b with an INSERT DISK prompt up: the player is swapping disks."""
    total, since = 0.0, None
    for t, kind, rest in events:
        if kind == 'prompt':
            if rest != '0' and since is None:
                since = max(t, a)
            elif rest == '0' and since is not None:
                if t > a and since < b:
                    total += min(t, b) - since
                since = None
        if kind == 'x' and rest.startswith('BusyShow') and 'kind=2' in rest and since is None:
            since = max(t, a)
        if kind == 'x' and rest.startswith('BusyHide') and since is not None:
            if t > a and since < b:
                total += min(t, b) - since
            since = None
    if since is not None and since < b:
        total += b - since
    return total


def first_after(events, start, kinds, test=None):
    for t, kind, rest in events:
        if t > start and kind in kinds and (test is None or test(rest)):
            return t
    return None


def wait_after_mark(events, name, end_kinds=('x',), end_test=None, occurrence=0):
    marks = [t for t, kind, rest in events if kind == 'mark' and rest == name]
    if len(marks) <= occurrence:
        return None
    t0 = marks[occurrence]
    return t0, first_after(events, t0, end_kinds, end_test)


def report_boot(events):
    rows = []

    def at(kind, test):
        return first_after(events, 0.5, (kind,), test)
    menu_boot = first_after(events, 5, ('x',), lambda r: r.startswith('MenuBoot'))
    picture = first_after(events, 5, ('x',), lambda r: r.startswith('BootPicture'))
    pgpage = first_after(events, 5, ('x',), lambda r: r.startswith('PgPage'))
    title = first_after(events, 5, ('id',), lambda r: r == '1')
    pg13 = first_after(events, 5, ('id',), lambda r: r == '14')
    rows.append(('power on to the front end (the loader and the start of the game)', menu_boot))
    if menu_boot and picture:
        rows.append(('front end start to the fade of the cover', picture - menu_boot))
    if picture and pgpage:
        rows.append(('the fade of the cover and the check for disk 1', pgpage - picture))
    if pgpage and pg13:
        rows.append(('PG-13 page ready', pg13 - pgpage))
    if title:
        rows.append(('power on to the title page', title))
    if menu_boot and title:
        rows.append(('front end start to the title page', title - menu_boot))
    return rows


def end_of_wait(events, t0):
    """The time at which the player can act again after the key at t0, or None when it took under 0.2 s.

    The menu code logs a PollKey event when it reads keys again after a gap of 0.2 s or more, and the game logs
    a frame event after such a gap. The gap belongs to the key when it began within 0.3 s of the key. A frame
    that ends the wait after a redraw (setView) counts only when it follows that redraw."""
    end = None
    for t, kind, rest in events:
        if t <= t0 + 0.02:
            continue
        m = re.search(r'gap=([\d.]+)', rest)
        if m and (kind == 'fr' or (kind == 'x' and rest.startswith('PollKey'))):
            if t - float(m.group(1)) > t0 + 0.3:
                return None
            end = t
            break
    if end is None:
        return None
    redraw = first_after(events, t0, ('x',), lambda r: r.startswith('setView'))
    if redraw is not None and redraw < end + 1.0:
        later = first_after(events, max(redraw, end) + 0.0005, ('fr',))
        if later is not None and later < redraw + 3.0:
            end = later
    return end


def screen_state(events, t0, t1):
    """What the player sees in [t0, t1], in seconds: the screen black, the busy sign up (the box is on the screen,
    whatever the flag of the code says), the strip of the loader (its text and bar, rows 180 to 199), neither of the
    two, and the longest stretch with neither."""
    state = {'blank': 0, 'signvis': 0, 'strip': 0}
    for t, kind, rest in events:
        if t > t0:
            break
        if kind in state and rest in ('0', '1'):
            state[kind] = int(rest)
    totals = [0.0, 0.0, 0.0, 0.0, 0.0]
    since = t0
    run = 0.0

    def add(t):
        nonlocal since, run
        span = t - since
        bare = not state['signvis'] and not state['strip']
        totals[0] += span * state['blank']
        totals[1] += span * state['signvis']
        totals[2] += span * state['strip']
        totals[3] += span * bare
        run = run + span if bare else 0.0
        totals[4] = max(totals[4], run)
        since = t

    for t, kind, rest in events:
        if t <= t0 or kind not in state:
            continue
        if t > t1:
            break
        add(t)
        if rest in ('0', '1'):
            state[kind] = int(rest)
    add(t1)
    return totals


def report_waits(events, names):
    rows = []
    for name in names:
        marks = [t for t, kind, rest in events if kind == 'mark' and rest == name]
        for i, t0 in enumerate(marks):
            end = end_of_wait(events, t0)
            label = name if i == 0 else '%s #%d' % (name, i + 1)
            if end is None:
                rows.append((label, '< 0.2 s', 0))
                continue
            swap = prompt_time(events, t0, end)
            rows.append((label, end - t0 - swap, swap) + tuple(screen_state(events, t0, end)))
    return rows


def report_restarts(events):
    """After a death: from RestartLevel to the first frame of the new life."""
    rows = []
    for n, t0 in enumerate(t for t, kind, rest in events if kind == 'x' and rest.startswith('RestartLevel')):
        later = first_after(events, t0, ('st',), lambda r: 'state=0' in r)
        end = first_after(events, t0, ('fr',), lambda r: 'gap=' in r)
        apply_t = first_after(events, t0, ('x',), lambda r: r.startswith('ApplyLevel'))
        reveal = first_after(events, t0, ('x',), lambda r: r.startswith('DeathReveal'))
        rows.append(('restart after a death #%d (RestartLevel to the first frame)' % (n + 1), end - t0 if end else None, 0)
                    + (tuple(screen_state(events, t0, end)) if end else ()))
        if apply_t and reveal:
            rows.append(('  of that, ApplyLevel (the level is built under the red)', reveal - apply_t, 0))
        if reveal and end:
            rows.append(('  of that, the first picture and the fade-in', end - reveal, 0))
    return rows


def report_demos(events):
    """The title loop: each demo start (PlayTitleDemo to its first frame) and end (last frame to the title)."""
    rows = []
    starts = [t for t, kind, rest in events if kind == 'x' and rest.startswith('PlayTitleDemo')]
    for n, t0 in enumerate(starts):
        first = first_after(events, t0, ('fr',), lambda r: 'gap=' in r)
        rows.append(('demo start #%d (PlayTitleDemo to the first demo frame)' % (n + 1), first - t0 if first else None, 0)
                    + (tuple(screen_state(events, t0, first)) if first else ()))
        over = first_after(events, t0 + 1, ('st',), lambda r: 'demo=0' in r)
        title = first_after(events, over, ('id',), lambda r: r in ('1', '12', '6', '14')) if over else None
        shown = first_after(events, over, ('blank',), lambda r: r == '1') if over else None
        back = first_after(events, shown if shown else over, ('blank',), lambda r: r == '0') if over else None
        if over and back:
            rows.append(('demo end #%d (the demo is over to the title page lit)' % (n + 1), back - over, 0)
                        + tuple(screen_state(events, over, back)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config', choices=('hd', 'two', 'one'))
    ap.add_argument('scenario', choices=sorted(SCENARIOS))
    ap.add_argument('--name')
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--again', action='store_true', help='only read the log of the last run')
    ap.add_argument('--poke', action='append', default=[], help='SYMBOL=VALUE: write a 16 bit word at the start (experiments)')
    ap.add_argument('--limit', type=int, help='stop at that many emulated seconds (the demos scenario runs to the limit)')
    ap.add_argument('--snaps', default='{}', help='JSON: {"PlayTitleDemo": [1, 4]} takes a snapshot that many seconds after the routine starts')
    args = ap.parse_args()
    name = args.name or 'waits-%s-%s' % (args.config, args.scenario)
    out = ROOT / 'build/tests' / name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(args.root / 'build/wolf.elf')
    steps, seconds = SCENARIOS[args.scenario](args.config)
    if args.limit:
        seconds = args.limit
        steps = [('sleep=%d' % (args.limit - 30) if s.startswith('sleep=1380') else s) for s in steps]
    for item in args.poke:
        sym, _, value = item.partition('=')
        steps.insert(1, 'poke16=%d,%s' % (symbols[sym], value))   # after the title page: the loader fills the data again at boot
    if not args.again:
        extra = []
        swap = ''
        media = out / 'media'
        media.mkdir(exist_ok=True)
        if args.config == 'hd':
            extra = ['--hd']
        else:
            _, swap = test_media.prepare(args.root / 'build/disk1.po', media, drives=1 if args.config == 'one' else 2)
            # The ROM ejects a disk a second time when one is put in while it still ejects the last: put it in again
            # while the prompt is up and the drive is empty. The newer test_media.py does that by itself.
            race = "  if swapInserted==wanted then return end\n"
            if race in swap:
                swap = swap.replace(race, "  if swapInserted==wanted then\n    local d=manager.machine.images[':fdc:2:35dd']\n"
                                    "    if d and not d.exists and manager.machine.time:as_double()-swapSince>=1 then swapInserted=nil else return end\n  end\n")
            swap = 'local s = mem\n' + swap
            extra = ['--disk', str(media / 'disk1.po')] + (['--disk2', str(media / 'disk2.po')] if args.config == 'two' else [])
        lua = build_lua(symbols, swap, media / 'disk1.po', args.config in ('one', 'two'), json.loads(args.snaps))
        (out / 'recorder.lua').write_text(lua)
        cmd = [sys.executable, str(ROOT / 'tools/ui_test.py'), '--name', name, '--seconds', str(seconds)] + extra
        cmd += ['--lua', str(out / 'recorder.lua'), '--steps', ';'.join(steps)]
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=seconds * 2 + 150)
        (out / 'driver.log').write_text(run.stdout + run.stderr)
        if run.returncode:
            raise SystemExit((run.stdout + run.stderr)[-2500:])
    if not (out / 'mame.log').exists():
        raise SystemExit('no MAME log; the driver said:\n' + (out / 'driver.log').read_text()[-1500:])
    log = (out / 'mame.log').read_text()
    events = parse(log)
    (out / 'events.txt').write_text('\n'.join('%.4f %s %s' % e for e in events) + '\n')
    if 'TIMEOUT at step' in log or re.search(r'Lua error', log, re.I):
        raise SystemExit(log[-2500:])
    marks = [rest for t, kind, rest in events if kind == 'mark']
    rows = report_boot(events) if args.scenario == 'boot' else report_waits(events, list(dict.fromkeys(marks)))
    if args.scenario in ('game', 'floors'):
        rows += report_restarts(events)
    if args.scenario == 'demos':
        rows += report_demos(events)
    if args.scenario == 'quit':
        mark = next((t for t, kind, rest in events if kind == 'mark' and rest == 'confirm-quit'), None)
        gone = first_after(events, mark or 1e9, ('x',), lambda r: r.startswith('UiQuitRom'))
        rows = [r for r in rows if r[0] != 'confirm-quit'] + [('confirm-quit (the Y key to the firmware)', gone - mark if gone and mark else None, 0)]
    for label, seconds_, *rest in rows:
        extra_note = ' (disk changes %.1f s, not counted)' % rest[0] if rest and rest[0] else ''
        if len(rest) >= 6:
            extra_note += ' black %.2f s, sign %.2f s, strip %.2f s, neither %.2f s (longest %.2f s)' % tuple(rest[1:6])
        print('%-60s %s%s' % (label, '%.2f s' % seconds_ if isinstance(seconds_, float) else seconds_ if seconds_ is not None else 'no end seen', extra_note))
    (out / 'waits.json').write_text(json.dumps([[r[0], r[1]] for r in rows], indent=1) + '\n')


if __name__ == '__main__':
    main()
