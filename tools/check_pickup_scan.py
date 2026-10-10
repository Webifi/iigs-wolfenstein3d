"""Compare refreshStatics (the pickup scan) of two builds over wandering view points.

Each trial builds a floor of statics (some pickups, some sharing a cell, some taken), then moves a
view point around the pickups for 8-40 frames, sometimes dropping a new pickup under it as
PlaceItemType does. Both builds start from the same state and run the real refreshStatics
code in tools/emu816.py; the statics list, all game variables and the object markers must agree after
every frame. It also prints the mean nominal cycles of one call.

  python3 tools/check_pickup_scan.py --before OLD.elf [--after build/wolf.elf] [--trials 300] [--seed 1]
"""
import memmap
import argparse
import random
from pathlib import Path

from check_sight_cast import image, ROOT, D, LB



def call(e, s, name, regs=None):
    e.d, e.db, e.mf, e.xf, e.s = D, s['LOGICBANK'], 0, 0, 0x1fff
    for k, v in (regs or {}).items():
        setattr(e, k, v)
    c0 = e.cycles
    e.call(s[name] >> 16, s[name] & 0xffff, sentinel=0xd7f00)
    return e.cycles - c0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--before', type=Path, required=True)
    ap.add_argument('--after', type=Path, default=ROOT / 'build/wolf.elf')
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    rigs = [image(args.before), image(args.after)]
    n, seed = args.trials, args.seed
    rnd=random.Random(seed)
    bad = 0
    cyc = [0, 0]
    frames = pick = 0
    for trial in range(n):
        nstat=rnd.choice([20,60,150]); nbonus=rnd.randrange(1,min(nstat,40)+1)
        cells=[]
        pool=[x*64+y for x in range(1,63) for y in range(1,63)]
        cells=rnd.sample(pool,nstat)
        # some statics share a cell (a drop on an item or decoration)
        for k in range(rnd.randrange(0,4)):
            cells[rnd.randrange(nstat)]=cells[rnd.randrange(nstat)]
        for k in range(rnd.randrange(0,4)):   # pickups that share a cell
            cells[rnd.randrange(nbonus)]=cells[rnd.randrange(nbonus)]
        # the pickups' cells that a wander can reach
        bonus_cells=[cells[i] for i in range(nbonus)]
        sx,sy=divmod(rnd.choice(bonus_cells),64)
        px,py=sx+0.5+rnd.uniform(-2,2),sy+0.5+rnd.uniform(-2,2)
        health=rnd.randrange(1,100); ammo=rnd.randrange(0,90)
        stamped=set(i for i in range(nstat) if rnd.random()<0.85)
        stamped.add(0)
        angle=rnd.randrange(360)
        for k,(e,s) in enumerate(rigs):
            STATICS=s['STATICS']
            e.m[memmap.OBJECT_MARKERS:memmap.RAY_PARTIAL]=bytes(0x1000)
            call(e,s,'ClearStaticIndex')
            e.m[LB+s['SPOTVIS']:LB+s['SPOTVIS']+4096]=bytes(4096)
            e.m[memmap.VIS_STAMPS:memmap.TILE_MIRROR]=bytes(8192)
            e.m[LB+STATICS:LB+STATICS+8*400]=bytes(8*400)
            for i,cell in enumerate(cells):
                rec=LB+STATICS+8*i
                e.wr16(rec,cell); e.wr16(rec+2,i%40+1); e.wr16(rec+4,2 if i<nbonus else 0); e.wr16(rec+6,13 if i==0 else 2+(i%16))
            e.wr16(LB+s['V_laststat'],STATICS+8*nstat)
            for i in range(nstat):
                rec=STATICS+8*i
                call(e,s,'AddStaticIndex',dict(x=rec)); e.d=D
                call(e,s,'MarkStaticCellL',dict(a=cells[i],x=rec))
            for i in stamped:
                e.m[LB+s['SPOTVIS']+cells[i]]=1
                e.wr16(memmap.VIS_STAMPS+2*cells[i],1)
            e.wr16(D+s['L_STAMP'],1)
            e.wr16(LB+s['V_health'],health); e.wr16(LB+s['V_ammo'],ammo)
        qx,qy,qa=px,py,angle
        for f in range(rnd.randrange(8,40)):
            qx=min(62.5,max(1.5,qx+rnd.uniform(-0.5,0.5))); qy=min(62.5,max(1.5,qy+rnd.uniform(-0.5,0.5))); qa=(qa+rnd.randrange(-20,21))%360
            if f == 0:
                bx,by=divmod(bonus_cells[0],64)
                qx,qy,qa=bx,by+0.5,0
            # occasionally a drop at the view cell, as PlaceItemType does it, in a slot a pickup freed
            drop=None
            if rnd.random()<0.08:
                e0,s0=rigs[0]
                for i in range(nstat):
                    if e0.rd16(LB+s0['STATICS']+8*i+2)==0xffff:
                        drop=(i,rnd.randrange(2,18));break
            results=[]
            for k,(e,s) in enumerate(rigs):
                if drop:
                    slot,item=drop
                    cell=int(qx)*64+int(qy)
                    rec=s['STATICS']+8*slot
                    call(e,s,'RemoveStaticIndex',dict(x=rec)); e.d=D
                    e.wr16(LB+rec,cell); e.wr16(LB+rec+2,5); e.wr16(LB+rec+4,2); e.wr16(LB+rec+6,item)
                    call(e,s,'AddStaticIndex',dict(x=rec)); e.d=D
                    call(e,s,'MarkStaticCellL',dict(a=cell,x=rec))
                    e.m[LB+s['SPOTVIS']+cell]=1
                    e.wr16(memmap.VIS_STAMPS+2*cell,1)
                fx,fy=int(qx),int(qy)
                e.wr16(LB+s['V_focaltx'],fx); e.wr16(LB+s['V_focalty'],fy)
                e.wr16(LB+s['V_viewx_hi'],fx); e.wr16(LB+s['V_viewy_hi'],fy)
                e.wr16(LB+s['V_viewx'],int((qx-fx)*65536)); e.wr16(LB+s['V_viewy'],int((qy-fy)*65536))
                x4=qa*4
                for name,off in (('V_viewsin',0),('V_viewcos',360)):
                    e.wr16(LB+s[name],e.rd16(LB+s['SINTAB']+off+x4)); e.wr16(LB+s[name+'_hi'],e.rd16(LB+s['SINTAB']+off+x4+2))
                if 'prepareTransformProducts' in s:
                    call(e,s,'prepareTransformProducts')  # shared with all actors, outside the pickup-only timing
                c=call(e,s,'refreshStatics'); cyc[k]+=c
                results.append((bytes(e.m[LB+s['STATICS']:LB+s['STATICS']+8*400]),bytes(e.m[LB+0x6c00:LB+0x6e00]),bytes(e.m[memmap.OBJECT_MARKERS:memmap.RAY_PARTIAL])))
            frames+=1
            if results[0]!=results[1]:
                bad+=1
                if bad<4: print('DIFFERENT trial',trial,'frame',f,'view',qx,qy)
                break
        t=sum(1 for i in range(nstat) if int.from_bytes(rigs[0][0].m[LB+rigs[0][1]['STATICS']+8*i+2:LB+rigs[0][1]['STATICS']+8*i+4],'little')==0xffff)
        pick+=t
    print('trials',n,'frames',frames,'differences',bad,'pickups taken',pick,'mean cycles old %.0f new %.0f'%(cyc[0]/frames,cyc[1]/frames))
    assert pick > 0, 'fixture did not exercise any successful pickups'
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
