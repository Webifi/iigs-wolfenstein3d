"""Save Episode 6 through real menus, cold-boot, and restore floor/world/visits.

Read-only native observers capture selected persistent fields at SaveWorldCore
and compare them at gsWorldRestored, before play resumes. No game-state or
input-register injection is used. The longer mid-fight trace is covered by
check_saved_world.py on Episode 1.
"""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from elf import read
from wolfdata import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',required=True)
    a=p.parse_args()
    out=ROOT/'build/tests'/a.name
    out.mkdir(parents=True,exist_ok=False)
    _,s=read(ROOT/'build/wolf.elf')
    logic=json.loads((ROOT/'build/assets/logic.json').read_text())
    names=('difficulty','mapon','lives','health','ammo','weapon','bestweapon',
           'chosenweapon','score','score_hi','oldscore','oldscore_hi',
           'nextextra','nextextra_hi','keys','killcount','secretcount','treasurecount')
    addresses={n:memmap.LOGIC_BASE+logic['layout']['VARS']+2*logic['vars'].index(n) for n in names}
    for n,offset in [('player_x',0),('player_x_hi',2),('player_y',4),('player_y_hi',6),('player_angle',50)]:
        addresses[n]=memmap.LOGIC_BASE+logic['layout']['OBJLIST']+offset
    table='{'+','.join(n+'='+str(v) for n,v in addresses.items())+'}'
    steps={
      'save':'wait=1;sleep=1;key=Esc;wait=2;sleep=1;key=Home;key=Return;wait=19;sleep=1;key=End;key=Return;wait=15;sleep=1;key=Home;key=Return;wait=3;sleep=1;key=Home;key=Return;wait=0;sleep=4;key=F2;wait=4;sleep=1;key=Home;key=Return;sleep=1;key=a;key=Return;sleep=3;key=Esc;wait=2;sleep=1;end=',
      'load':'wait=1;sleep=1;key=Esc;wait=2;sleep=1;key=Down;key=Return;wait=4;sleep=1;key=Home;key=Return;wait=0;sleep=3;snap=restored;end='}
    reports={}
    for mode in ('save','load'):
        folder=out/mode;folder.mkdir()
        script='local fields='+table+'\n'+f'''
local captured=false
stateTap=mem:install_read_tap({s['SaveWorldCore'] if mode=='save' else s['gsWorldRestored']},{s['SaveWorldCore'] if mode=='save' else s['gsWorldRestored']},'registered-save-state',function(ad,d,m)
 if captured or manager.machine:side_effects_disabled() or cpu.state.PC.value~=ad+1 then return end
 captured=true
 assert(mem:read_u16({s['levelIndex']})==50,'wrong registered floor')
 for name,address in pairs(fields) do print('SAVED_FIELD '..name..' '..mem:read_u16(address)) end
 print('VISITED_WORD '..mem:read_u16({s['visitMask']+6}))
end)
'''
        (folder/'observe.lua').write_text(script)
        command=[sys.executable,'tools/ui_test.py','--name',a.name+'/'+mode,'--hd','--seconds','300',
                 '--steps',steps[mode],'--lua',str(folder/'observe.lua')]
        if mode=='load':command+=['--disk',str(out/'save/wolf-hd.po')]
        run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=600)
        (folder/'driver.log').write_text(run.stdout+run.stderr)
        log=(folder/'mame.log').read_text()
        assert run.returncode==0 and '[LUA ERROR]' not in log,log[-4000:]
        rows=dict((n,int(v)) for n,v in re.findall(r'^SAVED_FIELD (\w+) (\d+)$',log,re.M))
        assert len(rows)==len(addresses),log[-4000:]
        assert int(re.search(r'^VISITED_WORD (\d+)$',log,re.M)[1])&4
        reports[mode]=rows
    assert reports['save']==reports['load'],reports
    image=(out/'save/wolf-hd.po').read_bytes()
    block=struct.unpack_from('<H',image,512+436)[0]
    settings=image[block*512:(block+1)*512]
    assert settings[21]==1 and int.from_bytes(settings[16:18]+settings[22:28],'little')&(1<<50)
    report=dict(fields=reports['save'],saved_visited_floor=50,cold_load_exact=True,method=__doc__,
                elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
