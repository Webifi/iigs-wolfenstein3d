"""Selected native demo pictures in the independent ray checker's format."""
import memmap
import json
from pathlib import Path
import logic_capture
from memmap import projections
from wolfdata import ROOT


def lua(symbols, frames, out):
    game_names=('health','ammo','keys','lives','score','killCount','weapon','chosenWeapon','bestWeapon','weaponFrame','levelState','levelIndex','pwallPosition')
    script=logic_capture.lua(symbols)+logic_capture.actor_visibility_lua(symbols)+memmap.fill(r'''
local captures=@FRAMES@
local function capturePicture(n)
  if not captures[n] then return end
  local function binary(name,base,count)
    local data={};for i=0,count-1 do data[#data+1]=string.char(s:read_u8(base+i)) end
    local f=io.open(@OUT@..'/'..name..n..'.bin','wb');f:write(table.concat(data));f:close()
  end
  binary('frame',@MM:SHR@,25600);binary('hud',@MM:SHR+0x6400@,6400);binary('map',@MM:MAP@,4096)
  local game={}
  for _,field in ipairs(@GAME@) do
    local v=field[1]=='score' and s:read_u32(field[2]) or s:read_u16(field[2])
    game[#game+1]='"'..field[1]..'":'..v
  end
  local doors={};for i=0,s:read_u16(@DOORCOUNT@)//2-1 do doors[#doors+1]=s:read_u16(@DOORS@+i*2) end
  local f=io.open(@OUT@..'/state'..n..'.json','w')
  f:write(string.format('{"x":%d,"y":%d,"angle":%d,"view_width":%d,"doors":[%s],"game":{%s},"actor_flags":%s}',s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004),s:read_u16(@VIEW@),table.concat(doors,','),table.concat(game,','),actorVisibility()));f:close()
  local objects={};for _,o in ipairs(logicObjects()) do objects[#objects+1]='['..table.concat(o,',')..']' end
  local visible={}
  for i=0,s:read_u16(0x107c)-1 do
    local fields={};for j=0,6 do fields[#fields+1]=s:read_u16(@RECORDS@+i*16+j*2) end
    visible[#visible+1]='['..table.concat(fields,',')..']'
  end
  local f=io.open(@OUT@..'/objects'..n..'.json','w');f:write('{"objects":['..table.concat(objects,',')..'],"visible":['..table.concat(visible,',')..']}');f:close()
  local posts={}
  for c=0,s:read_u16(@VIEW@)-1 do posts[#posts+1]=string.format('[%d,%d,%d,%d]',s:read_u16(@HEIGHT@+c*2),s:read_u16(@ADDR@+c*2),s:read_u16(@BANK@+c*2),s:read_u16(@PLANE@+c*2)) end
  local f=io.open(@OUT@..'/posts'..n..'.json','w');f:write('['..table.concat(posts,',')..']');f:close()
end
''')
    values={'FRAMES':'{'+','.join('[%d]=true'%n for n in frames)+'}','OUT':json.dumps(str(out)),
            'GAME':'{'+','.join('{'+json.dumps(n)+','+str(symbols[n])+'}' for n in game_names)+'}'}
    for token,name in {'DOORCOUNT':'doorBytes','DOORS':'doorPosition','VIEW':'viewWidth','HEIGHT':'heightIndex','ADDR':'sourceAddr','BANK':'sourceBank','PLANE':'hitPlane'}.items():values[token]=str(symbols[name])
    values['RECORDS']=str(projections(symbols)[0])
    for token,value in values.items():script=script.replace('@'+token+'@',value)
    return script


def metadata(symbols):
    labels=dict(unwrapped_rays='sameMaterial',material_lookup='resolveRayMaterial',coarse_material='nearbyMaterial',vector_weights='weightedSpanVector',split_span='prepareSplitSpan',mixed_span='prepareMixedSpan',weighted_span='fillWeightedSpan',weighted_rays='weightedRay',plane_rays='planeRay',door_planes='movingWallPlane',push_planes='pushPlane',span_fill='fillRaySpan')
    result={key:name in symbols for key,name in labels.items()}
    result['material_guard_texels']=0
    mode=(ROOT/'build/gen/ray_mode.inc').read_text()
    result['rays']='exact' if 'WOLF_EXACT_RAYS 1' in mode else 'sixteenth' if 'WOLF_RAY_STRIDE 16' in mode else 'eighth' if 'WOLF_RAY_STRIDE 8' in mode else 'quarter' if 'WOLF_QUARTER_RAYS 1' in mode else 'half'
    return result
