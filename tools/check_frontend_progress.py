"""Visited-floor selection and explicit settings persistence, using a prior-visit fixture."""
import argparse,json,struct,subprocess,sys,re
from pathlib import Path
from elf import read
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);args=ap.parse_args()
out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
_,s=read(ROOT/'build/wolf.elf')
script='''CALLS={}
local writes=0
mem:install_read_tap(WRITE,WRITE,"settings-write",function(a,d,m)
 if cpu.state.PC.value==a+1 then writes=writes+1 end
end)
CALLS.seed=function()
 assert(mem:read_u16(VISIT)==1,'fresh settings must unlock floor 1 only')
 mem:write_u16(VISIT,5)
end
CALLS.selected=function()
 assert(mem:read_u16(0x116e)==2,'Down must skip unvisited floor 2')
 assert(writes==0,'navigation wrote settings')
end
CALLS.play=function()
 assert(mem:read_u16(FLOOR)==2,'selected floor 3 did not start')
 assert(mem:read_u16(VISIT)==5,'wrong visited mask')
 assert(writes==0,'starting a visited floor wrote settings')
 print('VISITED_SELECTION_OK')
end
CALLS.saved=function()
 assert(writes==1,'SAVE SETTINGS must be the only write')
 print('EXPLICIT_WRITE_OK')
end
'''
for k,v in dict(WRITE=s['WriteSettings'],VISIT=s['visitMask'],FLOOR=s['levelIndex']).items():script=re.sub(r'\b'+k+r'\b',str(v),script)
(out/'observe.lua').write_text(script)
steps='wait=1;sleep=1;key=Return;wait=2;sleep=1;call=seed;key=Return;wait=15;sleep=1;key=Down;call=selected;key=Return;wait=3;sleep=1;key=Return;wait=0;sleep=1;call=play;key=Esc;wait=2;sleep=1;key=Down;key=Down;key=Down;key=Return;wait=7;sleep=1;key=Down;key=Down;key=Down;key=Return;sleep=2;call=saved;end='
subprocess.run([sys.executable,'tools/ui_test.py','--hd','--debug','--name',args.name,'--seconds','150','--lua',str(out/'observe.lua'),'--steps',steps],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
log=(out/'mame.log').read_text();assert 'EXPLICIT_WRITE_OK' in log and 'VISITED_SELECTION_OK' in log,log[-2000:]
image=next(p for p in out.glob('*.po') if p.stat().st_size>800*1024)
b=image.read_bytes();at=struct.unpack_from('<H',b,512+436)[0]*512
assert struct.unpack_from('<H',b,at+16)[0]==5,'visited mask was not persisted'
# Cold-boot the privately written image, proving application of the stored mask.
restore='CALLS={check=function() assert(mem:read_u16(%d)==5);print("VISITED_RESTORED") end}\n'%s['visitMask']
(out/'restore.lua').write_text(restore)
subprocess.run([sys.executable,'tools/ui_test.py','--hd','--disk',str(image),'--name',args.name+'-reload','--seconds','80','--lua',str(out/'restore.lua'),'--steps','wait=1;sleep=1;call=check;end='],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
assert 'VISITED_RESTORED' in (ROOT/'build/tests'/(args.name+'-reload')/'mame.log').read_text()
result=dict(prior_visit_fixture=5,selected_floor=3,automatic_writes=0,explicit_writes=1,cold_boot_mask=5)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
