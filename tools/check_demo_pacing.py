"""Compare every recorded state and every displayed picture against the benchmark.

Native memory observations are for correctness, not frame-rate claims. Normal
boot uses the existing demo request to select the route. Playback runs all
recorded packets in order; each displayed picture must match the benchmark
at its final packet. Clock and visible death timing on the real title route
are checked separately by check_attract_frames.py.
"""
import memmap
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import timedemo
from elf import read
from native_boot import BOOT

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--name',required=True)
ap.add_argument('--disk',type=Path,required=True)
ap.add_argument('--view',type=int,default=320)
ap.add_argument('--demos',type=int,nargs='+',default=[0,1])
a=ap.parse_args()
out=timedemo.ROOT/'build/tests'/a.name
out.mkdir(parents=True,exist_ok=False)
_,sym=read(timedemo.ROOT/'build/wolf.elf')
shutil.copy2(timedemo.ROOT/'build/wolf.elf',out/'wolf.elf')
original=timedemo.LUA
reports=[]
logic=json.loads((timedemo.ROOT/'build/assets/logic.json').read_text())
size=logic['layout']['VARS']+2*len(logic['vars'])
size=(size+3)&~3
for demo in a.demos:
    runs=[]
    for paced in (False,True):
        target=out/f'd{demo}-paced{int(paced)}'
        capture=memmap.fill(r'''
local logicFile=assert(io.open(OUTPUT,'wb'))
local pixelFile=assert(io.open(PIXELS,'wb'))
local function picture()
 local b={};for i=0,32255,4 do b[#b+1]=string.pack('<I4',s:read_u32(@MM:SHR@+i)) end
 pixelFile:write(table.concat(b))
end
local packets,pending=0,false
s:install_read_tap(PUBLISH,PUBLISH,'packet-state',function()
 if not active or not pending or manager.machine:side_effects_disabled() then return end
 pending=false
 local b={}
 for i=0,SIZE-1,4 do b[#b+1]=string.pack('<I4',s:read_u32(@MM:ART_FULL@+i)) end
 logicFile:write(table.concat(b))
 print(string.format('PACKET_STATE %d %.9f %d',packets,manager.machine.time:as_double(),s:read_u16(0x104c)))
end)
''').replace('OUTPUT',json.dumps(str(target/'logic.bin'))).replace('PUBLISH',str(sym['LogicEvents'])).replace('SIZE',str(size)).replace('PIXELS',json.dumps(str(target/'frames.bin')))
        timedemo.LUA=original.replace('for _,name in ipairs',BOOT+capture+'\nfor _,name in ipairs',1)
        timedemo.LUA=timedemo.LUA.replace('packet=true','packet=true;pending=true;packets=packets+1')
        timedemo.LUA=timedemo.LUA.replace('frames*4,t-previous','packets*4,t-previous')
        timedemo.LUA=timedemo.LUA.replace('frames=frames+1','frames=frames+1;picture()')
        timedemo.LUA=timedemo.LUA.replace('if d==1 then active=true',f'if d==1 then active=true;s:write_u16({sym["timeDemo"]},{0 if paced else 1})')
        timedemo.LUA=timedemo.LUA.replace('if not requested then s:write_u16(0x3e8,0x5a5a) end','')
        task=SimpleNamespace(machine='apple2gsr1',seed=None,pal=False,view=a.view,demo=demo,limit=650,
                             disk=a.disk.resolve(),disk2=None,drives=2,mame=timedemo.MAME,host_limit=600,debug=True)
        r=timedemo.run(task,target)
        log=(target/'mame.log').read_text()
        assert '[LUA ERROR]' not in log and 'ERROR ' not in log
        packets=[(int(n),float(t),int(doc)) for n,t,doc in re.findall(r'^PACKET_STATE (\d+) ([\d.]+) (\d+)$',log,re.M)]
        assert packets and [p[0] for p in packets]==list(range(1,len(packets)+1))
        raw=(target/'logic.bin').read_bytes()
        assert len(raw)==len(packets)*size
        with gzip.open(target/'logic.bin.gz','wb',compresslevel=1) as f:f.write(raw)
        (target/'logic.bin').unlink()
        pixels=(target/'frames.bin').read_bytes()
        assert len(pixels)==r['frames']*32256
        with gzip.open(target/'frames.bin.gz','wb',compresslevel=1) as f:f.write(pixels)
        (target/'frames.bin').unlink()
        runs.append((r,packets,raw,pixels))
        print(f'demo {demo}, paced {paced}: {len(packets)} logic packets, {r["frames"]} pictures, {r["seconds"]:.3f} seconds',flush=True)
    ref,test=runs
    assert len(ref[1])==len(test[1])==ref[0]['frames']
    assert 0<test[0]['frames']<=len(test[1])
    image_digest=hashlib.sha256()
    for n,row in enumerate(test[0]['frame_times']):
        packet=row['tic']//4
        expected_picture=ref[3][(packet-1)*32256:packet*32256]
        actual_picture=test[3][n*32256:(n+1)*32256]
        assert expected_picture==actual_picture,(demo,n+1,packet,'displayed pixels/SCBs differ')
        image_digest.update(actual_picture)
    if ref[2]!=test[2]:
        first=next(i for i,(x,y) in enumerate(zip(ref[2],test[2])) if x!=y)
        raise AssertionError(f'demo {demo}: packet {first//size+1}, world address ${memmap.OLD_WORLD+first%size:06x} differs')
    first,last=test[1][0],test[1][-1]
    elapsed=last[1]-first[1]
    doc=(last[2]-first[2])&65535
    expected=(len(test[1])-1)*4
    reports.append(dict(demo=demo,packets=len(test[1]),paced_pictures=test[0]['frames'],
                        seconds=elapsed,doc_tics=doc,recorded_tics=expected,
                        exact_world_bytes_per_packet=size,world_sha256=hashlib.sha256(test[2]).hexdigest(),
                        displayed_pixels_scb_sha256=image_digest.hexdigest()))
    (out/'result.json').write_text(json.dumps(dict(cases=reports,disk_sha256=timedemo.sha(a.disk),elf_sha256=timedemo.sha(out/'wolf.elf')),indent=2)+'\n')
    print(json.dumps(reports[-1]),flush=True)
