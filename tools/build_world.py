"""Convert ScanInfoPlane, statinfo and original enemy state data."""
import argparse
import json
import math
import struct
import shutil
from buildconfig import config
from wolfdata import ROOT,PROFILE,maps
from wolf_source import sprite_ids,statics,states,random_table,attack_table,hitpoints

OUT=ROOT/'build/assets';GEN=ROOT/'build/gen'
PICKUPS={name:n for n,name in enumerate(('dressing','block','bo_gibs','bo_alpo','bo_firstaid','bo_key1','bo_key2','bo_key3','bo_key4','bo_cross','bo_chalice','bo_bible','bo_crown','bo_clip','bo_clip2','bo_machinegun','bo_chaingun','bo_food','bo_fullheal','bo_25clip','bo_spear'))}

def build_level(level_index,out,gen):
 out.mkdir(parents=True,exist_ok=True);gen.mkdir(parents=True,exist_ok=True)
 level=maps()[level_index];tiles,info,_=level['planes'];ids=sprite_ids();st=states();sid={name:n for n,(name,row) in enumerate(st)}
 objects=[];blocking=bytearray(4096);areas=bytearray([255]*4096);paths=bytearray([255]*4096)
 for y in range(64):
  for x in range(64):
   tile=tiles[y*64+x];obj=info[y*64+x];index=x*64+y
   blocking[index]=int(tile<107 and tile!=106)
   if tile>=107:areas[index]=tile-107
   elif tile==106:
    for nx,ny in ((x+1,y),(x,y-1),(x,y+1),(x-1,y)):
     t=tiles[ny*64+nx]
     if t>=107:areas[index]=t-107
   if 90<=obj<=99:paths[index]=obj-90
   shape=kind=flags=state=hp=direction=minimum=0
   if 23<=obj<=(74 if PROFILE.spear else 70):
    pic,typ=statics()[obj-23];shape=ids[pic];kind=PICKUPS[typ]
    flags=1 if typ=='block' else (2 if typ.startswith('bo_') else 0)
    if flags&1:blocking[index]=1
   elif obj==124:
    shape=ids['SPR_GRD_DEAD'];flags=64
   elif obj==214 and not PROFILE.spear:
    kind=103;state=sid['s_bossstand'];hp=1050;direction=6;flags=4|8|16
   else:
    groups=((108,0,False),(112,0,True),(126,2,False),(130,2,True),(134,1,False),(138,1,True))
    found=False
    for base,family,patrol in groups:
     for shift,diff in ((0,0),(36,2),(72,3)):
      if base+shift<=obj<base+shift+4:
       minimum=diff;kind=100+family;direction=(obj-base-shift)*2
       prefix=('grd','dog','ss')[family]
       state=sid['s_'+prefix+('path1' if patrol or family==1 else 'stand')]
       hp=(25,1,100)[family];flags=4|16|(32 if patrol else 0)|(8 if tile==106 else 0)
       found=True;break
     if found:break
    if not found:continue
   if state:shape=st[state][1][1]
   gx=x;gy=y
   if flags&32:
    gx+=(1,0,-1,0)[direction//2];gy+=(0,-1,0,1)[direction//2]
   row=[x*256+128,y*256+128,shape,kind,flags,state*2,st[state][1][2] if state else 0,hp,direction,areas[index],256 if flags&32 else 0,0,gx,gy,minimum,index]
   objects.append(row)
 blob=bytearray(0xfd00)
 # Spear consumes this file's level metadata only. Native setup builds
 # actors and statics separately from the original planes; the legacy
 # combined object table cannot represent its most populated floors.
 if not PROFILE.spear:
  if len(objects)>512:raise ValueError('original object limit')
  for n,row in enumerate(objects):
   struct.pack_into('<16H',blob,n*32,*row)
 blob[0x4000:0x5000]=areas;blob[0x5000:0x6000]=paths;blob[0x6000:0x7000]=blocking
 doors=json.loads((out/'map.json').read_text())['doors']
 if PROFILE.spear:
  # Mission-pack doors can border walls or form chains. Resolve their areas
  # from an open side, as native setup does after removing ambush markers.
  for _ in doors:
   changed=False
   for door in doors:
    index=door['x']*64+door['y'];step=64 if door['vertical'] else 1
    if areas[index]<37:continue
    valid=[areas[i] for i in (index-step,index+step) if areas[i]<37]
    if valid:areas[index]=valid[0];changed=True
   if not changed:break
 connections=[]
 for door in doors:
  x,y=door['x'],door['y'];step=64 if door['vertical'] else 1;index=x*64+y
  a,b=areas[index-step],areas[index+step]
  if PROFILE.spear:
   if a>=37:a=b
   if b>=37:b=a
   if max(a,b)>=37:raise ValueError('Spear door has no adjacent area')
  if max(a,b)>=64:raise ValueError('door area outside original floor')
  connections.append((a,b));areas[index]=a
 blob[0x4000:0x5000]=areas
 blob[0x7000:0x8000]=(out/'map.bin').read_bytes()
 blob[0xc000:0xd000]=paths
 blob[0xd000:0xe000]=areas
 blob[0xe000:0xf000]=blocking
 for maximum in range(128):
  for minimum in range(128):
   blob[0x8000+maximum*128+minimum]=round(math.atan2(minimum,maximum)*1024/math.tau) if minimum<=maximum else 0
 for family,speed in enumerate((2,1500/256,2,2,6,3000/256,8,6)):
  for tics in range(13):struct.pack_into('<H',blob,0xf000+family*26+tics*2,round(speed*tics))
 enemies=[n*32 for n,o in enumerate(objects) if o[4]&16]
 for n,offset in enumerate(enemies):struct.pack_into('<H',blob,0xf200+n*2,offset)
 meta=json.loads((out/'map.json').read_text())
 struct.pack_into('<16H',blob,0xf700,0x4c57,len(objects),len(objects)*32,len(enemies)*2,len(doors)*2,meta['spawn']['x'],meta['spawn']['y'],meta['spawn']['angle'],level_index,*([0]*7))
 for page,offset in meta['directory_offsets'].items():
  struct.pack_into('<H',blob,0xf800+int(page)*2,offset)
 for n,(door,connection) in enumerate(zip(doors,connections)):
  struct.pack_into('<5H',blob,0xf940+n*10,door['x']*64+door['y'],int(door['vertical']),door['lock'],*connection)
 (out/'world.bin').write_bytes(blob)
 (out/'world.json').write_text(json.dumps(dict(level=level_index,objects=objects,states=st),separators=(',',':'))+'\n')
 constants=['WORLDCOUNT .equ %d'%len(objects),'WORLDBYTES .equ %d'%(len(objects)*32)]
 constants+=['WORLDENEMYBYTES .equ %d'%(len(enemies)*2)]
 meta=json.loads((out/'map.json').read_text())
 constants+=['LEVELSTART'+name.upper()+' .equ '+str(meta['spawn'][name]) for name in ('x','y','angle')]
 constants+=['LEVELDOORS .equ '+str(len(doors))]
 for n,(name,row) in enumerate(st):constants.append(name+' .equ '+str(n*2))
 (gen/'world.inc').write_text('\n'.join(constants)+'\n')
 think={'NULL':0,'T_Stand':1,'T_Path':2,'T_Chase':3,'T_DogChase':4}
 action={'NULL':0,'A_DeathScream':1,'T_Shoot':2,'T_Bite':3}
 lines=[' .section gamedata, data, root']
 for name,values in [('stateRotate',[row[0] for _,row in st]),('stateShape',[row[1] for _,row in st]),('stateTicks',[row[2] for _,row in st]),('stateThink',[think[row[3]] for _,row in st]),('stateAction',[action[row[4]] for _,row in st]),('stateNext',[sid[row[5]]*2 for _,row in st])]:
  lines.append(name+': .word '+','.join(map(str,values)))
 lines.append('randomTable: .byte '+','.join(map(str,random_table())))
 for name,speed in (('playerForwardSpeed',35*150/256),('playerBackSpeed',35*100/256)):
  lines.append(name+': .word '+','.join(str(min(175,round(speed*tics))) for tics in range(13)))
 for name,values,kind in [('rngSixth',[n//6 for n in range(256)],'.byte'),('rngTwentieth',[n%20 for n in range(256)],'.byte'),('sourceHitpoints',[hp for row in hitpoints() for hp in row],'.word'),('weaponTics',[r[0] for r in attack_table()],'.word'),('weaponAction',[r[1]&65535 for r in attack_table()],'.word'),('weaponFrames',[r[2] for r in attack_table()],'.word'),('weaponReady',[ids['SPR_'+prefix+'READY'] for prefix in ('KNIFE','PISTOL','MACHINEGUN','CHAIN')],'.word')]:
  lines.append(name+': '+kind+' '+','.join(map(str,values)))
 for table,ending in [('familyChase','chase1'),('familyShoot','shoot1'),('familyDie','die1'),('familyPain','pain'),('familyPain1','pain1')]:
  names=['s_'+prefix+ending for prefix in ('grd','dog','ss','trans' if PROFILE.spear else 'boss')]
  if ending=='shoot1':names[1]='s_dogjump1'
  if ending.startswith('pain'):names[1]='s_dogchase1';names[3]='s_transchase1' if PROFILE.spear else 's_bosschase1'
  lines.append(table+': .word '+','.join(str(sid.get(name,0)*2) for name in names))
 lines.append('attackChance: .word '+','.join(str(min(300,(tics*16)//max(dist,1))) for tics in range(13) for dist in range(64)))
 shapes={typ:ids[pic] for pic,typ in statics()}
 lines.append('pickupShapes: .word '+','.join(str(shapes.get(typ,ids['SPR_STAT_0'])) for typ in PICKUPS))
 for name,values in [('doorAreaA',[a for a,b in connections]),('doorAreaB',[b for a,b in connections]),('doorCells',[d['x']*64+d['y'] for d in doors]),('doorLocks',[d['lock'] for d in doors])]:
  lines.append(name+': .word '+','.join(map(str,values+[0]*(64-len(values)))))
 (gen/'states.inc').write_text('\n'.join(lines)+'\n')
 print('world:',len(objects),'objects,',len(st),'original states')

def main():
 for level in range(PROFILE.floors):
  out=ROOT/'build/levels'/str(level)
  gen=ROOT/'build/gen/levels'/str(level)
  build_level(level,out,gen)
 selected=config()['floor']-1
 for name in ('world.bin','world.json'):shutil.copyfile(ROOT/'build/levels'/str(selected)/name,OUT/name)
 for name in ('world.inc','states.inc'):shutil.copyfile(ROOT/'build/gen/levels'/str(selected)/name,GEN/name)

if __name__=='__main__':main()
