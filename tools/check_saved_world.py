#!/usr/bin/env python3
"""Mid-fight save, cold-boot load, and the next 200 logic tics.

Runs one isolated MAME process at a time. Debugger fixtures place the
player, inject menu keys and clamp each world
batch and command queue to two tics for comparison, including empty idle queues. A fallback wounds the guard
if the scripted shot misses, and reports that intervention. Checks 16 selected
world fields over 200 tics, not every saved byte or unmodified live-clock timing.
Both branches pause through Esc before the comparison point; the control resumes
without saving, while the saved branch cold-boots and restores from disk.
The first frame after the resume and after the load is the same in both runs: one
world batch of two tics, then two idle player tics, whatever DOC time has passed.
Without that the control and the loaded game could differ by one world batch.
The pause key becomes visible at the entry of tryRunTics, so the pause always falls before the first command build
of a frame; --branch N moves the key to another game frame and the result must not change.
All code/data addresses outside the fixed logic bank come from the current ELF.
Usage: python3 tools/check_saved_world.py hd --name saved-world-build
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from elf import read
import argparse
import re
from test_media import prepare
import lua_guard
import mame_kit

BINARY = mame_kit.BINARY
ROMPATH = mame_kit.ROMPATH
ROOT = Path(__file__).resolve().parents[1]
OUT = None
BRANCH_FRAME = 340

DEBUG = r"""focus :maincpu
fill 3e0,1,00
fill 3ea,6,00
fill 3fa,2,00
go
"""

LUA = r"""
local LB=0x@LOGICBANK@*65536
local cpu=manager.machine.devices[":maincpu"]
local mem=cpu.spaces["program"]
local s=mem
local mode=MODE
local drives=DRIVES
local disk1=DISK1
local emuLimit=EMULIMIT
local DOOR_AT, USE_DOOR, USE_DOOR_END = 8, 16, 48
local GUARD_AT, FIRE_AT, FIRE_END, POKE_AT = 160, 180, 210, 240
local PUSH_AT, USE_PUSH, USE_PUSH_END, BRANCH = 300, 310, 334, __BRANCH__
local phase="boot"
local playFrames=0
local beat=0
local lastSeq=0
local startHp=nil
local armSum=nil
local armed=false
local reported=false
local busyT, busyKind, busySign=nil, nil, -1
local inserted=false
local lastSign=-1
local sawBusy=false
local mailCleared=false
local nav=0
local navWait=0
local titleTick=0
local titlePending=false
local loadT=nil
local regListed=false
local pausedFingerprint=false
__SWAP__
local function now() return manager.machine.time:as_double() end
local function w16(a,v) mem:write_u16(a, v & 65535) end
local function r16(a) return mem:read_u16(a) end
local function r8(a) return mem:read_u8(a) end
local function say(msg)
  print(msg)
  io.stdout:flush()
end
local function fail(msg)
  say(string.format("FAIL %s %.3f", msg, now()))
  manager.machine:exit()
end
local function addbp(addr, cond, act)
  local dev = manager.machine.devices[":maincpu"].debug
  if not dev then say(string.format("BPFAIL %x nodebug", addr)) return end
  local ok, id = pcall(function() return dev:bpset(addr, cond, act) end)
  if not ok then say(string.format("BPFAIL %x %s", addr, tostring(id)))
  else say(string.format("BPSET %x id=%s", addr, tostring(id))) end
end
-- Breakpoints are installed after the machine exists. A debugscript bp
-- never stopped in LogicWorldRun; the same request from Lua does.
addbp(0x@gsPhaseSave@, "1", "do b@@logic+0x6dc6@=1;go")
addbp(0x@gsPhaseLoad@, "1", "do b@@logic+0x6dc6@=3;go")
addbp(0x@gsPhaseDone@, "1", "do b@@logic+0x6dc6@=2;go")
addbp(0x@BusyShow@, "1", "do b@3ed=A;go")
addbp(0x@gsWorldRestored@, "1", "do b@3ea=1;b@3eb=1;w@@logic+0x6d80@=0;w@3fa=0;b@@logic+0x6dc0@=1;b@@logic+0x6dc1@=1;go")
addbp(0x@SyncSaved@, "1", "do b@3ee=2;fill @logic+0x6d70@,8,00;go")
-- The pause key is made visible at the entry of tryRunTics: the first command build of a frame reads it, so the
-- pause always falls between two frames. A key made visible by this callback at any cycle can be read by the second
-- command build, after a world batch and before the player tics, and then the paused world is half a frame ahead.
addbp(0x@tryRunTics@, "(b@@logic+0x6dc2@)==1", "do b@@logic+0x6dc2@=0;w@@inputHead@=w@@logic+0x6dc4@;go")
addbp(0x@castFrame@, "b@@logic+0x6d75@==0", "do b@@logic+0x6d75@=1;go")
addbp(0x@paintFrame@, "b@@logic+0x6d76@==0", "do b@@logic+0x6d76@=1;go")
addbp(0x@preparedColumn@, "b@@logic+0x6d77@==0", "do b@@logic+0x6d77@=1;go")
addbp(0x@ShowNote@, "1", "do b@3ee=1;go")
addbp(0x@LogicWorldRun@, "(b@3ea)==1", "do temp0=A;temp0=temp0-2;w@@worldAt@=w@@worldAt@-temp0;A=2;w@3fa=w@3fa+A;w@@logic+0x6d82@=A;w@@logic+0x6d84@=w@3fa;w@@logic+0x6d86@=w@@logic+0x3002@;w@@logic+0x6d88@=w@@logic+0x3006@;w@@logic+0x6d8a@=w@@logic+0x3032@;w@@logic+0x6d8c@=w@@logic+0x6c0e@;w@@logic+0x6d8e@=w@@logic+0x6c10@;w@@logic+0x6d90@=w@@logic+0x6c32@;w@@logic+0x6d92@=w@@logic+0x6c46@;w@@logic+0x6d94@=w@@logic+0x6c48@;w@@logic+0x6d96@=w@@logic+0x6304@;w@@logic+0x6d98@=w@@logic+0x6504@;w@@logic+0x6d9a@=w@@logic+0x30e2@;w@@logic+0x6d9c@=w@@logic+0x30d0@;w@@logic+0x6d9e@=w@@logic+0x30d8@;w@@logic+0x6da0@=w@@logic+0x30da@;w@@logic+0x6da2@=0;temp0=w@@logic+0x6d80@;temp0=temp0+1;w@@logic+0x6d80@=temp0;go")
-- The first frame after a resume or a load is made the same in both runs. The
-- world is due for exactly two tics whatever the DOC time since ResetTics (the
-- first runLiveCommands), and the player runs two idle tics (the first
-- runCommands). Without this the control and the loaded game differ by one
-- world batch before their first player tics whenever that time rounds to zero
-- or to one tic, and every Rnd call of UpdateFace then shifts the random numbers.
addbp(0x@runLiveCommands@, "(b@3ea)==1 && (b@@logic+0x6dc0@)==1", "do w@@worldAt@=w@(D+46)+w@@ticCount@-2;go")
addbp(0x@runCommands+3@, "(b@3ea)==1 && (b@@logic+0x6dc1@)==1", "do b@@logic+0x6dc1@=0;w@@ticCommands@=0;w@@ticCommands+2@=0;w@@ticCommands+4@=0;w@@ticCommands+6@=0xffff;w@@ticCommands+8@=0;w@@ticCommands+10@=0;w@@ticCommands+12@=0;w@@ticCommands+14@=0xffff;w@@ticCount@=2;go")
-- An empty live-clock queue still receives two idle player tics; match
-- every two-tic world batch after pause/load instead of drifting the RNG.
addbp(0x@runCommands+3@, "(b@3ea)==1 && (b@@logic+0x6dc1@)==0 && (b@@logic+0x6dc0@)==1 && w@@ticCount@==0", "do b@@logic+0x6dc1@=0;w@@ticCommands@=0;w@@ticCommands+2@=0;w@@ticCommands+4@=0;w@@ticCommands+6@=0xffff;w@@ticCommands+8@=0;w@@ticCommands+10@=0;w@@ticCommands+12@=0;w@@ticCommands+14@=0xffff;w@@ticCount@=2;go")
addbp(0x@runCommands+3@, "(b@3ea)==1 && (b@@logic+0x6dc1@)==0 && w@@ticCount@>2", "do w@@ticCount@=2;go")
addbp(0x@LogicPlayerTick@, "(b@3eb)==1", "do w@@logic+0x6db2@=w@@logic+0x6da4@;w@@logic+0x6db4@=w@@logic+0x6da6@;w@@logic+0x6db6@=w@@logic+0x6da8@;w@@logic+0x6db8@=w@@logic+0x6daa@;w@@logic+0x6dba@=w@@logic+0x6dac@;w@@logic+0x6dbc@=w@@logic+0x6dae@;w@@logic+0x6dbe@=w@@logic+0x6db0@;w@@logic+0x6da4@=w@3fa;w@@logic+0x6da6@=w@@logic+0x3002@;w@@logic+0x6da8@=w@@logic+0x3006@;w@@logic+0x6daa@=w@@logic+0x3032@;w@@logic+0x6dac@=w@@logic+0x6c32@;w@@logic+0x6dae@=w@@logic+0x30e2@;w@@logic+0x6db0@=w@@logic+0x30d0@;temp0=w@@logic+0x6da2@;temp0=temp0+1;w@@logic+0x6da2@=temp0;go")
-- ResetTics can initially build only one command. Make both fixtures run the
-- same two whole player tics, copying the already initialized first command.
addbp(0x@runCommands+3@, "(b@3ea)==1 && (b@@logic+0x6dc1@)==0 && w@@ticCount@==1", "do w@@ticCommands+8@=w@@ticCommands@;w@@ticCommands+10@=w@@ticCommands+2@;w@@ticCommands+12@=w@@ticCommands+4@;w@@ticCommands+14@=w@@ticCommands+6@;w@@ticCount@=2;go")
local restoredChecked=false
local function checkCaches()
  if mode~="load" or restoredChecked or r8(0x3ea)~=1 then return end
  restoredChecked=true
  assert(r8(0x3ec)==0, "saved world checksum mismatch")
  local counts={}
  for id=0,255 do counts[id]=0 end
  for cell=0,4095 do
    local id=r8(0x@LINEIDS@+cell)
    if id~=0 and r8((LB+0x0)+cell)~=0 then counts[id]=counts[id]+1 end
  end
  for id=0,255 do assert(r16(0x@LINECOUNTS@+2*id)==counts[id], "restored LOS count "..id) end
  local at=0
  for id=0,r16((LB+0x6c5a))-1 do
    if r16((LB+0x6500)+2*id)~=1 then
      assert(r16(0x@ACTIVE_DOORS@+at)==2*id, "restored active door "..id)
      at=at+2
    end
  end
  assert(r16(0x@ACTIVE_DOORS@+at)==65535, "restored active door terminator")
  say("RESTORED_CACHES 256 "..at//2)
end
addbp(0x@gsPenalty@, "1", "do b@3ec=1;go")
local function place(x, y, ang)
  w16((LB+0x3000), 0x8000)
  w16((LB+0x3002), x)
  w16((LB+0x3004), 0x8000)
  w16((LB+0x3006), y)
  w16((LB+0x3018), x)
  w16((LB+0x301a), y)
  w16((LB+0x3032), ang)
end
local function queue(code, up)
  local head=r16(0x@inputHead@)
  local function put(c)
    w16(0x@inputRing@+head, 0)
    w16(0x@inputRing@+head+2, 0)
    w16(0x@inputRing@+head+4, c)
    w16(0x@inputRing@+head+6, 0)
    head=(head+8)%1024
  end
  put(code)
  if up~=false then put(code|0x80) end
  w16(0x@inputHead@, head)
end
local function queueAtFrameStart(code)
  local head=r16(0x@inputHead@)
  w16(0x@inputRing@+head, 0)
  w16(0x@inputRing@+head+2, 0)
  w16(0x@inputRing@+head+4, code)
  w16(0x@inputRing@+head+6, 0)
  local released=(head+8)%1024
  w16(0x@inputRing@+released, 0)
  w16(0x@inputRing@+released+2, 0)
  w16(0x@inputRing@+released+4, code|0x80)
  w16(0x@inputRing@+released+6, 0)
  w16((LB+0x6dc4), (head+16)%1024)
  mem:write_u8((LB+0x6dc2), 1)
end
local function sumbytes(addr, n)
  local t=0
  for i=0,n-1 do t=t+mem:read_u8(addr+i) end
  return t
end
local function checksum()
  local s1=sumbytes((LB+0x0), 0x6d20)
  local s2=sumbytes((LB+0x6e00), 0x3200)
  say(string.format("CHECK %d %d %x %x %x %x %x %x %x %x %x %x",
    s1, s2, r16((LB+0x3002)), r16((LB+0x3006)), r16((LB+0x3032)), r16((LB+0x6c0e)),
    r16((LB+0x6c10)), r16((LB+0x6c32)), r16((LB+0x6c46)), r16((LB+0x6304)),
    r16((LB+0x30e2)), r16((LB+0x30d0))))
  if mode=="save" then
    local f=io.open("branch.bin","wb")
    if not f then say("DUMP fail") return end
    local acc={}
    for i=0,0x9fff do acc[#acc+1]=string.char(mem:read_u8((LB+0x0)+i)) end
    f:write(table.concat(acc))
    f:close()
    say(string.format("DUMP %d", #acc))
  end
end
local function song()
  say(string.format("SONG %d %d", r16(0x@floorSong@), r16(0x@currentSong@)))
end
local function emitP(base)
  say(string.format("P %x %x %x %x %x %x %x",
    r16(base), r16(base+2), r16(base+4), r16(base+6),
    r16(base+8), r16(base+10), r16(base+12)))
end
-- The world breakpoint leaves one snapshot in the gap above the save mark.
-- Printing it here is the trace; the debugger console does not reach the log.
local function drain()
  if r8(0x3ea)~=1 then return end
  local seq=r16((LB+0x6d80))
  if seq==0 or seq==lastSeq then return end
  lastSeq=seq
  say(string.format("W %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x",
    r16((LB+0x6d82)), r16((LB+0x6d84)), r16((LB+0x6d86)), r16((LB+0x6d88)),
    r16((LB+0x6d8a)), r16((LB+0x6d8c)), r16((LB+0x6d8e)), r16((LB+0x6d90)),
    r16((LB+0x6d92)), r16((LB+0x6d94)), r16((LB+0x6d96)), r16((LB+0x6d98)),
    r16((LB+0x6d9a)), r16((LB+0x6d9c)), r16((LB+0x6d9e)), r16((LB+0x6da0))))
  local pc=r16((LB+0x6da2))
  if pc>=2 then emitP((LB+0x6db2)) end
  if pc>=1 then emitP((LB+0x6da4)) end
  if pc>2 then say(string.format("PEXTRA %d", pc)) end
end
-- Save navigation: slot 0, accept its empty name, then Esc twice.
local saveKeys={
  {screen=2, hold=8},
  {key=0x3d, up=true}, {wait=5},
  {key=0x3d, up=true}, {wait=5},
  {key=0x24},
  {screen=4, hold=8},
  {key=0x24},
  {wait=60},
  {key=0x24},
  {phase=2},
  {wait=4},
  {key=0x35},
  {screen=2, hold=8},
  {key=0x35},
  {screen=0, hold=8},
  {done="save"},
}
local continueKeys={
  {screen=2, hold=8},
  {key=0x35},
  {done="continue"},
}
-- A title Esc queued during the fade sits ahead of these keys and selects
-- New Game. Drain the ring when the screen appears, then wait until the gun
-- cursor (direct page UL_CUR) has moved before confirming.
local loadKeys={
  {screen=2, hold=12, drain=true},
  {key=0x3d, up=true},
  {untilCur=1, limit=180},
  {key=0x24},
  {screen=4, hold=20, drain=true},
  {key=0x24},
  {done="loaded"},
}
-- Debugger stores do not notify a write tap, so the busy sign is polled.
-- The private logic gap holds the save phase; $03EF belongs to menu painting.
local function watchBusy()
  if not mailCleared then
    mailCleared=true
    mem:write_u8(0x3ed, 0)
    mem:write_u8(0x3ee, 0)
    mem:write_u16(0x3ec, 0)
    mem:write_u8(LB+0x6dc6, 0)
    lastSign=0
    return
  end
  local ph=r8(LB+0x6dc6)
  local sign=r8(0x3ed)
  if ph==1 or ph==3 then
    if not busyT then busyT=now(); busyKind=ph; busySign=-1 end
    sawBusy=true
    if sign<=3 then busySign=sign end
  elseif ph==2 and not reported and (sawBusy or phase=="menu") then
    local dt=0
    if busyT then dt=now()-busyT end
    if sign<=3 then busySign=sign end
    local kind=busyKind or (mode=="load" and 3 or 1)
    reported=true
    say(string.format("BUSY %s %.3f %d", kind==1 and "save" or "load", dt, busySign))
    busyT=nil
  end
  if sign==2 and lastSign~=2 and drives>0 and not inserted then
    inserted=true
    say(string.format("INSERTDISK %.3f", now()))
    local img=manager.machine.images[":fdc:2:35dd"]
    if img then img:load(disk1) end
  end
  lastSign=sign
end
emu.register_frame_done(function()
  local t=now()
  if t>emuLimit then fail("timeout "..phase) return end
  watchBusy()
  checkCaches()
  drain()
  local function reg(name)
    local v=nil
    pcall(function() v=cpu.state[name].value end)
    return v or -1
  end
  if not regListed then
    regListed=true
    local names={}
    pcall(function()
      for k in pairs(cpu.state) do names[#names+1]=k end
    end)
    table.sort(names)
    say("REGS "..table.concat(names, ","))
  end
  local pb, pcv = reg("PB"), reg("PC")
  local pc = pb * 65536 + (pcv % 65536)
  if pcv >= 65536 then pc = pcv end
  local span = (t - beat) >= (phase=="watchload" and 5 or 15)
  if span then
    beat=t
    local sp = reg("S") % 65536
    local stk={}
    for i=1,24 do stk[#stk+1]=string.format("%02x", r8((sp+i)&65535)) end
    local op={}
    for i=0,5 do op[#op+1]=string.format("%02x", r8(pc+i)) end
    local marks={}
    for i=0,7 do marks[#marks+1]=string.format("%x", r8((LB+0x6d70)+i)) end
    say(string.format("HEART %s %.0f scr=%d fc=%d ph=%d mark=%x ee=%d pc=%06x PB=%x PCv=%x S=%04x X=%x P=%x D=%x DB=%x E=%x op=%s stk=%s steps=%s",
      phase, t, r8(0x3e4), r16(0x@frameCount@), r8(LB+0x6dc6), r16((LB+0x6d68)), r8(0x3ee), pc, pb, pcv, sp, reg("X"), reg("P"), reg("D"), reg("DB"), reg("E"),
      table.concat(op), table.concat(stk), table.concat(marks)))
  end
  if phase=="boot" then
    mem:write_u8((LB+0x6dc0), 0)
    mem:write_u8((LB+0x6dc1), 0)
    mem:write_u8((LB+0x6dc2), 0)
    if mode~="load" then mem:write_u16(0x3e8, 0x5a5a) end
    local ready=r16((LB+0x301e))==1 and r16((LB+0x30de))==3 and r16((LB+0x30d8))==8 and r16((LB+0x30da))==16 and r16((LB+0x6384))==2191 and r16(0x@levelState@)==0 and r16(0x@levelIndex@)==0 and r16(0x@frameCount@)>=1 and r16(0x@frameCount@)<40
    if mode=="load" then
      local scr=r8(0x3e4)
      if scr==2 then
        -- Drop an Esc that the fade queued after the page had already ended.
        w16(0x@inputTail@, r16(0x@inputHead@))
        say(string.format("DRAIN menu %d", r16(0x@inputHead@)))
        phase="menu"
        nav=1
        navWait=0
        say(string.format("MENU slot=%d magic=%02x", r16(0x7ce8), r8(0x7c00)))
      elseif scr==14 or scr==1 or scr==12 or scr==13 then
        if titlePending then
          if r16(0x@inputHead@)~=r16(0x@inputTail@) then
            local h=r16(0x@inputHead@)
            if h>=8 then h=h-8 else h=h+1016 end
            w16(0x@inputHead@, h)
          end
          titlePending=false
        end
        titleTick=titleTick+1
        if titleTick%8==0 and r16(0x@inputHead@)==r16(0x@inputTail@) then
          queue(0x35, false)
          titlePending=true
        end
      end
      return
    end
    if ready then
      mem:write_u16(0x3e8, 0)
      mem:write_u16((LB+0x6d80), 0)
      mem:write_u16((LB+0x6da2), 0)
      mem:write_u16(0x3fa, 0)
      lastSeq=0
      mem:write_u8(0x3ea, 1)
      phase="play"
      playFrames=0
      say(string.format("PLAY %.3f", t))
    elseif t>emuLimit*0.6 then
      fail("boot")
    end
    return
  end
  if phase=="play" then
    playFrames=playFrames+1
    if playFrames==1 then
      -- The skip into the floor never runs LoadSettings, so the settings block is
      -- still the zero image from the disk. A cold boot would throw that image
      -- away and the slot would not select. Stamp the header the menu boot stores.
      -- WriteSettings fills in the checksum.
      if mode=="save" then
        local mag={0x57,0x4f,0x4c,0x46,0x53,0x45,0x54,2}
        for i=1,8 do mem:write_u8(0x7bff+i, mag[i]) end
        say(string.format("MAGIC %02x%02x", r8(0x7c00), r8(0x7c07)))
      end
      local cls,tx,ty=r16((LB+0x30de)), r16((LB+0x30d8)), r16((LB+0x30da))
      local tile=r16((LB+0x6384))
      startHp=r16((LB+0x30e2))
      say(string.format("ACTOR %d %d %d hp=%d door=%d push=%d", cls, tx, ty, startHp, tile, r8((LB+0x834a))))
      if cls~=3 or tx~=8 or ty~=16 or tile~=2191 or startHp==0 then fail("actor layout") return end
    end
    if playFrames==30 then
      local seq=r16((LB+0x6d80))
      say(string.format("SEQ %d hits=%d ea=%d code=%02x%02x%02x%02x", seq, r16((LB+0x6d7e)), r8(0x3ea), r8(0x@LogicWorldRun@), r8(0x@LogicWorldRun+1@), r8(0x@LogicWorldRun+2@), r8(0x@LogicWorldRun+3@)))
      if seq==0 then fail("trace bp") return end
    end
    -- A one-frame pulse misses the game, which samples $3E0 only when a tic is due.
    local cmd=0
    if (playFrames>=USE_DOOR and playFrames<USE_DOOR_END) or (playFrames>=USE_PUSH and playFrames<USE_PUSH_END) then cmd=0x10 end
    if playFrames>=FIRE_AT and playFrames<FIRE_END then cmd=cmd+0x20 end
    mem:write_u8(0x3e0, cmd)
    if playFrames==USE_DOOR_END then
      say(string.format("USED tile=%d btn=%d act=%d pos=%d", r8((LB+0x88f)), r16((LB+0x6d06)), r16((LB+0x6504)), r16((LB+0x6304))))
    end
    if playFrames==DOOR_AT then place(34, 16, 90); say("STEP door") end
    if playFrames==GUARD_AT then
      say(string.format("STEP guard dooract=%d doorpos=%d", r16((LB+0x6504)), r16((LB+0x6304))))
      place(8, 17, 90)
    end
    if playFrames==POKE_AT then
      local hp=r16((LB+0x30e2))
      say(string.format("STEP poke hp=%d ammo=%d", hp, r16((LB+0x6c10))))
      if hp>=startHp then
        say("POKE")
        w16((LB+0x30e2), (startHp-1) & 65535)
        w16((LB+0x30d0), 0xd69c)
        w16((LB+0x30d2), 1)
      end
    end
    if playFrames==PUSH_AT then place(10, 14, 90); say("STEP push") end
    if playFrames==BRANCH then
      local dooract, doorpos=r16((LB+0x6504)), r16((LB+0x6304))
      local pwall, hp=r16((LB+0x6c46)), r16((LB+0x30e2))
      say(string.format("BRANCH door=%d pos=%d wall=%d wpos=%d hp=%d", dooract, doorpos, pwall, r16((LB+0x6c48)), hp))
      -- Live-clock setup may already be closing; retain that serialized state.
      if dooract<0 or dooract>3 or (dooract==1 and doorpos==0) then fail("door not used") return end
      if pwall==0 or pwall>=257 then fail("wall not moving") return end
      if hp>=startHp then fail("guard unhurt") return end
      queueAtFrameStart(0x35)
      phase="menu"
      nav=1
      navWait=0
    end
    return
  end
  if phase=="watch" then
    if armSum and r16(0x3fa)>=armSum+200 then
      song()
      say("PASS continue")
      manager.machine:exit()
    end
    return
  end
  if phase=="menu" then
    local keys=mode=="load" and loadKeys or (mode=="continue" and continueKeys or saveKeys)
    local step=keys[nav]
    if not step then fail("menu overrun") return end
    navWait=navWait+1
    if step.screen then
      if r8(0x3e4)==step.screen then
        if mode~="load" and not pausedFingerprint then
          pausedFingerprint=true
          checksum()
          armSum=r16(0x3fa)
          say(string.format("ARM %d", armSum))
          mem:write_u8((LB+0x6dc0), 1)
          mem:write_u8((LB+0x6dc1), 1)
          if mode=="continue" then mem:write_u8(0x3eb, 1) end
        end
        if step.drain and navWait==1 then
          w16(0x@inputTail@, r16(0x@inputHead@))
          -- Draining an old confirm must not discard its key release.
          queue(0xa4, false)
          queue(0xb5, false)
          say(string.format("DRAIN scr %d", step.screen))
        end
        if navWait>=step.hold then
          nav=nav+1
          navWait=0
          say(string.format("NAV screen %d cur=%d", step.screen, r16(0x116e)))
        end
      elseif navWait>900 then
        fail(string.format("screen %d stuck at %d cur=%d", step.screen, r8(0x3e4), r16(0x116e)))
      end
      return
    end
    if step.untilCur then
      local scr=r8(0x3e4)
      local cur=r16(0x116e)
      if cur==step.untilCur then
        nav=nav+1
        navWait=0
        say(string.format("NAV cur %d", cur))
      elseif scr~=2 or navWait>(step.limit or 180) then
        fail(string.format("cursor %d scr %d", cur, scr))
      end
      return
    end
    if step.phase then
      -- Eighty floppy blocks take longer than the screen waits. 0x114a is
      -- U_DONE and 0x1144 is U_CNT on the menu direct page.
      if r8(LB+0x6dc6)==step.phase then nav=nav+1; navWait=0; say("NAV phase") end
      if navWait%300==0 then
        say(string.format("WRITE done=%d left=%d blk=%d pc=%06x", r16(0x114a), r16(0x1144), r16(0x1142), pc))
      end
      if navWait>18000 then
        fail(string.format("disk phase done=%d left=%d", r16(0x114a), r16(0x1144)))
      end
      return
    end
    if step.wait then
      if navWait>=step.wait then nav=nav+1; navWait=0 end
      return
    end
    if step.key then
      queue(step.key, step.up)
      say(string.format("NAV key %x", step.key))
      nav=nav+1
      navWait=0
      return
    end
    if step.done=="save" then
      say("PASS save")
      manager.machine:exit()
      return
    end
    if step.done=="continue" then
      phase="watch"
      return
    end
    if step.done=="loaded" then
      phase="watchload"
      say("LOADED")
      return
    end
  end
  if phase=="watchload" then
    if not loadT then loadT=t end
    if r8(0x3e4)==4 and t>loadT+75 then fail("slot held") return end
    if r8(0x3eb)==1 and not armed then
      armed=true
      armSum=0
      say("ARM 0")
    end
    if armed and r16(0x3fa)>=200 then
      song()
      say("PASS load")
      manager.machine:exit()
    end
  end
end)
say("ALIVE")
"""


def write_cfg(out):
    (out / "cfg").mkdir(parents=True, exist_ok=True)
    for name in ("state", "nvram", "snap"):
        (out / name).mkdir(parents=True, exist_ok=True)
    (out / "cfg" / "apple2gsr1.cfg").write_text(
        '<mameconfig version="10"><system name="apple2gsr1"><input>'
        '<port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/>'
        '<port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/>'
        '</input></system></mameconfig>'
    )


def run_mame(mode, work, media_args, swap, disk1, drives, seconds, wall, emu):
    write_cfg(work)
    (work / "debug.txt").write_text(DEBUG)
    _, symbols = read(ROOT / "build/wolf.elf")
    # LINEIDS is an equate of line_regions.inc, not a linked symbol: the build's own table.
    symbols.setdefault("LINEIDS", symbols["REGISTERED_LINEIDS" if "EnsureGameplayAssets" in symbols
                                          else "SHAREWARE_LINEIDS"])
    def address(match):
        name, _, offset = match[1].partition("+")
        base = symbols["LOGICBANK"] << 16 if name == "logic" else symbols[name]
        return f"{base + int(offset or '0', 0):x}"
    lua = re.sub(r"@([A-Za-z_][A-Za-z_0-9]*(?:\+(?:0x[0-9a-f]+|[0-9]+))?)@", address, LUA)
    lua = lua.replace("MODE", json.dumps(mode)).replace("DRIVES", str(drives))
    lua = lua.replace("DISK1", json.dumps(disk1)).replace("EMULIMIT", str(emu)).replace("__BRANCH__", str(BRANCH_FRAME))
    lua = lua.replace("__SWAP__", swap or "")
    lua_guard.write(work / "run.lua", lua)
    cmd = [
        "nice", "-n", "20", BINARY, "apple2gsr1",
        "-rompath", ROMPATH, "-ramsize", "4352K",
        *media_args,
        "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo",
        "-seconds_to_run", str(seconds), "-autoboot_delay", "0",
        "-autoboot_script", str(work / "run.lua"),
        "-debug", "-debugger", "none", "-debuglog", "-debugscript", str(work / "debug.txt"),
        "-cfg_directory", str(work / "cfg"),
        "-state_directory", str(work / "state"),
        "-nvram_directory", str(work / "nvram"),
        "-snapshot_directory", str(work / "snap"),
    ]
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["SDL_MAC_BACKGROUND_APP"] = "1"
    live = [line for line in subprocess.run(
        ["pgrep", "-fl", "/iigs.app/Contents/MacOS/iigs"], capture_output=True,
        text=True).stdout.splitlines() if str(ROOT / "build/tests") in line]
    if live:
        raise SystemExit("A main worker MAME process is already running")
    log_path = work / (mode + ".log")
    print(f"RUN {mode} wall={wall}s", flush=True)
    with log_path.open("w") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=work)
        deadline = time.time() + wall
        while proc.poll() is None and time.time() < deadline:
            time.sleep(2)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
            print(f"KILL {mode}", flush=True)
    text = log_path.read_text(errors="replace")
    assert proc.returncode == 0 and "[LUA ERROR]" not in text, text[-3000:]
    dbg = work / "debug.log"
    if dbg.exists():
        lines = dbg.read_text(errors="replace").splitlines()
        bad = [ln for ln in lines if any(w in ln.lower() for w in ("error", "invalid", "unable", "syntax"))]
        if bad:
            text += "\nDBG " + "\nDBG ".join(bad[:30]) + "\n"
    print(f"EXIT {mode} code={proc.returncode} bytes={len(text)}", flush=True)
    return text


def save_blob(path):
    data = Path(path).read_bytes()
    name = b"WOLF.SAVE0"
    for blk in range(2, 6):
        b = data[blk * 512:(blk + 1) * 512]
        for i in range(13):
            e = 4 + i * 39
            ln = b[e] & 0x0F
            if ln != len(name) or bytes(b[e + 1:e + 1 + ln]) != name:
                continue
            aux = b[e + 31] | (b[e + 32] << 8)
            mark = int.from_bytes(data[aux*512:aux*512+2], "little")
            size = 24 * 512                 # GS_BLOCKS: every saved game, one form
            blob = data[aux * 512:aux * 512 + size]
            if len(blob) != size:
                raise SystemExit("short save file")
            return blob[0] | (blob[1] << 8), len(blob), blob
    raise SystemExit("WOLF.SAVE0 is not on the image")


def line_value(text, prefix):
    found = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    return found


def parse_check(text):
    rows = line_value(text, "CHECK ")
    if not rows:
        return None
    p = rows[-1].split()
    return int(p[1]), int(p[2]), p[3:]


def parse_trace(text, arm):
    rows = []
    for ln in text.splitlines():
        parts = ln.split()
        if not parts or parts[0] not in ("W", "P"):
            continue
        try:
            nums = [int(x, 16) for x in parts[1:]]
        except ValueError:
            continue
        rows.append((parts[0], nums))
    kept = []
    acc = 0
    limit = None
    for tag, nums in rows:
        if tag != "W" or len(nums) < 2:
            continue
        sm = nums[1]
        if sm <= arm:
            continue
        if limit is not None and sm > limit:
            break
        acc += nums[0]
        kept.append(sm)
        if acc >= 200 and limit is None:
            limit = sm
    if limit is None:
        return None, acc
    want = set(kept)
    out = []
    for tag, nums in rows:
        if tag == "W" and len(nums) > 1 and nums[1] in want:
            out.append((tag, nums))
        elif tag == "P" and nums and nums[0] in want:
            out.append((tag, nums))
    return out, acc


def busy_ok(text):
    rows = line_value(text, "BUSY ")
    info = []
    bad = []
    for ln in rows:
        p = ln.split()
        # BUSY save 1.234 1
        kind, dt, sign = p[1], float(p[2]), int(p[3])
        info.append((kind, dt, sign))
        if dt >= 2.0:
            want = 1 if kind == "save" else 0
            if sign != want:
                bad.append(ln)
    return info, bad


def shift_trace(rows, arm):
    shifted = []
    for tag, nums in rows:
        nums = list(nums)
        if tag == "W" and len(nums) > 1:
            nums[1] = (nums[1] - arm) & 0xFFFF
        elif tag == "P" and nums:
            nums[0] = (nums[0] - arm) & 0xFFFF
        shifted.append((tag, nums))
    return shifted


def arm_of(text, default=None):
    rows = line_value(text, "ARM ")
    if not rows:
        return default
    return int(rows[-1].split()[1])


def song_ok(text):
    rows = line_value(text, "SONG ")
    if not rows:
        return False
    p = rows[-1].split()
    return p[1] == "3" and p[2] == "3"


def media_setup(kind, dest):
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "hd":
        args, swap = prepare(ROOT / "build" / "wolf-hd.po", dest, drives=2)
        image = dest / "wolf-hd.po"
        return args, swap, image, 0
    drives = 2 if kind == "flop2" else 1
    args, swap = prepare(ROOT / "build" / "disk1.po", dest, drives=drives)
    return args, swap, dest / "disk1.po", drives


def prove(kind):
    base = OUT / kind
    if base.exists():
        raise SystemExit(f"Choose a fresh output directory; already exists: {base}")
    cont = base / "continue"
    live = base / "live"
    args_c, swap_c, image_c, drives = media_setup(kind, cont)
    args_l, swap_l, image_l, drives = media_setup(kind, live)
    emu = 420 if kind == "hd" else 900
    wall = 360 if kind == "hd" else 1800
    seconds = emu + 40
    disk1 = str(image_c if kind != "hd" else image_c)
    # BusyShow insert always reloads this media's disk 1.
    disk_for_prompt = str(image_l)
    cont_log = run_mame("continue", cont, args_c, swap_c, str(image_c), drives, seconds, wall, emu)
    if "PASS continue" not in cont_log:
        tail = "\n".join(cont_log.splitlines()[-30:])
        print(tail)
        print(f"RESULT {kind} FAIL continue")
        return 1
    if not song_ok(cont_log):
        print(f"RESULT {kind} FAIL continue song")
        return 1
    check_c = parse_check(cont_log)
    arm_c = arm_of(cont_log)
    trace_c, acc_c = parse_trace(cont_log, arm_c if arm_c is not None else -1)
    if trace_c is None:
        print(f"RESULT {kind} FAIL continue trace acc={acc_c} arm={arm_c}")
        return 1
    save_log = run_mame("save", live, args_l, swap_l, disk_for_prompt, drives, seconds, wall, emu)
    if "PASS save" not in save_log:
        tail = "\n".join(save_log.splitlines()[-30:])
        print(tail)
        print(f"RESULT {kind} FAIL save")
        return 1
    check_s = parse_check(save_log)
    if check_c is None or check_s is None or check_c != check_s:
        print("continue", check_c)
        print("save", check_s)
        print(f"RESULT {kind} FAIL fingerprint")
        return 1
    mark, nbytes, saved = save_blob(image_l)
    if mark != 0xC0E1:                  # GS_MARKC
        print(f"file mark={mark:#x} bytes={nbytes}")
        print(f"RESULT {kind} FAIL file")
        return 1
    print(f"FILE compact {nbytes} bytes")
    info, bad = busy_ok(save_log)
    if not any(k == "save" for k, _, _ in info) or bad:
        print("busy", info, bad)
        print(f"RESULT {kind} FAIL save busy")
        return 1
    # Same image, cold boot.
    load_log = run_mame("load", live, args_l, swap_l, disk_for_prompt, drives, seconds, wall, emu)
    if "PASS load" not in load_log:
        tail = "\n".join(load_log.splitlines()[-40:])
        print(tail)
        print(f"RESULT {kind} FAIL load")
        return 1
    if not line_value(load_log, "RESTORED_CACHES "):
        print(f"RESULT {kind} FAIL restored caches")
        return 1
    if not song_ok(load_log):
        print(f"RESULT {kind} FAIL load song")
        return 1
    info, bad = busy_ok(load_log)
    if not any(k == "load" for k, _, _ in info) or bad:
        print("busy", info, bad)
        print(f"RESULT {kind} FAIL load busy")
        return 1
    trace_l, acc_l = parse_trace(load_log, 0)
    if trace_l is None:
        print(f"RESULT {kind} FAIL load trace acc={acc_l}")
        return 1
    # The live sum keeps climbing from boot; the loaded sum starts at zero.
    # Compare the distance from each arm so the same 200 tics line up.
    norm_c = shift_trace(trace_c, arm_c or 0)
    norm_l = shift_trace(trace_l, 0)
    # The 200 tics are the world-run records. A cold boot calls ResetTics, so
    # the idle player-tick prints bunch differently and are not the comparison.
    world_c = [row for row in norm_c if row[0] == "W"]
    world_l = [row for row in norm_l if row[0] == "W"]
    if world_c != world_l or acc_c < 200 or acc_l < 200:
        print(f"world {len(world_c)} vs {len(world_l)} acc {acc_c} {acc_l}")
        for i, (a, b) in enumerate(zip(world_c, world_l)):
            if a != b:
                print("first", i, a, b)
                break
        else:
            print("prefix", len(world_c), len(world_l))
        print(f"RESULT {kind} FAIL mismatch")
        return 1
    saves = [ln for ln in save_log.splitlines() if ln.startswith("BUSY ")]
    loads = [ln for ln in load_log.splitlines() if ln.startswith("BUSY ")]
    songs = line_value(load_log, "SONG ")
    print(f"TRACE {kind} lines={len(trace_c)} tics={acc_c}")
    print("BUSY-SAVE", " | ".join(saves))
    print("BUSY-LOAD", " | ".join(loads))
    print("SONG", songs[-1] if songs else "missing")
    poked = "POKE" in cont_log
    print(f"POKE {poked}")
    evidence = dict(media=kind, elf_sha256=hashlib.sha256((ROOT/"build/wolf.elf").read_bytes()).hexdigest(),
                    disk_sha256=hashlib.sha256((ROOT/"build/wolf-hd.po").read_bytes()).hexdigest(),
                    method=__doc__, tics=acc_c, world_records=len(world_c),
                    world_trace=world_c, poked=poked, songs=songs,
                    restored_caches=line_value(load_log, "RESTORED_CACHES "),
                    busy_save=saves, busy_load=loads, exact=True)
    (base / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"RESULT {kind} PASS")
    return 0


def main():
    global OUT, BRANCH_FRAME
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("media", choices=("hd", "flop1", "flop2"))
    p.add_argument("--name", required=True)
    p.add_argument("--branch", type=int, default=BRANCH_FRAME, help="video frame of the pause key while the door and pushwall are moving")
    args = p.parse_args()
    BRANCH_FRAME = args.branch
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        p.error("name must contain only letters, digits, underscores, and hyphens")
    OUT = ROOT / "build/tests" / args.name
    sys.exit(prove(args.media))

if __name__ == "__main__":
    main()
