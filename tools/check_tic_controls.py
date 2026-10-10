"""Run both linked control entries on the stock CPU for identical inputs."""
import memmap
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
from elf import read
import lua_guard
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
from asm import Asm
from smoke_make import build_boot


def main():
    out=ROOT/'build/tests/tic-controls-native'
    for name in ('cfg','nvram','state','snap'):(out/name).mkdir(parents=True,exist_ok=True)
    segments,symbols=read(ROOT/'build/wolf.elf')
    decoded='decodedWeaponChoice' in symbols
    payload=bytearray(65536)
    for segment in segments:
        if 0x20000<=segment['address']<0x30000:
            offset=segment['address']-0x20000
            payload[offset:offset+len(segment['data'])]=segment['data']
    definitions={k:int(v,0) for k,v in re.findall(r'^(V_\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    fields=[memmap.OLD_WORLD+definitions[k] for k in ('V_tics','V_controlx','V_controly','V_controlstrafe')]
    fields += [memmap.OLD_WORLD+definitions[k]+2*n for k in ('V_buttonstate','V_buttonheld') for n in range(8)]
    fields += [symbols['weaponRequest']]
    mouse=[(0,0),(100,-100),(101,-101),(35,-35),(70,-70),
           (32767,-32768),(-32768,32767),(32733,-32733),(-32733,32733),
           (32700,-32700),(-32700,32700),(-1,1),(-100,100),(-101,101),
           (65,-65),(30,-30),(32732,-32734),(-32734,32732)]
    vectors=[(x,y,(0,1,2,3,4,65535)[n%6]) for n,(x,y) in enumerate(mouse)]
    payload[0x1200:0x1200+6*len(vectors)]=b''.join(struct.pack('<3H',*(v&65535 for v in row)) for row in vectors)
    fine_vectors=[]
    if 'BuildFineTurn' in symbols:
        for mode,units in enumerate((35,70,140,0),1):
            for bits in (0,4,8,12,132,136,68,72,196,200):
                for mx,my in ((0,0),(100,-100),(-100,100),(101,-101),(32767,-32768),(-32768,32767)):
                    sign=(bool(bits&8)-bool(bits&4))
                    fine_vectors.append((bits|(mode<<10),mx,my,sign*units+max(-100,min(100,mx))))
    payload[0x1500:0x1500+8*len(fine_vectors)]=b''.join(struct.pack('<4H',*(v&65535 for v in row)) for row in fine_vectors)
    payload[0x5000:0x9000]=(ROOT/'build/assets/ray-logic-setup.bin').read_bytes()[0xba00:0xfa00]
    payload[symbols['packetButtonsDone']-0x20000]=0x60
    p=Asm(0,bank=2);p.sei();p.cld();p.rep(0x30)
    p.lda_i(0x1000);p.tcd();p.ldx_i(0x1fff);p.txs();p.phk();p.plb()
    p.sep(0x20);p.lda_al(0xc036);p.ora_i(0x80);p.and_i(0xef);p.sta_al(0xc036);p.rep(0x20)
    p.ldx_i(0x5000);p.ldy_i(0xba00);p.lda_i(0x3fff);p.mvn(0x36,2);p.phk();p.plb()
    p.lda_i(0);p.sta_a(0x1000);p.sta_a(0x1002);p.sta_a(0x1004);p.sta_a(0x1006)
    p.label('case')
    for candidate,function in enumerate(('LogicControls','LogicTicControls')):
        for n in range(8):
            p.lda_i(0x1357+0x123*n);p.sta_al(memmap.OLD_WORLD+definitions['V_buttonstate']+2*n)
            p.lda_i(0xdead);p.sta_al(memmap.OLD_WORLD+definitions['V_buttonheld']+2*n)
        p.lda_i(1);p.sta_d(0x48)
        p.ldx_a(0x1002);p.lda_ax(0x1204);p.sta_al(symbols['weaponRequest'])
        p.lda_ax(0x1202);p.tay();p.lda_ax(0x1200);p.tax()
        p.lda_a(0x1000);p.jsr(symbols[function]&65535)
        if decoded:
            p.ldx_a(0x1002);p.lda_ax(0x1204);p.cmp_i(4);p.bcc('weaponExpected%d'%candidate)
            p.lda_i(65535);p.label('weaponExpected%d'%candidate);p.sta_a(0x1008)
            p.lda_al(memmap.OLD_WORLD+definitions['V_weaponchoice']);p.cmp_a(0x1008);p.beq('weaponExact%d'%candidate)
            p.ldx_i(8);p.jmp('fail');p.label('weaponExact%d'%candidate)
            for n in (5,6,7):
                p.lda_al(memmap.OLD_WORLD+definitions['V_buttonstate']+2*n);p.cmp_i(0x1357+0x123*n)
                p.beq('retiredExact%d_%d'%(candidate,n));p.ldx_i(4+n);p.jmp('fail');p.label('retiredExact%d_%d'%(candidate,n))
        for n,address in enumerate(fields):
            p.lda_al(address)
            if not candidate:p.sta_a(0x1100+n*2)
            else:
                p.cmp_a(0x1100+n*2);p.beq('equal%d'%n);p.ldx_i(n);p.jmp('fail');p.label('equal%d'%n)
    p.lda_a(0x1002);p.clc();p.adc_i(6);p.cmp_i(len(vectors)*6);p.beq('nextCommand')
    p.sta_a(0x1002);p.jmp('case')
    p.label('nextCommand');p.lda_i(0);p.sta_a(0x1002)
    p.lda_a(0x1000);p.inc_acc();p.cmp_i(1024);p.bne('nextOrDone');p.lda_i(0xfc00)
    p.label('nextOrDone');p.sta_a(0x1000);p.cmp_i(0);p.beq('success');p.jmp('case')
    p.label('fail');p.stx_a(0x1004);p.lda_i(1);p.jmp('finish')
    p.label('success');p.lda_i(0);p.sta_a(0x1000)
    p.label('packet')
    for n in range(8):
        p.lda_i(0xa55a);p.sta_al(memmap.OLD_WORLD+definitions['V_buttonstate']+2*n)
    p.lda_a(0x1000);p.jsr(symbols['packetButtons']&65535)
    for n in range(8):
        if n==2 or decoded and n>=5:p.lda_i(0xa55a)
        elif decoded and n==4:
            for weapon in range(4):
                p.lda_a(0x1000);p.and_i(16<<weapon);p.bne('demoWeapon%d'%weapon)
            p.lda_i(65535);p.bra('demoWeaponExpected')
            for weapon in range(4):
                p.label('demoWeapon%d'%weapon);p.lda_i(weapon);p.bra('demoWeaponExpected')
            p.label('demoWeaponExpected')
        else:
            p.lda_a(0x1000)
            for _ in range(n):p.lsr_a()
            p.and_i(1)
        p.sta_a(0x1008)
        p.lda_al(memmap.OLD_WORLD+definitions['V_buttonstate']+2*n)
        p.cmp_a(0x1008);p.beq('packetEqual%d'%n);p.ldx_i(len(fields)+n);p.jmp('fail');p.label('packetEqual%d'%n)
    p.lda_a(0x1000);p.inc_acc();p.cmp_i(256);p.beq('packetsDone')
    p.sta_a(0x1000);p.jmp('packet')
    p.label('packetsDone')
    if fine_vectors:
        p.lda_i(0);p.sta_a(0x1002);p.label('fineCase')
        for candidate,function in enumerate(('LogicControls','LogicTicControls')):
            for n in range(8):
                p.lda_i(0x1357+0x123*n);p.sta_al(memmap.OLD_WORLD+definitions['V_buttonstate']+2*n)
                p.lda_i(0xdead);p.sta_al(memmap.OLD_WORLD+definitions['V_buttonheld']+2*n)
            p.lda_i(1);p.sta_d(0x48)
            p.lda_i(65535);p.sta_al(symbols['weaponRequest'])
            p.ldx_a(0x1002);p.lda_ax(0x1500);p.sta_a(0x1000)
            p.lda_ax(0x1504);p.tay();p.lda_ax(0x1502);p.tax();p.lda_a(0x1000)
            if not candidate:p.and_i(1023)
            p.jsr(symbols[function]&65535)
            for n,address in enumerate(fields):
                p.lda_al(address)
                if not candidate:p.sta_a(0x1100+n*2)
                else:
                    p.cmp_a(0x1100+n*2);p.beq('fineEqual%d'%n);p.ldx_i(n);p.jmp('fail');p.label('fineEqual%d'%n)
            if not candidate:
                p.lda_a(0x1000);p.and_i(64);p.bne('fineStrafe')
                p.ldx_a(0x1002);p.lda_ax(0x1506);p.sta_a(0x1102);p.label('fineStrafe')
        p.lda_a(0x1002);p.clc();p.adc_i(8);p.cmp_i(len(fine_vectors)*8);p.beq('fineDone')
        p.sta_a(0x1002);p.jmp('fineCase');p.label('fineDone')
    p.lda_i(0)
    p.label('finish');p.sta_a(0x1006);p.sep(0x20);p.lda_i(255);p.sta_al(0x3f0);p.label('hang');p.bra('hang')
    driver=p.resolve();assert len(driver)<0x1000
    payload[:len(driver)]=driver
    boot,_=build_boot(128);disk=bytearray(819200);disk[:len(boot)]=boot;disk[512:66048]=payload
    (out/'probe.po').write_bytes(disk)
    (out/'cfg/apple2gsr1.cfg').write_text('<mameconfig version="10"><system name="apple2gsr1"><input><port tag=":a2_config" type="CONFIG" mask="7" defvalue="0" value="0"/><port tag=":bus_timing" type="CONFIG" mask="1" defvalue="1" value="1"/></input></system></mameconfig>')
    lua_guard.write(out/'probe.lua', '''local s=manager.machine.devices[":maincpu"].spaces["program"]
emu.register_frame_done(function() if manager.machine.time:as_double()>159 then print(string.format("TIMEOUT pc=%06x case=%d vector=%d result=%d",manager.machine.devices[":maincpu"].state["PC"].value,s:read_u16(0x21000),s:read_u16(0x21002),s:read_u16(0x21006))) end end)
probe=s:install_write_tap(0x3f0,0x3f0,"result",function(a,d,m)
if d==255 then print(string.format("RESULT %d %d %d %d",s:read_u16(0x21006),s:read_u16(0x21000),s:read_u16(0x21002),s:read_u16(0x21004)));manager.machine:exit() end
end)
''')
    running=subprocess.run(['pgrep','-fl','/iigs.app/Contents/MacOS/iigs'],capture_output=True,text=True).stdout
    if str(ROOT/'build/tests') in running:raise SystemExit('A worker MAME process is already running')
    command=['nice','-n','20',mame_kit.BINARY,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K','-flop3',str(out/'probe.po'),'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run','160','-autoboot_delay','0','-autoboot_script',str(out/'probe.lua')]
    for flag,directory in (('cfg','cfg'),('state','state'),('nvram','nvram'),('snapshot','snap')):command+=['-'+flag+'_directory',str(out/directory)]
    env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_MAC_BACKGROUND_APP='1')
    with (out/'mame.log').open('w') as f:
        process=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:code=process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            raise SystemExit('Native control check timed out')
    result=re.search(r'^RESULT (\d+) (\d+) (\d+) (\d+)',(out/'mame.log').read_text(),re.M)
    if code or not result or int(result[1]):raise SystemExit((out/'mame.log').read_text()[-2000:])
    report=dict(decoded_weapon=decoded,retired_weapon_words_untouched=decoded,fine_mixed_cases=len(fine_vectors),demo_button_cases=256,unused_run_word_preserved=True,cases=2048*len(vectors),compared_words=len(fields),mouse_weapon_vectors=vectors,
                high_command_bits=[0,0xfc00],failures=[],elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
