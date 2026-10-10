"""Execute weapon preparation for every pose/view and check exact art coverage."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path

from build_weapon_masks import source_pixels
from check_sight_cast import image
from viewgeometry import SIZES


def run(elf, allow_missing=False):
    e, s = image(elf)
    assets = elf.resolve().parent/'assets'
    # Some test images install commands outside load-list.txt. Load that
    # bank explicitly only when the list has not already supplied it.
    if not any(line.endswith(memmap.fill('@@MM:SPRITE_CMDS@')) for line in (assets/'load-list.txt').read_text().splitlines()):
        e.load(memmap.SPRITE_CMDS, (assets/'spritecmd.bin').read_bytes())
    full = (assets/'weapon-mask-full.bin').read_bytes()
    e.load(memmap.WEAPON_RUNS, (assets/'weapon-mask.bin').read_bytes())
    failures, cycles = [], []
    for vi, view in enumerate(SIZES):
        for pose in range(20):
            e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
            for name, value in [('viewWidth',view), ('viewBytes',view), ('weaponViewIndex',vi*2),
                                ('weapon',pose//5), ('weaponFrame',pose%5),
                                ('touchedLow',255), ('touchedHigh',0)]:
                e.wr16(s[name],value)
            e.wr16(e.d+s['SP_COUNT'],0)
            e.wr16(e.d+s['SP_OBJ'],0)
            e.load(memmap.MARKS, bytes(160))
            e.pb, e.pc = s['weaponVisible']>>16, s['weaponVisible']&65535
            before = e.cycles
            for _ in range(3000):
                if e.pb<<16|e.pc == s['spritesReady']: break
                e.step()
            else: raise AssertionError(('weapon preparation did not finish',vi,pose))
            cycles.append(e.cycles-before)
            columns={address%160-(160-view)//2 for address in source_pixels(full,pose,vi)}
            missing=sorted(col for col in columns if e.m[memmap.MARKS+col]&5 != 5)
            if missing: failures.append(dict(view=view,pose=pose,missing=missing))
            if not allow_missing:
                first,limit=(min(columns),max(columns)+1) if columns else (0,0)
                assert e.m[memmap.MARKS:(memmap.MARKS+0xa0)] == bytes(5 if first<=col<limit else 0 for col in range(160)), (vi,pose)
                assert e.rd16(e.d+s['SP_N'])==first and e.rd16(e.d+s['SP_LIMIT'])==limit
    if not allow_missing: assert not failures, failures
    return dict(elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), cases=len(cycles),
                missing_cases=failures, mean_nominal_cycles=sum(cycles)/len(cycles),
                worst_nominal_cycles=max(cycles), scope='Executed 65816 routine; not complete-frame timing')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf',type=Path,default=Path('build/wolf.elf'))
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    result=dict(candidate=run(args.elf))
    if args.baseline: result['baseline']=run(args.baseline,allow_missing=True)
    raw=json.dumps(result,indent=2)+'\n'
    if args.out: args.out.write_text(raw)
    print(raw,end='')


if __name__=='__main__': main()
