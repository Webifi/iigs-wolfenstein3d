"""Serial bounded stock MAME picture oracles and real death walk."""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run(*args):
    p=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True,timeout=90)
    if p.returncode:raise RuntimeError(' '.join(args)+'\n'+p.stdout[-2000:]+p.stderr[-2000:])


def main():
    ap=argparse.ArgumentParser();ap.add_argument('step');ap.add_argument('--disk',type=Path);args=ap.parse_args()
    media_args=['--disk',str(args.disk.resolve())] if args.disk else []
    prefix='sound-'+args.step
    def pictures():
        reports=[]
        for machine,view,pal in [('apple2gsr1',160,False),('apple2gsr1',214,False),
                                 ('apple2gsr1',320,False),('apple2gs',214,False),('apple2gs',214,True)]:
            name=f'{prefix}-{machine}-{view}'+('-pal' if pal else '')
            run('tools/run_scene.py','--name',name,'--view',str(view),'--frames','4','--command','8',
                '--machine',machine,*media_args,*(['--pal'] if pal else []))
            scene=ROOT/'build/tests'/name
            run('tools/reference.py',str(scene))
            reports.append(dict(name=name,oracle=json.loads((scene/'oracle.json').read_text()),
                                result=json.loads((scene/'result.json').read_text())))
        return reports
    def death():
        name=prefix+'-death'
        run('tools/room_walk.py','--name',name,'--seconds','35',*media_args)
        scene=ROOT/'build/tests'/name
        run('tools/check_room_walk.py',str(scene))
        return json.loads((scene/'walk-oracle.json').read_text())
    with ThreadPoolExecutor(max_workers=1) as pool:
        p=pool.submit(pictures);d=pool.submit(death)
        result=dict(pictures=p.result(),death=d.result())
    out=ROOT/'docs/evidence/sound';out.mkdir(parents=True,exist_ok=True)
    (out/(args.step+'-regression.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(args.step+': five stock 4 MB picture fixtures and the death walk passed')


if __name__=='__main__':main()
