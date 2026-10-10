"""Wolf's DOS projection and 256-color art, independent of native GS tables."""
import functools
import math
import struct
import zlib
from wolfdata import maps,vswap,sprite,graphics,palette
from wolf_source import sprite_ids
from native_map_format import wall_material
from floor_art import ceiling as floor_ceiling, floor_color

@functools.lru_cache(None)
def resources():
    return maps(),vswap(),graphics(),sprite_ids()

@functools.lru_cache(None)
def shape(number):
    _,(pages,base,_),_,_=resources()
    return sprite(pages[base+number])


@functools.lru_cache(maxsize=4096)
def wall_samples(height, first, last):
    return tuple(min(63,max(0,int((row-(80-height/2))*64/height)))
                 for row in range(first,last))


@functools.lru_cache(None)
def floor_grid(level_index):
    rawtiles=resources()[0][level_index]['planes'][0]
    doorinfo=[(i%64,i//64,t%2==0) for i,t in enumerate(rawtiles) if 90<=t<=101]
    doorids={(x,y):n for n,(x,y,_) in enumerate(doorinfo)}
    grid=bytearray(4096)
    for y in range(64):
        for x in range(64):
            t=rawtiles[y*64+x]
            grid[x*64+y]=128+doorids[x,y] if (x,y) in doorids else (t if wall_material(t) is not None else 0)
    return doorinfo,bytes(grid)


def source_frame(level_index,state,view=200,objects=(),status=True):
    levels,(pages,sprite_start,_),chunks,ids=resources();level=levels[level_index]
    height=view//2;left=(320-view)//2;top=(160-height)//2;bottom=top+height
    doorinfo,source_grid=floor_grid(level_index)
    grid=state.get('tilemap')
    if grid is None:
        grid=source_grid
    out=bytearray([127]*64000)
    if top:
        for x in range(left,left+view):out[(top-1)*320+x]=0;out[bottom*320+x]=125
        for y in range(top-1,bottom+1):out[y*320+left-1]=0;out[y*320+left+view]=125
    theta=state['angle']*math.tau/1024
    vx=state['x']/256-math.cos(theta)*0x5700/65536
    vy=state['y']/256+math.sin(theta)*0x5700/65536
    doors=state.get('doors',[0]*len(doorinfo));heights=[];seen=set()
    ceiling=floor_ceiling(level_index)
    floor=floor_color()
    for col in range(view):
        delta=math.atan(((view-1)/2-col)/(view/2)*(65536/(2*(0x5700+0x5800))))
        c=math.cos(theta+delta);s=-math.sin(theta+delta)
        mx,my=math.floor(vx),math.floor(vy);sx=1 if c>=0 else -1;sy=1 if s>=0 else -1
        dx=1/max(abs(c),1e-15);dy=1/max(abs(s),1e-15)
        tx=((mx+1-vx) if sx>0 else (vx-mx))*dx;ty=((my+1-vy) if sy>0 else (vy-my))*dy
        for _ in range(128):
            if tx<ty:dist=tx;tx+=dx;mx+=sx;side=0
            else:dist=ty;ty+=dy;my+=sy;side=1
            seen.add(mx*64+my);t=grid[mx*64+my]
            if not t:continue
            if t>=192:
                dt=dist+(dx if side==0 else dy)*state.get('game',{}).get('pwallPosition',0)/256
                if dt>=min(tx,ty):continue
                dist=dt;t&=63
            elif t>=128:
                n=t&127;vertical=doorinfo[n][2];dt=tx-dx/2 if vertical else ty-dy/2
                if not dist<=dt<min(tx,ty):continue
                side=0 if vertical else 1;dist=dt
                frac=((vy+dist*s) if vertical else (vx+dist*c))%1
                if frac<doors[n]/256:continue
                u=min(63,int((frac-doors[n]/256)*64));page=sprite_start-8+int(vertical);break
            frac=((vy+dist*s) if side==0 else (vx+dist*c))%1;u=min(63,int(frac*64))
            if (side==0 and sx<0) or (side==1 and sy>0):u=63-u
            if t&64:
                adjacent=grid[(mx-sx)*64+my] if side==0 else grid[mx*64+my-sy]
                page=sprite_start-6+int(side==0) if adjacent&128 else ((t&63)-1)*2+int(side==0)
            else:page=(t-1)*2+int(side==0)
            break
        else:raise ValueError('unbounded DOS ray')
        h=max(1,int(view*(0x5700+0x5800)/65536/max(dist*math.cos(delta),0x5800/65536)))
        heights.append(h);a=max(top,80-h//2);b=min(bottom,80+(h+1)//2)
        texture=pages[page][u*64:u*64+64]
        out[top*320+left+col:bottom*320+left+col:320] = (
            bytes([ceiling])*(a-top) + bytes(texture[t] for t in wall_samples(h,a,b)) +
            bytes([floor])*(bottom-b))
    def draw_shape(number,center,h,weapon=False):
        art=shape(number);start=int(center-h/2)
        for col in range(max(0,start),min(view,int(center+h/2))):
            if not weapon and heights[col]>=h:continue
            u=min(63,max(0,int((col-start)*64/h)))
            if not art['left']<=u<=art['right']:continue
            for a,b,data in art['columns'][u-art['left']]:
                ra=max(top,math.ceil(80-h/2+a*h/64));rb=min(bottom,math.ceil(80-h/2+b*h/64))
                for row in range(ra,rb):
                    tex=min(b-1,max(a,int((row-(80-h/2))*64/h)))
                    out[row*320+left+col]=data[tex-a]
    projected=[]
    for obj in objects:
        x,y,number,kind,flags,state_id=obj[:6]
        if number==65535 or (x>>8)*64+(y>>8) not in seen:continue
        rx=x/256-vx;ry=y/256-vy
        depth=rx*math.cos(theta)-ry*math.sin(theta)-(.25 if flags&16 else .125)
        if depth<0x5800/65536:continue
        lateral=ry*math.cos(theta)+rx*math.sin(theta)
        h=view*(0x5700+0x5800)/65536/depth
        center=view/2+lateral*(view/2)*(0x5700+0x5800)/65536/depth
        projected.append((depth,number,center,h))
    for _,number,center,h in sorted(projected,reverse=True):draw_shape(number,center,h)
    game=state.get('game',{})
    if objects or status:
        number=ids['SPR_'+('KNIFE','PISTOL','MACHINEGUN','CHAIN')[game.get('weapon',1)]+'READY']+game.get('weaponFrame',0)
        draw_shape(number,view/2,2*((height+1)//2),True)
    if status:
        def pic(n,x,y):
            w,h=struct.unpack_from('<HH',chunks[0],(n-3)*4);data=chunks[n];plane=w*h//4
            for row in range(h):
                for col in range(w):out[(160+y+row)*320+x+col]=data[(col&3)*plane+row*(w//4)+col//4]
        def number(value,w,x):
            for n,c in enumerate(str(value)[-w:].rjust(w)):pic(110 if c==' ' else 111+int(c),x+n*8,16)
        pic(98,0,0);number(level_index+1,2,16);number(game.get('score',0),6,48);number(game.get('lives',3),1,112)
        health=game.get('health',100);number(health,3,168);number(game.get('ammo',8),2,216)
        pic(103+game.get('weapon',1),256,8);pic(108 if game.get('keys',0)&1 else 107,240,4)
        pic(109 if game.get('keys',0)&2 else 107,240,20);pic(122+3*((100-health)//16) if health else 142,136,4)
    return out,heights


def rgb_png(path,data,width=320,height=200,pal=None):
    pal=pal or palette()
    def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
    rows=b''.join(b'\0'+bytes(v for c in data[y*width:(y+1)*width] for v in pal[c]) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
