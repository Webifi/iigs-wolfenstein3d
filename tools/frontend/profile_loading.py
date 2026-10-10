"""Real-key cold load profile; --no-progress is an explicit RTL test-tap control."""
import argparse,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from elf import read
ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);ap.add_argument('--media',choices=('hd','one','two'),default='hd');ap.add_argument('--no-progress',action='store_true');ap.add_argument('--all-floors',action='store_true');args=ap.parse_args()
_,syms=read(ROOT/'build/wolf.elf')
out=ROOT/'build/tests'/args.name;out.mkdir(parents=True,exist_ok=True)
labels='ProgressFinish ProgressPlan ProgressRemaining PrepareRayPages rpWarmDone gsRestore SyncSaved SaveWorldCore LoadWorldCore LoadFloorAssets LoadFloorData demoFloorLoaded CacheFloorMusic CacheFloorEffects FloorMusic SelectMusic StartMusic ExpandMusic ExpandMusicBlocks nextWaveBlock blockRegisterMode blockHot decodeRaw ExpandArt expandChunk expandDone setView buildLightTables ApplyLevel LogicSetupLevel InitRayTextureDirectory UiLoadSign UiLoadDone gsPhaseLoad gsPhaseDone gsApply'.split()
lua='CALLS={}\nFRAMEADDR='+str(syms['frameCount'])+'\n'
lua+='CALLS.choose=function() mem:write_u16('+str(syms['visitMask'])+',1023);mem:write_u16('+str(syms['chosenFloor'])+',1) end\n'
lua+='local function stamp(tag) if mem:read_u16('+str(syms['bootComplete'])+')~=0 then print(string.format("LOAD_EVENT %.6f %s A=%04x X=%04x Y=%04x",now(),tag,cpu.state.A.value,cpu.state.X.value,cpu.state.Y.value)) end end\n'
for label in labels:
 if label in syms:
  addr=syms[label];lua+=f'mem:install_read_tap({addr},{addr},"load-{label}",function(a,d,m) if cpu.state.PC.value==a+1 then stamp("{label}") end end)\n'
for label in ('busyShown','busyProgress','busyKind'):
 addr=syms[label];lua+=f'mem:install_write_tap({addr},{addr+1},"state-{label}",function(a,d,m) if a=={addr} then stamp("{label}="..d) end end)\n'
if args.no_progress: lua+=f'mem:install_read_tap({syms["ProgressAdd"]},{syms["ProgressAdd"]},"disable-progress",function(a,d,m) return 0x6b end)\n'
steps=['wait=1','sleep=1','key=Return','wait=2','sleep=1','key=Return','wait=15','key=Return','wait=3','key=Return','waitframes=3','key=Esc','wait=2','call=choose','key=Return','wait=15','key=Return','wait=3','key=Return','sleep=1','key=Y','waitframes=3','key=Equals','waitframes=3','end=']
if args.all_floors:
 for floor in range(2,10):
  lua+=f'CALLS.choose{floor}=function() mem:write_u16({syms["chosenFloor"]},{floor}) end\n'
  steps[-1:-1]=['key=Esc','wait=2',f'call=choose{floor}','key=Return','wait=15','key=Return','wait=3','key=Return','sleep=1','key=Y','waitframes=3']
command=[sys.executable,'tools/ui_test.py','--name',args.name,'--seconds','600','--steps',';'.join(steps)]
if args.media=='hd':command+=['--hd']
else:
 import test_media
 from check_boot_picture import KEEPER
 _,swaps=test_media.prepare(ROOT/'build/disk1.po',out,drives=1 if args.media=='one' else 2)
 lua+='\n'+KEEPER.replace('@DISK1@',json.dumps(str(out/'disk1.po'))).replace('@NEEDWAIT@',str(syms['needWait'])).replace('@NEEDDONE@',str(syms['needDone']))+'\nlocal s=mem\n'+swaps
 if args.media=='two':command+=['--disk2',str(out/'disk2.po')]
(out/'observer.lua').write_text(lua);command+=['--lua',str(out/'observer.lua')]
r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=900)
(out/'driver.log').write_text(r.stdout+r.stderr)
assert r.returncode==0,(r.stdout+r.stderr)[-3000:]
assert 'TIMEOUT' not in r.stdout and 'Lua error' not in r.stdout,r.stdout[-3000:]
log=(out/'mame.log').read_text()
assert 'TIMEOUT' not in log and 'Lua error' not in log and '[LUA ERROR]' not in log,log[-3000:]
events=[dict(time=float(t),label=n,a=int(a,16),x=int(x,16),y=int(y,16)) for t,n,a,x,y in re.findall(r'^LOAD_EVENT ([\d.]+) (\S+) A=(\w+) X=(\w+) Y=(\w+)',log,re.M)]
(out/'profile.json').write_text(json.dumps(events,indent=2)+'\n')
for e in events:print(f'{e["time"]:.6f} {e["label"]} {e["a"]:04x} {e["x"]:04x} {e["y"]:04x}')
