"""Read exact-logic records into the picture checker's stable object IDs."""
import json
from wolfdata import ROOT
import memmap


def layout(symbols=None):
    base=memmap.world(symbols)
    data = json.loads((ROOT / 'build/assets/logic.json').read_text())
    symbols = {name: base + value for name, value in data['layout'].items()}
    symbols.update(data['fields'])
    symbols.update({'V_' + name: base + data['layout']['VARS'] + 2 * i
                    for i, name in enumerate(data['vars'])})
    symbols["BASE"] = base
    return symbols


def lua(symbols=None):
    constants = 'local LC={' + ','.join('%s=%d' % item for item in layout(symbols).items()) + '}\n'
    return constants + r'''
local function logicObjects()
  local objects={}
  for i=0,549 do objects[i+1]={0,0,65535,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0} end
  local last=s:read_u16(LC.V_laststat)
  for a=LC.STATICS,LC.BASE+last-1,8 do
    local cell=s:read_u16(a)
    local id=(a-LC.STATICS)//8
    objects[id+1]={cell//64*256+128,(cell%64)*256+128,s:read_u16(a+2),s:read_u16(a+6),0,0,0,0,0,0,0,0,0,0,0,0,cell,0}
  end
  local a=s:read_u16(LC.OBJLIST+LC.O_NEXT)
  while a~=0 do
    local b=LC.BASE+a
    local state=LC.BASE+s:read_u16(b+LC.O_STATE)
    local id=400+(b-LC.OBJLIST)//64
    local shape=s:read_u16(state+2)
    if shape==0 then shape=65535 end
    local kind=({[3]=100,[5]=102,[6]=101,[7]=103})[s:read_u16(b+LC.O_CLASS)] or 0
    objects[id+1]={s:read_u16(b+LC.O_X+1),s:read_u16(b+LC.O_Y+1),shape,kind,16,0,0,0,s:read_u16(b+LC.O_DIR),0,0,0,s:read_u16(b+LC.O_TILEX),s:read_u16(b+LC.O_TILEY),0,0,s:read_u16(b+LC.O_MARKED),s:read_u16(state),s:read_u16(b+LC.O_FLAGS)}
    a=s:read_u16(b+LC.O_NEXT)
  end
  return objects
end
local function logicSpawn(x,y,angle)
  local p=LC.OBJLIST
  s:write_u32(p+LC.O_X,x*256);s:write_u32(p+LC.O_Y,y*256)
  s:write_u16(p+LC.O_ANGLE,math.floor(angle*360/1024+0.5)%360)
  s:write_u16(p+LC.O_TILEX,x//256);s:write_u16(p+LC.O_TILEY,y//256)
  local area=s:read_u8(LC.MAP0+(y//256)*64+x//256)-107
  assert(area>=0 and area<37,"spawn must be on an area tile")
  s:write_u16(p+LC.O_AREA,area)
  for i=0,63 do s:write_u8(LC.AREABYPLAYER+i,i==area and 1 or 0) end
end
'''


def actor_visibility_lua(symbols):
    if 'logicActorVisibility' not in symbols:
        return 'local function actorVisibility() return "false" end\n'
    return 'local function actorVisibility() return s:read_u16(%d)~=0 and "true" or "false" end\n'%symbols['logicActorVisibility']
