"""Compare paired paint timings and every captured native pixel index."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path


def main():
    ap=argparse.ArgumentParser();ap.add_argument('before',type=Path);ap.add_argument('after',type=Path);ap.add_argument('output',type=Path);args=ap.parse_args()
    a=json.loads((args.before/'summary.json').read_text());b=json.loads((args.after/'summary.json').read_text())
    before={(r['demo'],r['view']):r for r in a['cases']};report=[]
    for new in b['cases']:
        demo,view=new['demo'],new['view'];old=before[demo,view]
        assert old['identical_runs']==new['identical_runs']==2
        case=f'd{demo}-v{view}';paths=[root/case/'0/frames.shr'for root in (args.before,args.after)]
        assert paths[0].stat().st_size==paths[1].stat().st_size==new['frames']*32768
        pixel=[];pal=[]
        with paths[0].open('rb')as fa,paths[1].open('rb')as fb:
            aa=mmap.mmap(fa.fileno(),0,access=mmap.ACCESS_READ);bb=mmap.mmap(fb.fileno(),0,access=mmap.ACCESS_READ)
            for n in range(new['frames']):
                at=n*32768
                if aa[at:at+32000]!=bb[at:at+32000]:pixel.append(n+1)
                if aa[at+32000:at+32768]!=bb[at+32000:at+32768]:pal.append(n+1)
        old_times=json.loads((args.before/case/'1/result.json').read_text())['frame_times']
        new_times=json.loads((args.after/case/'1/result.json').read_text())['frame_times']
        assert len(old_times)==len(new_times)==new['frames']
        delta=[n['ns']-o['ns'] for o,n in zip(old_times,new_times)]
        row=dict(demo=demo,view=view,frames=new['frames'],before_seconds=old['seconds'],after_seconds=new['seconds'],
                 gain_percent=100*(1-new['seconds']/old['seconds']),pixel_difference_frames=pixel,palette_phase_frames=pal,
                 faster_frames=sum(d<0 for d in delta),slower_frames=sum(d>0 for d in delta),
                 before_slowest=[dict(frame=r['frame'],before_ns=r['ns'],after_ns=new_times[r['frame']-1]['ns'])for r in old['slowest']],
                 after_slowest=new['slowest'],picture_sha256=[hashlib.sha256(p.read_bytes()).hexdigest()for p in paths])
        report.append(row)
        print(f'demo {demo} view {view}: {old["seconds"]:.9f} -> {new["seconds"]:.9f} s; {row["gain_percent"]:.3f}%; pixel differences {len(pixel)}')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(before=a['disk_sha256'],after=b['disk_sha256'],cases=report),indent=2)+'\n')
    assert not any(r['pixel_difference_frames']for r in report), 'Native pixel indices changed'


if __name__=='__main__':main()
