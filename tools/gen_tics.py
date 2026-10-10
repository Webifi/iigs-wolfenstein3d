"""World cadence and bounded frame work; the DOC remains the clock."""
import sys
from pathlib import Path
from write_generated import write_generated
step,maximum=map(int,sys.argv[1:])
if not 1<=step<=16:raise SystemExit('TICSTEP must be 1 to 16')
if not 1<=maximum<=128:raise SystemExit('MAXTICS must be 1 to 128')
out=Path(__file__).resolve().parents[1]/'build/gen'
out.mkdir(parents=True,exist_ok=True)
write_generated(out/'tics.inc','#define TICSTEP %d\n#define MAXTICS %d\n'%(step,maximum))
write_generated(out/'tics-mode.mk','BUILT_TICS := %d-%d\n'%(step,maximum))
