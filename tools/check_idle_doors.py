"""Compare native door and optional guard batches with the preceding build."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from check_sight_ratio import ROOT,Asm
from elf import read


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True)
    ap.add_argument('--actors',action='store_true',help='include stand and timed path states with one and three active guards')
    args=ap.parse_args();case_total=3780 if args.actors else 420
    out=ROOT/'build/tests/idle-doors-native';out.mkdir(parents=True,exist_ok=True)
    variants=[];end=0
    for name,path in (('before',args.before),('after',ROOT/'build/wolf.elf')):
        segments,sym=read(path);code=bytearray(32768)
        for seg in segments:
            if 0xd8000<=seg['address']<0xe0000:
                offset=seg['address']-0xd8000;code[offset:offset+len(seg['data'])]=seg['data'];end=max(end,seg['address']+len(seg['data']))
        (out/f'{name}.bin').write_bytes(code)
        variants.append(dict(name=name,path=str(out/f'{name}.bin'),entry=sym['LogicWorldRun'],sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    probe=(end+15)&~15
    p=Asm(probe&65535,bank=13);p.sei();p.cld();p.rep(0x30);p.lda_i(0x1100);p.tcd();p.ldx_i(0x1fff);p.txs();p.pea(0x2828);p.plb();p.plb()
    p.label('case');p.rep(0x30);p.lda_al(0x11fc)
    call=p.here+0xd0000;p.jsl(0)
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.bra('case')
    driver=p.resolve();assert probe+len(driver)<=0xe0000
    definitions={k:int(v,0)+memmap.OLD_WORLD for k,v in re.findall(r'^(V_\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    script=memmap.fill(r'''
local s=mem
local vars=VARS
local variants=VARIANTS
local counts={1,2,4,8,16,32,64}
local version=1
local index=0
local armed=false
local mode=0
local count=0
local start=0
local totals={}
local checks=0
local actors=0
local style=0
local expectedState=0
local expectedTics=0
local expectedReaction=0
local function loadCase()
 count=counts[index%7+1];mode=(index//7)%3
 style=ACTORSENABLED and (index//63)%3 or 0
 expectedState=style==0 and GUARDSTAND or GUARDPATH
 expectedTics=({0,1,20})[style+1];expectedReaction=300
 local initialState,initialTics=expectedState,expectedTics
 for tic=1,count do
  if expectedTics~=0 then
   expectedTics=expectedTics-1
   while expectedTics<=0 do
    assert(s:read_u16(@MM:OLD_WORLD@+expectedState+8)==0,"fixture acquired an action")
    expectedState=s:read_u16(@MM:OLD_WORLD@+expectedState+10)
    local duration=s:read_u16(@MM:ART_FULL@+expectedState+4)
    if duration==0 then expectedTics=0;break end
    expectedTics=expectedTics+duration
   end
  end
  if s:read_u16(@MM:ART_FULL@+expectedState+6)~=0 then expectedReaction=expectedReaction-1 end
 end
 s:write_u16(0x11fc,count)
 actors=ACTORSENABLED and ({0,1,3})[(index//21)%3+1] or 0
 s:write_u16(@MM:ART_FULL+0x302a@,actors>0 and 0x3040 or 0)
 for i=1,3 do
  local ob=@MM:ART_FULL+0x3000@+64*i
  for j=0,62,2 do s:write_u16(ob+j,0) end
  s:write_u16(ob+2,3+i);s:write_u16(ob+6,21)
  s:write_u16(ob+16,initialState);s:write_u16(ob+18,initialTics);s:write_u16(ob+20,4)
  s:write_u16(ob+32,1);s:write_u16(ob+38,300)
  s:write_u16(ob+42,i<actors and 0x3000+64*(i+1) or 0)
 end
 s:write_u16(vars.V_victoryflag,0);s:write_u16(vars.V_madenoise,1)
 s:write_u16(@MM:ART_FULL+0x3ca82@,mode==1 and 0 or 65535);s:write_u16(@MM:ART_FULL+0x3ca84@,65535)
 s:write_u16(@MM:OLD_WORLD+0x6580@,10);s:write_u16(@MM:OLD_WORLD+0x6500@,mode==1 and 0 or 1)
 s:write_u16(@MM:ART_FULL+0x6300@,mode==1 and 65535 or 0)
 s:write_u16(vars.V_pwallstate,mode==2 and 10 or 0)
 s:write_u16(vars.V_pwallpos,mode==2 and 5 or 0)
 s:write_u16(PWALLPOSITION,mode==2 and 20 or 0)
 s:write_u16(WALLDIRTY,0);s:write_u16(0x11ea,0)
end
local function installDriver()
 for i,n in ipairs(DRIVER) do s:write_u8(PROBE+i-1,n) end
end
local function installVersion()
 local v=variants[version];local f=assert(io.open(v.path,"rb"));local code=f:read("a");f:close()
 for i=1,#code do s:write_u8(0xd8000+i-1,code:byte(i)) end
 installDriver();s:write_u16(CALL+1,v.entry&65535);s:write_u8(CALL+3,13)
 loadCase()
end
doorEntry=s:install_read_tap(PROBE,PROBE,"door-entry",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then installVersion() end
end)
doorCost=s:install_read_tap(CALL,CALL,"door-cost",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then start=manager.machine.time:as_double() end
end)
doorResult=s:install_write_tap(0x3f0,0x3f0,"door-result",function(a,d,m)
 if d==1 and not armed then
  armed=true;installDriver();s:write_u32(FRAMEDONE,0x0d00005c|((PROBE&65535)<<8))
 elseif d==254 then
  local elapsed=manager.machine.time:as_double()-start
  local key=index%(ACTORSENABLED and 189 or 21)+1;totals[key]=(totals[key] or 0)+elapsed
  local pos=mode==2 and ((10+count)//2)&63 or 0
  local want={{vars.V_tics,1},{vars.V_madenoise,0},{@MM:OLD_WORLD+0x302a@,actors>0 and 0x3040 or 0},
   {@MM:ART_FULL+0x3ca82@,mode==1 and 0 or 65535},{@MM:OLD_WORLD+0x6580@,mode==1 and 10+count or 10},
   {@MM:ART_FULL+0x6300@,mode==1 and 65535 or 0},{vars.V_pwallstate,mode==2 and 10+count or 0},
   {vars.V_pwallpos,pos},{PWALLPOSITION,pos*4},{WALLDIRTY,mode==2 and 1 or 0},
   {0x11ea,mode==2 and 1 or 0}}
  for _,pair in ipairs(want) do
   if s:read_u16(pair[1])~=pair[2] then print(string.format("FAILED %s %d %x %d %d",variants[version].name,index,pair[1],s:read_u16(pair[1]),pair[2]));manager.machine:exit();return end
  end
  for i=1,actors do
   local ob=@MM:ART_FULL+0x3000@+64*i
   assert(s:read_u16(ob+16)==expectedState and s:read_u16(ob+18)==expectedTics and s:read_u16(ob+20)==4 and s:read_u16(ob+32)==1 and s:read_u16(ob+38)==expectedReaction,"guard tic state differs")
   assert(s:read_u16(ob+52)==(3+i)*64+21,"guard cell publication differs")
  end
  checks=checks+1;index=index+1
  if index==CASETOTAL then
   for key,total in pairs(totals) do print(string.format("COST %s %d %d %d %d %.12f",variants[version].name,((key-1)//7)%3,counts[(key-1)%7+1],({0,1,3})[((key-1)//21)%3+1],(key-1)//63,total/20)) end
   print(string.format("RESULT %s %d",variants[version].name,index))
   version=version+1;index=0;totals={}
   if version>#variants then manager.machine:exit();return end
   installVersion()
  else loadCase() end
 end
end)
''')
    variants_lua='{'+','.join('{name='+json.dumps(v['name'])+',path='+json.dumps(v['path'])+',entry='+str(v['entry'])+'}' for v in variants)+'}'
    replacements=dict(VARS='{'+','.join(k+'='+str(v) for k,v in definitions.items())+'}',VARIANTS=variants_lua,
                      DRIVER='{'+','.join(map(str,driver))+'}',PROBE=str(probe),CALL=str(call),FRAMEDONE=str(sym['frameDone']),
                      PWALLPOSITION=str(sym['pwallPosition']),WALLDIRTY=str(sym['wallDirty']),
                      ACTORSENABLED='true' if args.actors else 'false',CASETOTAL=str(case_total),
                      GUARDSTAND=str(sym['s_grdstand']),GUARDPATH=str(sym['s_grdpath1']))
    for a,b in replacements.items():script=script.replace(a,b)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();results=re.findall(r'^RESULT (\w+) (\d+)',log,re.M)
    if results!=[('before',str(case_total)),('after',str(case_total))]:raise SystemExit(log[-3000:])
    costs=[dict(version=v,mode=('idle','open_door','pushwall')[int(m)],tics=int(n),actors=int(a),state=('stand','path_expiry','path_running')[int(k)],mean_ms=float(t)*1000)
           for v,m,n,a,k,t in re.findall(r'^COST (\w+) (\d+) (\d+) (\d+) (\d+) (\S+)',log,re.M)]
    report=dict(cases_per_version=case_total,actor_counts=[0,1,3] if args.actors else [0],failures=[],variants=variants,costs=costs,
                checks='0/1/3 active stand/path guards when requested, initial countdowns 0/1/20 and exact transitions/thinker counts; 1-64 whole world tics; empty systems, active open-door timer, active pushwall fraction; exact published fields and actor countdown/cells',
                timing='20 repetitions per mode/count; IRQ disabled; includes equal JSL/result-probe overhead')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
