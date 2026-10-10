"""Use Esc from title/game menus and verify the saved game picture is restored."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
import music_capture

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    ap.add_argument('--benchmark', action='store_true', help='finish demo 0 from the in-game Options screen')
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, sym = read(ROOT/'build/wolf.elf')
    observer = music_capture.lua()+memmap.fill(r'''
local snapshot=nil
local regions={{@MM:SHR@,32000},{@MM:SHR_SCB@,200},{@MM:SHR_PAL@,512}}
menuCaptureTap=mem:install_read_tap(@CAPTURE@,@CAPTURE@,'menu-capture',function(a,d,m)
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=@CAPBANK@ then return end
 snapshot={}
 for _,r in ipairs(regions) do for i=0,r[2]-1 do snapshot[r[1]+i]=mem:read_u8(r[1]+i) end end
end)
menuRestoreTap=mem:install_read_tap(@KEEP@,@KEEP@,'menu-restored',function(a,d,m)
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 then return end
 assert(snapshot,'no captured game picture')
 local changed=0
 for address,value in pairs(snapshot) do if mem:read_u8(address)~=value then changed=changed+1 end end
 print('MENU_RESTORED '..changed)
 assert(changed==0,'menu return changed the saved picture')
 snapshot=nil
end)
CALLS={}
CALLS.dim=function()
 local grays={0x000,0x222,0x666,0x888,0x444,0x555}
 for i=0,5 do assert(mem:read_u16(@MM:SHR_PAL@+15*32+i*2)==grays[i+1],'wrong menu gray color') end
 assert(mem:read_u16(@DIM@)==1,'game menu backdrop is not active')
 print('MENU_GRAY_OK')
end
CALLS.benchmark=function()
 assert(mem:read_u16(@FRAMES@)==1055,'benchmark did not finish demo 0')
 assert(mem:read_u16(@FROMDIM@)==1,'benchmark lost the menu backdrop flag')
 print('MENU_BENCHMARK_OK')
end
''')
    for key, value in dict(CAPBANK=sym['SnapMeta']>>16, CAPTURE=sym['SnapMeta'], KEEP=sym['UiKeepView'], DIM=sym['menuDim'],
                           FRAMES=sym['benchFrames'], FROMDIM=sym['benchFromDim']).items():
        observer=observer.replace('@'+key+'@',str(value))
    (out/'observe.lua').write_text(observer)
    steps=['wait=1','sleep=1','key=Space','wait=2','sleep=0.5','snap=title-menu',
           'key=Esc','wait=1','sleep=1','snap=title-return','key=Return','wait=2',
           'sleep=1','key=Return','wait=15','sleep=1','key=Return','wait=3','sleep=0.5','key=Return','wait=0',
           'sleep=1','key=Esc','wait=2','sleep=1','call=dim','snap=game-menu',
           'key=Down','key=Down','key=Down','key=Return','wait=7','sleep=0.5','snap=options',
           'key=Esc','wait=2','sleep=0.5','key=Esc','wait=0','sleep=0.5','snap=game-return','end=']
    if args.benchmark:
        at=steps.index('snap=options')+1
        steps[at:at]=['key=Down']*2+['key=Return','sleep=0.5','key=Y','wait=10',
                      'wait=11','sleep=0.5','call=benchmark','snap=benchmark-result',
                      'key=Return','wait=7','sleep=0.5','call=dim','snap=benchmark-options']
    run=subprocess.run([sys.executable,'tools/ui_test.py','--name',args.name,'--hd',
                        '--seconds','360' if args.benchmark else '180',
                        '--steps',';'.join(steps),'--lua',str(out/'observe.lua')],
                       cwd=ROOT,capture_output=True,text=True,timeout=750)
    (out/'driver.log').write_text(run.stdout+run.stderr)
    log=(out/'mame.log').read_text()
    assert run.returncode==0 and 'TIMEOUT' not in log and 'MENU_GRAY_OK' in log,log[-2500:]
    assert re.findall(r'^MENU_RESTORED (\d+)$',log,re.M)==['0','0'],log[-2500:]
    songs=music_capture.events(log)
    expected=[7,3]
    assert [s['song'] for s in songs]==expected,songs
    if args.benchmark:
        assert 'MENU_BENCHMARK_OK' in log,log[-2500:]
    result=dict(disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),
                elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                machine='apple2gsr1',ramsize='4352K',restored_bytes=32712,
                differing_bytes=0,gray_menu=True,songs=songs,glu_violations=0,
                benchmark_frames=1055 if args.benchmark else None)
    (out/'return.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
