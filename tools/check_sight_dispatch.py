"""Check native sight entry paths against the source model and preceding build."""
import memmap
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
from check_sight_ratio import ROOT, Asm
from elf import read
from wolfsim import Game, Obj


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True);args=ap.parse_args()
    out=ROOT/'build/tests/sight-dispatch-native';out.mkdir(parents=True,exist_ok=True)
    _,sym=read(ROOT/'build/wolf.elf');game=Game(0);game.tilemap=[0]*4096
    poses=((0,0),(4,0),(-4,0),(0,4),(0,-4))
    cases=[]
    inputs=list(itertools.product((3,5,6,7),range(9),(0,1),(0,1),(0,64),poses))
    inputs=[(*c,0,1,65536) for c in inputs]
    inputs += [(kind,0,connected,0,0,(0,0),timer,tics,distance)
               for kind,connected,timer,tics,distance in itertools.product((3,5,6,7),(0,1),(1,4,65),(1,4,64),(-1,65536))]
    sounds={3:sym['HALTSND'],5:sym['SCHUTZADSND'],6:sym['DOGBARKSND'],7:sym['GUTENTAGSND']}
    for index,(kind,direction,connected,noise,ambush,pose,timer,tics,distance) in enumerate(inputs):
        ob=Obj(1);ob.x=ob.y=0x208000;ob.tilex=ob.tiley=32;ob.areanumber=0
        ob.obclass=kind;ob.dir=direction;ob.flags=ambush|4;ob.state=game.states['s_grdstand']
        ob.temp2=timer;ob.speed=512;ob.distance=distance;ob.active=1
        px=ob.x+pose[0]*65536;py=ob.y+pose[1]*65536
        game.player.x=px;game.player.y=py;game.player.tilex=px>>16;game.player.tiley=py>>16
        game.plux=px>>8;game.pluy=py>>8
        game.areabyplayer=[connected]*len(game.areabyplayer);game.tics=tics;game.madenoise=noise
        game.rndindex=index&255;before_index=game.rndindex
        reacted=game.sight_player(ob)
        state=sym[ob.state.name]
        phase=('reaction' if reacted else 'countdown') if timer else 'disconnected' if not connected else 'ambush' if ambush else 'noise' if noise else 'search'
        want=[state,ob.ticcount,ob.flags,ob.speed,ob.temp2,ob.distance&0xffffffff,game.rndindex,sounds[kind] if reacted else 0,int(reacted)]
        cases.append([kind,direction,connected,noise,ambush,px,py,timer,tics,distance&0xffffffff,before_index,want,phase])
    variants=[];end=0
    for name,path in (('before',args.before),('after',ROOT/'build/wolf.elf')):
        segments,symbols=read(path);code=bytearray(32768)
        for seg in segments:
            if 0xd8000<=seg['address']<0xe0000:
                offset=seg['address']-0xd8000;code[offset:offset+len(seg['data'])]=seg['data'];end=max(end,seg['address']+len(seg['data']))
        (out/f'{name}.bin').write_bytes(code)
        variants.append(dict(name=name,path=str(out/f'{name}.bin'),entry=symbols['SightPlayer'],sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    probe=(end+15)&~15
    p=Asm(probe&65535,bank=13);p.sei();p.cld();p.rep(0x30);p.lda_i(0x1100);p.tcd();p.ldx_i(0x1fff);p.txs();p.pea(0x2828);p.plb();p.plb()
    p.label('case');p.rep(0x30);p.ldx_i(0x3040);call=p.here+0xd0000;p.jsr(0)
    p.lda_i(0);p.byte(0x2a);p.sta_al(0x11fe)
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.bra('case');driver=p.resolve();assert probe+len(driver)<=0xe0000
    script=memmap.fill(r'''
local s=mem
local variants=VARIANTS
local cases=CASES
local v=VARS
local version,index=1,1
local armed=false
local start=0
local totals,counts={},{}
local function loadCase()
 local c=cases[index]
 for i=0,62,2 do s:write_u16(0x283040+i,0) end
 s:write_u32(@MM:OLD_WORLD+0x3040@,@MM:ART_BRIGHT+0x8000@);s:write_u32(@MM:OLD_WORLD+0x3044@,@MM:ART_BRIGHT+0x8000@)
 s:write_u32(@MM:OLD_WORLD+0x3048@,c[10]);s:write_u16(@MM:OLD_WORLD+0x3050@,GUARDSTAND)
 s:write_u16(@MM:OLD_WORLD+0x3054@,c[5]|4);s:write_u16(@MM:OLD_WORLD+0x3056@,c[2]);s:write_u16(@MM:OLD_WORLD+0x3058@,32);s:write_u16(@MM:OLD_WORLD+0x305a@,32)
 s:write_u16(@MM:OLD_WORLD+0x305e@,c[1]);s:write_u16(@MM:OLD_WORLD+0x3060@,1);s:write_u16(@MM:OLD_WORLD+0x3064@,512);s:write_u16(@MM:OLD_WORLD+0x3066@,c[8])
 s:write_u32(@MM:OLD_WORLD+0x3000@,c[6]);s:write_u32(@MM:OLD_WORLD+0x3004@,c[7]);s:write_u16(@MM:OLD_WORLD+0x3018@,c[6]>>16);s:write_u16(@MM:OLD_WORLD+0x301a@,c[7]>>16)
 s:write_u8(@MM:ART_FULL+0x6b80@,c[3]);s:write_u16(v.V_madenoise,c[4]);s:write_u16(v.V_tics,c[9]);s:write_u16(v.V_rndindex,c[11]);s:write_u16(v.V_sound,0)
 s:write_u16(v.V_plux,c[6]>>8);s:write_u16(v.V_pluy,c[7]>>8);s:write_u16(0x1100,0x3040);s:write_u16(0x11c4,0xdead)
end
local function installDriver()
 for i,n in ipairs(DRIVER) do s:write_u8(PROBE+i-1,n) end
end
local function installVersion()
 local row=variants[version];local f=assert(io.open(row.path,"rb"));local code=f:read("a");f:close()
 for i=1,#code do s:write_u8(0xd8000+i-1,code:byte(i)) end
 installDriver();s:write_u16(CALL+1,row.entry&65535);loadCase()
end
sightEntry=s:install_read_tap(PROBE,PROBE,"sight-entry",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then
  for i=0,4095 do s:write_u8(@MM:ART_FULL@+i,0);s:write_u8(0xd1000+i,0) end
  installVersion()
 end
end)
sightCost=s:install_read_tap(CALL,CALL,"sight-cost",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then start=manager.machine.time:as_double() end
end)
sightResult=s:install_write_tap(0x3f0,0x3f0,"sight-result",function(a,d,m)
 if d==1 and not armed then
  armed=true;installDriver();s:write_u32(FRAMEDONE,0x0d00005c|((PROBE&65535)<<8))
 elseif d==254 then
  local c=cases[index];local phase=c[13]
  totals[phase]=(totals[phase] or 0)+manager.machine.time:as_double()-start;counts[phase]=(counts[phase] or 0)+1
  local actual={s:read_u16(@MM:ART_FULL+0x3050@),s:read_u16(@MM:ART_FULL+0x3052@),s:read_u16(@MM:ART_FULL+0x3054@),s:read_u16(@MM:ART_FULL+0x3064@),s:read_u16(@MM:ART_FULL+0x3066@),s:read_u32(@MM:ART_FULL+0x3048@),s:read_u16(v.V_rndindex),s:read_u16(v.V_sound),s:read_u16(0x11fe)}
  for i,n in ipairs(c[12]) do
   assert(actual[i]==n,string.format("sight differs %s case=%d field=%d got=%d expected=%d",variants[version].name,index,i,actual[i],n))
  end
  index=index+1
  if index>#cases then
   for phase,total in pairs(totals) do print(string.format("COST %s %s %d %.12f",variants[version].name,phase,counts[phase],total/counts[phase])) end
   print(string.format("RESULT %s %d",variants[version].name,#cases))
   version=version+1;index=1;totals={};counts={}
   if version>#variants then manager.machine:exit();return end
   installVersion()
  else loadCase() end
 end
end)
''')
    def lua(value):
        if isinstance(value,str):return json.dumps(value)
        if isinstance(value,(int,float)):return str(value)
        if isinstance(value,list):return '{'+','.join(lua(v) for v in value)+'}'
        return '{'+','.join(k+'='+lua(v) for k,v in value.items())+'}'
    vars={k:memmap.OLD_WORLD+a for k,a in sym.items() if k.startswith('V_')}
    for a,b in dict(VARIANTS=lua(variants),CASES=lua(cases),VARS=lua(vars),GUARDSTAND=str(sym['s_grdstand']),DRIVER=lua(list(driver)),PROBE=str(probe),CALL=str(call),FRAMEDONE=str(sym['frameDone'])).items():script=script.replace(a,b)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();results=re.findall(r'^RESULT (\w+) (\d+)',log,re.M)
    if results!=[(v['name'],str(len(cases))) for v in variants]:raise SystemExit(log[-3000:])
    costs=[dict(version=v,phase=phase,calls=int(n),mean_us=float(t)*1e6) for v,phase,n,t in re.findall(r'^COST (\w+) (\w+) (\d+) (\S+)',log,re.M)]
    report=dict(cases_per_version=len(cases),failures=[],costs=costs,variants=variants,
                checks='source-model countdown, state, flags, speed, distance, RNG, reaction carry and native sound ID; four classes, nine directions, connected/disconnected areas, noise/ambush, five player offsets, 1/4/64 tics and positive/negative distance',
                timing='equal JSR/result-probe overhead; IRQ disabled; empty map initialized before use; L_ARG is scratch')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
