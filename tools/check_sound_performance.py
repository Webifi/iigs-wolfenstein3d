"""Compare music on/off during sustained real-input stock 2/3-view play."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--seconds',type=int,default=902);ap.add_argument('--effects-every',type=float,default=0);ap.add_argument('--analyze',action='store_true');ap.add_argument('--song',type=int);ap.add_argument('--jobs',type=int,choices=(1,),default=1);args=ap.parse_args()
assert args.seconds>=302
end=args.seconds;measure_end=end-3;measure_seconds=measure_end-62
out=ROOT/'build/tests/sound-performance';out.mkdir(parents=True,exist_ok=True)
plans=dict(turn=[[1,end-1,['Right Arrow']]],walk=[])
for i in range(int((end-2)/3.3)):
    t=1+i*3.3
    plans['walk'] += [[t,t+1.3,['w  W']],[t+1.3,t+3.3,['s  S']]]
for scenario,plan in plans.items():(out/(scenario+'.json')).write_text(json.dumps(plan)+'\n')

def run(scenario,volume):
    name=f'sound-parentfix-{scenario}-{volume}'+('-effects' if args.effects_every else '')+(f'-song{args.song:02}' if args.song is not None else '')
    if not args.analyze:
        p=subprocess.run([sys.executable,'tools/playtest.py','--name',name,'--scenario',scenario,
                          '--plan',str(out/(scenario+'.json')),'--end',str(end),'--view','214',
                          '--input-origin','150','--music-volume',str(volume),'--sound-audit',*(['--music-song',str(args.song)] if args.song is not None else []),*(['--effects-every',str(args.effects_every)] if args.effects_every else [])],cwd=ROOT,
                         capture_output=True,text=True,timeout=max(190,end/3+90))
        if p.returncode:raise RuntimeError(p.stdout[-1800:]+p.stderr[-1800:])
    folder=ROOT/'build/tests'/name
    log=(folder/'mame.log').read_text()
    frames=[(float(t),float(dt),int(x),int(y),int(angle)) for _,t,dt,x,y,angle in
            re.findall(r'^FRAME (\d+) ([\d.]+) ([\d.]+) (\d+) (\d+) (\d+)',log,re.M)]
    work=[r[1] for r in frames if 62<=r[0]<measure_end]
    frames=[(b[0],b[0]-a[0],*b[2:]) for a,b in zip(frames,frames[1:]) if 62<=a[0] and b[0]<measure_end]
    report=json.loads((folder/'result.json').read_text())
    if 'mame' not in report:
        prior=json.loads((ROOT/'docs/evidence/sound'/('played-effects-performance.json' if args.effects_every else f'prince-{args.song:02}-performance.json' if args.song is not None else 'played-performance.json')).read_text())[scenario]['on' if volume else 'off']
        assert prior['disk_sha256']==report['disk_sha256'] and prior['elf_sha256']==report['elf_sha256']
        report.update(mame=prior['mame'],mame_sha256=prior['mame_sha256'])
    assert report['input_dropped']==0,report['input_dropped']
    assert report['sound_violations']==0,report['sound_violations']
    if not volume:assert report['music_wakes']==0
    else:assert report['music_wakes']>2000
    assert len(set((r[2],r[3],r[4]) for r in frames))>100
    return dict(name=name,mame=report['mame'],mame_sha256=report['mame_sha256'],disk_sha256=report['disk_sha256'],elf_sha256=report['elf_sha256'],
                metric='consecutive completed-frame timestamps',
                marked_work_mean_ms=statistics.mean(work)*1000,
                frames=len(frames),seconds=measure_seconds,mean_ms=statistics.mean(r[1] for r in frames)*1000,
                p95_ms=sorted(r[1] for r in frames)[int(len(frames)*.95)]*1000,
                music_wakes=report['music_wakes'],music_notes=report['music_notes'],music_song=args.song,
                effect_pairs=len(re.findall(r'^EFFECTPAIR',log,re.M)),
                dropped=report['input_dropped'],violations=report['sound_violations'])

with ThreadPoolExecutor(max_workers=args.jobs) as pool:
    jobs={(scenario,volume):pool.submit(run,scenario,volume) for scenario in plans for volume in (0,12)}
    results={key:job.result() for key,job in jobs.items()}
report={}
for scenario in plans:
    off,on=results[scenario,0],results[scenario,12]
    for key in ('disk_sha256','elf_sha256','mame','mame_sha256'):
        assert off[key]==on[key],(scenario,key)
    report[scenario]=dict(off=off,on=on,frame_increase_percent=(on['mean_ms']/off['mean_ms']-1)*100)
(ROOT/'docs/evidence/sound'/('played-effects-performance.json' if args.effects_every else f'prince-{args.song:02}-performance.json' if args.song is not None else 'played-performance.json')).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
for scenario,r in report.items():assert r['frame_increase_percent']<=1,(scenario,r['frame_increase_percent'])
