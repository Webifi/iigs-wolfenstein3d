"""Source moving-wall timeline and death/restart acceptance from DOC traces."""
import argparse
import json
import re
from pathlib import Path
from wolfdata import ROOT,maps
from wolf_source import statics

ap=argparse.ArgumentParser();ap.add_argument('scene');ap.add_argument('--push',action='store_true');ap.add_argument('--blocked',action='store_true');ap.add_argument('--restart',action='store_true');args=ap.parse_args()
p=ROOT/'build/tests'/args.scene
rows=json.loads((p/'logic.json').read_text());result=json.loads((p/'result.json').read_text())
poses={int(n):(int(x),int(y),int(a)) for n,x,y,a in re.findall(r'^POSE (\d+) (\d+) (\d+) (\d+)',(p/'mame.log').read_text(),re.M)}
level=maps()[0];tiles,info,_=level['planes'];original=bytearray(4096);blocking=bytearray(4096);secrets=set();door=0
for y in range(64):
    for x in range(64):
        index=x*64+y;t=tiles[y*64+x];o=info[y*64+x]
        if 90<=t<=101:original[index]=128+door;door+=1
        elif t<64:original[index]=t
        if 23<=o<=70 and statics()[o-23][1]=='block':blocking[index]=1
        if o==98:secrets.add(index)
world=json.loads((ROOT/'build/assets/world.json').read_text())['objects']
goals={o[12]*64+o[13] for o in world if o[4]&4 and o[14]<=2}
failures=[];checks=0;crossings=0;activated=None;stopped=None;restarted=None;frozen=0
if args.push or args.blocked:
    grid=bytearray(original);state=position=cell=step=tile=secret_count=0;held=False
    for row in rows:
        n,tics,cmd,g=row['frame'],row.get('world_tics',row['tics']),row['command'],row['game']
        if state:
            old_block=state//128;state+=tics
            if state//128!=old_block:
                crossings+=1;grid[cell]=0;blocking[cell]=0;cell+=step
                if state>=256:state=position=0;stopped=n
                else:
                    next_cell=cell+step
                    if grid[next_cell] or blocking[next_cell] or next_cell in goals:state=position=0;stopped=n
                    else:grid[next_cell]=tile;grid[cell]=tile|192
            if state:position=((state//2)&63)*4
        if cmd&16 and not held:
            x,y,a=poses[n-1] if n>1 else result['spawn']
            delta=(64,-1,-64,1)[((a+128)%1024)//256]
            target=(x//256)*64+y//256+delta
            if target in secrets and not state and 0<grid[target]<64:
                cell,step,tile=target,delta,grid[target];next_cell=cell+step
                if 0<=next_cell<4096 and not grid[next_cell] and not blocking[next_cell] and next_cell not in goals:
                    grid[next_cell]=tile;grid[cell]=tile|192
                    secrets.remove(cell);secret_count+=1;state=1;position=0;activated=n
        held=bool(cmd&16)
        wanted=dict(pwallState=state,pwallPosition=position,secretCount=secret_count)
        for field,value in wanted.items():
            checks+=1
            if g[field]!=value:failures.append(dict(frame=n,field=field,wanted=value,actual=g[field]))
        capture=p/f'map{n}.bin'
        if capture.exists():
            checks+=4096
            diff=sum(a!=b for a,b in zip(grid,capture.read_bytes()))
            if diff:failures.append(dict(frame=n,map_differing_cells=diff))
    if args.blocked:
        if activated is not None:failures.append('blocked fixture moved its secret wall')
    else:
        if activated is None:failures.append('fixture never moved its secret wall')
        if stopped is None:failures.append('fixture did not finish the wall movement')
if args.restart:
    previous=None;dead_pose=None;checked_reset_doors=False
    for row in rows:
        n,g=row['frame'],row['game']
        if g['health']==0:
            if dead_pose is None:dead_pose=poses[n]
            checks+=1;frozen+=1
            if poses[n]!=dead_pose or g['levelState']!=1:failures.append(dict(frame=n,death_freeze=g,pose=poses[n]))
        elif dead_pose is not None and restarted is None:
            restarted=n
            expected=dict(objectCount=len(world),health=100,ammo=8,keys=0,lives=2,score=0,killCount=0,weapon=1,chosenWeapon=1,bestWeapon=1,weaponFrame=0,attackActive=0,levelState=0,secretCount=0,pwallState=0)
            checks+=len(expected)
            for field,value in expected.items():
                if g[field]!=value:failures.append(dict(frame=n,field=field,wanted=value,actual=g[field]))
        if restarted is not None:
            capture=p/f'map{n}.bin'
            if capture.exists():
                checks+=4096
                if capture.read_bytes()!=original:failures.append(dict(frame=n,map_restoration=False))
            capture=p/f'state{n}.json'
            if capture.exists() and not checked_reset_doors:
                checked_reset_doors=True
                if any(json.loads(capture.read_text())['doors']):failures.append(dict(frame=n,doors_not_closed=True))
                # Later patrols may legitimately open doors again. The first
                # post-restart capture checks restoration, not permanent closure.
                live=json.loads((p/f'objects{n}.json').read_text())['objects']
                for i,original_actor in enumerate(world):
                    if original_actor[4]&4 and original_actor[14]<=2:
                        checks+=1
                        if not live[i][4]&4 or live[i][7]!=(25,1,100,1050)[original_actor[3]-100]:
                            failures.append(dict(frame=n,enemy_not_restored=i))
    if not frozen or restarted is None:failures.append('fixture did not freeze and restart')
report=dict(checks=checks,activated_frame=activated,stopped_frame=stopped,tile_crossings=crossings,frozen_frames=frozen,restarted_frame=restarted,failures=failures)
(p/'level-oracle.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if failures:raise SystemExit(1)
