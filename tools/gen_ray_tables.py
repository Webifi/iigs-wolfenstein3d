"""Exact reciprocal partials and packed word products for ray arithmetic."""
import math
import struct
from wolfdata import ROOT
import memmap


def words(values):
    return struct.pack('<%dH'%len(values),*(v&65535 for v in values))


def main():
    out=ROOT/'build/assets'
    out.mkdir(parents=True,exist_ok=True)
    rows={}
    packed=bytearray()
    row_steps=[]
    def partial(step):
        row=words([step*f//256 for f in range(256)])
        if row not in rows:
            rows[row]=(memmap.RAY_PARTIAL+len(packed))>>8
            packed.extend(row)
            row_steps.append(step)
        return rows[row]
    setup=[]
    for a in range(1024):
        theta=a*math.tau/1024
        c,s=math.cos(theta),-math.sin(theta)
        dx=min(65535,round(256/max(abs(c),1e-9)))
        dy=min(65535,round(256/max(abs(s),1e-9)))
        # Fixed 256-byte wall DDA slots: quadrant PN/PP/NN/NP, then major V/H.
        setup.extend((dx,dy,-128 if c<0 else 128,-2 if s<0 else 2,
                      partial(dx),partial(dy),0x8000+256*((4 if c<0 else 0)+(0 if s<0 else 2)+(1 if dx>=dy else 0)),min(65535,2*dy)))
    assert len(packed)<=0x1a600
    # The boot builds the rows (src/iigs/ui_overlays.s BuildRayPartial); it needs only the steps.
    steps=list(row_steps)
    assert all(step*255//256<65536 for step in steps)
    (ROOT/'build/gen').mkdir(parents=True,exist_ok=True)
    (ROOT/'build/gen/ray_partial.inc').write_text('RAY_PARTIAL_ROWS .equ %d\nrayPartialSteps:\n' % len(steps) +
        ''.join('              .word %d\n' % s for s in steps))
    packed.extend(bytes(0x1a600-len(packed)))
    product_rows=[words([a*b for a in range(256)]) for b in range(256)]
    directory=[(memmap.WORD_PRODUCTS+512*i)>>8 for i in range(256)]
    (out/'word-products.bin').write_bytes(b''.join(product_rows))
    (out/'ray-products-directory.bin').write_bytes(words(directory))
    # Logic keeps the source's 3600 fine angles and exact 16.16 tangents. A record is
    # the step, twice each of its four bytes (the index of that byte's product in a
    # packed row of the partial fraction) and the negated step.
    from wolfsim import build_tables, fixed_by_frac
    tangents=build_tables()[1]
    logic=bytearray(0x3900)
    for angle,step in enumerate(tangents):
        struct.pack_into('<I4Hi',logic,angle*16,step,
                         *(2*((step>>shift)&255) for shift in (0,8,16,24)),-step)
    for angle in range(3600):
        if angle<900:x,y,sx,sy=899-angle,angle,1,-1
        elif angle<1800:x,y,sx,sy=angle-900,1799-angle,-1,-1
        elif angle<2700:x,y,sx,sy=2699-angle,angle-1800,-1,1
        else:x,y,sx,sy=angle-2700,3599-angle,1,1
        # word +4 selects the setup of lsight.s: the quadrant 0/2/4/6 (PN/PP/NN/NP), +8 when the tangent of the
        # ray is above 1 (it follows Y), +16 when a step has an integer part of 256 or more
        follows=16 if max(x,y)>=898 else 8 if y>=450 else 0
        logic+=words((x*16,y*16,(4 if sx<0 else 0)|(2 if sy>0 else 0)|follows,sy))
    assert len(logic)==0xa980
    logic.extend(bytes(0xaa00-len(logic)))
    for trig in (math.cos,math.sin):
        for angle in range(1024):
            factor=round(abs(trig(angle*math.tau/1024))*256)
            logic+=words((0 if factor==256 else directory[factor],))
    assert len(logic)==0xba00
    for command in range(1024):
        speed=70 if command&128 else 35
        axis=lambda positive,negative: speed*(bool(command&positive)-bool(command&negative))
        logic+=words((axis(8,4),axis(2,1),axis(256,512),
                      bool(command&32),bool(command&64),0,bool(command&16),0))
    # The unused run word and padding of four live rows hold one demo byte.
    for packet in range(256):
        for bit in range(8):
            offset=0xba00+packet*64+(bit//2)*16+(10 if bit%2==0 else 14)
            struct.pack_into('<H',logic,offset,(packet>>bit)&1)
        # The unused run slot carries the lowest pressed weapon instead.
        weapon=next((i for i in range(4) if packet&(16<<i)),65535)
        struct.pack_into('<H',logic,0xba1a+packet*64,weapon)
    assert len(logic)==0xfa00
    for tics in (1,4):
        logic.extend(bytes(16*tics//distance if distance else 0 for distance in range(256)))
    logic.append(0)  # the final byte lookup uses a native word load
    (out/'ray-logic-setup.bin').write_bytes(logic)
    controls=(35,70,100,140,280)
    thrust_index=bytearray(words([controls.index(n)*12 if n in controls else 65535 for n in range(281)]))
    thrust_rows=bytearray()
    thrust_extra=bytearray()
    sine=build_tables()[2]
    for row,speed in enumerate(n*scale for n in controls for scale in (100,150)):
        address=memmap.THRUST_MAIN+row*1800 if row<6 else memmap.THRUST_EXTRA+(row-6)*1800
        thrust_index+=words((address&65535,address>>16,speed))
        target=thrust_rows if row<6 else thrust_extra
        for angle in range(360):
            x=fixed_by_frac(speed,sine[angle+90])
            y=-fixed_by_frac(speed,sine[angle])
            target+=struct.pack('<2HB',x&65535,y&65535,(x<0)|((y<0)<<1))
    # Native word loads of the final sign byte also read the following byte.
    thrust_rows.append(0)
    thrust_extra.append(0)
    assert len(thrust_index)==622 and len(thrust_rows)==10801 and len(thrust_extra)==7201
    (out/'thrust-index.bin').write_bytes(thrust_index)
    (out/'thrust-vectors.bin').write_bytes(thrust_rows)
    (out/'thrust-extra.bin').write_bytes(thrust_extra)
    (out/'ray-partial.bin').write_bytes(packed)
    (out/'ray-setup.bin').write_bytes(words(setup))
    focal=[]
    for trig in (math.cos,lambda a:-math.sin(a)):
        for a in range(1024):
            value=round(trig(a*math.tau/1024)*256)
            focal.append((-1 if value<0 else 1)*(abs(value)*87//256))
    (out/'ray-focal.bin').write_bytes(words(focal))
    print('ray tables:',len(packed),'partial bytes;',len(rows),'unsigned rows; 128 KiB word products')


if __name__=='__main__':main()
