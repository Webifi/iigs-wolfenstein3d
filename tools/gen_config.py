"""Build flags are data and tables; they never add a game-loop branch."""
import json
import sys
from wolfdata import ROOT, PROFILE
from write_generated import write_generated
floor,colors,pixels,shading,scaler=sys.argv[1:];floor=int(floor);shading=int(shading)
if not 1<=floor<=PROFILE.floors or colors not in ('four','two') or pixels not in ('pair','true') or shading not in (0,4,6,8):raise SystemExit('invalid picture option')
if (colors,pixels,scaler) != ('four','pair','rows'):
    raise SystemExit('Registered campaigns currently require COLORS=four PIXELS=pair SCALER=rows')
if pixels=='true' and colors!='four':raise SystemExit('true pixels require the four-color source symbols')
if scaler not in ('rows','groups'):raise SystemExit('invalid scaler form')
out=ROOT/'build/gen';out.mkdir(parents=True,exist_ok=True)
changed=write_generated(out/'config.json',json.dumps(dict(floor=floor,colors=colors,pixels=pixels,shading=shading,scaler=scaler))+'\n')
# FLOOR changes asset inputs even though it does not change an assembler define.
write_generated(out/'picture_config.inc','#define WOLF_FOUR_COLORS %d\n#define WOLF_TRUE_PIXELS %d\n#define WOLF_GROUPS %d\n#define WOLF_PREPARED %d\n#define WOLF_POST_BYTES %d\n#define WOLF_COLUMN_BYTES %d\nDEFAULT_SHADING .equ %d\n'%(colors=='four',pixels=='true',colors=='four' and scaler=='groups' and pixels=='pair',colors=='four' and scaler=='rows' and pixels=='pair',640 if pixels=='true' else 320,320 if pixels=='true' else 160,(0,4,6,8).index(shading)),force=changed)
write_generated(out/'picture-config.mk','BUILT_PICTURE := %d-%s-%s-%d-%s\n'%(floor,colors,pixels,shading,scaler))
