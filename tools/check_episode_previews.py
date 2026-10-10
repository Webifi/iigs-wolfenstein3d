"""Check source episode illustrations with real native menu input and game return."""
import memmap
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from elf import read
from wolfdata import ROOT, PROFILE
from frontend.native_assets import unpack_block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mame', required=True, type=Path, help='J13 matrix capable emulator')
    parser.add_argument('--name', default='episode-previews-native')
    args = parser.parse_args()
    name = args.name
    out = ROOT/'build/tests'/name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT/'build/wolf.elf')
    for glyphs, bank in (('steelGlyphs',0x0f),('mediumGlyphs',0x0f),('smallGlyphs',0x3f)):
        assert symbols[glyphs]>>16==bank,(glyphs,hex(symbols[glyphs]),'font bank table mismatch')
    count = len(PROFILE.campaign.document['episode_menu_order'])
    assert count > 1
    callbacks = []
    checks = []
    def capture(label, episode):
        checks.append((label, episode))
        callbacks.append(f'''CALLS[{json.dumps(label)}]=function()
 if not ready then return false end
 assert(mem:read_u8(0x3e4)==19,'episode page')
 assert(mem:read_u16(0x116e)=={episode},'episode selection')
 local b={{}};for i=0,32767 do b[#b+1]=string.char(mem:read_u8({memmap.SHR}+i)) end
 local f=assert(io.open(OUT..'/{label}.shr','wb'));f:write(table.concat(b));f:close()
 print('EPISODE {label}');io.stdout:flush()
end''')
        return 'call='+label
    steps=['wait=1','sleep=1','key=Esc','wait=2','sleep=0.3','key=Return','wait=19']
    steps += [capture('episode-1',0)]
    for i in range(1,count):
        steps += ['key=Down',capture(f'episode-{i+1}',i)]
    steps += ['key=Return','wait=15','call=menu-ready','snap=episode-six-floors','key=Esc','wait=2',
              'sleep=0.3','key=Return','wait=19',
              capture('episode-six-reopened',count-1),'key=Down',capture('episode-one-returned',0),
              'key=Return','wait=15','call=menu-ready','key=Return','wait=3','call=menu-ready',
              'key=Return','wait=0','sleep=1','key=Esc','wait=2','sleep=0.3','key=Return','wait=19',
              capture('episode-one-from-game',0),'key=Esc','wait=2','sleep=0.3',
              'key=Esc','wait=0','sleep=1','snap=game-return','end=']
    steps=[('key=J13 '+('Escape' if step[4:]=='Esc' else step[4:]))
           if step.startswith('key=') else step for step in steps]
    lua='''CALLS={}
local ready=false
local readyTap=mem:install_read_tap(READY,READY,'episode-menu-ready',function(a,d,m)
 if cpu.state.PC.value==a+1 then ready=true end
end)
local keyTap=mem:install_read_tap(KEY,KEY,'episode-key',function(a,d,m)
 if cpu.state.PC.value==a+1 then ready=false end
end)
-- The screen ID changes before drawing finishes. Wait for the actual input
-- loop before pressing through a freshly drawn floor or difficulty menu.
CALLS['menu-ready']=function() return ready end
'''
    for key,value in dict(OUT=json.dumps(str(out)),READY=symbols['GetKey'],KEY=symbols['keyDown']).items():
        lua=re.sub(r'\b'+key+r'\b',lambda m:str(value),lua+'\n'+'\n'.join(callbacks) if key=='OUT' else lua)
    (out/'observer.lua').write_text(lua)
    result=subprocess.run([sys.executable,'tools/ui_test.py','--name',name,'--mame',str(args.mame),'--hd','--debug','--j13','only',
        '--seconds','350','--lua',str(out/'observer.lua'),'--steps',';'.join(steps)],cwd=ROOT,
        capture_output=True,text=True,timeout=600)
    (out/'driver.log').write_text(result.stdout+result.stderr)
    log=(out/'mame.log').read_text()
    assert result.returncode==0 and '[LUA ERROR]' not in log and 'TIMEOUT' not in log,log[-2500:]
    assert re.findall(r'^EPISODE (\S+)',log,re.M)==[name for name,_ in checks],log[-2500:]
    for label,index in checks:
        screen=(out/f'{label}.shr').read_bytes()
        record=(ROOT/f'build/assets/episode-previews/episode-{index+1}.bin').read_bytes()
        top=struct.unpack_from('<H',record)[0]
        for y,row in enumerate(unpack_block(record,130,64)):
            colors=struct.unpack_from('<16H',record,2+32*(record[66+y]-13))
            for x,pixel in enumerate(row):
                if pixel is None:continue
                sy=top+y; palette=screen[32000+sy]&15
                packed=screen[sy*160+x//2]
                actual=(packed>>(0 if x&1 else 4))&15
                color=struct.unpack_from('<H',screen,32256+palette*32+actual*2)[0]
                assert color==colors[pixel],(label,x,sy,color,colors[pixel])
    sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
    from render import shr_screen
    from imaging import png
    for label,_ in checks:
        png(out/f'{label}.png',shr_screen((out/f'{label}.shr').read_bytes()).rows,3)
    report=dict(episodes=count,source_record_checks=len(checks),pixel_mismatches=0,
        real_j13_keys=True,menu_reopened=True,game_return=True,
        elf_sha256=__import__('hashlib').sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
        machine='apple2gsr1',ram='4352K',accelerator='none')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
