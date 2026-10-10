"""One MAME run per case: demo state/posts plus complete frame and phase times.

States must match by default. --review-differences records the first difference
for a quality trial without weakening the default checks.

Uses the same packet-to-frame-done clock boundaries as timedemo.py. No debugger,
state injection, extra emulated instructions, or writes beyond the demo request.
"""
import argparse,hashlib,json,re
from pathlib import Path
import demo_check as d
import mame_kit
from elf import read

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--disk',type=Path,required=True);ap.add_argument('--elf',type=Path,required=True);ap.add_argument('--name',required=True);ap.add_argument('--views',type=int,nargs='+',default=[214,320]);ap.add_argument('--demos',type=int,nargs='+',default=[0,1,2,3]);ap.add_argument('--review-differences',action='store_true',help='capture and report changed gameplay states for a quality trial; never label them exact');ap.add_argument('--quality',action='store_true',help='write-only full SHR capture and intermediate-write checks');args=ap.parse_args()
    d.LUA=d.LUA.replace('local frames=0', '''local frames=0
local measurePrevious=nil
local measurePacket=false
measurePacketTap=s:install_write_tap(0x3f7,0x3f7,"measure-packet",function(a,data,m)
  if data==1 and s:read_u8(0x3f5)==1 then
    measurePacket=true
    if measurePrevious==nil then measurePrevious=manager.machine.time:as_double() end
  end
end)''')
    d.LUA=d.LUA.replace('    dump()','''    if measurePacket then
      local t=manager.machine.time:as_double()
      print(string.format("MEASURE %d %.9f %.9f %.9f %.9f %.9f",frames+1,t-measurePrevious,tc-measurePrevious,tc2-tc,tp-tc2,t-tp))
      measurePrevious=t;measurePacket=false
    end
    dump()''')
    if args.quality:
        import quality_capture
        d.LUA=quality_capture.install(d.LUA)
    cases=[];crashes=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('iigs-*.ips'))
    shared_visibility='CastLogicView' in read(args.elf)[1]
    models={n:d.oracle_rows(n,shared_visibility=shared_visibility) for n in args.demos}
    for view in args.views:
        for demo in args.demos:
            name=f'{args.name}-{view}-{demo}'
            native,end=d.run_mame(demo,name,400,disk=args.disk,elf=args.elf,view=view,ray_posts=True)
            visibility_changes={}
            first,diff=d.compare(native,models[demo],shared_visibility,visibility_changes)
            if first and not args.review_differences:raise AssertionError((view,demo,first,diff))
            assert end=='DEMOEND' and len(native)==len(models[demo]),(end,len(native))
            now=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('iigs-*.ips'))
            assert now==crashes, 'New MAME crash report; stop and investigate'
            out=d.ROOT/'build/tests'/name;text=(out/'mame.log').read_text()
            rows=[dict(frame=int(f),ns=round(float(t)*1e9),logic_ms=float(l)*1000,cast_ms=float(c)*1000,sprites_ms=float(s)*1000,paint_ms=float(p)*1000) for f,t,l,c,s,p in re.findall(r'^MEASURE (\d+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)$',text,re.M)]
            assert len(rows)==len(native)
            top=sorted(rows,key=lambda x:-x['ns'])[:20]
            inactive_differences=sum(x[11] != y[11] or x[12] != y[12] for a,b in zip(native,models[demo])
                                     for x,y in zip(a['actors'],b['actors'])
                                     if not ((x[6] | y[6]) & d.wolfsim.FL_SHOOTABLE))
            row=dict(demo=demo,view=view,frames=len(rows),exact_states=not first and not inactive_differences,gameplay_states_match=not first,first_state_difference=dict(frame=first,fields=diff) if first else None,inactive_projection_differences=inactive_differences,worst20_mean_ms=sum(x['ns'] for x in top)/20e6,mean_ms=sum(x['ns'] for x in rows)/len(rows)/1e6,top20_phases={k:sum(x[k] for x in top)/20 for k in ('logic_ms','cast_ms','sprites_ms','paint_ms')},frame_times=rows,disk=str(args.disk),disk_sha256=hashlib.sha256(args.disk.read_bytes()).hexdigest(),mame=mame_kit.BINARY,mame_sha256=hashlib.sha256(Path(mame_kit.BINARY).read_bytes()).hexdigest())
            if shared_visibility:
                row['visibility_differences']=visibility_changes
                row['shared_visibility_audit']=d.audit_shared_visibility(native,models[demo])
                row['exact_states'] &= not any(visibility_changes.values())
                if not args.review_differences:
                    assert not row['shared_visibility_audit']['unexpected'],row['shared_visibility_audit']
            if args.quality:
                quality=[tuple(map(int,m)) for m in re.findall(r'^QUALITY (\d+) (\d+) (\d+)$',text,re.M)]
                assert len(quality)==len(rows)
                row['quality']=dict(wrong_bytes=sum(x[1] for x in quality),exposed_bytes=sum(x[2] for x in quality),capture=str(out/'frames.shr'))
                assert not row['quality']['wrong_bytes'] and not row['quality']['exposed_bytes'],row['quality']
            (out/'measure.json').write_text(json.dumps(row,indent=2)+'\n');cases.append(row)
            state_note='changed; review required' if first else 'gameplay matches'
            print(f'{name}: {len(native)} states ({state_note}); top20 {row["worst20_mean_ms"]:.3f} ms; phases {row["top20_phases"]}',flush=True)
            (d.ROOT/'build/tests'/f'{args.name}-matrix.json').write_text(json.dumps(cases,indent=2)+'\n')
if __name__=='__main__':main()
