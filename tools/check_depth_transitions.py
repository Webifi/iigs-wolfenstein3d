"""Observe height/gray overlay ownership through menus, resizing and a benchmark.

Uses real ADB menu keys. RAM observers never supply game state or replace the
height table. The completed stock benchmark also exercises relocated CPU info.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from elf import read
from wolfdata import ROOT
from viewgeometry import SIZES
import memmap


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--baseline-khz',type=int,required=True,
                        help='unchanged build measured with the same emulator and stock machine')
    args=parser.parse_args()
    out=ROOT/'build/tests'/args.name
    out.mkdir(parents=True,exist_ok=True)
    _,symbols=read(ROOT/'build/wolf.elf')
    tables=[]
    for view in SIZES:
        path=ROOT/f'build/assets/view-height-{view}.bin'
        tables.append(json.dumps(str(path)))
    script='local S={'+','.join(n+'='+str(symbols[n]) for n in
                              ('heightView','weaponViewIndex','castFrame','cpuKHz','cpuCard'))+'}\n'
    script+='local TABLE='+str(memmap.HEIGHT_TABLE)+'\nlocal files={'+','.join(tables)+'}\n'
    script+=r'''
local expected={}
for i,path in ipairs(files) do
 local f=assert(io.open(path,'rb'));expected[(i-1)*2]=f:read('*a');f:close()
end
local restored,borrowed,casts=0,0,0
local previous=65535
local seen={}
mem:install_write_tap(S.heightView+1,S.heightView+1,'height-owner',function(a,d,m)
 if manager.machine:side_effects_disabled() then return end
 local view=mem:read_u8(S.heightView)|(d<<8)
 if view==65535 then
  if previous~=65535 then borrowed=borrowed+1 end
 elseif expected[view] then
  local raw=expected[view]
  for n=1,#raw do assert(mem:read_u8(TABLE+n-1)==raw:byte(n),'height table differs at '..n) end
  restored=restored+1;seen[view]=true
  print('HEIGHT_RESTORED '..view..' '..restored)
 end
 previous=view
end)
mem:install_read_tap(S.castFrame,S.castFrame,'height-before-cast',function(a,d,m)
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=a>>16 or cpu.state.PC.value~=a+1 then return end
 assert(mem:read_u16(S.heightView)==mem:read_u16(S.weaponViewIndex),'cast used menu gray pixels as heights')
 casts=casts+1
end)
CALLS.cpu=function()
 local khz=mem:read_u16(S.cpuKHz);local card=mem:read_u16(S.cpuCard)
 assert(card==0 and math.abs(khz-BASELINE_KHZ)<=BASELINE_KHZ*0.01,'stock CPU result '..card..' '..khz)
 print('DEPTH_CPU '..card..' '..khz)
end
CALLS.done=function()
 assert(restored>=6 and borrowed>=2 and casts>100,'overlay lifecycle not exercised')
 for _,v in ipairs({0,2,4,6}) do assert(seen[v],'missing view '..v) end
 print(string.format('DEPTH_TRANSITIONS {"restores":%d,"menu_borrows":%d,"casts":%d}',restored,borrowed,casts))
end
'''
    observer=out/'observe.lua';observer.write_text(script.replace('BASELINE_KHZ',str(args.baseline_khz)))
    steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=0.4','snap=title-menu',
           'key=Return','wait=15','sleep=0.3','key=Return','wait=3','sleep=0.3',
           'key=Return','wait=0','sleep=1']
    for key in ('Equals','Equals','Minus','Minus','Minus'):
        steps+=['key='+key,'sleep=1.2']
    steps+=['key=Esc','wait=2','sleep=0.4','snap=paused',
            'key=Esc','wait=0','sleep=1.2','snap=menu-resumed',
            'key=Esc','wait=2','sleep=0.4','key=Home','key=Down','key=Down','key=Down','key=Return','wait=7','sleep=0.4',
            'key=Down','key=Down','key=Return','sleep=0.3','key=Y','wait=10',
            'wait=11','sleep=0.3','call=cpu','snap=benchmark','key=Return','wait=7',
            'key=Esc','wait=2','key=Esc','wait=0','sleep=1','call=done','snap=resumed','end=']
    cmd=[sys.executable,'tools/ui_test.py','--name',args.name,'--hd','--debug',
         '--seconds','260','--lua',str(observer),'--steps',';'.join(steps)]
    run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=600)
    (out/'driver.log').write_text(run.stdout+run.stderr)
    log=(out/'mame.log').read_text()
    results=re.findall(r'^DEPTH_TRANSITIONS (.*)$',log,re.M)
    assert run.returncode==0 and len(results)==1 and '[LUA ERROR]' not in log,log[-4000:]
    result=json.loads(results[0])
    result.update(cpu=json.loads('['+','.join(re.search(r'^DEPTH_CPU (\d+) (\d+)$',log,re.M).groups())+']'),
                  machine='apple2gsr1',ram='4352K',baseline_khz=args.baseline_khz,
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
