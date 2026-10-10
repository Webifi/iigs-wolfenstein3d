"""Exact native cached-view transforms versus the saved generic implementation.

All 360 view angles, coordinate signs and fraction boundaries; repeated calls
per prepared view exercise reuse. Random 24-bit magnitudes test carry limits.
"""
import memmap
import argparse,json,random
from pathlib import Path
from check_sight_cast import image
import wolfsim as w

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--before',type=Path,required=True);ap.add_argument('--after',type=Path,required=True);ap.add_argument('--trials',type=int,default=10000);a=ap.parse_args();rigs=[image(a.before),image(a.after)];r=random.Random(881);cycles=[0,0];cold=[0,0];warm=[0,0];prep=0;n=0;sine=w.build_tables()[2]
 for angle in range(360):
  for k,(e,s) in enumerate(rigs):
   e.d,e.db,e.mf,e.xf,e.s=0x1100,0x28,0,0,0x1fff
   for name,v in [('V_viewangle',angle),('V_viewcos',sine[angle+90]),('V_viewsin',sine[angle])]:
    e.wr16(memmap.OLD_WORLD+s[name],v&65535)
    if name!='V_viewangle':e.wr16(memmap.OLD_WORLD+s[name]+2,v>>16)
   if k:
    c=e.cycles;e.call(0xd,s['prepareTransformProducts']&65535,sentinel=0xd7f00);prep+=e.cycles-c
    if 'transformRowsReady' in s:
     e.wr16(s['transformRowsReady']+1,s['prepareFirstTransform']&65535)
     e.m[e.d+s['L_XSTEP']:e.d+s['L_XSTEP']+20]=bytes([0x55])*20
  for t in range(max(24,(a.trials+359)//360)):
   mag=lambda:r.choice([0,1,255,256,257,65535,65536,65537,0x3fffff,0xffffff,r.randrange(1<<24)])
   gx=mag()*r.choice([-1,1]);gy=mag()*r.choice([-1,1]);off=r.choice([8192,16384]);got=[]
   for k,(e,s) in enumerate(rigs):
    for name,v in [('L_GX',gx),('L_GY',gy)]:e.wr16(e.d+s[name],v&65535);e.wr16(e.d+s[name]+2,(v>>16)&65535)
    e.a=off;e.mf=e.xf=0;c=e.cycles;e.call(0xd,s['transformViewGXGY' if k else 'transformGXGY']&65535,sentinel=0xd7f00);cycles[k]+=e.cycles-c;(cold if t==0 else warm)[k]+=e.cycles-c
    got.append(tuple(w.s32(e.rd16(e.d+s[name])|e.rd16(e.d+s[name]+2)<<16) for name in ('L_NX','L_NY')))
   want=(w.s32(w.fixed_by_frac(gx,sine[angle+90])-w.fixed_by_frac(gy,sine[angle])-off),w.s32(w.fixed_by_frac(gy,sine[angle+90])+w.fixed_by_frac(gx,sine[angle])))
   assert got[0]==got[1]==want,(angle,gx,gy,got,want);n+=1
 print(json.dumps(dict(cases=n,exact=True,mean_cycles=[x/n for x in cycles],prepare_cycles_per_refresh=prep/360,first_transform_mean_cycles=[x/360 for x in cold],warm_transform_mean_cycles=[x/(n-360) for x in warm]),indent=2))
if __name__=='__main__':main()
