"""Independent grid/ScalePost reference and byte checks for selected frames."""
import argparse
import json
import math
from pathlib import Path
import struct
import zlib
from wolfdata import ROOT
from wolfdata import graphics
from wolf_source import sprite_ids

ASSETS=ROOT/'build/assets'

HEIGHTS=list(range(2,161,2))+list(range(164,641,4))


def light(h,rows,on=True):
    """Full-field thresholds 32, 56 and 104 select four stored light levels."""
    factor=round(rows*256/160)
    if not on or h*256>=104*factor:return 3
    if h*256<=32*factor:return 0
    return 1 if h*256<=56*factor else 2


def light_tables(meta):
    record=json.loads((ROOT/'build/palettes'/(str(meta.get('level_index',0))+'.json')).read_text())
    pools=ASSETS/'pool-colors.json'
    return record['wall_lights'],json.loads(pools.read_text()) if pools.exists() else record['sprite_lights']


def png(path, data, palette, width=160, height=160):
    def chunk(t,b):
        return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
    rows=[]
    for y in range(height):
        row=bytearray([0])
        colors=palette(y) if callable(palette) else palette
        for byte in data[y*width:(y+1)*width]:
            row.extend(colors[byte>>4]); row.extend(colors[byte&15])
        rows.append(bytes(row))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width*2,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))


def render_hud(game):
    """The 6400 bytes of the status bar as hud.s copies them from ui.bin; x is in bytes."""
    blob=(ROOT/'build/assets/ui.bin').read_bytes()
    records=json.loads((ROOT/'build/assets/ui.json').read_text())['records']
    out=bytearray(6400)
    def draw(pic,x,y,lower_key=False):
        offset,width,height=records[43 if lower_key else 0 if pic==98 else pic-102]
        for row in range(height):
            out[(y+row)*160+x:(y+row)*160+x+width]=blob[offset+row*width:offset+(row+1)*width]
    def number(value,width,x):
        text=str(value)[-width:].rjust(width)
        for n,c in enumerate(text):draw(110 if c==' ' else 111+int(c),x+n*4,16)
    draw(98,0,0)
    number(game.get('levelIndex',0)+1,2,8)
    number(game['score'],6,24)
    number(game['lives'],1,56)
    number(game['health'],3,84)
    number(game['ammo'],2,108)
    draw(103+game['weapon'],128,8)
    draw(108 if game['keys']&1 else 107,120,4)
    draw(109 if game['keys']&2 else 107,120,20,lower_key=not game['keys']&2)
    draw(122+3*((100-game['health'])//16) if game['health'] else 142,68,4)
    return out


def hud_palette(row):
    """The 16 colors of the status bar row `row` (0-39), as build_ui.py gave it."""
    ui=json.loads((ROOT/'build/assets/ui.json').read_text())
    return ui['palettes'][ui['rows'][row]-1]


def play_border(view):
    """Black margin around a smaller view. A full view covers this buffer."""
    return bytearray(25600)


def render(state, view=100, original=False, interpolate=True):
    assets=ASSETS
    meta=json.loads((assets/'map.json').read_text())
    true=meta.get('pixels')=='true'
    rows=view//2 if true else view
    if original:
        from sourceview import source_frame
        pixels,heights=source_frame(meta.get('level_index',0),state,view if true else view*2,state.get('objects',()),True)
        return pixels,dict(heights=heights,original=True)
    tilemap=state.get('tilemap') or (assets/'map.bin').read_bytes()
    from wolfdata import vswap
    pages=vswap()[0];wall_lights,_=light_tables(meta)
    stride=meta.get('texel_stride',1)
    out=play_border(rows)
    left=(160-rows)//2; top=(160-rows)//2; bottom=top+rows
    wallpixels=steps=0; records=[]; visits=[]; coords=[]
    unwrapped=state.get("unwrapped_rays",False)
    theta=state['angle']*math.tau/1024
    px=state['x']-int(round(math.cos(theta)*256)*87/256)
    py=state['y']+int(round(math.sin(theta)*256)*87/256)
    doors=state.get('doors',[0]*len(meta['doors']))
    def coordinate(dist,component,origin,negative):
        delta=(dist*component)//256
        return (origin+(-delta if negative else delta))&255
    for col in range(view):
        cells={(px>>8)*64+(py>>8)}
        offset=round(math.atan(((view-1)/2-col)/(view/2)*(0x10000/(2*(0x5700+0x5800))))*1024/math.tau)
        angle=(state['angle']+offset)%1024
        c=math.cos(angle*math.tau/1024); s=-math.sin(angle*math.tau/1024)
        sx,sy=(-1 if c<0 else 1),(-1 if s<0 else 1)
        dx=min(65535,round(256/max(abs(c),1e-9)))
        dy=min(65535,round(256/max(abs(s),1e-9)))
        mx,my=px>>8,py>>8
        tx=dx*((256-(px&255)) if sx>0 else px&255)//256
        ty=dy*((256-(py&255)) if sy>0 else py&255)//256
        for _ in range(128):
            steps+=1
            if tx<ty:
                side=0; dist=tx; tx=min(65535,tx+dx); mx+=sx
            else:
                side=1; dist=ty; ty=min(65535,ty+dy); my+=sy
            if not (0<=mx<64 and 0<=my<64): raise ValueError('ray left map')
            cells.add(mx*64+my)
            tile=tilemap[mx*64+my]
            if not tile: continue
            if tile>=192:
                dt=dist+((dx if side==0 else dy)*state['game']['pwallPosition']//256)
                if dt>=min(tx,ty):continue
                dist=dt
                frac=coordinate(dist,round(abs(s if side==0 else c)*256),py if side==0 else px,sy<0 if side==0 else sx<0)
                u=frac//4
                if (side==0 and sx<0) or (side==1 and sy>0):u=63-u
                page=((tile&63)-1)*2+(1 if side==0 else 0)
            elif tile>=128:
                door=tile&127; vertical=meta['doors'][door]['vertical']
                dt=(tx-dx//2) if vertical else (ty-dy//2)
                if not dist<=dt<min(tx,ty): continue
                side=0 if vertical else 1; dist=dt
                frac=coordinate(dist,round(abs(s if vertical else c)*256),py if vertical else px,sy<0 if vertical else sx<0)
                if (frac//4)*4<doors[door]: continue
                u=((frac//4)*4-doors[door])//4
                page=98+(1 if vertical else 0)
            else:
                frac=coordinate(dist,round(abs(s if side==0 else c)*256),py if side==0 else px,sy<0 if side==0 else sx<0)
                u=frac//4
                if (side==0 and sx<0) or (side==1 and sy>0):u=63-u
                page=(tile-1)*2+(1 if side==0 else 0)
            break
        else: raise ValueError('unbounded ray')
        perp=dist*round(math.cos(offset*math.tau/1024)*256)//256
        raw=min(1024,round(56000/max(perp,1)))
        raw=raw*round(rows*256/160)//256
        h=min(HEIGHTS,key=lambda h:abs(h-raw))
        a=max(top,80-h//2); b=min(bottom,80+h//2)
        full=(py if side==0 else px)+(-1 if (sy<0 if side==0 else sx<0) else 1)*(dist*round(abs(s if side==0 else c)*256)//256)
        if state.get('door_planes',False) and 128<=tile<192:
            coords.append(full//4-doors[tile&127]//4)
        else:
            coords.append((full//4)^(4095 if (side==0 and sx<0) or (side==1 and sy>0) else 0))
        plane=(mx*64 if side==0 else (my|0x8000)) if unwrapped else ((mx*64+my)|(0x8000 if side else 0))
        if state.get('door_planes',False) and 128<=tile<192:
            plane=0x4000|(mx*64+my)|(0x8000 if side else 0)
        elif tile>=192:plane=(0x2000|(mx*64+my)|(0x8000 if side else 0)) if state.get('push_planes',False) else 65535
        elif tile>=128:plane=65535
        records.append((h,page,u,dist,side,plane))
        visits.append(cells)
    traced=set(range(view))
    plane_columns=set()
    def plane_hit(col,plane):
        if plane&0x4000:return None
        offset=round(math.atan(((view-1)/2-col)/(view/2)*(0x10000/(2*(0x5700+0x5800))))*1024/math.tau)
        angle=(state['angle']+offset)%1024
        c=math.cos(angle*math.tau/1024);s=-math.sin(angle*math.tau/1024)
        side=int(bool(plane&0x8000));component=c if side==0 else s
        origin=px if side==0 else py;wall=plane//64 if side==0 else plane&63
        count=abs(wall-(origin>>8))-1
        if count<0:return None
        step=min(65535,round(256/max(abs(component),1e-9)))
        dist=step*((origin&255) if component<0 else 256-(origin&255))//256+min(65535,count*step)
        if dist>=65536:return None
        along_component=s if side==0 else c
        full=((py if side==0 else px)+(-1 if along_component<0 else 1)*(dist*round(abs(along_component)*256)//256))//4
        cell=(wall*64+(full//64)) if side==0 else (full//64)*64+wall
        if not 0<=cell<4096:return None
        tile=tilemap[cell]
        if not 0<tile<64:return None
        if (side==0 and c<0) or (side==1 and s>0):full^=4095
        perp=dist*round(math.cos(offset*math.tau/1024)*256)//256
        raw=min(1024,round(56000/max(perp,1)))*round(rows*256/160)//256
        h=min(HEIGHTS,key=lambda h:abs(h-raw))
        return (h,(tile-1)*2+(side==0),full&63,dist,side,plane),full,cell
    filled=set()
    def material(u,plane,side):
        along=u//64
        if (side==0 and plane//64<px//256) or (side==1 and (plane&63)>=py//256):along=63-along
        cell=(plane|along) if side==0 else (along*64|(plane&63))
        if not 0<=cell<4096:return None
        tile=tilemap[cell]
        return (tile-1)*2+(side==0) if 0<tile<64 else None
    def valid_materials(a,b,l):
        return not l[5]&0x6000 and all(material(u*64,l[5],l[4]) is not None for u in range(min(a,b)//64,max(a,b)//64+1))
    weighted_columns=set()
    def angle_weight(col,step,side,left=None,right=None):
        offsets=[round(math.atan(((view-1)/2-c)/(view/2)*(65536/(2*(0x5700+0x5800))))*1024/math.tau) for c in (col-step if left is None else left,col,col+step if right is None else right)]
        center=(state['angle']+offsets[1]+side*256)%512
        if left is not None and state.get('vector_weights',False):
            anchor=(left+right)//2
            offset=round(math.atan(((view-1)/2-anchor)/(view/2)*(65536/(2*(0x5700+0x5800))))*1024/math.tau)
            direction=(state['angle']+offset+side*256)%512
            center+=(2-direction)%4-2
        slopes=[-math.tan((center+offset-offsets[1])*math.tau/1024) for offset in offsets]
        denominator=slopes[2]-slopes[0]
        w=round(256*(slopes[1]-slopes[0])/denominator) if denominator else 128
        return max(1,min(255,w))
    if interpolate:
        for step in ((16,8,4,2,1) if interpolate==32 else (8,4,2,1) if interpolate==16 else (4,2,1) if interpolate==8 else (2,1) if interpolate==4 else (1,)):
            for col in range(step,view-step,step*2):
                if col in filled:continue
                l,r=records[col-step],records[col+step]
                if l[5]==65535 or l[5]!=r[5]:continue
                if l[1]!=r[1] and not state.get('material_lookup',False):continue
                page=l[1]
                if unwrapped:
                    gap=min(255,3*(l[0]+r[0])//(2*abs(l[0]-r[0]))) if l[0]!=r[0] else 255
                    corrected=abs(coords[col-step]-coords[col+step])>gap
                    midpoint=(coords[col-step]+coords[col+step])//2
                    if corrected:
                        if state.get('weighted_rays',False):
                            delta=coords[col+step]-coords[col-step]
                            if l[5]&0x4000 or not 0<=delta<256:continue
                            midpoint=coords[col-step]+delta*angle_weight(col,step,l[4])//256
                            weighted_columns.add(col)
                        else:
                            if state.get('plane_rays',False) and abs(coords[col-step]-coords[col+step])<256:
                                hit=plane_hit(col,l[5])
                                if hit:
                                    records[col],coords[col],cell=hit
                                    visits[col]={(px>>8)*64+(py>>8),cell}
                                    traced.remove(col);plane_columns.add(col)
                            continue
                    if l[1]!=r[1] or (state.get('coarse_material',False) and step>=8 and not l[5]&0x6000):
                        margin=state.get('material_guard_texels',3)
                        if not margin<=(midpoint&63)<64-margin:continue
                        along=midpoint//64
                        if (l[4]==0 and (l[5]//64)<(px//256)) or (l[4]==1 and (l[5]&63)>=(py//256)):along=63-along
                        cell=(l[5]|along) if l[4]==0 else (along*64|(l[5]&63))
                        tile=tilemap[cell]
                        if not 0<tile<64:continue
                        page=(tile-1)*2+(not l[4])
                    coords[col]=midpoint
                    u=midpoint&63
                else:
                    if abs(l[2]-r[2])>16:continue
                    u=(l[2]+r[2])//2
                h=min(HEIGHTS,key=lambda h:abs(h-(l[0]+r[0])//2))
                records[col]=(h,page,u,0,l[4],l[5])
                traced.remove(col)
                if state.get('span_fill',False) and (not corrected or state.get('weighted_span',False)) and step in (2,4) and unwrapped and (l[1]==r[1] or (state.get('split_span',False) and coords[col+step]//64-coords[col-step]//64==1) or (state.get('mixed_span',False) and valid_materials(coords[col-step],coords[col+step],l))):
                    a,b=coords[col-step],coords[col+step]
                    length=step*2
                    for j in range(1,length):
                        c=col-step+j
                        height=(l[0]*(length-j)+r[0]*j)//length
                        h=min(HEIGHTS,key=lambda h:abs(h-height))
                        coords[c]=a+(b-a)*angle_weight(c,step,l[4],col-step,col+step)//256 if corrected else (a*(length-j)+b*j)//length
                        split=state.get('split_span',False) and b//64-a//64==1
                        page=(l[1] if coords[c]//64==a//64 else r[1]) if split else l[1] if l[1]==r[1] else material(coords[c],l[5],l[4])
                        records[c]=(h,page,coords[c]&63,0,l[4],l[5])
                        traced.discard(c);filled.add(c)
    for col,(h,page,u,dist,side,plane) in enumerate(records):
        a=max(top,80-h//2); b=min(bottom,80+h//2)
        lit=wall_lights[light(h,rows,state.get('light',True))]
        wallpixels+=b-a
        for row in range(top,bottom):
            if row<a:byte=meta['ceiling']*17
            elif row>=b:byte=meta['floor']*17
            else:
                tex=max(0,min(63,(row-(80-h//2))*64//h))
                byte=lit[pages[page][u*64+tex]][row&1]
            address=row*160+left+(col//2 if true else col)
            if true:
                out[address]=(out[address]&15)|(byte&0xf0) if col%2==0 else (out[address]&0xf0)|(byte&15)
            else:out[address]=byte
    seen=set().union(*(visits[col] for col in traced|plane_columns))
    return out,dict(ray_cells=steps,wall_bytes=wallpixels,records=records,visible_tiles=seen,ray_visits=visits,traced_columns=sorted(traced),plane_columns=sorted(plane_columns),weighted_columns=sorted(weighted_columns))


def project_sprites(state, objects, seen, view):
    """Transform the live source records independently of native projection.
    Signed fixed products truncate toward zero, as the source FixedByFrac.
    """
    assets=ASSETS
    true=json.loads((assets/'map.json').read_text()).get('pixels')=='true'
    rows=view//2 if true else view
    shapes=json.loads((assets/'sprites.json').read_text())
    frame_bytes=json.loads((assets/'sprite-stats.json').read_text()).get('frame_bytes',194)
    frames={int(shape):n*frame_bytes for n,shape in enumerate(sorted(shapes,key=int))}
    states=json.loads((assets/'world.json').read_text())['states']
    angle=state['angle'];theta=angle*math.tau/1024
    c=round(math.cos(theta)*256);s=round(-math.sin(theta)*256)
    vx=state['x']-int(c*87/256);vy=state['y']-int(s*87/256)
    def product(a,b):return (-1 if (a<0)!=(b<0) else 1)*(abs(a)*abs(b)//256)
    tilemap=state.get('tilemap') or (assets/'map.bin').read_bytes()
    visible=[]
    for n,obj in enumerate(objects):
        x,y,shape,kind,flags,state_id=obj[:6]
        cell=obj[16] if len(obj)>16 else (x>>8)*64+(y>>8)
        seen_actor=cell in seen or flags&16 and any(0<=cell+d<4096 and cell+d in seen and not tilemap[cell+d] for d in (-1,1,-65,-64,-63,65,64,63))
        if flags&16 and state.get('actor_flags',False):seen_actor=bool(obj[18]&8)
        if shape==65535 or not seen_actor:continue
        dx=x-vx;dy=y-vy
        depth=product(dx,c)+product(dy,s)-32-(32 if flags&16 else 0)
        if not 88<=depth<16384:continue
        raw=min(1024,round(56000/depth))*round(rows*256/160)//256
        h=min(HEIGHTS,key=lambda h:abs(h-raw));hi=HEIGHTS.index(h)*2
        side=product(dy,c)-product(dx,s)
        if flags&2 and depth<256 and -128<side<128:continue
        offset=product(side,h//2)
        if true:offset*=2
        width=h if true else h//2
        left=(view-width)//2+offset;right=left+width
        if right<=0 or left>=view:continue
        rotate=obj[17] if len(obj)>17 else states[state_id//2][1][0]
        if rotate:
            rotation=((angle-obj[8]*128+576)&1023)//128
            shape+=rotation&4 if rotate==2 else rotation
        visible.append([left&65535,right&65535,hi,frames[shape],n*32,h,0])
    h=(rows+1)&~1;left=(view-(h if true else h//2))//2
    game=state.get('game',{})
    if game.get('levelState',0):return visible
    ready=('KNIFE','PISTOL','MACHINEGUN','CHAIN')[game.get('weapon',1)]
    weapon_shape=sprite_ids()['SPR_'+ready+'READY']+game.get('weaponFrame',0)
    visible.append([left,left+(h if true else h//2),HEIGHTS.index(h)*2,frames[weapon_shape],len(objects)*32,h,65535])
    return visible


def overlay_sprites(out, visible, view, walls):
    shapes=json.loads((ASSETS/'sprites.json').read_text())
    stride=json.loads((ASSETS/'map.json').read_text()).get('texel_stride',1)
    true=json.loads((ASSETS/'map.json').read_text()).get('pixels')=='true'
    rows=view//2 if true else view
    frame_bytes=json.loads((ASSETS/'sprite-stats.json').read_text()).get('frame_bytes',194)
    frames={n*frame_bytes:shape for n,shape in enumerate(sorted(shapes,key=int))}
    top=(160-rows)//2;bottom=top+rows;screen_left=(160-rows)//2
    _,sprite_lights=light_tables(json.loads((ASSETS/'map.json').read_text()))
    # Later objects win equal-height ties, matching DrawScaleds' order.
    for _,obj in sorted(enumerate(visible),key=lambda pair:(pair[1][6],pair[1][2],pair[0])):
        left,right,hi,frame,_,h,priority=obj
        if left&32768:left-=65536
        if right&32768:right-=65536
        shape=shapes[frames[frame]]
        lit=sprite_lights[-1 if priority==65535 else light(h,rows)]
        for col in range(max(0,left),min(view,right)):
            if priority!=65535 and hi<HEIGHTS.index(walls[col][0])*2:continue
            u=((col-left)*64//(h if true else h//2) if priority==65535 else
               round((16384 if true else 32768)/h)*(col-left)//256)
            if u>=64:continue
            for a,b,pixels in shape['columns'][u]:
                if a>=200:
                    import pool_cover
                    first,last=pool_cover.plan().span(h,a)
                    start=max(top,first);end=min(bottom,last)
                else:
                    start=max(top,80-h//2+(a*h+63)//64)
                    end=min(bottom,80-h//2+(b*h+63)//64)
                for row in range(start,end):
                    tex=(row-(80-h//2))*64//h
                    if a>=200:
                        tex=pool_cover.plan().slot[h,row] if h<64 else tex
                    else:tex-=a
                    byte=lit[pixels[tex]][row&1]
                    address=row*160+screen_left+(col//2 if true else col)
                    if true:
                        out[address]=(out[address]&15)|(byte&0xf0) if col%2==0 else (out[address]&0xf0)|(byte&15)
                    else:out[address]=byte
    return out


def original_render(state,view):
    """Unquantized source projection: WL_MAIN CalcProjection, WL_DRAW viewpoint,
    CalcHeight and ScalePost; grid and half-cell tests from WL_DR_A.ASM.
    The DOS fixed-point operations become floats here, independently of the
    port's reciprocal/product/height tables and interpolation.
    """
    assets=ASSETS;meta=json.loads((assets/'map.json').read_text())
    grid=state.get('tilemap') or (assets/'map.bin').read_bytes();textures=(assets/'textures.bin').read_bytes()
    stride=meta.get('texel_stride',1);pages={p:i*4096*stride for i,p in enumerate(meta['textures'])}
    theta=state['angle']*math.tau/1024
    vx=state['x']/256-math.cos(theta)*0x5700/65536
    vy=state['y']/256+math.sin(theta)*0x5700/65536
    out=play_border(view);top=(160-view)//2;bottom=top+view;left=(160-view)//2
    doors=state.get('doors',[0]*len(meta['doors']))
    for col in range(view):
        delta=math.atan(((view-1)/2-col)/(view/2)*(65536/(2*(0x5700+0x5800))))
        c=math.cos(theta+delta);s=-math.sin(theta+delta)
        mx,my=math.floor(vx),math.floor(vy);sx=1 if c>=0 else -1;sy=1 if s>=0 else -1
        dx=1/max(abs(c),1e-15);dy=1/max(abs(s),1e-15)
        tx=((mx+1-vx) if sx>0 else (vx-mx))*dx
        ty=((my+1-vy) if sy>0 else (vy-my))*dy
        for _ in range(128):
            if tx<ty:dist=tx;tx+=dx;mx+=sx;side=0
            else:dist=ty;ty+=dy;my+=sy;side=1
            tile=grid[mx*64+my]
            if not tile:continue
            if tile>=192:
                dt=dist+(dx if side==0 else dy)*state['game']['pwallPosition']/256
                if dt>=min(tx,ty):continue
                dist=dt
                frac=((vy+dist*s) if side==0 else (vx+dist*c))%1
                u=min(63,int(frac*64))
                if (side==0 and sx<0) or (side==1 and sy>0):u=63-u
                page=((tile&63)-1)*2+(side==0)
            elif tile>=128:
                door=tile&127;vertical=meta['doors'][door]['vertical']
                dt=(tx-dx/2) if vertical else (ty-dy/2)
                if not dist<=dt<min(tx,ty):continue
                side=0 if vertical else 1;dist=dt
                frac=((vy+dist*s) if vertical else (vx+dist*c))%1
                if frac<doors[door]/256:continue
                u=min(63,int((frac-doors[door]/256)*64));page=98+int(vertical)
            else:
                frac=((vy+dist*s) if side==0 else (vx+dist*c))%1
                u=min(63,int(frac*64))
                if (side==0 and sx<0) or (side==1 and sy>0):u=63-u
                page=(tile-1)*2+(side==0)
            break
        else:raise ValueError('original ray left closed map')
        # Actual DOS post height is heightbuffer >> 2.
        h=max(1,int((2*view)*(0x5700+0x5800)/65536/max(dist*math.cos(delta),0x5800/65536)))
        a=max(top,80-h//2);b=min(bottom,80+(h+1)//2)
        for row in range(top,bottom):
            if row<a:byte=meta['ceiling']*17
            elif row>=b:byte=meta['floor']*17
            else:byte=textures[pages[page]+u*64*stride+min(63,max(0,int((row-(80-h/2))*64/h)))*stride+((row&1) if stride==2 else 0)]
            out[row*160+left+col]=byte
    return out


def main():
    global ASSETS
    ap=argparse.ArgumentParser();ap.add_argument('scene');ap.add_argument('--view',type=int,default=100)
    args=ap.parse_args(); out=Path(args.scene)
    meta=json.loads((ASSETS/'map.json').read_text())
    reports=[]
    mode=json.loads((out/'result.json').read_text()).get('rays','half')
    interpolate=False if mode=='exact' else {'thirtytwo':32,'sixteenth':16,'eighth':8,'quarter':4}.get(mode,True)
    for st in sorted(out.glob('state*.json'),key=lambda p:int(p.stem[5:])):
        n=st.stem[5:]; state=json.loads(st.read_text())
        floor=state.get('game',{}).get('levelIndex',meta.get('level_index',0))
        folder=ROOT/'build/levels'/str(floor)
        if (folder/'sprites.json').exists():ASSETS=folder
        meta=json.loads((ASSETS/'map.json').read_text())
        state["unwrapped_rays"]=json.loads((out/"result.json").read_text()).get("unwrapped_rays",False)
        state["material_lookup"]=json.loads((out/"result.json").read_text()).get("material_lookup",False)
        state["material_guard_texels"]=json.loads((out/"result.json").read_text()).get("material_guard_texels",3)
        state['push_planes']=json.loads((out/'result.json').read_text()).get('push_planes',False)
        state["door_planes"]=json.loads((out/"result.json").read_text()).get("door_planes",False)
        state["coarse_material"]=json.loads((out/"result.json").read_text()).get("coarse_material",False)
        state['vector_weights']=json.loads((out/'result.json').read_text()).get('vector_weights',False)
        state['split_span']=json.loads((out/'result.json').read_text()).get('split_span',False)
        state['mixed_span']=json.loads((out/'result.json').read_text()).get('mixed_span',False)
        state["weighted_span"]=json.loads((out/"result.json").read_text()).get("weighted_span",False)
        state["weighted_rays"]=json.loads((out/"result.json").read_text()).get("weighted_rays",False)
        state["plane_rays"]=json.loads((out/"result.json").read_text()).get("plane_rays",False)
        state["span_fill"]=json.loads((out/"result.json").read_text()).get("span_fill",False)
        grid=out/f'map{n}.bin'
        if grid.exists():state['tilemap']=grid.read_bytes()
        view=state.get('view_width',args.view)
        expected,stats=render(state,view,interpolate=interpolate)
        post_diff=0
        posts=out/f'posts{n}.json'
        if posts.exists():
            reference=[]
            # The hit plane is not stored for span-filled columns (rays 74f5f92); only the anchors keep it and
            # the picture bytes above check what it selects. Height index and column address are compared.
            for h,page,u,dist,side,plane in stats['records']:
                address=meta['column_addresses'][str(page)][u]
                reference.append([HEIGHTS.index(h)*2,address&65535,(address>>16)|(page<<8)])
            native=[post[:3] for post in json.loads(posts.read_text())]
            post_diff=sum(a!=b for a,b in zip(reference,native))+abs(len(reference)-len(native))
        objects=out/f'objects{n}.json'
        projection_diff=0
        if objects.exists():
            world=json.loads(objects.read_text())
            visible=project_sprites(state,world['objects'],stats['visible_tiles'],view)
            projection_diff=sum(a!=b for a,b in zip(visible,world['visible']))+abs(len(visible)-len(world['visible']))
            overlay_sprites(expected,visible,view,stats['records'])
        got=(out/f'frame{n}.bin').read_bytes()
        differences=sum(a!=b for a,b in zip(expected,got))
        reports.append(dict(frame=int(n),differing_bytes=differences,projection_mismatches=projection_diff,wall_post_mismatches=post_diff,ray_cells=stats['ray_cells'],wall_bytes=stats['wall_bytes']))
        hud=out/f'hud{n}.bin'
        if hud.exists():
            actual=hud.read_bytes();wanted=render_hud(state['game'])
            reports[-1]['hud_differing_bytes']=sum(a!=b for a,b in zip(actual,wanted))
            png(out/f'hud{n}.png',actual,hud_palette,height=40)
        png(out/f'frame{n}.png',got,meta['palette'])
        png(out/f'reference{n}.png',expected,meta['palette'])
        rows=view//2 if meta.get('pixels')=='true' else view
        if not (ASSETS/'textures.bin').exists():continue
        original=original_render(state,rows)
        png(out/f'original{n}.png',original,meta['palette'])
        source=dict(state)
        if objects.exists():source['objects']=world['objects']
        source_pixels,_=render(source,view,original=True,interpolate=False)
        from sourceview import rgb_png
        from wolfdata import palette
        rgb_png(out/f'dos256-{n}.png',source_pixels,pal=palette())
        wall_reference,_=render(state,view,interpolate=interpolate)
        reports[-1]['source_projection_diff_percent']=round(100*sum(a!=b for a,b in zip(wall_reference,original))/(rows**2),3)
    (out/'oracle.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps(reports,indent=2))
    if any(r['differing_bytes'] or r['projection_mismatches'] or r['wall_post_mismatches'] or r.get('hud_differing_bytes') for r in reports):raise SystemExit(1)


if __name__=='__main__':main()
