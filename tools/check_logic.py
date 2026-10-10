"""Replay original weapon/state tables over captured DOC deltas and inputs.

Stationary combat cases can name their known source target; the check then
also verifies damage, score, RNG and the death-state sequence. It never reads
native projected candidates or derives expected state from native fields.
"""
import argparse
import json
import math
import re
from pathlib import Path
from wolf_source import attack_table,hitpoints,random_table,states
from wolfdata import ROOT


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('scene')
    ap.add_argument('--target',type=int)
    ap.add_argument('--weapon',type=int,default=1)
    ap.add_argument('--ammo',type=int,default=8)
    args=ap.parse_args()
    scene=Path(args.scene)
    rows=json.loads((scene/'logic.json').read_text())
    original=json.loads((ROOT/'build/assets/world.json').read_text())['objects']
    attack=attack_table();state=states();sid={name:n for n,(name,_) in enumerate(state)}
    rng=random_table()
    random_index=sum(bool(o[4]&16 and o[6] and o[14]<=2) for o in original)
    model=dict(attackActive=0,attackPhase=0,attackTicks=0,weaponFrame=0,
               fireHeld=0,weapon=args.weapon,ammo=args.ammo)
    target=original[args.target][:] if args.target is not None else None
    if target:target[7]=hitpoints()[2][target[3]-100]
    kills=score=0;failures=[];shots=0;drop=None;picked=False
    poses={int(n):(int(x),int(y),int(a)) for n,x,y,a in re.findall(r'^POSE (\d+) (\d+) (\d+) (\d+)',(scene/'mame.log').read_text(),re.M)}
    def rand():
        nonlocal random_index
        random_index=(random_index+1)&255
        return rng[random_index]
    for row in rows:
        held=bool(row['command']&32);pressed=held and not model['fireHeld']
        model['fireHeld']=int(held)
        if model['attackActive']:
            model['attackTicks']-=row['tics']
            while model['attackTicks']<=0:
                tics,action,frame=attack[model['weapon']*4+model['attackPhase']]
                if action==-1:
                    model.update(attackActive=0,attackPhase=0,weaponFrame=0)
                    if not model['ammo']:model['weapon']=0
                    break
                if action in (3,4) and model['ammo'] and held:model['attackPhase']-=2
                if action in (1,4):
                    if model['ammo']:
                        model['ammo']-=1;shots+=1
                        if target and target[4]&4:
                            # These named fixtures are two tiles from their guard.
                            damage=rand()//6
                            if not target[4]&256:damage*=2
                            target[7]-=damage
                            family=('grd','dog','ss','boss')[target[3]-100]
                            if target[7]<=0:
                                target[7]=0;target[4]=(target[4]&~4)|64|128
                                target[5]=sid['s_'+family+'die1']*2
                                kills+=1;score+=(100,200,500,5000)[target[3]-100]
                                if target[3]==100:drop=((target[0]&65280)|128,(target[1]&65280)|128)
                            else:
                                target[4]|=128|256|512
                                suffix='pain' if target[7]&1 else 'pain1'
                                target[5]=sid['s_'+family+suffix]*2
                            target[2]=state[target[5]//2][1][1]
                            target[6]=state[target[5]//2][1][2]
                    elif action==1:model['attackPhase']+=1
                model['attackTicks']+=tics
                model['attackPhase']+=1
                model['weaponFrame']=attack[model['weapon']*4+model['attackPhase']][2]
        elif pressed:
            tics,_,frame=attack[model['weapon']*4]
            model.update(attackActive=1,attackPhase=0,attackTicks=tics,weaponFrame=frame)
        if target and target[4]&128 and target[6]:
            target[6]-=row['tics']
            while target[6]<=0:
                next_state=state[target[5]//2][1][5]
                target[5]=sid[next_state]*2
                _,target[2],tics,_,_,_=state[target[5]//2][1]
                if not tics:target[6]=0;break
                target[6]+=tics
        if drop and not picked:
            x,y,angle=poses[row['frame']]
            c=round(math.cos(angle*math.tau/1024)*256)
            s=round(-math.sin(angle*math.tau/1024)*256)
            dx=drop[0]-x+int(c*87/256);dy=drop[1]-y+int(s*87/256)
            def product(a,b):return (-1 if (a<0)!=(b<0) else 1)*(abs(a)*abs(b)//256)
            depth=product(dx,c)+product(dy,s)-32
            side=product(dy,c)-product(dx,s)
            if 88<=depth<256 and -128<side<128:
                model['ammo']=min(99,model['ammo']+4);picked=True
        expected={k:v&65535 for k,v in model.items()}
        if target:expected.update(randomIndex=random_index,killCount=kills,score=score)
        for key,value in expected.items():
            if row['game'][key]!=value:
                failures.append([row['frame'],key,value,row['game'][key]])
        objects=scene/('objects%d.json'%row['frame'])
        if target and objects.exists():
            got=json.loads(objects.read_text())['objects'][args.target]
            for field in (2,4,5,6,7):
                if got[field]!=target[field]&65535:
                    failures.append([row['frame'],'actor.%d'%field,target[field]&65535,got[field]])
    result=dict(frames=len(rows),shots=shots,drop_picked=picked,failures=failures)
    (scene/'logic-oracle.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
