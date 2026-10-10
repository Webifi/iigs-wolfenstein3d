"""Summarize actual visible loading pixels, excluding INSERT DISK waits."""
import argparse,json,re
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('logs',nargs='+',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
results={}
pattern=re.compile(r'^PROGRESS_EVENT ([\d.]+) (\w+) (\d+) (\d+) (\d+) (\d+)$',re.M)
for p in a.logs:
 text=p.read_text();assert '[LUA ERROR]' not in text,p
 segments=[];current=None;phases=[]
 for t,name,done,total,px,kind in pattern.findall(text):
  t=float(t);px=int(px)
  if name not in ('visible','pixel','hidden'):phases.append(dict(time=t,label=name,done=int(done),total=int(total),pixels=px))
  if name=='visible':current=dict(start=t,last=t,pixels=px,updates=0,gaps=[])
  elif name=='pixel' and current is not None:
   if px!=current['pixels']:
    current['gaps'].append(dict(seconds=round(t-current['last'],6),time=t,pixels=px))
    current['last']=t;current['pixels']=px;current['updates']+=1
  elif name=='hidden' and current is not None:
   current['gaps'].append(dict(seconds=round(t-current['last'],6),time=t,pixels=px))
   current['end']=t;segments.append(current);current=None
 if not segments:continue
 gaps=[g for seg in segments for g in seg['gaps']]
 results[str(p)]=dict(max_gap_seconds=max(g['seconds'] for g in gaps),updates=sum(s['updates'] for s in segments),visible_segments=len(segments),worst_gaps=sorted(gaps,key=lambda v:v['seconds'],reverse=True)[:5],phases=phases)
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(results,indent=2)+'\n')
for path,row in results.items():print(path,row['max_gap_seconds'],row['updates'])
