"""Compare short native actor moves with the preceding full-word implementation."""
import memmap
import argparse
import hashlib
import json
import random
import re
import struct
import subprocess
import sys
from pathlib import Path
from check_sight_ratio import Asm,ROOT
from elf import read
from wolfsim import Game,Obj,s32


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True)
    ap.add_argument('--player',action='store_true',help='check the player collision predicate instead of guard movement')
    args=ap.parse_args()
    game=Game(0);ob=Obj(1);vectors=[]
    directions=((1,0),(1,-1),(0,-1),(-1,-1),(-1,0),(-1,1),(0,1),(1,1))
    def case(direction,x,y,move,distance,px=0,py=0,connected=0):
        ob.x=s32(x);ob.y=s32(y);ob.distance=s32(distance);ob.dir=direction;ob.areanumber=0
        game.player.x=s32(px);game.player.y=s32(py);game.areabyplayer[0]=connected
        game.move_obj(ob,move)
        vectors.append(struct.pack('<10I2H',x&0xffffffff,y&0xffffffff,move,distance&0xffffffff,
                                   px&0xffffffff,py&0xffffffff,ob.x&0xffffffff,ob.y&0xffffffff,
                                   ob.distance&0xffffffff,int(abs(s32(px-x))>65536 or abs(s32(py-y))>65536),direction,connected))
    for direction in range(8):
        for high in (0,1,32,63,32767,32768,65535):
            for low in (0,1,32767,32768,65534,65535):
                for move in (0,1,680,3000,43520,65535):
                    for distance in (0,65536,0xffff0000,0xffffffff):
                        case(direction,high*65536+low,(high^65535)*65536+(low^65535),move,distance)
        dx,dy=directions[direction]
        for move in ((0,1,680,3000,43520,65535) if args.player else (1,680,3000,43520,65535)):
            for xdist in (-65537,-65536,-65535,0,65535,65536,65537):
                for ydist in (-65537,-65536,-65535,0,65535,65536,65537):
                    case(direction,0x208000,0x208000,move,65536,
                         0x208000+dx*move-xdist,0x208000+dy*move-ydist,1)
    rng=random.Random(65816)
    for _ in range(4096):
        case(rng.randrange(8),rng.randrange(2**32),rng.randrange(2**32),rng.randrange(65536),rng.randrange(2**32))
    out=ROOT/'build/tests'/('collision-range-native' if args.player else 'short-moves-native');out.mkdir(parents=True,exist_ok=True)
    (out/'vectors.bin').write_bytes(b''.join(vectors))
    variants=[];end=0
    for name,path in (('before',args.before),('after',ROOT/'build/wolf.elf')):
        seg,sym=read(path)
        code=bytearray(32768)
        for s in seg:
            if 0xd8000<=s['address']<0xe0000:
                offset=s['address']-0xd8000;code[offset:offset+len(s['data'])]=s['data'];end=max(end,s['address']+len(s['data']))
        (out/f'{name}.bin').write_bytes(code)
        variants.append(dict(name=name,path=str(out/f'{name}.bin'),entry=sym['moveActorInBox' if args.player else 'MoveObj'],mark=sym['actorNext' if args.player else 'MarkActorCell'],
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    probe=(end+15)&~15
    p=Asm(probe&65535,bank=13);p.sei();p.cld();p.rep(0x30);p.lda_i(0x1100);p.tcd();p.ldx_i(0x1fff);p.txs();p.pea(0x2828);p.plb();p.plb()
    p.label('case');p.rep(0x30);p.ldx_i(0x3040)
    call=p.here+0xd0000;p.jsr(0)
    if args.player:p.lda_i(0);p.byte(0x2a);p.sta_al(0x11fe)
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.bra('case')
    driver=p.resolve();assert probe+len(driver)<=0xe0000
    script=memmap.fill(r'''
local s=mem
local armed=false
local vfile=assert(io.open(VECTORS,"rb"));local vectors=vfile:read("a");vfile:close()
local variants=VARIANTS
local version=1
local index=0
local t=0
local elapsed=0
local expected={}
local expectedCarry=0
local function loadCase()
 local x,y,move,distance,px,py,ex,ey,ed,carry,direction,connected=string.unpack("<I4I4I4I4I4I4I4I4I4I4I2I2",vectors,index*44+1)
 s:write_u32(@MM:OLD_WORLD+0x3040@,x);s:write_u32(@MM:OLD_WORLD+0x3044@,y);s:write_u32(@MM:OLD_WORLD+0x3048@,distance)
 s:write_u32(0x112c,move);s:write_u16(0x1100,0x3040)
 s:write_u16(@MM:OLD_WORLD+0x3056@,direction);s:write_u16(@MM:OLD_WORLD+0x305c@,0)
 s:write_u16(@MM:OLD_WORLD+0x6b80@,connected);s:write_u32(@MM:OLD_WORLD+0x3000@,px);s:write_u32(@MM:OLD_WORLD+0x3004@,py)
 expected={ex,ey,ed}
 if PLAYERTEST then
  s:write_u16(@MM:OLD_WORLD+0x306e@,0);s:write_u16(@MM:OLD_WORLD+0x1000@,0x3040)
  expected={x,y,distance};expectedCarry=carry
 end
end
local function installDriver()
 for i,n in ipairs(DRIVER) do s:write_u8(PROBE+i-1,n) end
end
local function installVersion()
 local v=variants[version];local f=assert(io.open(v.path,"rb"));local code=f:read("a");f:close()
 for i=1,#code do s:write_u8(0xd8000+i-1,code:byte(i)) end
 s:write_u8(v.mark,0x60)
 if PLAYERTEST then s:write_u16(v.mark,0x6038) end
 installDriver()
 s:write_u16(CALL+1,v.entry&65535)
 loadCase()
end
moveEntry=s:install_read_tap(PROBE,PROBE,"move-entry",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then installVersion() end
end)
moveCost=s:install_read_tap(CALL,CALL,"move-cost",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then t=manager.machine.time:as_double() end
end)
moveResult=s:install_write_tap(0x3f0,0x3f0,"move-result",function(a,d,m)
 if d==1 and not armed then
  armed=true;installDriver()
  s:write_u32(FRAMEDONE,0x0d00005c|((PROBE&65535)<<8))
 elseif d==254 then
  elapsed=elapsed+manager.machine.time:as_double()-t
  if PLAYERTEST and s:read_u16(0x11fe)~=expectedCarry then
   print(string.format("FAILED_CARRY %s %d %d %d",variants[version].name,index,s:read_u16(0x11fe),expectedCarry));manager.machine:exit();return
  end
  for i=1,3 do
   local got=s:read_u32(@MM:OLD_WORLD+0x3040@+(i-1)*4)
   if got~=expected[i] then print(string.format("FAILED %s %d %d %u %u",variants[version].name,index,i,got,expected[i]));manager.machine:exit();return end
  end
  index=index+1
  if index==#vectors//44 then
   print(string.format("RESULT %s %d %.12f",variants[version].name,index,elapsed))
   version=version+1;index=0;elapsed=0
   if version>#variants then manager.machine:exit();return end
   installVersion()
  else loadCase() end
 end
end)
''')
    variant_lua='{'+','.join('{name='+json.dumps(v['name'])+',path='+json.dumps(v['path'])+',entry='+str(v['entry'])+',mark='+str(v['mark'])+'}' for v in variants)+'}'
    for a,b in [('PLAYERTEST','true' if args.player else 'false'),('VECTORS',json.dumps(str(out/'vectors.bin'))),('VARIANTS',variant_lua),('DRIVER','{'+','.join(map(str,driver))+'}'),('PROBE',str(probe)),('CALL',str(call)),('FRAMEDONE',str(sym['frameDone']))]:script=script.replace(a,b)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();results=re.findall(r'^RESULT (\w+) (\d+) (\S+)',log,re.M)
    if len(results)!=2 or any(int(count)!=len(vectors) for name,count,t in results):raise SystemExit(log[-3000:])
    report=dict(cases=len(vectors),failures=[],variants=variants,times_ms={name:float(t)*1000 for name,count,t in results},
                checks='all eight directions; unsigned short steps; coordinate carry/borrow/wrap; distance borrow; inclusive player collision and exact undo; same vectors on both native versions',
                timing='includes the same call/result probe overhead; interrupts disabled; actor marker replaced with RTS')
    if args.player:
        report.update(checks='both player collision axes at and around inclusive one-tile boundaries; coordinate wrap; same vectors on both native versions',
                      timing='includes the same call/result probe overhead; interrupts disabled; actorNext returns clear after the tested candidate')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
