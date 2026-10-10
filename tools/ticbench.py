"""Build and measure live DOC pacing and simulation cost for tic options."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument('--cases',default='1:4,1:16,1:32,1:64,2:32,4:32,8:32',help='TICSTEP:MAXTICS pairs')
ap.add_argument('--name',default='doom-tics')
args=ap.parse_args()
cases=[tuple(map(int,row.split(':'))) for row in args.cases.split(',')]
out=ROOT/'build/tests'/args.name
out.mkdir(parents=True,exist_ok=True)
results=[]
for step,maximum in cases:
    print(f'Building TICSTEP={step} MAXTICS={maximum}',flush=True)
    with (out/f'build-{step}-{maximum}.log').open('w') as log:
        subprocess.run(['make','-j2',f'TICSTEP={step}',f'MAXTICS={maximum}'],cwd=ROOT,
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    def run(view):
        name=f'{args.name}-{step}-{maximum}-{view}'
        with (out/f'{step}-{maximum}-{view}.log').open('w') as log:
            subprocess.run([sys.executable,'tools/live_clock.py','--view',str(view),'--name',name,'--measure'],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        return json.loads((ROOT/'build/tests'/name/'clock.json').read_text())
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows=list(pool.map(run,(320,240,214,160)))
    results+=rows
    (out/'matrix.json').write_text(json.dumps(results,indent=2)+'\n')
    for row in rows:
        print(f"  {row['view']}: game/DOC={row['ratio']:.6f}, world/DOC={row['world_doc_ratio']:.6f}, "
              f"simulation={row['mean_simulation_ms']:.3f} ms, debt={row['max_debt']}, "
              f"worst={row['worst_frame_ms']:.3f} ms, failures={row['failures']}",flush=True)
print('Results:',out/'matrix.json',flush=True)
