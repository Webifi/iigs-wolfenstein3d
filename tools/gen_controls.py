"""Generate 2,600 bytes of turn/thrust values: 10 sensitivity rows of 65 counts."""
import struct
from wolfdata import ROOT
blob=bytearray()
for speed in range(10):
 for count in range(65):
  control=int(count*20/(13-speed))
  blob.extend(struct.pack('<HBB',count*(15+3*speed),int(control*150/256),int(control*100/256)))
(ROOT/'build/assets/mouse.bin').write_bytes(blob)
(ROOT/'build/gen/controls.inc').write_text('mouseSpeedOffsets: .word '+','.join(str(n*260) for n in range(10))+'\nmouseData: .byte '+','.join(map(str,blob))+'\n')
