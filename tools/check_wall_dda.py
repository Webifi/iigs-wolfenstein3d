"""Execute traceRay through its first solid cell in two ELFs; compare DDA state and all visibility stamps.

Every quantized angle, fraction boundaries, sparse/dense random maps, marked
empty cells and saturated crossing distances run on the built 65816 code.
The unchanged door handler resumes this same DDA entry after a passed door.
"""
import memmap
import argparse, random, json
from pathlib import Path
from check_sight_cast import image

D=0x1000
FIELDS=('RA','DX','DY','STEPX','STEPY','TX','TY','DIST','SIDE','TILE')
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before',type=Path,required=True)
    ap.add_argument('--after',type=Path,required=True)
    ap.add_argument('--trials',type=int,default=12000)
    ap.add_argument('--stamp-all-empty',action='store_true',help='mark every empty parent cell; require candidate to stamp them without markers')
    args=ap.parse_args(); rigs=[image(args.before),image(args.after)];r=random.Random(91)
    cycles=[0,0]; hist=[{},{}]; exits=[s['solidTile'] for e,s in rigs]
    if 'wdPNV' in rigs[1][1]:
        for i,q in enumerate(('PN','PP','NN','NP')):
            for j,axis in enumerate('VH'):
                assert rigs[1][1]['wd'+q+axis]==memmap.WALL_CAST+(2*i+j)*256

    for n in range(args.trials):
        angle=n%1024; px=r.randrange(2,62); py=r.randrange(2,62)
        fx=r.choice([0,1,127,128,254,255,r.randrange(256)]);fy=r.choice([0,1,127,128,254,255,r.randrange(256)])
        grid=bytearray(8192)
        for x in range(64):
            for y in range(64):
                v=r.randrange(1,128) if x in (0,63) or y in (0,63) or r.random()<.06 else (0x8000 if r.random()<.08 else 0)
                i=2*(x*64+y);grid[i]=v&255;grid[i+1]=v>>8
        result=[]
        for k,(e,s) in enumerate(rigs):
            actual_grid=bytearray(grid)
            if args.stamp_all_empty and k==0:
                for cell in range(0,8192,2):
                    if actual_grid[cell:cell+2]==b'\0\0':actual_grid[cell+1]=0x80
            e.m[(memmap.OLD_VISIBILITY+0x2000):(memmap.OLD_VISIBILITY+0x4000)]=actual_grid;e.m[memmap.OLD_VISIBILITY:(memmap.OLD_VISIBILITY+0x2000)]=bytes(8192)
            e.d,e.db,e.mf,e.xf,e.s=D,2,0,0,0x1fff
            for name,val in [('SCAN',0),('ANGLE',0),('ENTRY',0),('ROOTMAP',2*(px*64+py)),('VISSTAMP',17)]:e.wr16(D+s[name],val)
            for name,val in [('pixelAngle',angle),('fracNegativeX',2*fx),('fracPositiveX',2*((256-fx)&255)),('fracNegativeY',2*fy),('fracPositiveY',2*((256-fy)&255))]:e.wr16(s[name],val)
            e.pb,e.pc=2,s['traceRay']&65535;e.hist=hist[k];c=e.cycles
            for steps in range(15000):
                if (e.pb<<16|e.pc)==exits[k]:break
                e.step()
            else:raise RuntimeError(('runaway',n,k,hex(e.pb<<16|e.pc)))
            cycles[k]+=e.cycles-c
            result.append(([e.rd16(D+s[key]) for key in FIELDS],e.x,bytes(e.m[memmap.OLD_VISIBILITY:(memmap.OLD_VISIBILITY+0x2000)])))
        if result[0]!=result[1]:raise AssertionError((n,angle,px,py,fx,fy,result[0][:2],result[1][:2]))
    print(json.dumps(dict(cases=args.trials,exact=True,mean_cycles=[c/args.trials for c in cycles]),indent=2))
    for k,h in enumerate(hist):
        Path(str(args.after)+f'.profile{k}.json').write_text(json.dumps(h))
if __name__=='__main__':main()
