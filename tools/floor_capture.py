"""Read-only verification of native floor loads at the first demo packet."""
import hashlib
import json
import struct
from wolfdata import ROOT, PROFILE
from elf import read
import memmap
import wolfsim
from build_weapon_masks import prepared


def lua(out, demo=None, *, floor=None, trigger=0x3f7, value=1):
    if floor is None:
        floor = wolfsim.demo_chunks()[demo]['mapon']
    return registered_lua(out, floor, trigger, value)


def registered_lua(out, floor, trigger, value):
    """Read every prepared art byte after the real load/view transition."""
    from build_logic import RAW_PLANES_ADDRESS
    from registered_loads import art_rows
    folder = ROOT/'build/levels'/str(floor)
    _, symbols = read(ROOT/'build/wolf.elf')
    checks = art_rows(floor)
    checks += [dict(file=str(folder/'source-planes.bin'), address=RAW_PLANES_ADDRESS),
               dict(file=str(folder/'spriteFrame.bin'), address=symbols['spriteFrame'])]
    rows = ','.join('{%s,%d}' % (json.dumps(str(ROOT/r['file'])), r['address']) for r in checks)
    return '''
local assetsChecked=false
assetTap=s:install_write_tap(@TRIGGER@,@TRIGGER@,"registered-loaded-assets",function(a,d,m)
  if d~=@VALUE@ or assetsChecked or s:read_u16(@LEVELINDEX@)~=@FLOOR@ then return end
  assetsChecked=true
  local failures,total=0,0
  for _,check in ipairs({@CHECKS@}) do
    local f=assert(io.open(check[1],"rb"));local data=f:read("*a");f:close()
    local count,first=0,nil
    for i=1,#data do
      if s:read_u8(check[2]+i-1)~=data:byte(i) then count=count+1;first=first or i-1 end
    end
    print(string.format("ASSET %06x %d differences first %s",check[2],count,tostring(first)))
    failures=failures+count;total=total+#data
  end
  print(string.format("ASSETS_DONE %d %d",failures,total));io.stdout:flush()
end)
'''.replace('@CHECKS@', rows).replace('@TRIGGER@', str(trigger)).replace('@VALUE@', str(value)).replace('@LEVELINDEX@', str(symbols['levelIndex'])).replace('@FLOOR@', str(floor))
