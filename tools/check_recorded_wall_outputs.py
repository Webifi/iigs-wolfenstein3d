"""Compare paced recording updates and complete native pictures.

The baseline follows the native DOC clock. The candidate repeats its packet
batches, setting the test clock frontier and lifting the batch cap to 64 tics.
Every packet,
world update, visibility check and paint still executes in the selected build.
This isolates work cost; it is not an automatic-playback frame-rate test.
With --natural both builds retain the native clock and batch limit. World
state must still match after every packet, and pictures at shared packet
ends must agree. The duration check rejects an accumulating playback delay.
"""
import memmap
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from elf import read
from memmap import world
import timedemo

ROOT = Path(__file__).resolve().parents[1]
WORLD_BYTES = 0x6e00
PICTURE_BYTES = 32000 + 200

CAPTURE = memmap.fill(r'''
local packetCount,pending=0,false
local frontier=@FRONTIER@
local workStart=nil
local logicFile=assert(io.open(@WORLD_FILE@,'wb'))
local pixelFile=assert(io.open(@PIXEL_FILE@,'wb'))
local handles={}
local function entry(address,name,fn)
 handles[#handles+1]=s:install_read_tap(address,address,name,function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PC.value==a+1 then fn() end
 end)
end
local function bytes(at,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(s:read_u8(at+i)) end;return table.concat(b)
end
entry(@EVENTS@,'recorded-world',function()
 if active and pending then
  logicFile:write(bytes(@WORLD@,@WORLD_BYTES@));pending=false
 end
end)
entry(@RECORDED@,'recorded-frontier',function()
 if active and frontier then
  for _,address in ipairs(@LIMIT_ADDRESSES@) do s:write_u16(address,64) end
  local due=(assert(frontier[frames+1])-packetCount)*4
  assert(due>=4 and due<=64,'invalid packet batch')
  s:write_u16(0x104c,(s:read_u16(0x1046)+due)&65535)
 end
end)
local previousPixel,history={},{}
local painting=false
local scratchWrites=0
handles[#handles+1]=s:install_write_tap(@MM:SHORT_LIGHT_MAPS@,@MM:SHORT_LIGHT_MAPS+0x7f@,'short-light-scratch',function(a,d,m)
 if active then scratchWrites=scratchWrites+1 end
end)
handles[#handles+1]=s:install_write_tap(@MM:SHR@,@MM:SHR+0x7cff@,'recorded-pixels',function(a,d,m)
 if painting then
  local h=history[a];if not h then h={old=previousPixel[a],values={}};history[a]=h end
  h.values[#h.values+1]=d
 end
 previousPixel[a]=d
end)
handles[#handles+1]=s:install_write_tap(0x3f3,0x3f3,'recorded-paint',function(a,d,m)
 if d==1 and active then painting=true;history={} elseif d==2 then painting=false end
end)
handles[#handles+1]=s:install_write_tap(0x3f0,0x3f0,'recorded-work',function(a,d,m)
 if active and d==1 then workStart=manager.machine.time:as_double() end
end)
local function captureFrame()
 local wrong,exposed=0,0
 local examples={}
 for a,h in pairs(history) do
  local final=s:read_u8(a);local bad,extra=false,false
  for _,v in ipairs(h.values) do
   if v~=final then extra=true;if v~=h.old then bad=true end end
  end
  if bad then
   wrong=wrong+1
   if #examples<20 then examples[#examples+1]=string.format('%06x:%s>%s>%d',a,tostring(h.old),table.concat(h.values,','),final) end
  end
  if extra then exposed=exposed+1 end
 end
 pixelFile:write(bytes(@MM:SHR@,32000)..bytes(@MM:SHR_SCB@,200))
 print(string.format('RECORDING_FRAME %d %d %.9f %d %d',frames,packetCount,
  manager.machine.time:as_double()-assert(workStart),wrong,exposed))
 if wrong>0 then print('WRITE_DETAIL '..frames..' '..table.concat(examples,' ')) end
end
captureStop=emu.add_machine_stop_notifier(function()
 logicFile:close();pixelFile:close();print('SHORT_LIGHT_WRITES '..scratchWrites)
end)
''')


def read_run(out):
    log = (out/'mame.log').read_text()
    assert '[LUA ERROR]' not in log and 'ERROR ' not in log,log[-2500:]
    rows = [(int(f),int(p),float(t)*1000,int(w),int(e)) for f,p,t,w,e in re.findall(
        r'^RECORDING_FRAME (\d+) (\d+) ([\d.]+) (\d+) (\d+)$',log,re.M)]
    assert rows and re.search(r'^DONE '+str(len(rows))+r' ',log,re.M),'incomplete recording'
    assert [x[0] for x in rows]==list(range(1,len(rows)+1))
    def content(name):
        path=out/name
        return path.read_bytes() if path.is_file() else gzip.open(str(path)+'.gz','rb').read()
    state,pixels=content('world.bin'),content('frames.bin')
    assert len(state)==rows[-1][1]*WORLD_BYTES
    assert len(pixels)==len(rows)*PICTURE_BYTES
    seconds=float(re.search(r'^DONE \d+ ([\d.]+)$',log,re.M)[1])
    return rows,state,pixels,seconds


def run(directory, out, mame, demo, view, frontier=None):
    out.mkdir(parents=True)
    segments, symbols = read(directory/'wolf.elf')
    pc=symbols['runRecordedTics']
    segment=next(s for s in segments if s['address']<=pc<s['address']+len(s['data']))
    code=segment['data'][pc-segment['address']:pc-segment['address']+30]
    limits=list(re.finditer(rb'\xc9(.)\x00\x90.\xa9\1\x00',code,re.S))
    assert limits,'recorded work bound is not recognized'
    limit_addresses=[pc+m.start()+offset for m in limits for offset in (1,6)]
    capture = CAPTURE
    values = dict(FRONTIER='nil' if frontier is None else '{'+','.join(map(str,frontier))+'}',
                  WORLD_FILE=json.dumps(str(out/'world.bin')), PIXEL_FILE=json.dumps(str(out/'frames.bin')),
                  EVENTS=symbols['LogicEvents'], RECORDED=symbols['runRecordedTics'],
                  WORLD=world(symbols), WORLD_BYTES=WORLD_BYTES,
                  LIMIT_ADDRESSES='{'+','.join(map(str,limit_addresses))+'}')
    for key,value in values.items():
        capture = capture.replace('@'+key+'@',str(value))
    script = timedemo.LUA.replace('local first, previous, frames = nil, nil, 0',
                                  'local first, previous, frames = nil, nil, 0\n'+capture)
    script = script.replace('packet=true',
        'packet=true;if packetCount==0 then workStart=manager.machine.time:as_double() end;'
        'packetCount=packetCount+1;pending=true')
    script = script.replace('frames=frames+1','frames=frames+1;captureFrame()')
    script = script.replace('s:write_u8(0x3e3,1)','s:write_u8(0x3e3,0)')
    script = script.replace('@VIEW@',str({214:2,320:4}[view])).replace('@DEMO@',str(demo))
    script = script.replace('@PAL@','false').replace('@LIMIT@','1200')
    (out/'observe.lua').write_text(script)
    name = str(out.relative_to(ROOT/'build/tests'))
    command = [sys.executable,'tools/ui_test.py','--name',name,'--mame',str(mame),
               '--hd','--disk',str(directory/'wolf-hd.po'),'--disk2',str(directory/'wolf-hd2.po'),
               '--j13','only','--debug','--seconds','1200','--steps','sleep=1199;end=',
               '--lua',str(out/'observe.lua')]
    result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=600)
    (out/'driver.log').write_text(result.stdout+result.stderr)
    log = (out/'mame.log').read_text()
    assert result.returncode==0 and '[LUA ERROR]' not in log and 'ERROR ' not in log,log[-2500:]
    return read_run(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,default=ROOT/'build')
    parser.add_argument('--mame',type=Path,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--demos',type=int,nargs='+',default=[0,1,2,3])
    parser.add_argument('--view',type=int,choices=(214,320),default=214)
    parser.add_argument('--reuse-before',type=Path,
                        help='reuse complete baseline captures with matching image identities')
    parser.add_argument('--natural',action='store_true',
                        help='retain the real clock and compare common packet-end pictures')
    args=parser.parse_args()
    out=ROOT/'build/tests'/args.name
    out.mkdir(parents=True,exist_ok=False)
    report=dict(machine='apple2gsr1',ram='4352K',accelerator='none',view=args.view,
                matched_packet_batches=not args.natural,world_bytes_per_packet=WORLD_BYTES,cases=[])
    for kind,path in (('baseline',args.baseline.resolve()),('candidate',args.candidate.resolve())):
        report[kind]={name:hashlib.sha256((path/name).read_bytes()).hexdigest()
                      for name in ('wolf.elf','wolf-hd.po','wolf-hd2.po')}
    for demo in args.demos:
        reuse=args.reuse_before/f'd{demo}-before' if args.reuse_before else None
        if reuse and (reuse/'mame.log').is_file():
            receipt=json.loads((args.reuse_before/'result.json').read_text())
            assert receipt['baseline']==report['baseline'] and receipt['view']==args.view
            old=read_run(reuse)
        else:
            old=run(args.baseline.resolve(),out/f'd{demo}-before',args.mame.resolve(),demo,args.view)
        new=run(args.candidate.resolve(),out/f'd{demo}-after',args.mame.resolve(),demo,args.view,
                frontier=None if args.natural else [row[1] for row in old[0]])
        assert old[1]==new[1],f'demo {demo}: world state changed; captures retained'
        if args.natural:
            pictures=[]
            for rows,_,pixels,_ in (old,new):
                pictures.append({row[1]:pixels[i*PICTURE_BYTES:(i+1)*PICTURE_BYTES]
                                 for i,row in enumerate(rows)})
            common=pictures[0].keys() & pictures[1].keys()
            assert common and all(pictures[0][p]==pictures[1][p] for p in common),'common pictures changed'
        else:
            assert len(old[0])==len(new[0]),'displayed frame count changed'
            assert [r[1] for r in old[0]]==[r[1] for r in new[0]],'packet batches changed'
            assert old[2]==new[2],f'demo {demo}: pixels or SCBs changed; captures retained'
            assert [r[3:] for r in old[0]]==[r[3:] for r in new[0]],'transient drawing writes changed'
        slow=sorted(range(len(old[0])),key=lambda i:-old[0][i][2])[:20]
        new_slow=sorted(range(len(new[0])),key=lambda i:-new[0][i][2])[:20] if args.natural else slow
        result=dict(demo=demo,packets=old[0][-1][1],pictures=len(old[0]),
                    after_pictures=len(new[0]),before_seconds=old[3],after_seconds=new[3],
                    common_exact_pictures=len(common) if args.natural else len(old[0]),
                    before_mean_ms=sum(r[2] for r in old[0])/len(old[0]),
                    after_mean_ms=sum(r[2] for r in new[0])/len(new[0]),
                    before_slow20_ms=sum(old[0][i][2] for i in slow)/len(slow),
                    after_slow20_ms=sum(new[0][i][2] for i in new_slow)/len(new_slow),
                    before_worst_ms=max(r[2] for r in old[0]),after_worst_ms=max(r[2] for r in new[0]),
                    maximum_frame_delta_ms=None if args.natural else max(b[2]-a[2] for a,b in zip(old[0],new[0])),
                    world_sha256=hashlib.sha256(new[1]).hexdigest(),
                    pictures_sha256=hashlib.sha256(new[2]).hexdigest(),
                    before_wrong_transient_bytes=sum(r[3] for r in old[0]),
                    after_wrong_transient_bytes=sum(r[3] for r in new[0]))
        report['cases'].append(result)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        if args.natural:
            assert new[3]<=old[3]+max(r[2] for r in new[0])/1000+0.02,'recording slowed beyond one picture'
        for kind in ('before','after'):
            for name in ('world.bin','frames.bin'):
                path=out/f'd{demo}-{kind}'/name
                if not path.is_file():
                    continue
                with gzip.open(str(path)+'.gz','wb',compresslevel=1) as stream:
                    stream.write(path.read_bytes())
                path.unlink()
        print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
