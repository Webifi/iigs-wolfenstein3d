"""Exercise every resident picture block through the native cache decoder."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from elf import read
import music_capture

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', required=True)
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    segments, sym = read(ROOT/'build/wolf.elf')
    raw = (ROOT/'build/assets/menu.bin').read_bytes()
    assert len(raw) % 512 == 0
    address, saved_dp = memmap.WALL_COLUMNS, (memmap.WALL_COLUMNS+0x1000)
    for segment in segments:
        start = segment['address']
        assert start + len(segment['data']) <= address or start >= saved_dp + 256
    assert not any(address <= value < saved_dp + 256 for value in sym.values())
    def long(op, value): return bytes([op])+value.to_bytes(3, 'little')
    def word(op, value): return bytes([op])+struct.pack('<H', value)
    def put(offset, value): return word(0xa9, value)+bytes([0x85, offset])
    code = bytearray(b'\x08\xc2\x30\x48\xda\x5a\x8b\x0b')
    code += word(0xa9, 0x1100)+b'\x5b'
    code += word(0xa2, 0x1100)+word(0xa0, saved_dp & 65535)+word(0xa9, 255)+b'\x54\x02\x00'
    batches = []
    for block in range(0, len(raw)//512, 8):
        count = min(8, len(raw)//512-block)
        batches.append((block, count))
        code += put(0x42, block)+put(0x44, count)+put(0x46, 0xba00)+put(0x48, 0x3f)
        code += long(0x22, sym['CopyMenuBlocks'])
        code += word(0xa9, len(batches))+long(0x8f, memmap.TEST_MARKERS)
    code += word(0xa2, saved_dp & 65535)+word(0xa0, 0x1100)+word(0xa9, 255)+b'\x54\x00\x02'
    code += b'\x2b\xab\x7a\xfa\x68\x28'+long(0x5c, sym['LoadLump'])
    assert len(code) < saved_dp-address
    script = memmap.fill(r'''
@MUSIC@
local function file(path)
 local f=assert(io.open(path,'rb'));local b=f:read('a');f:close();return b
end
local original=file(@RAW@)
local batches=@BATCHES@
local injected,active,finished=false,false,false
local prefix={}
local started,wakes,reads=0,0,0
local blockStart=nil
local function executing(bank)
 return not manager.machine:side_effects_disabled() and cpu.state.PB.value==bank
end
cacheWake=mem:install_read_tap(@WAKE@,@WAKE@,'cache-wake',function(a,d,m)
 if active and executing(0x3d) then wakes=wakes+1 end
end)
cacheRead=mem:install_read_tap(@BLOCK@,@BLOCK@,'cache-read',function(a,d,m)
 if active and executing(0) then reads=reads+1 end
end)
cacheCopy=mem:install_read_tap(@COPY@,@COPY@,'cache-copy',function(a,d,m)
 if active and executing(2) then
  assert(cpu.state.P.value&4==0,'picture decode masks interrupts')
  blockStart=manager.machine.time:as_double()
 end
end)
cacheMark=mem:install_write_tap(@MM:TEST_MARKERS@,@MM:TEST_MARKERS@,'cache-batch',function(a,d,m)
 local row=batches[d];assert(row,'unexpected cache batch')
 for i=0,row[2]*512-1 do
  assert(mem:read_u8(@MM:UI_STAGE@+i)==original:byte(row[1]*512+i+1),'picture byte differs at '..(row[1]*512+i))
 end
 print(string.format('CACHE_BATCH %d %d %.9f',row[1],row[2],manager.machine.time:as_double()-blockStart))
 if d==#batches then
  print(string.format('CACHE_ALL %d %.9f %d %d',@CHECKED@,manager.machine.time:as_double()-started,wakes,reads))
  for i=1,4 do mem:write_u8(@LUMP@+i-1,prefix[i]) end
  active=false;finished=true
 end
end)
cacheBoot=mem:install_read_tap(@BOOT@,@BOOT@,'cache-boot',function(a,d,m)
 if injected or not executing(0x3f) then return end
 injected=true
 for i=1,4 do prefix[i]=mem:read_u8(@LUMP@+i-1) end
 for i,v in ipairs(@CODE@) do mem:write_u8(@ADDRESS@+i-1,v) end
 mem:write_u8(@LUMP@,0x5c)
 for i=1,3 do mem:write_u8(@LUMP@+i,(@ADDRESS@>>((i-1)*8))&255) end
end)
cacheBegin=mem:install_read_tap(@ADDRESS@,@ADDRESS@,'cache-begin',function(a,d,m)
 if not executing(@BANK@) then return end
 active=true;started=manager.machine.time:as_double()
 print('CACHE_MUSIC_INITIAL '..mem:read_u16(@ACTIVE@))
end)
emu.register_frame_done(function()
 if finished and mem:read_u8(0x3e4)~=0 then print('CACHE_TITLE_DONE');manager.machine:exit() end
end)
''')
    values = dict(ACTIVE=sym['musicActive'],CHECKED=sum(count*512 for _,count in batches),MUSIC=music_capture.lua(), RAW=json.dumps(str(ROOT/'build/assets/menu.bin')),
                  BATCHES='{'+','.join('{%d,%d}' % x for x in batches)+'}',
                  CODE='{'+','.join(map(str, code))+'}', ADDRESS=address, BANK=address>>16,
                  LUMP=sym['LoadLump'], BOOT=sym['MenuBoot'], WAKE=sym['MusicWake'],
                  COPY=sym['CopyMenuBlocks'], BLOCK=sym['UiBlock'])
    for key, value in values.items():
        script = script.replace('@'+key+'@', str(value))
    (out/'observe.lua').write_text(script)
    command = [sys.executable, 'tools/ui_test.py', '--name', args.name, '--hd',
               '--seconds', '180', '--steps', 'sleep=175;end=', '--lua', str(out/'observe.lua')]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=510)
    (out/'driver.log').write_text(run.stdout+run.stderr)
    log = (out/'mame.log').read_text()
    assert run.returncode == 0 and 'CACHE_TITLE_DONE' in log, log[-3000:]
    music_capture.events(log)
    done = re.search(r'^CACHE_ALL (\d+) ([\d.]+) (\d+) (\d+)$', log, re.M)
    assert done and int(done[1]) == sum(count*512 for _,count in batches) and int(done[4]) == 0
    initial_music=int(re.search(r'^CACHE_MUSIC_INITIAL (\d+)$',log,re.M)[1])
    assert int(done[3])>0 if initial_music else int(done[3])==0
    result = dict(machine='apple2gsr1', ramsize='4352K',
                  disk_sha256=hashlib.sha256((ROOT/'build/wolf-hd.po').read_bytes()).hexdigest(),
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest(),
                  checked_bytes=int(done[1]), elapsed_seconds=float(done[2]),
                  music_was_active=bool(initial_music), music_wakes=int(done[3]), firmware_calls=int(done[4]),
                  batches=[dict(block=int(b), count=int(n), seconds=float(t))
                           for b,n,t in re.findall(r'^CACHE_BATCH (\d+) (\d+) ([\d.]+)$', log, re.M)],
                  layout=json.loads((ROOT/'build/assets/menu-cache.json').read_text()))
    (out/'cache.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
