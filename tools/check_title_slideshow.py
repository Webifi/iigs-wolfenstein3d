"""Observe source-derived pages and the first automatic demo in stock MAME."""
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

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols = read(ROOT/'build/wolf.elf')
    menu = (ROOT/'build/assets/menu.bin').read_bytes()
    constants = (ROOT/'build/gen/menu.inc').read_text()
    for name in ('title', 'credits', 'pg13'):
        index = int(re.search(r'(?m)^LUMP_'+name.upper()+r'\s+\.equ\s+(\d+)', constants)[1])
        first = struct.unpack_from('<H', menu, 8+index*8)[0]
        (out/(name+'-expected.shr')).write_bytes(menu[first*512:first*512+32768])
    demos = json.loads((ROOT/'build/assets/demo-source.json').read_text())
    first = demos['demos'][0]
    directory = (ROOT/'build/assets/demos.bin').read_bytes()
    offset, packets, floor = struct.unpack_from('<3H', directory)
    raw = (ROOT/'build/assets/demo-0.bin').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == first['packet_sha256']
    (out/'demo-expected.bin').write_bytes(raw)
    script = memmap.fill(r'''
local out=@OUT@
local seen={};local shots={[14]='pg13',[1]='title',[12]='credits'}
local function snapshot(name)
 local b={};for i=0,32767 do b[#b+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(out..'/'..name..'.shr','wb'));f:write(table.concat(b));f:close()
end
mem:install_read_tap(@WAIT@,@WAIT@,'page-ready',function(a,d,m)
 if cpu.state.PC.value~=a+1 then return end
 local id=mem:read_u8(0x3e4);local name=shots[id]
 if not name or seen[id] then return end;seen[id]=true;snapshot(name)
 local f=assert(io.open(out..'/'..name..'-expected.shr','rb'));local rec=f:read('a');f:close()
 local pix,rows,pals=0,0,0
 for i=0,31999 do if mem:read_u8(@MM:SHR@+i)~=rec:byte(i+1) then pix=pix+1 end end
 for i=0,199 do if mem:read_u8(@MM:SHR_SCB@+i)~=rec:byte(32001+i) then rows=rows+1 end end
 for i=0,511 do if mem:read_u8(@MM:SHR_PAL@+i)~=rec:byte(32257+i) then pals=pals+1 end end
 print(string.format('PAGE %s pixels=%d rows=%d palettes=%d',name,pix,rows,pals))
end)
local playing=false;local frames=0
mem:install_write_tap(0x3e4,0x3e4,'demo',function(a,d,m)
 if d~=13 then return end;playing=true
 local f=assert(io.open(out..'/demo-expected.bin','rb'));local rec=f:read('a');f:close()
 local bad=0;for i=1,#rec do if mem:read_u8(@PACKETS@+i-1)~=rec:byte(i) then bad=bad+1 end end
 print(string.format('DEMO floor=%d number=%d bad_packets=%d',mem:read_u16(@FLOOR@),mem:read_u16(@DEMO@),bad))
end)
mem:install_write_tap(0x3f0,0x3f0,'frame',function(a,d,m)
 if playing and d==2 then frames=frames+1;if frames==5 then snapshot('demo');print('DEMO_FRAMES '..frames);manager.machine:exit() end end
end)
''')
    for key, value in dict(OUT=json.dumps(str(out)), WAIT=symbols['WaitInput'],
                           FLOOR=symbols['levelIndex'], DEMO=symbols['demoNumber'], PACKETS=0xb0000+offset).items():
        script = script.replace('@'+key+'@', str(value))
    (out/'observe.lua').write_text(script)
    subprocess.run([sys.executable, str(ROOT/'tools/ui_test.py'), '--name', args.name,
                    '--hd', '--debug', '--j13', 'only', '--seconds', '180',
                    '--steps', 'sleep=179;end=', '--lua', str(out/'observe.lua')], cwd=ROOT, check=True)
    log = (out/'mame.log').read_text()
    pages = re.findall(r'^PAGE (\w+) pixels=(\d+) rows=(\d+) palettes=(\d+)$', log, re.M)
    demo = re.search(r'^DEMO floor=(\d+) number=(\d+) bad_packets=(\d+)$', log, re.M)
    assert {p[0] for p in pages} == {'pg13', 'title', 'credits'} and all(p[1:] == ('0','0','0') for p in pages), pages
    assert demo and tuple(map(int, demo.groups())) == (floor, 0, 0) and 'DEMO_FRAMES 5' in log, 'automatic source demo failed'
    report = dict(machine='apple2gsr1', ram='4352K', accelerator='none', j13='only',
                  page_differences={p[0]: dict(zip(('pixels','rows','palettes'), map(int,p[1:]))) for p in pages},
                  automatic_demo=first, packed_packet_differences=0, completed_demo_frames=5,
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print('All three native slideshow pages and automatic demo match the selected assets.')


if __name__ == '__main__':
    main()
