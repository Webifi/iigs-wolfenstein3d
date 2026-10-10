"""Exercise both effect slots through normal playback and a firmware IRQ blackout."""
import memmap
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from elf import read

ROOT = Path(__file__).resolve().parents[1]


def main():
    name = 'effect-stall'
    out = ROOT/'build/tests'/name
    out.mkdir(parents=True, exist_ok=True)
    _, sym = read(ROOT/'build/wolf.elf')
    bank = (ROOT/'build/sound/effects.bin').read_bytes()
    def length(sound):
        return struct.unpack_from('<H', bank, sound*16+4)[0]
    def long(op, a): return bytes([op])+a.to_bytes(3, 'little')
    def lda(n): return b'\xa9'+struct.pack('<H', n)
    code = bytearray(b'\x08\xc2\x30\x48\xda\x5a\x8b')
    code += long(0x22, sym['StopMusic'])+long(0x22, sym['StopEffects'])
    def wait(tics):
        code.extend(long(0x22, sym['I_GetTime'])+long(0x8f, (memmap.MENU+0x2c00)))
        loop = len(code)
        code.extend(long(0x22, sym['I_GetTime'])+b'\x38'+long(0xef, (memmap.MENU+0x2c00))+b'\xc9'+struct.pack('<H', tics))
        code.extend(bytes([0x90, (loop-len(code)-2)&255]))
    scenarios = [(44, False), (44, True), (72, False), (72, True)]
    for i, (sound, masked) in enumerate(scenarios):
        code += lda(i*2+1)+long(0x8f, memmap.TEST_MARKERS)
        if masked: code += b'\x08\x78'
        code += lda(sound)+long(0x22, sym['PlaySound'])
        if masked:
            wait(140)
            code += b'\x28'
        wait(210)
        code += long(0x22, sym['PollEffects'])
        code += lda(i*2+2)+long(0x8f, memmap.TEST_MARKERS)
    code += b'\x80\xfe'
    script = memmap.fill(r'''
local active=false
local ctl,adr,hi=0,0,0
local stage=0
local started=0
local rows={}
local writes=0
local interrupted=0
local function now() return manager.machine.time:as_double() end
stallMark=mem:install_write_tap(@MM:TEST_MARKERS@,@MM:TEST_MARKERS@,'stall-stage',function(a,d,m)
 stage=d
 if d%2==1 then started=now();writes=0
 else
  local zero=mem:read_u16(@ACTIVE@)|mem:read_u16(@ACTIVE@+2)|mem:read_u16(@PENDING@)|mem:read_u16(@PENDING@+2)
  assert(zero==0,'effect failed to finish')
  local doc=manager.machine.devices[':doc'].spaces['rom']
  for i=0,255 do assert(doc:read_u8(0xff00+i)==(i==0 and 255 or i),'timer ramp overwritten') end
  print(string.format('EFFECT_STALL %d %.9f %d',d,now()-started,writes))
  if d==8 then print('EFFECT_STALL_DONE '..interrupted);manager.machine:exit() end
 end
end)
stallWrite=mem:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDADRH@,'stall-write',function(a,d,m)
 if a==@MM:SOUNDCTL@ then ctl=d elseif a==@MM:SOUNDADRL@ then adr=d elseif a==@MM:SOUNDADRH@ then hi=d
 elseif stage>0 then
  if ctl&64~=0 then assert(hi<64,'effect wrote outside its DOC buffers');writes=writes+1 end
  if ctl&32~=0 then adr=(adr+1)&255;if adr==0 then hi=(hi+1)&255 end end
 end
end)
stallRead=mem:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'stall-read',function(a,d,m)
 if ctl&32~=0 then adr=(adr+1)&255;if adr==0 then hi=(hi+1)&255 end end
end)
@STARVED@
stallStart=mem:install_write_tap(0x3f0,0x3f0,'stall-start',function(a,d,m)
 if d==1 and not active then
  active=true
  for i,v in ipairs(@CODE@) do mem:write_u8(@MM:MENU+0x1c00@+i-1,v) end
  mem:write_u8(@FRAME@,0x5c);mem:write_u8(@FRAME@+1,0);mem:write_u8(@FRAME@+2,0x80);mem:write_u8(@FRAME@+3,0x3f)
 end
end)
''')
    # One-shots never enter the effect IRQ. interrupted counts those entries.
    starved = (
        "local function fxirq(a,d,m) if cpu.state.PB.value==0x3d and (cpu.state.PC.value&65535)==((a+1)&65535) then interrupted=interrupted+1 end end\n"
        "stallRefill=mem:install_read_tap(%d,%d,'stall-refill',fxirq)\n"
        "stallEnd=mem:install_read_tap(%d,%d,'stall-end',fxirq)\n"
    ) % (sym['EffectRefill'], sym['EffectRefill'], sym['EffectBufferEnd'], sym['EffectBufferEnd'])
    for key, value in dict(ACTIVE=str(sym['fxActive']), PENDING=str(sym['fxPending']),
                           FRAME=str(sym['frameDone']), STARVED=starved,
                           CODE='{'+','.join(map(str, code))+'}').items():
        script = script.replace('@'+key+'@', value)
    (out/'observe.lua').write_text(script)
    proc = subprocess.run([sys.executable, 'tools/ui_test.py', '--name', name, '--hd', '--skip',
                           '--seconds', '180', '--steps', 'sleep=170;end=', '--lua', str(out/'observe.lua')],
                          cwd=ROOT, capture_output=True, text=True, timeout=490)
    (out/'driver.log').write_text(proc.stdout+proc.stderr)
    log = (out/'mame.log').read_text()
    assert proc.returncode == 0 and 'EFFECT_STALL_DONE' in log and not re.search('Lua error', log, re.I), log[-2500:]
    assert 'EFFECT_STALL_DONE 0' in log, log[-2500:]
    rows = [(int(n), float(t), int(w)) for n,t,w in re.findall(r'^EFFECT_STALL (\d+) ([\d.]+) (\d+)$', log, re.M)]
    assert len(rows)==4, rows
    for (_, seconds, _), (_, masked) in zip(rows, scenarios):
        assert abs(seconds-((350 if masked else 210)/70)) < 0.09, rows
    # A dropped sound also leaves the oscillators halted. The first play of an
    # unpinned effect has to upload its table; the replay is already resident.
    assert [rows[0][2], rows[1][2], rows[2][2], rows[3][2]] == [length(44), 0, length(72), 0], rows
    report = dict(scenarios=[dict(sound=s, interrupts_masked=m, seconds=r[1], doc_writes=r[2]) for (s,m),r in zip(scenarios, rows)],
                  checks=['both one-shots finish with the oscillators halted',
                          'a two-second IRQ blackout still finishes, with no effect IRQ',
                          'every PCM write stays inside the effect pages', 'all 256 timer ramp bytes unchanged',
                          'DOC clock matches elapsed time within 90 ms',
                          'the first play uploads the whole table and the replay uploads nothing'],
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256((out/'wolf-hd.po').read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
