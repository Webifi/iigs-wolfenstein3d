"""Native canary for the 32 KiB released by direct SHR rendering."""
import memmap


def lua(symbols):
    return memmap.fill(r'''
local freeRamArmed=false
local freeRamSeeded=false
local freeRamWriteCount=0
local function freeRamByte(i) return ((i*73) ~ (i>>8) ~ 0xa5)&255 end
freeRamStart=mem:install_read_tap(@START@,@START@,'free-screen-ram-start',function(a,d,m)
 if freeRamArmed or manager.machine:side_effects_disabled() then return end
 if cpu.state.PB.value~=(a>>16) or cpu.state.PC.value~=a+1 then return end
 assert((mem:read_u8(@MM:SHADOW@)&8)~=0,'SHR shadowing is enabled')
 if not freeRamSeeded then
  for i=0,32767 do mem:write_u8(@MM:WALL_COLUMNS@+i,freeRamByte(i)) end
  freeRamSeeded=true
  return
 end
 -- MAME delivers nested write taps after this read callback. Arm on the
 -- following clearDP iteration so the canary's own writes are excluded.
 freeRamArmed=true
end)
freeRamWrites=mem:install_write_tap(@MM:WALL_COLUMNS@,@MM:SHR_SHADOW+0x7fff@,'free-screen-ram-write',function(a,d,m)
 if freeRamArmed then freeRamWriteCount=freeRamWriteCount+1 end
end)
function checkFreeScreenRam()
 assert(freeRamArmed,'free RAM canary was not armed')
 assert(freeRamWriteCount==0,'reclaimed RAM received '..freeRamWriteCount..' writes')
 assert((mem:read_u8(@MM:SHADOW@)&8)~=0,'SHR shadowing is enabled')
 for i=0,32767 do
  assert(mem:read_u8(@MM:WALL_COLUMNS@+i)==freeRamByte(i),'reclaimed RAM canary changed')
 end
 print('FREE_SCREEN_RAM_OK 32768')
end
''').replace('@START@', str(symbols['clearDP']))
