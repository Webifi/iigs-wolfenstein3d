"""Check native sight slopes against signed division and clamp boundaries."""
import memmap
import hashlib
import json
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
from elf import read

ROOT=Path(__file__).resolve().parents[1]
from asm import Asm


def main():
    divisors=sorted({1,2,3,5,7,31,63,127,255,256,257,511,1023,4095,8191,16383,32767,32768,65535})
    pairs={(n,divisors[n%len(divisors)]) for n in range(65536)}
    rng=random.Random(65816)
    for d in divisors+list(range(1,258))+rng.sample(range(258,16384),512):
        for q in (0,1,2,3,4,5,127,128):
            for offset in (-1,0,1):
                n=q*d+offset
                if 0<=n<=32768:
                    pairs.add((n&65535,d));pairs.add((-n&65535,d))
    records=[]
    for bits,d in sorted(pairs):
        n=bits if bits<32768 else bits-65536
        expected=min(abs(n)*256//d,32767)*(-1 if n<0 else 1)
        records.append(struct.pack('<3H',bits,d,expected&65535))
    report=check_native('sight-ratio-native',records,'stepRatio',0x118a)
    report.update(signed_inputs=65536,divisors=divisors,checks='signed quotient, integer 0-3 fast path, fallback and clamp boundaries')
    (ROOT/'build/tests/sight-ratio-native/result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


def check_native(name,records,entry,field,patches=(),input_field=None,x_dp=None,output_field=None,byte_store=None,long_entry=False):
    out=ROOT/'build/tests'/name;out.mkdir(parents=True,exist_ok=True)
    segments,symbols=read(ROOT/'build/wolf.elf')
    code_end=max(s['address']+len(s['data']) for s in segments if 0xd8000<=s['address']<0xe0000)
    probe=(code_end+15)&~15
    (out/'vectors.bin').write_bytes(b''.join(records))
    p=Asm(probe&65535,bank=0x0d);p.sei();p.cld();p.rep(0x30)
    p.lda_i(0x1100);p.tcd();p.ldx_i(0x1fff);p.txs();p.pea(0x2828);p.plb();p.plb()
    p.label('batch');p.lda_i(0);p.sta_a(0xa000)
    p.label('case');p.ldx_a(0xa000);p.lda_alx((memmap.OLD_VISIBILITY+0x2));p.sta_al(field)
    p.lda_alx(memmap.OLD_VISIBILITY)
    if input_field is not None:p.sta_al(input_field)
    if x_dp is not None:p.ldx_d(x_dp)
    if byte_store is not None:
        p.sep(0x20);p.sta_alx(byte_store);p.rep(0x20)
    if long_entry:p.jsl(symbols[entry])
    else:p.jsr(symbols[entry]&65535)
    if output_field is not None:p.lda_al(output_field)
    p.ldx_a(0xa000);p.byte(0xdf,0x04,0x00,0x2b);p.beq('equal')
    p.sta_a(0xa002);p.sep(0x20);p.lda_i(255);p.sta_al(0x3f0);p.label('fail');p.bra('fail')
    p.label('equal');p.rep(0x20);p.txa();p.clc();p.adc_i(6);p.sta_a(0xa000);p.cmp_a(0xa010);p.bne('case')
    p.sep(0x20);p.lda_i(254);p.sta_al(0x3f0);p.rep(0x20);p.bra('batch')
    driver=p.resolve();assert probe+len(driver)<=0xe0000
    script=memmap.fill('''local s=mem
local armed=false
local f=assert(io.open(VECTORPATH,"rb"));local vectors=f:read("a");f:close()
local offset=1
local count=0
local function loadBatch()
  count=math.min(60000,#vectors-offset+1)
  for i=0,count-1 do s:write_u8(@MM:ART_FULL+0x30000@+i,vectors:byte(offset+i)) end
  s:write_u16(@MM:ART_FULL+0xa010@,count)
end
ratioEntry=s:install_read_tap(PROBE,PROBE,"ratio-entry",function(a,d,m)
  if not manager.machine:side_effects_disabled() and cpu.state.PB.value==13 then loadBatch() end
end)
ratioResult=s:install_write_tap(0x3f0,0x3f0,"ratio-result",function(a,d,m)
if d==1 and not armed then
  armed=true
  PATCHES
  for i,v in ipairs(DRIVER) do s:write_u8(PROBE+i-1,v) end
  local jump=JUMP
  for i,v in ipairs(jump) do s:write_u8(FRAMEDONE+i-1,v) end
elseif d==254 then
  offset=offset+count
  if offset>#vectors then print("RESULT 0 "..tostring(#vectors//6));manager.machine:exit()
  else loadBatch() end
elseif d==255 then
  print(string.format("RESULT 1 %d actual=%d",(offset-1+s:read_u16(@MM:ART_FULL+0xa000@))//6,s:read_u16(@MM:ART_FULL+0xa002@)))
  manager.machine:exit()
end
end)
''')
    script=script.replace('VECTORPATH',json.dumps(str(out/'vectors.bin'))).replace('DRIVER','{'+','.join(map(str,driver))+'}').replace('FRAMEDONE',str(symbols['frameDone']))
    script=script.replace('PATCHES',';'.join('s:write_u8(%d,0x60)'%symbols[n] for n in patches))
    script=script.replace('PROBE',str(probe)).replace('JUMP','{0x5c,%d,%d,0x0d}'%(probe&255,(probe>>8)&255))
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',out.name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();result=re.search(r'^RESULT (\d+) (\d+)',log,re.M)
    if not result or int(result[1]) or int(result[2])!=len(records):raise SystemExit(log[-2000:])
    return dict(cases=len(records),failures=[],elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())


if __name__=='__main__':main()
