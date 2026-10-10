"""Source reaction timing plus map/goal invariants for selected live actors."""
import argparse
import json
from pathlib import Path
from wolf_source import random_table,states
from wolfdata import ROOT


def source_line(x1,y1,x2,y2,grid):
    """WL_STATE CheckLine's two fixed-point crossing loops, closed doors."""
    def quotient(a,b):return (-1 if a<0 else 1)*(abs(a)//b)
    for swap in (False,True):
        a,b,c,d=(y1,x1,y2,x2) if swap else (x1,y1,x2,y2)
        start,end=a>>8,c>>8
        if start==end:continue
        direction=1 if end>start else -1
        partial=256-(a&255) if direction>0 else a&255
        step=max(-32767,min(32767,quotient((d-b)<<8,abs(c-a))))
        frac=b+(step*partial>>8)
        for cell in range(start+direction,end+direction,direction):
            x,y=(frac>>8,cell) if swap else (cell,frac>>8)
            if grid[x*64+y]:return False
            frac+=step
    return True


def main():
    ap=argparse.ArgumentParser();ap.add_argument('scene')
    ap.add_argument('--first-sight',nargs='+',type=int,default=[])
    args=ap.parse_args();scene=Path(args.scene)
    world=json.loads((ROOT/'build/assets/world.json').read_text())['objects']
    state=states();sid={name:n*2 for n,(name,row) in enumerate(state)}
    grid=(ROOT/'build/assets/map.bin').read_bytes()
    data=(ROOT/'build/assets/world.bin').read_bytes()
    blocked=data[0x6000:0x7000];areas=data[0x4000:0x5000]
    logic=json.loads((scene/'logic.json').read_text());rng=random_table()
    index=sum(bool(o[4]&16 and o[6] and o[14]<=2) for o in world)
    delay={};reacted={};expect={};failures=[]
    # Named fixtures have clear lines and face the stationary player. Source
    # SightPlayer consumes one random byte in original actor-list order.
    pose=json.loads((scene/'state1.json').read_text());px,py=pose['x'],pose['y']
    area=areas[(px>>8)*64+(py>>8)]
    visible=[]
    for actor,o in enumerate(world):
        if not o[4]&16 or o[14]>2 or o[9]!=area:continue
        dx,dy=px-o[0],py-o[1]
        near=abs(dx)<384 and abs(dy)<384
        behind=(o[8]==0 and dx<0 or o[8]==2 and dy>0 or o[8]==4 and dx>0 or o[8]==6 and dy<0)
        if near or (not behind and source_line(o[0],o[1],px,py,grid)):visible.append(actor)
    for actor in visible:
        index=(index+1)&255;family=world[actor][3]-100
        delay[actor]=1+rng[index]//(4,8,6,256)[family]
    for actor in args.first_sight:
        if actor not in delay:raise SystemExit('fixture is outside source first sight: '+str(actor))
    initial_delay=delay.copy()
    if args.first_sight and logic[0]['game']['randomIndex']!=index:
        failures.append([1,'randomIndex',index,logic[0]['game']['randomIndex']])
    for tick in logic:
        for actor in args.first_sight:
            if actor in reacted:continue
            if tick['frame']>1:delay[actor]-=tick['tics']
            if delay[actor]<=0:reacted[actor]=tick['frame']
            expect[actor,tick['frame']]=max(0,delay[actor])
    frames=sorted(scene.glob('objects*.json'),key=lambda p:int(p.stem[7:]))
    checks=0
    for path in frames:
        frame=int(path.stem[7:]);objects=json.loads(path.read_text())['objects']
        occupied={}
        for actor,o in enumerate(objects):
            if o[2]==65535 or not o[4]&4:continue
            x,y=o[0]>>8,o[1]>>8;gx,gy=o[12:14]
            if max(x,y,gx,gy)>=64:failures.append([frame,actor,'outside map']);continue
            if 0<grid[x*64+y]<128:failures.append([frame,actor,'inside wall'])
            cell=gx*64+gy
            if cell in occupied:failures.append([frame,actor,'shared goal',occupied[cell]])
            occupied[cell]=actor
            if grid[cell]==0 and blocked[cell]:failures.append([frame,actor,'goal in blocking static'])
            if o[10]<32768 and o[10]:
                dx=abs(gx*256+128-o[0]);dy=abs(gy*256+128-o[1])
                expected=(dx if o[8] in (0,4) else dy)
                if expected!=o[10]:failures.append([frame,actor,'distance',expected,o[10]])
                if o[8]&1 and dx!=dy:failures.append([frame,actor,'diagonal drift',dx,dy])
            checks+=1
        for actor in args.first_sight:
            o=objects[actor]
            if frame<=reacted.get(actor,10**9):
                want=expect[actor,frame]
                if o[11]!=want:failures.append([frame,actor,'reaction',want,o[11]])
                if frame==reacted.get(actor):
                    family=('grd','dog','ss','boss')[o[3]-100]
                    want=sid['s_'+family+'chase1']
                    if o[5]!=want:failures.append([frame,actor,'first chase',want,o[5]])
        if frame==1 and args.first_sight:
            for actor,want in initial_delay.items():
                if objects[actor][11]!=want:failures.append([frame,actor,'initial reaction',want,objects[actor][11]])
    result=dict(selected_frames=len(frames),actor_checks=checks,source_initial_sight=visible,first_sighting=reacted,failures=failures)
    (scene/'ai-oracle.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
