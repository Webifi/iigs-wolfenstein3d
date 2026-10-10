"""Depth-first column calls let a finished span skip all its descendants."""
from pathlib import Path
import re
from wolfdata import ROOT
from viewgeometry import SIZES

out=ROOT/'build/gen/ray_programs.s'
mode=(ROOT/'build/gen/ray_mode.inc').read_text()
prepared='#define WOLF_PREPARED 1' in (ROOT/'build/gen/picture_config.inc').read_text()
stride=int(re.search(r'WOLF_RAY_STRIDE (\d+)',mode)[1])
active=prepared and stride>=8 and 'WOLF_EXACT_RAYS 0' in mode
command_bytes=int(re.search(r'RAY_INTERPOLATE_BYTES\s+\.equ\s+(\d+)',
                           (ROOT/'src/iigs/ray_program.inc').read_text())[1])
lines=['#include "game.inc"',' .section raycode, text, root, noreorder']
if active:
    lines+=[' .extern traceRay,castDone,'+','.join('interpolateAnchors%d'%n for n in (2,4,8,16)),
            ' .public castProgramsBegin,castProgramsEnd','castProgramsBegin:']
    total=0
    for width in SIZES:
        lines+=[' .public castProgram%d'%width,'castProgram%d:'%width]
        emitted=[]
        def emit(col,step=0):
            global total
            emitted.append(col)
            lines.extend([' lda ##%d'%(2*col),' sta dp:SCAN'])
            if step and col+step<width:
                # The view already fixes both anchors. No runtime bounds
                # check or scan +/- spacing arithmetic is necessary.
                lines.extend([' ldx ##%d'%(2*(col-step)), ' ldy ##%d'%(2*(col+step)),
                              ' jsl long:interpolateAnchors%d'%(2*step)])
                assert command_bytes==3+2+3+3+4
                total+=command_bytes
            else:
                # An absent right anchor always took the exact trace path.
                lines.append(' jsl long:traceRay');total+=9
        def interval(left,right):
            middle=(left+right)//2
            if middle==left or left>=width:return
            if middle<width:emit(middle,(right-left)//2)
            interval(left,middle)
            interval(middle,right)
        for col in range(0,width,stride):emit(col)
        for left in range(0,width,stride):interval(left,left+stride)
        assert sorted(emitted)==list(range(width))
        lines.append(' jmp long:castDone');total+=4
    # The linker checks the remaining Scale5 space after the wall scalers.
    # A fixed stream-only budget cannot establish that the combined bank fits.
    lines+=['castProgramsEnd:',' .section gamedata, data, root',' .public castProgramAddrs','castProgramAddrs: .word '+','.join('.word0 castProgram%d'%w for w in SIZES)]
    print('ray programs:',total,'bytes')
out.write_text('\n'.join(lines)+'\n')
