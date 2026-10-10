"""Check palette bytes, DOC lifetimes and IRQ cost from the played walk."""
import argparse,json,statistics
from pathlib import Path
from wolfdata import ROOT
ap=argparse.ArgumentParser();ap.add_argument('scene',type=Path);ap.add_argument('--pickup',action='store_true');args=ap.parse_args()
d=json.loads((args.scene/'walk.json').read_text());fail=[];flashes=d['flashes'];requests=d['flashrequests'];irqs=d['irqs']
if not flashes:raise SystemExit('No timed palette changes')
latencies=[]
for request in requests:
    red=request['kind']=='red'
    showing=[f for f in flashes if request['time']-.001<=f['first']<=request['time']+.023 and (1<=f['tint']<=6 if red else 7<=f['tint']<=9)]
    before=[f for f in flashes if f['first']<request['time']]
    already=bool(before and (1<=before[-1]['tint']<=6 if red else 7<=before[-1]['tint']<=9))
    if not showing and not already:fail.append('missing '+request['kind']+' flash at %.3f'%request['time'])
    if showing:latencies.append((showing[0]['first']-request['time'])*1000)
for f in flashes:
    remaining={}
    for kind in ('red','white'):
        events=[r for r in requests if r['kind']==kind and r['time']<=f['time']]
        r=events[-1] if events else None
        remaining[kind]=max(0,r['count']-((f['tic']-r['tic'])&65535)) if r else 0
    red,white=remaining['red'],remaining['white']
    expected=min(6,red//10+1) if red else 6+min(3,white//6+1) if white else 0
    if f['tint']!=expected:fail.append('DOC tint mismatch at %.3f'%f['first'])
    raw=(ROOT/'build/palettes'/('tints-%d.bin'%(f['level']+1))).read_bytes()
    status=(ROOT/'build/palettes/tints-status.bin').read_bytes()
    wanted=list(raw[f['tint']*32:(f['tint']+1)*32]+status[f['tint']*384:(f['tint']+1)*384])
    if f['palette']!=wanted or f['palette_mismatches'] or f['row_palette_mismatches']:fail.append('wrong palette bytes')
    if f['bytes'] not in (416,2080):fail.append('unexpected palette write count')
idle=[i for i in irqs if not i['damage'] and not i['bonus']]
if any(i['alarm_reads'] for i in idle):fail.append('idle ADB read DOC IRQ register')
if args.pickup and not d['bonuses']:fail.append('pickup fixture took no bonus')
if d['bonuses'] and not any(f['tint']>=7 for f in flashes):fail.append('pickup never showed white')
expiry=[]
for kind in ('red','white'):
    events=[r for r in requests if r['kind']==kind]
    if not events:continue
    r=events[-1];deadline=r['time']+r['count']/(894886/34*174/65536)
    ended=[f for f in flashes if f['first']>=r['time'] and f['tint']==0]
    if not ended and deadline<d['final']['time']-.023:fail.append(kind+' never returned to base')
    elif not ended:continue
    else:
        error=(ended[-1]['first']-deadline)*1000;expiry.append(dict(kind=kind,error_ms=error))
        if not -15<=error<=23:fail.append(kind+' expiry outside one DOC tic plus one alarm')
copies={}
for count in (416,2080):
    group=[f for f in flashes if f['bytes']==count]
    if group:copies[str(count)]=dict(changes=len(group),copy_mean_ms=statistics.mean(f['copy_ms'] for f in group),irq_mean_ms=statistics.mean(f['ms'] for f in group),irq_worst_ms=max(f['ms'] for f in group))
report=dict(hits=len(d['hits']),pickups=len(d['bonuses']),requests=len(requests),palette_changes=len(flashes),idle_adb_irqs=len(idle),idle_doc_irq_reads=sum(i['alarm_reads'] for i in idle),first_palette_latency_max_ms=max(latencies,default=0),copies=copies,expiry=expiry,failures=fail)
(args.scene/'flash-check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if fail:raise SystemExit(1)
