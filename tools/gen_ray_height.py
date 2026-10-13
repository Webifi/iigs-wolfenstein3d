"""Prepared midpoint, span-height, and perspective-weight tables."""
import struct
from wolfdata import ROOT
from viewgeometry import HEIGHTS

out=ROOT/'build/assets'
indices=[min(range(len(HEIGHTS)),key=lambda i:abs(HEIGHTS[i]-h)) for h in range(1025)]

from viewgeometry import midpoint_table
(out/'ray-midpoint.bin').write_bytes(midpoint_table())
from gen_ray_weights import build as build_weights
build_weights()

# Height in eighths enters directly during a completed eight-column span.
span=struct.pack('<5121H',*(indices[h//8]*2 for h in range(5121)))
assert len(span)<=0x4000
(out/'ray-span-height.bin').write_bytes(span)
# One contiguous load avoids another floppy header segment.
fixed=bytearray(span+(out/'ray-weight-views.bin').read_bytes())
assert len(fixed)<=0x3400
fixed.extend(bytes(0x4000-len(fixed)))
(out/'ray-fixed.bin').write_bytes(fixed+(out/'ray-setup.bin').read_bytes())
