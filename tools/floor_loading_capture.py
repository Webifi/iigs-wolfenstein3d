"""Passive display checks for real elevator/tally/floor-load routes.

The route fixture supplies positions and input. This observer changes no game
state: it checks every display write while a runtime loading box owns the view.
"""
import memmap
import json
import re

LUA = memmap.fill(r'''
do
local armed=false
local tallyVisible=false
local serial=0
local busy=nil
local function dump(tag)
 local parts={};for i=0,32767 do parts[#parts+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(OUT..string.format('/load-%02d-%s.shr',serial,tag),'wb'))
 f:write(table.concat(parts));f:close()
end
local function tap(addr,name,fn)
 mem:install_read_tap(addr,addr,name,function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==(a>>16) and cpu.state.PC.value==a+1 then fn() end
 end)
end
local function checkFill()
 if not busy or mem:read_u16(KIND)~=0 then return end
 local pixels=mem:read_u16(PIXELS)
 for y=109,111 do
  local n=0
  for x=0,159 do
   local b=mem:read_u8(@MM:SHR@+y*160+40+x//2)
   local ink=x%2==0 and b>>4 or b&15
   if ink==1 then n=n+1 end
  end
  if n~=pixels then busy.bad_fill=busy.bad_fill+1 end
 end
 busy.fills=busy.fills+1
 if not busy.closing then busy.work_pixels=math.max(busy.work_pixels,pixels) end
end
local function checkNeutral()
 if not busy or not busy.tally then return end
 for y=83,116 do
  local pal=@MM:SHR_PAL@+(mem:read_u8(@MM:SHR_SCB@+y)&15)*32
  for x=35,124 do
   local b=mem:read_u8(@MM:SHR@+y*160+x)
   for _,i in ipairs({b>>4,b&15}) do
    local c=mem:read_u16(pal+i*2)
    local r,g,b=(c>>8)&15,(c>>4)&15,c&15
    if math.max(r,g,b)-math.min(r,g,b)>2 then busy.chromatic=busy.chromatic+1 end
   end
  end
 end
 busy.neutralChecks=busy.neutralChecks+1
end
local function close(restored)
 if not busy then return end
 local wrong=0
 if restored then
  for i=0,32767 do
   if (i<32000 or (i>=32000 and i<32200) or i>=32256) and mem:read_u8(@MM:SHR@+i)~=busy.before[i] then wrong=wrong+1 end
  end
 end
 dump(restored and 'restored' or 'finished')
 print(string.format('TALLY_LOADING_INK {"number":%d,"checks":%d,"chromatic_pixels":%d}',serial,busy.neutralChecks,busy.chromatic))
 print(string.format('FLOOR_LOADING {"number":%d,"floor":%d,"seconds":%.6f,"palette_changes":%d,"scb_changes":%d,"outside_pixel_changes":%d,"fill_checks":%d,"bad_fill_rows":%d,"work_pixels":%d,"final_pixels":%d,"restored":%s,"restore_differences":%d}',serial,busy.floor,now()-busy.start,busy.palette,busy.scb,busy.outside,busy.fills,busy.bad_fill,busy.work_pixels,mem:read_u16(PIXELS),tostring(restored),wrong))
 busy=nil
end
tap(TALLY,'elevator-loading-arm',function() armed=true;tallyVisible=false end)
tap(TALLY_REVEAL,'elevator-tally-visible',function() tallyVisible=true end)
tap(SHOW,'elevator-loading-show',function()
 if not armed or busy or mem:read_u16(BOOT)==0 then return end
 serial=serial+1
 busy={before={},start=now(),floor=mem:read_u16(FLOOR),palette=0,scb=0,outside=0,fills=0,bad_fill=0,work_pixels=0,closing=false,tally=tallyVisible,neutralChecks=0,chromatic=0}
 for i=0,32767 do busy.before[i]=mem:read_u8(@MM:SHR@+i) end
 assert(mem:read_u16(BLACK)==0,'elevator fixture must exercise loading over a visible picture')
 dump('before')
end)
tap(READY,'elevator-loading-ready',function() if busy then dump('ready');checkNeutral() end end)
tap(PIXELS_OUT,'elevator-loading-fill',checkFill)
tap(FINISH,'elevator-loading-finish',function() if busy then busy.closing=true;dump('work-done');checkNeutral() end end)
tap(HIDE_DONE,'elevator-loading-hidden',function() close(true) end)
tap(FORGOT,'elevator-loading-forgotten',function() close(false) end)
mem:install_write_tap(@MM:SHR@,@MM:SHR_PAL+0x1ff@,'elevator-loading-display',function(a,d,m)
 if not busy then return end
 local offset=a-@MM:SHR@
 if d==busy.before[offset] then return end
 if offset>=32256 then busy.palette=busy.palette+1
 elseif offset>=32000 and offset<32200 then busy.scb=busy.scb+1
 elseif offset<32000 then
  local y=offset//160;local x=offset%160
  if not(y>=83 and y<117 and x>=35 and x<125) then
   busy.outside=busy.outside+1
   if busy.outside<=3 then print(string.format('LOADING_OUTSIDE %06x %06x %02x',cpu.state.PC.value,a,d)) end
  end
 end
end)
end
''')


def lua(symbols, out):
    names = dict(TALLY='TallyOpen', TALLY_REVEAL='TallyReveal', SHOW='BusyShow', READY='busySuppressed',
                 BOOT='bootComplete', FLOOR='levelIndex', BLACK='screenBlack',
                 KIND='busyKind', PIXELS='busyProgress', PIXELS_OUT='pixelsOut',
                 FINISH='ProgressFinish', HIDE_DONE='hideDone', FORGOT='busyForgot')
    script = LUA
    for token, name in names.items():
        script = re.sub(r'\b'+token+r'\b', str(symbols[name]), script)
    return script.replace('OUT', json.dumps(str(out)))


def check(log):
    loads = [json.loads(row) for row in re.findall(r'^FLOOR_LOADING (.*)$', log, re.M)]
    ink = [json.loads(row) for row in re.findall(r'^TALLY_LOADING_INK (.*)$', log, re.M)]
    assert any(row['checks'] for row in ink), 'no loading ink checked over the tally'
    assert all(row['chromatic_pixels']==0 for row in ink), ink
    assert len(loads) >= 2, 'cold intermission song and next-floor loading were not both observed'
    for load in loads:
        load['ink'] = next(row for row in ink if row['number']==load['number'])
        assert all(load[k] == 0 for k in ('palette_changes', 'scb_changes',
                   'outside_pixel_changes', 'bad_fill_rows', 'restore_differences')), load
        assert load['fill_checks'] > 0 and 0 < load['work_pixels'] <= 160, load
        assert load['final_pixels'] == 160, load
    assert any(load['restored'] for load in loads), 'song overlay was not restored'
    assert any(not load['restored'] for load in loads), 'floor overlay was not completed'
    return loads
