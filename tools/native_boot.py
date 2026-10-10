"""Real ADB menu keys to start a game after normal settings loading."""

BOOT = r'''
local keys={{1,'Esc'},{2,'Return'},{15,'Return'},{3,'Return'}}
local keyStep,keyAt,keyHeld=1,nil,nil
local function field(name)
 for _,port in pairs(manager.machine.ioport.ports) do for _,f in pairs(port.fields) do if f.name==name then return f end end end
 error('missing key '..name)
end
emu.register_frame_done(function()
 local step=keys[keyStep];if not step then return end
 local t=manager.machine.time:as_double()
 if keyHeld then
  if t-keyAt>0.12 then keyHeld:set_value(0);keyHeld=nil;keyAt=nil;keyStep=keyStep+1 end
 elseif s:read_u8(0x3e4)==step[1] then
  if not keyAt then keyAt=t end
  if t-keyAt>1 then keyHeld=field(step[2]);keyHeld:set_value(1);keyAt=t end
 else keyAt=nil end
end)
'''
