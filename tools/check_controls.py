"""Assert real ADB control results, not just synthetic command injection."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
r=ROOT/'build/tests';data=json.loads((r/'controls-all/result.json').read_text());fail=[];checks={}
for event in data['events']:
 if event['edge']!='down' or event['time']>=11:continue
 start=event['time'];before=next((m for m in reversed(data['motion']) if m['time']<=start),data['motion'][0]);after=next((m for m in reversed(data['motion']) if m['time']<=start+.45),before)
 dx,dy,da=[after[k]-before[k] for k in ('x','y','angle')];key=event['keys'];checks[key]=dict(dx=dx,dy=dy,angle=da)
 if key in ('a  A',',','Option+Left Arrow') and not (dx==da==0 and dy<0):fail.append([key,dx,dy,da])
 if key in ('d  D','.','Command+Right Arrow') and not (dx==da==0 and dy>0):fail.append([key,dx,dy,da])
 if key in ('w  W','Shift+Up Arrow') and not (dx>0 and dy==da==0):fail.append([key,dx,dy,da])
 if key in ('s  S','Shift+Down Arrow') and not (dx<0 and dy==da==0):fail.append([key,dx,dy,da])
if abs(checks['Shift+Up Arrow']['dx']-2*checks['w  W']['dx'])>2:fail.append('forward run speed')
if abs(checks['Shift+Down Arrow']['dx']-2*checks['s  S']['dx'])>2:fail.append('backward run speed')
log=(r/'controls-all/mame.log').read_text();rows=[list(map(float,row)) for row in re.findall(r'^CONTROL ([\d.]+) (\d+) (\d+) (\d+) (\d+) (\d+)',log,re.M)]
for time,field,want in [(11.2,1,0),(11.7,1,1),(12.2,1,2),(12.7,1,3),(13.2,1,0),(13.7,2,120),(14.2,2,107),(14.7,2,80),(15.2,2,107),(15.7,3,0),(16.2,3,1),(16.7,4,6),(17.2,4,5)]:
 actual=next(row[field] for row in rows if row[0]>=time)
 if actual!=want:fail.append([time,field,want,actual])
for start,bit in [(18,32),(19,16),(20,16),(21,128)]:
 if not any(int(row[5])&bit for row in rows if start<=row[0]<start+.45):fail.append(['command bit',start,bit])
for name in ('controls-tap-fixed-r1','controls-tap-fixed-r3','controls-slowtap-final'):
 d=json.loads((r/name/'result.json').read_text())
 if d['input_dropped'] or any(t['angle_units']!=t['expected_units'] for t in d['taps']):fail.append(['tap',name])
 checks[name]=d['taps']
m=json.loads((r/'controls-mouse-complete/result.json').read_text());motion=m['motion']
def pose(time):return next((p for p in reversed(motion) if p['time']<=time),motion[0])
if pose(1.6)['angle']!=1015:fail.append('Doom mouse turn gain')
if pose(5.3)['x']<=pose(5)['x'] or pose(5.9)['x']>=pose(5.3)['x']:fail.append('mouse forward/back')
o=json.loads((r/'controls-mouse-switch/result.json').read_text());p0=next(p for p in reversed(o['motion']) if p['time']<=5);p1=next(p for p in reversed(o['motion']) if p['time']<=5.3)
if p0!=p1:fail.append('mouse Y moved while disabled')
result=dict(checks=checks,mouse_x_angle_after_20_counts=1015,mouse_y_default=True,failures=fail)
(r/'controls-all/controls-oracle.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(checks=len(checks),failures=fail)))
if fail:raise SystemExit(1)
