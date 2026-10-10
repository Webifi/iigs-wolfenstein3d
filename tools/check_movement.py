"""Replay source Thrust/ClipMove over DOC deltas in closed-door fixtures."""
import argparse
import json
import math
import re
from pathlib import Path
from wolfdata import ROOT

ap=argparse.ArgumentParser()
ap.add_argument('scene')
args=ap.parse_args()
folder=ROOT/'build/tests'/args.scene
meta=json.loads((ROOT/'build/assets/map.json').read_text())
world=json.loads((ROOT/'build/assets/world.json').read_text())
result=json.loads((folder/'result.json').read_text())
spawn=result['spawn'] or [meta['spawn'][name] for name in ('x','y','angle')]
x,y,angle=spawn
walls=(ROOT/'build/assets/map.bin').read_bytes()
blocking=(ROOT/'build/assets/world.bin').read_bytes()[0x6000:0x7000]
actors=[o for o in world['objects'] if o[4]&4 and o[14]<=2]
poses={int(n):(int(px),int(py),int(a)) for n,px,py,a in re.findall(r'^POSE (\d+) (\d+) (\d+) (\d+)',(folder/'mame.log').read_text(),re.M)}
failures=[];capped=slides=0

def free(px,py):
    for cx in ((px-88)//256,(px+88)//256):
        for cy in ((py-88)//256,(py+88)//256):
            if not 0<=cx<64 or not 0<=cy<64:return False
            index=cx*64+cy
            if walls[index] or blocking[index]:return False
    # These fixtures stay in the initial closed room. A live actor nearby
    # would require replaying AI positions, so fail rather than assume them.
    if any(abs(px-o[0])<=512 and abs(py-o[1])<=512 for o in actors):
        raise SystemExit('fixture leaves the isolated player-movement area')
    return True

for row in json.loads((folder/'logic.json').read_text()):
    n,tics,cmd=row['frame'],row['tics'],row['command']
    if cmd&16:raise SystemExit('closed-door fixture must not use a door')
    angle=(angle+5*tics*bool(cmd&4)-5*tics*bool(cmd&8))%1024
    motion=cmd&3
    if motion in (1,2) and tics:
        speed=round(35*(150 if motion==1 else 100)/256*tics)
        capped+=speed>175;speed=min(175,speed)
        a=(angle+(512 if motion==2 else 0))%1024
        def product(fraction):
            value=round(fraction*256)
            return (1 if value>=0 else -1)*(abs(value)*speed//256)
        dx=product(math.cos(a*math.tau/1024))
        dy=product(-math.sin(a*math.tau/1024))
        if free(x+dx,y+dy):x+=dx;y+=dy
        elif free(x+dx,y):x+=dx;slides+=1
        elif free(x,y+dy):y+=dy;slides+=1
    if poses[n]!=(x,y,angle):failures.append(dict(frame=n,wanted=[x,y,angle],actual=poses[n]))
report=dict(frames=len(poses),capped_frames=capped,sliding_frames=slides,failures=failures)
(folder/'movement-oracle.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if failures:raise SystemExit(1)
