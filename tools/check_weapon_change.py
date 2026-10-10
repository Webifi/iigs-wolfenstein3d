"""Compare native weapon-button priority and cost across all valid inputs."""
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


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True);args=ap.parse_args()
    out=ROOT/'build/tests/weapon-change-native';out.mkdir(parents=True,exist_ok=True)
    definitions={k:int(v,0)+memmap.OLD_WORLD for k,v in re.findall(r'^(V_\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    cases=[]
    for mask,best,ammo,weapon,events,pressed in itertools.product(range(16),range(4),(0,1,99),range(4),(0,10),(1,65535)):
        choices=[i for i in range(best+1) if mask>>i&1]
        chosen=(weapon+1)%4;expected=[weapon,chosen,events]
        if ammo and choices:expected=[choices[0],choices[0],events|1]
        phase='ammo_zero' if not ammo else 'no_buttons' if not mask else 'selected' if choices else 'unavailable'
        cases.append([mask,best,ammo,weapon,chosen,events,pressed,*expected,phase])
    variants=[];end=0
    for name,path in (('before',args.before),('after',ROOT/'build/wolf.elf')):
        segments,symbols=read(path);code=bytearray(32768)
        for seg in segments:
            if 0xd8000<=seg['address']<0xe0000:
                offset=seg['address']-0xd8000;code[offset:offset+len(seg['data'])]=seg['data'];end=max(end,seg['address']+len(seg['data']))
        (out/f'{name}.bin').write_bytes(code)
        variants.append(dict(name=name,path=str(out/f'{name}.bin'),entry=symbols['CheckWeaponChange'],decoded=int('decodedWeaponChoice' in symbols),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    scratch=(end+15)&~15;probe=memmap.SW_SEG_CODE
    stub=Asm(scratch&65535,bank=13);stub.sei();stub.jml(probe)
    wrapper=0xd0000+stub.here;wrapper_call=wrapper;stub.jsr(0);stub.rtl();stub=stub.resolve();assert scratch+len(stub)<=0xe0000
    p=Asm(0,bank=2);p.sei();p.cld();p.rep(0x30);p.ldx_i(0x1fff);p.txs();p.lda_i(0x1100);p.tcd();p.pea(0x2828);p.plb();p.plb()
    p.label('case');p.rep(0x30);call=probe+p.here;p.jsl(wrapper)
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.bra('case');driver=p.resolve()
    script=r'''
local s=mem
local variants=VARIANTS
local cases=CASES
local vars=VARS
local version=1
local index=1
local armed=false
local ready=false
local start=0
local totals={}
local counts={}
local function loadCase()
 local c=cases[index]
 for i,name in ipairs({"V_bestweapon","V_ammo","V_weapon","V_chosenweapon","V_events"}) do s:write_u16(vars[name],c[i+1]) end
 for i=0,3 do s:write_u16(vars.V_buttonstate+8+2*i,(c[1]&(1<<i))~=0 and c[7] or 0) end
 if variants[version].decoded~=0 then
  local choice=65535
  for i=0,3 do if (c[1]&(1<<i))~=0 then choice=i;break end end
  s:write_u16(vars.V_weaponchoice,choice)
 end
end
local function installVersion()
 local v=variants[version];local f=assert(io.open(v.path,"rb"));local code=f:read("a");f:close()
 for i=1,#code do s:write_u8(0xd8000+i-1,code:byte(i)) end
 for i,n in ipairs(STUB) do s:write_u8(SCRATCH+i-1,n) end
 s:write_u16(WRAPPERCALL+1,v.entry&65535)
 for i,n in ipairs(DRIVER) do s:write_u8(PROBE+i-1,n) end
 loadCase();ready=true
end
weaponEntry=s:install_read_tap(SCRATCH,SCRATCH,"weapon-entry",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then installVersion() end
end)
weaponCost=s:install_read_tap(CALL,CALL,"weapon-cost",function(a,d,m)
 if ready and not manager.machine:side_effects_disabled() and cpu.state.PB.value==2 then start=manager.machine.time:as_double() end
end)
weaponResult=s:install_write_tap(0x3f0,0x3f0,"weapon-result",function(a,d,m)
 if d==1 and not armed then
  armed=true
  for i,n in ipairs(STUB) do s:write_u8(SCRATCH+i-1,n) end
  s:write_u32(FRAMEDONE,0x0d00005c|((SCRATCH&65535)<<8))
 elseif d==254 and ready then
  local c=cases[index];local phase=c[11]
  totals[phase]=(totals[phase] or 0)+manager.machine.time:as_double()-start;counts[phase]=(counts[phase] or 0)+1
  for i,name in ipairs({"V_weapon","V_chosenweapon","V_events"}) do
   local got=s:read_u16(vars[name])
   if got~=c[7+i] then print(string.format("FAILED %s %d %s %d %d",variants[version].name,index,name,got,c[7+i]));manager.machine:exit();return end
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
'''
    def lua(value):
        if isinstance(value,str):return json.dumps(value)
        if isinstance(value,(int,float)):return str(value)
        if isinstance(value,list):return '{'+','.join(lua(v) for v in value)+'}'
        return '{'+','.join(k+'='+lua(v) for k,v in value.items())+'}'
    replacements=dict(VARS=lua(definitions),VARIANTS=lua(variants),CASES=lua(cases),STUB=lua(list(stub)),SCRATCH=str(scratch),WRAPPERCALL=str(wrapper_call),DRIVER=lua(list(driver)),PROBE=str(probe),CALL=str(call),FRAMEDONE=str(symbols['frameDone']))
    for a,b in replacements.items():script=script.replace(a,b)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();results=re.findall(r'^RESULT (\w+) (\d+)',log,re.M)
    if results!=[(v['name'],str(len(cases))) for v in variants]:raise SystemExit(log[-3000:])
    costs=[dict(version=v,phase=phase,calls=int(n),mean_us=float(t)*1e6) for v,phase,n,t in re.findall(r'^COST (\w+) (\w+) (\d+) (\S+)',log,re.M)]
    report=dict(cases_per_version=len(cases),failures=[],costs=costs,variants=[dict(name=v['name'],sha256=v['sha256'],decoded_weapon=bool(v['decoded'])) for v in variants],checks='all sixteen button masks, four owned weapon limits, ammo 0/1/99, four current weapons, distinct chosen weapon, existing status events, button words 1/FFFF; lowest owned pressed weapon wins',timing='equal JSL/result-probe overhead; IRQ disabled')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
