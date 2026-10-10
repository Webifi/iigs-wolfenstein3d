"""The original game's font as the text GAME OVER, with no level-load work (showGameOver in level.s)."""
import struct
from wolfdata import graphics,ROOT
lines=[]
# ID_VH.C fontstruct: height, 256 locations, 256 widths, bitmap bytes.
font=graphics()[1];h=struct.unpack_from('<H',font)[0];loc=struct.unpack_from('<256H',font,2);width=font[514:770]
text='GAME OVER';w=sum(width[ord(c)] for c in text);image=[0]*(w*h);x=0
for c in text:
 cw=width[ord(c)];p=loc[ord(c)]
 for y in range(h):
  for xx in range(cw):image[y*w+x+xx]=bool(font[p+y*cw+xx])
 x+=cw
# Enlarge the original text twice. Every pair shares a byte, centered.
spots=[];left=(160-w)//2;top=(160-h*2)//2
for y in range(h):
 for x in range(w):
  if image[y*w+x]:spots += [0x2000+(top+y*2+dy)*160+left+x for dy in (0,1)]
lines += ['deathGameOverBytes .equ '+str(len(spots)*2),'deathGameOver: .word '+','.join(map(str,spots))]
(ROOT/'build/gen/death.inc').write_text('\n'.join(lines)+'\n')
print('original font',w,h)
