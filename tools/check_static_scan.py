"""Differential execution of static visibility enumeration, including all projection call inputs."""
import memmap
import argparse,random,json
from pathlib import Path
from check_sight_cast import image
D=0x1000

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--before',type=Path,required=True);ap.add_argument('--after',type=Path,required=True);ap.add_argument('--trials',type=int,default=1000);a=ap.parse_args()
    rigs=[image(a.before),image(a.after)];r=random.Random(81);cycles=[0,0];calls=0
    for n in range(a.trials):
        count=r.randrange(16,400);lo=r.randrange(0,62);hi=min(63,lo+r.randrange(1,28));stat=[(r.randrange(4096),r.choice([0xffff,r.randrange(300)])) for i in range(count)];visible={i for i in range(4096) if r.random()<.12};vx=r.randrange(16000);vy=r.randrange(16000);results=[]
        for k,(e,s) in enumerate(rigs):
            e.d,e.db,e.mf,e.xf,e.s=D,2,0,0,0x1fff
            for name,val in [('VISSTAMP',31),('ENTRY',0),('ENTRY+2',0x2b),('VX',vx),('VY',vy)]:
                off=s[name] if '+' not in name else s['ENTRY']+2;e.wr16(D+off,val)
            e.m[(memmap.OLD_VISIBILITY+0xe000):(memmap.OLD_VISIBILITY+0xedac)]=bytes(3500)
            for g in range((count+15)//16):
                records=stat[g*16:g*16+16]
                for x in range(65):e.wr16((memmap.OLD_VISIBILITY+0xe004)+140*g+2*x,sum(1<<b for b,(cell,shape) in enumerate(records) if cell//64<x))
            e.m[memmap.OLD_VISIBILITY:(memmap.OLD_VISIBILITY+0x2000)]=bytes(8192)
            for i in visible:e.wr16(memmap.OLD_VISIBILITY+2*i,31)
            for i,(cell,shape) in enumerate(stat):e.wr16(memmap.OLD_WORLD+s['STATICS']+8*i,cell);e.wr16((memmap.OLD_WORLD+0x2)+s['STATICS']+8*i,shape)
            e.wr16(s['staticMaskEnd'],s['STATICS']+8*count)
            e.wr16(s['staticLowLoad']+1,0xe004+lo*2);e.wr16(s['staticHighLoad']+1,0xe006+hi*2)
            e.m[s['projectObject']]=0x60
            e.x=0;e.y=s['STATICS'];e.pb=2;e.pc=s['staticGroup']&65535;c=e.cycles;got=[]
            while e.pb<<16|e.pc != s['staticsDone']:
                if e.pb<<16|e.pc == s['projectObject']:got.append(tuple(e.rd16(D+s[key]) for key in ('SP_SHAPE','SP_OBJ','SP_DX','SP_DY','AI_OBJ')))
                e.step()
            cycles[k]+=e.cycles-c;results.append(got)
        assert results[0]==results[1],(n,results)
        calls+=len(results[0])
    print(json.dumps(dict(trials=a.trials,projection_calls=calls,exact=True,mean_cycles=[c/a.trials for c in cycles]),indent=2))
if __name__=='__main__':main()
