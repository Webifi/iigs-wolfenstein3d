"""The first lines of every MAME script that the tools write: taps and notifier subscriptions are kept and removed at machine stop.

MAME closes its Lua state before it destroys the address spaces. Anything that still holds a Lua function
at that moment calls luaL_unref on a dead state and the process dies with SIGSEGV at exit (a crash report
in ~/Library/Logs/DiagnosticReports). So the guard keeps every handle that install_read_tap and
install_write_tap return and every subscription that emu.add_machine_*_notifier returns, and removes and
unsubscribes them all in a machine stop notifier. No script may call emu.wait after the stop notice; none does.
add_change_notifier is refused: its listener stays in the address space even after unsubscribe(). A script
that needs a tap after a memory map change calls tap:reinstall() from emu.add_machine_frame_notifier.

Write every script with write(path, text), or call guard(text) on a script that is built another way.
"""

MARK = '-- tools/lua_guard.py:'

PRELUDE = '''-- tools/lua_guard.py: taps and subscriptions are kept and removed at machine stop; add_change_notifier is refused
GUARD_TAPS={}
GUARD_SUBS={}
do
 local space=manager.machine.devices[":maincpu"].spaces["program"]
 local mt=getmetatable(space)
 local index=mt.__index
 mt.__index=function(self,key)
  local f=index(self,key)
  if key=="install_read_tap" or key=="install_write_tap" or key=="install_readwrite_tap" then
   return function(obj,...)
    local tap=f(obj,...)
    GUARD_TAPS[#GUARD_TAPS+1]=tap
    return tap
   end
  elseif key=="add_change_notifier" then
   return function() error("add_change_notifier is not allowed (MAME exit crash): call tap:reinstall() from emu.add_machine_frame_notifier") end
  end
  return f
 end
 for _,name in ipairs({"add_machine_reset_notifier","add_machine_pause_notifier","add_machine_resume_notifier","add_machine_frame_notifier"}) do
  local add=emu[name]
  if add then
   emu[name]=function(...)
    local sub=add(...)
    GUARD_SUBS[#GUARD_SUBS+1]=sub
    return sub
   end
  end
 end
 GUARD_STOP=emu.add_machine_stop_notifier(function()
  for _,sub in ipairs(GUARD_SUBS) do pcall(function() sub:unsubscribe() end) end
  GUARD_SUBS={}
  for _,tap in ipairs(GUARD_TAPS) do pcall(function() tap:remove() end) end
  GUARD_TAPS={}
 end)
end
'''


def guard(text):
    """The script text with the prelude in front, once."""
    if MARK in text:
        return text
    import os
    from pathlib import Path
    observer = os.environ.get('WOLF_LOADING_TRACE')
    return PRELUDE + (Path(observer).read_text() if observer else '') + text


def write(path, text):
    """Write a script file that MAME runs with -autoboot_script."""
    path.write_text(guard(text))
