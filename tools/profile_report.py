"""Stock total-time counters from the team's fastprof PC-region method."""
import memmap
import argparse
import bisect
import collections
import json
from pathlib import Path
import struct
ap=argparse.ArgumentParser();ap.add_argument('scene');ap.add_argument('--elf',type=Path);args=ap.parse_args()
root=Path(__file__).resolve().parents[1];out=Path(args.scene)
raw=(args.elf or root/'build/wolf.elf').read_bytes();so=struct.unpack_from('<I',raw,32)[0];ss,sn=struct.unpack_from('<HH',raw,46)
secs=[struct.unpack_from('<10I',raw,so+i*ss) for i in range(sn)];syms=[]
for sec in secs:
 if sec[1]!=2:continue
 strings=secs[sec[6]]
 for i in range(sec[4],sec[4]+sec[5],16):
  n,v,size,info,other,idx=struct.unpack_from('<IIIBBH',raw,i)
  if n and idx and (0x8000<=v<0x9000 or 0x20000<=v<0x60000 or 0xd8000<=v<0xe0000 or memmap.OLD_RAY_CODE<=v<memmap.LOGIC_BASE):
   start=strings[4]+n;name=raw[start:raw.index(b'\0',start)].decode();syms.append((v,name))
syms.sort();addresses=[s[0] for s in syms];tot=collections.Counter()
result=json.loads((out/'result.json').read_text())
frames=result.get('profile_frames') or result['frames']-1
for line in (out/'profile.txt').read_text().splitlines():
 a,t=line.split();addr=int(a,16);name=syms[bisect.bisect_right(addresses,addr)-1][1]
 # PC+16 counts total time, not accelerator stalls; one unit is 66 ticks.
 tot[name]+=int(t)*66/15120000/frames
report=dict(tot.most_common());(out/'profile.json').write_text(json.dumps(report,indent=2)+'\n')
for name,ms in tot.most_common(30):print('%-28s %8.3f ms'% (name,ms))
