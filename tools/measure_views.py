"""Four real-key scenes at the requested view sizes, one MAME at a time."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SCENES=('turn','walk','guards','fight')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--name',required=True)
    ap.add_argument('--disk',type=Path,required=True)
    ap.add_argument('--elf',type=Path,required=True)
    ap.add_argument('--views',nargs='+',type=int,default=[120,200,320])
    ap.add_argument('--analyze',action='store_true')
    ap.add_argument('--audit-view',type=int,help='profile and trace one changing frame in this view')
    args=ap.parse_args()
    hashes={n+'_sha256':hashlib.sha256(p.read_bytes()).hexdigest()
            for n,p in (('disk',args.disk),('elf',args.elf))}
    def run(item):
        view,scene=item;name=f'{args.name}-{view}-{scene}'
        target=ROOT/'build/tests'/name
        existing=target/'result.json'
        valid=existing.exists() and all(json.loads(existing.read_text()).get(k)==v for k,v in hashes.items())
        if not args.analyze and not valid:
            cmd=[sys.executable,str(ROOT/'tools/playtest.py'),'--name',name,
                 '--scenario',scene,'--view',str(view),'--disk',str(args.disk.resolve()),
                 '--elf',str(args.elf.resolve())]
            if view==args.audit_view:
                cmd.extend(['--profile-at','1.2','--profile-phase','frame','--instruction-counts'])
            with (ROOT/'build'/f'{name}.log').open('w') as log:
                subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=125)
        if view==args.audit_view:
            with (ROOT/'build'/f'{name}-profile.log').open('w') as log:
                subprocess.run([sys.executable,str(ROOT/'tools/profile_report.py'),str(target),
                                '--elf',str(args.elf.resolve())],cwd=ROOT,stdout=log,
                               stderr=subprocess.STDOUT,check=True,timeout=30)
        data=json.loads((target/'result.json').read_text())
        if any(data[k]!=v for k,v in hashes.items()):raise ValueError('image changed during matrix')
        phase=data['phases'][-1]
        return dict(view=view,scene=scene,**phase['visible'],loop=phase['loop'],
                    phase_seconds=phase['end']-phase['start'],death_time=data['death_time'])
    # Each playtest owns a bounded/reaped process; independent scene runs
    # share no runtime state, NVRAM or snapshots.
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows=list(pool.map(run,[(v,s) for v in args.views for s in SCENES]))
    out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
    (out/'matrix.json').write_text(json.dumps(dict(**hashes,rows=rows),indent=2)+'\n')
    for row in rows:
        print(f"{row['view']} {row['scene']}: {row['updates_per_second']:.2f} visible/s, "
              f"paint {row['paint_mean_ms']:.1f}/{row['paint_worst_ms']:.1f} ms mean/worst")


if __name__=='__main__':main()
