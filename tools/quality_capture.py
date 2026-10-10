"""Write-only SHR capture and intermediate-write checks for demo quality review."""
import memmap
LUA=memmap.fill(r'''
local qualityBytes, qualityKnown = {}, {}
local qualityShadow=255
local qualityOn=false
local qualityWrites={}
local qualityFile=nil
s:install_write_tap(0x3f0,0x3f0,"quality-reset",function(a,d,m) if d==1 then qualityWrites={} end end)
s:install_write_tap(@MM:SHADOW@,@MM:SHADOW@,"quality-shadow",function(a,d,m) qualityShadow=d end)
s:install_write_tap(@MM:SHADOW_00@,@MM:SHADOW_00@,"quality-shadow0",function(a,d,m) qualityShadow=d end)
s:install_write_tap(0x3f3,0x3f3,"quality-phase",function(a,d,m) qualityOn=d==1 end)
local function qualityWrite(a,d)
 local off=a-@MM:SHR@; local v=d&255
 if qualityOn and off<32000 then
  local q=qualityWrites[off]
  if not q then q={old=qualityBytes[off],values={}};qualityWrites[off]=q end
  q.values[#q.values+1]=v
 end
 qualityBytes[off]=v;qualityKnown[off]=true
end
s:install_write_tap(@MM:SHR@,@MM:SHR_PAL+0x1ff@,"quality-screen",function(a,d,m) qualityWrite(a,d) end)
s:install_write_tap(@MM:WALL_COLUMNS@,@MM:SHR_SHADOW+0x7fff@,"quality-mirror",function(a,d,m)
 if (qualityShadow&8)==0 then qualityWrite(@MM:BANK_E1@|(a&65535),d) end
end)
local function qualityCapture(n)
 if not qualityFile then qualityFile=assert(io.open("@OUT@/frames.shr","wb")) end
 local parts={};local wrong,exposed=0,0
 for off,q in pairs(qualityWrites) do
  local final=qualityBytes[off];local w,e=false,false
  for _,v in ipairs(q.values) do
   if v~=final then e=true;if v~=q.old then w=true end end
  end
  if w then wrong=wrong+1 end;if e then exposed=exposed+1 end
 end
 for i=0,32767 do
  if i<32000 then assert(qualityKnown[i],"uninitialized screen byte "..i) end
  parts[#parts+1]=string.char(qualityBytes[i] or 0)
 end
 qualityFile:write(table.concat(parts));qualityWrites={}
 print(string.format("QUALITY %d %d %d",n,wrong,exposed))
end
emu.add_machine_stop_notifier(function() if qualityFile then qualityFile:close();qualityFile=nil end end)
''')
def install(script):
 script=script.replace('local function dump()',LUA+'\nlocal function dump()',1)
 return script.replace('    dump()','    qualityCapture(frames+1)\n    dump()',1)
