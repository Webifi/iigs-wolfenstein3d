"""Compare tabled and original player vectors in the linked stock game."""
import memmap
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from elf import read

ROOT=Path(__file__).resolve().parents[1]
from asm import Asm


def main():
    name='thrust-vectors-native'
    out=ROOT/'build/tests'/name;out.mkdir(parents=True,exist_ok=True)
    segments,symbols=read(ROOT/'build/wolf.elf')
    code_end=max(s['address']+len(s['data']) for s in segments if 0xd8000<=s['address']<0xe0000)
    probe=(code_end+255)&~255
    definitions={k:int(v,0) for k,v in re.findall(r'^(V_\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    fields=[0x1144,0x1146,0x115c,0x115e,0x1160,0x1162]
    fields += [memmap.OLD_WORLD+definitions[k] for k in ('V_thrustspeed','V_thrustspeed_hi')]
    controls=(0,1,34,35,36,69,70,71,100,139,140,141,279,280,281,400)
    vectors=[(n,scale) for n in controls for scale in (100,150)]
    params=b''.join(struct.pack('<2H',*row) for row in vectors)
    p=Asm(probe&65535,bank=0x0d);p.sei();p.cld();p.rep(0x30)
    p.lda_i(0x1100);p.tcd();p.ldx_i(0x1fff);p.txs();p.pea(0x2828);p.plb();p.plb()
    p.lda_i(0)
    for address in (0xa000,0xa002,0xa004,0xa006):p.sta_a(address)
    p.label('case')
    for candidate,function in enumerate(('speedThrustSlow','speedThrust')):
        p.lda_i(0xffff);p.sta_al(fields[-2]);p.lda_i(0x1234);p.sta_al(fields[-1])
        p.lda_a(0xa000);p.sta_d(0x48)
        p.ldx_a(0xa002);p.lda_ax(0xa202);p.tay();p.lda_ax(0xa200)
        p.jsr(symbols[function]&65535)
        for n,address in enumerate(fields):
            p.lda_al(address)
            if not candidate:p.sta_a(0xa100+n*2)
            else:
                p.cmp_a(0xa100+n*2);p.beq('equal%d'%n);p.ldx_i(n);p.jmp('fail');p.label('equal%d'%n)
    p.lda_a(0xa000);p.inc_acc();p.cmp_i(360);p.beq('nextVector')
    p.sta_a(0xa000);p.jmp('case')
    p.label('nextVector');p.lda_i(0);p.sta_a(0xa000)
    p.lda_a(0xa002);p.clc();p.adc_i(4);p.sta_a(0xa002);p.cmp_i(len(vectors)*4)
    p.beq('success');p.jmp('case')
    p.label('fail');p.stx_a(0xa004);p.lda_i(1);p.jmp('finish')
    p.label('success');p.lda_i(0)
    p.label('finish');p.sta_a(0xa006);p.sep(0x20);p.lda_i(255);p.sta_al(0x3f0);p.label('hang');p.bra('hang')
    driver=p.resolve();assert probe+len(driver)<=0xe0000
    script=memmap.fill('''local s=mem
local armed=false
local function put(a,bytes) for i,v in ipairs(bytes) do s:write_u8(a+i-1,v) end end
thrustProbe=s:install_write_tap(0x3f0,0x3f0,"thrust-probe",function(a,d,m)
if d==1 and not armed then
armed=true
put(PROBE,DRIVER)
put(@MM:ART_FULL+0xa200@,PARAMS)
-- The check returns after vector preparation, before collision or world changes.
s:write_u8(VECTORREADY,0x60)
put(FRAMEDONE,JUMP)
elseif d==255 then
print(string.format("RESULT %d %d %d %d",s:read_u16(@MM:ART_FULL+0xa006@),s:read_u16(@MM:ART_FULL+0xa000@),s:read_u16(@MM:ART_FULL+0xa002@),s:read_u16(@MM:ART_FULL+0xa004@)))
manager.machine:exit()
end
end)
''')
    for key,value in [('DRIVER','{'+','.join(map(str,driver))+'}'),('PARAMS','{'+','.join(map(str,params))+'}'),('VECTORREADY',str(symbols['thrustVectorReady'])),('FRAMEDONE',str(symbols['frameDone'])),('PROBE',str(probe)),('JUMP','{0x5c,%d,%d,0x0d}'%(probe&255,(probe>>8)&255))]:script=script.replace(key,value)
    (out/'probe.lua').write_text(script)
    subprocess.run([sys.executable,'tools/ui_test.py','--name',name,'--hd','--skip','--seconds','200','--steps','sleep=190;end=','--lua',str(out/'probe.lua')],cwd=ROOT,check=True,timeout=540,stdout=subprocess.DEVNULL)
    log=(out/'mame.log').read_text();result=re.search(r'^RESULT (\d+) (\d+) (\d+) (\d+)',log,re.M)
    if not result or int(result[1]):raise SystemExit(log[-2000:])
    report=dict(cases=len(vectors)*360,compared_words=len(fields),controls=controls,scales=[100,150],angles=360,
                checks='signed vectors, capped speed, accumulated thrust including carry',failures=[],
                elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                disk_sha256=hashlib.sha256((out/'wolf-hd.po').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
