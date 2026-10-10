"""Check dormant timer wakeups and the bank-two saved-state reset contract."""
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
from wolfsim import ITEM


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True);args=ap.parse_args()
    out=ROOT/'build/tests/idle-timers-native';out.mkdir(parents=True,exist_ok=True)
    definitions={k:int(v,0) for k,v in re.findall(r'^(\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    cases=[];counts=[0,0,0]
    def case(action,tics,phase,restore=None):
        nonlocal counts
        if restore is not None:counts=list(restore)
        inputs=list(restore) if restore is not None else [-1,-1,-1]
        if action==2:counts[2]+=8
        if action in (3,4):counts[1]=18
        if action==4:counts[0]=definitions['GATLINGTICS']
        counts=[max(0,n-tics) for n in counts]
        cases.append([action,tics,*inputs,*counts,phase])
    case(1,1,'restore_zero',(0,0,0))
    for _ in range(100):case(0,1,'idle')
    for initial,tics in (((13,18,31),1),((15,18,45),4),((90,18,500),64),((1,1,1),1)):
        case(1,tics,'restore_active',initial)
        for _ in range(max(initial)//tics+3):case(0,tics,'countdown')
    for action,name in ((2,'damage_wake'),(3,'bonus_wake'),(4,'gatling_wake')):
        assert counts==[0,0,0]
        case(action,1,name)
        for _ in range(max(counts)+3):case(0,1,'countdown')
    assert counts==[0,0,0]
    case(1,1,'restore_after_idle',(7,9,11))
    for _ in range(15):case(0,1,'countdown')
    for _ in range(100):case(0,1,'idle')
    variants=[];end=0
    for name,path in (('before',args.before),('after',ROOT/'build/wolf.elf')):
        segments,sym=read(path);code=bytearray(32768)
        for seg in segments:
            if 0xd8000<=seg['address']<0xe0000:
                offset=seg['address']-0xd8000;code[offset:offset+len(seg['data'])]=seg['data'];end=max(end,seg['address']+len(seg['data']))
        (out/f'{name}.bin').write_bytes(code)
        variants.append(dict(name=name,path=str(out/f'{name}.bin'),symbols=sym,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    scratch=(end+15)&~15;probe=memmap.SW_SEG_CODE
    for v in variants:
        y=v['symbols'];stub=Asm(scratch&65535,bank=13);stub.sei();stub.jml(probe)
        old_reset=0xd0000+stub.here;stub.rtl()
        v['reset']=y.get('ResetLogicTimers',old_reset)
        v['retired']=int('paletteCounts' not in y)
        v['counts']=0xd0000+stub.here;stub.jsr(y['playerCounts']&65535)
        if not v['retired']:stub.jsr(y['paletteCounts']&65535)
        stub.rtl()
        v['damage']=0xd0000+stub.here;stub.rep(0x30);stub.ldx_i(0x3040);stub.lda_i(8);stub.jsr(y['TakeDamage']&65535);stub.rtl()
        v['bonus']=0xd0000+stub.here;stub.ldx_i(0x5600);stub.jsr(y['GetBonus']&65535);stub.rtl()
        v['stub']=list(stub.resolve());assert scratch+len(v['stub'])<=0xe0000
    p=Asm(0,bank=2);p.sei();p.cld();p.rep(0x30);p.ldx_i(0x1fff);p.txs()
    p.label('case');p.rep(0x30);p.lda_al(0x3e0);p.cmp_i(1);p.bne('countContext')
    p.lda_i(0x1000);p.tcd();p.pea(0x0202);p.plb();p.plb();p.ldx_i(0x1234);p.ldy_i(0x5678);p.byte(0xb8);p.sec()
    reset_call=probe+p.here;p.jsl(0);reset_return=probe+p.here;p.nop()
    p.label('countContext');p.lda_i(0x1100);p.tcd();p.pea(0x2828);p.plb();p.plb()
    p.lda_al(0x3e0);p.cmp_i(2);p.bne('notDamage')
    damage_call=probe+p.here;p.jsl(0);p.bra('counts')
    p.label('notDamage');p.cmp_i(3);p.bcc('counts')
    bonus_call=probe+p.here;p.jsl(0)
    p.label('counts');counts_call=probe+p.here;p.jsl(0)
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.bra('case')
    driver=p.resolve()
    script=memmap.fill(r'''
local s=mem
local vars=VARS
local variants=VARIANTS
local cases=CASES
local version=1
local index=1
local armed=false
local ready=false
local start=0
local totals={}
local ns={}
local resets=0
local retiredValues={0,0}
local retiredDifferences=0
local function loadCase()
 local c=cases[index]
 s:write_u16(0x3e0,c[1]);s:write_u16(vars.V_tics,c[2])
 if c[1]==1 then
  s:write_u16(vars.V_gatling,c[3]);s:write_u16(vars.V_bonuscount,c[4]);s:write_u16(vars.V_damagecount,c[5])
  retiredValues={c[4],c[5]}
 end
 if c[1]>=2 then
  for _,name in ipairs({"V_victoryflag","V_damageflash","V_events","V_sound","V_mapdirty","V_attackframe","V_ammo","V_facecount","V_gotgatgun"}) do s:write_u16(vars[name],0) end
  s:write_u16(vars.V_health,100);s:write_u16(vars.V_difficulty,1)
  for _,name in ipairs({"V_weapon","V_bestweapon","V_chosenweapon"}) do s:write_u16(vars[name],1) end
  s:write_u16(@MM:ART_FULL+0x5602@,1);s:write_u16(@MM:ART_FULL+0x5606@,c[1]==4 and CHAINITEM or CLIPITEM)
 end
end
local function installVersion()
 local v=variants[version];local f=assert(io.open(v.path,"rb"));local code=f:read("a");f:close()
 for i=1,#code do s:write_u8(0xd8000+i-1,code:byte(i)) end
 for i,n in ipairs(v.stub) do s:write_u8(SCRATCH+i-1,n) end
 for i,n in ipairs(DRIVER) do s:write_u8(PROBE+i-1,n) end
 for _,pair in ipairs({{RESETCALL,v.reset},{COUNTCALL,v.counts},{DAMAGECALL,v.damage},{BONUSCALL,v.bonus}}) do
  s:write_u16(pair[1]+1,pair[2]&65535);s:write_u8(pair[1]+3,13)
 end
 loadCase();ready=true
end
timerEntry=s:install_read_tap(SCRATCH,SCRATCH,"timer-entry",function(a,d,m)
 if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then installVersion() end
end)
timerReset=s:install_read_tap(RESETRETURN,RESETRETURN,"timer-reset",function(a,d,m)
 if not ready or manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 then return end
 local r=cpu.state
 assert(r.DB.value==2 and r.D.value==0x1000 and r.X.value==0x1234 and r.Y.value==0x5678 and (r.P.value&255)==5,"reset clobbered saved caller context")
 resets=resets+1
end)
timerCost=s:install_read_tap(COUNTCALL,COUNTCALL,"timer-cost",function(a,d,m)
 if ready and not manager.machine:side_effects_disabled() and cpu.state.PB.value==2 then start=manager.machine.time:as_double() end
end)
timerResult=s:install_write_tap(0x3f0,0x3f0,"timer-result",function(a,d,m)
 if d==1 and not armed then
  armed=true
  for i,n in ipairs(variants[1].stub) do s:write_u8(SCRATCH+i-1,n) end
  s:write_u32(FRAMEDONE,0x0d00005c|((SCRATCH&65535)<<8))
 elseif d==254 and ready then
  local c=cases[index];local phase=c[9]
  totals[phase]=(totals[phase] or 0)+manager.machine.time:as_double()-start;ns[phase]=(ns[phase] or 0)+1
  for i,name in ipairs({"V_gatling","V_bonuscount","V_damagecount"}) do
   local got=s:read_u16(vars[name])
   local expected=c[5+i]
   if variants[version].retired~=0 and i>1 then
    expected=retiredValues[i-1]
    if got~=c[5+i] then retiredDifferences=retiredDifferences+1 end
   end
   if got~=expected then print(string.format("FAILED %s %d %s %d %d",variants[version].name,index,name,got,expected));manager.machine:exit();return end
  end
  if c[1]==2 then assert(s:read_u16(vars.V_health)==92 and s:read_u16(vars.V_damageflash)==8 and (s:read_u16(vars.V_events)&4)~=0,"damage publication changed") end
  if c[1]>=3 then assert(s:read_u16(@MM:ART_FULL+0x5602@)==65535 and (s:read_u16(vars.V_events)&8)~=0,"bonus publication changed") end
  index=index+1
  if index>#cases then
   for phase,total in pairs(totals) do print(string.format("COST %s %s %d %.12f",variants[version].name,phase,ns[phase],total/ns[phase])) end
   print(string.format("RESULT %s %d %d %d",variants[version].name,#cases,resets,retiredDifferences))
   version=version+1;index=1;totals={};ns={};resets=0;retiredDifferences=0
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
    small=[{k:v[k] for k in ('name','path','reset','counts','damage','bonus','stub','retired')} for v in variants]
    replacements=dict(VARS=lua({k:v+memmap.OLD_WORLD for k,v in definitions.items() if k.startswith('V_')}),VARIANTS=lua(small),CASES=lua(cases),
                      DRIVER=lua(list(driver)),PROBE=str(probe),SCRATCH=str(scratch),RESETCALL=str(reset_call),RESETRETURN=str(reset_return),
                      COUNTCALL=str(counts_call),DAMAGECALL=str(damage_call),BONUSCALL=str(bonus_call),FRAMEDONE=str(sym['frameDone']),
                      CHAINITEM=str(ITEM['bo_chaingun']),CLIPITEM=str(ITEM['bo_clip']))
    for a,b in replacements.items():script=script.replace(a,b)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();results=re.findall(r'^RESULT (\w+) (\d+) (\d+) (\d+)',log,re.M)
    resets=sum(c[0]==1 for c in cases)
    dead=[0,0];differences=0
    for c in cases:
        if c[0]==1:dead=c[3:5]
        differences+=sum(a!=b for a,b in zip(dead,c[6:8]))
    if results!=[(v['name'],str(len(cases)),str(resets),str(differences if v['retired'] else 0)) for v in variants]:raise SystemExit(log[-3000:])
    costs=[dict(version=v,phase=phase,calls=int(n),mean_us=float(t)*1e6) for v,phase,n,t in re.findall(r'^COST (\w+) (\w+) (\d+) (\S+)',log,re.M)]
    report=dict(cases_per_version=len(cases),saved_context_checks_per_version=resets,failures=[],costs=costs,
                variants=[dict(name=v['name'],sha256=v['sha256'],retired_palette=bool(v['retired']),
                               retired_word_differences=differences if v['retired'] else 0) for v in variants],
                checks='dormant and active counters; native damage/ammo/chaingun wakeups; restore nonzero counters after idle; ResetLogicTimers called from PB2/DB2/D1000/P05/X1234/Y5678',
                timing='equal JSL/result-probe overhead; IRQ disabled; countdown timing excludes producers and cold reset')
    if any(v['retired'] for v in variants):
        report['retired_fields']=['V_bonuscount','V_damagecount']
        report['checks']+='; retired palette words stay untouched, including old saved nonzero values; health, DOC damageflash, flash events and consumed pickup stay exact'
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
