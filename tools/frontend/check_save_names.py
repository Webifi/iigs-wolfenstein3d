"""Linked save-name API, row bounds and final-pixel editor checks; optional real-key HD route."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/frontend/lettering')]
import memmap
from elf import read
from emu816 import Emu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--native', action='store_true')
    ap.add_argument('--name', default='save-names')
    ap.add_argument('--mame', type=Path)
    ap.add_argument('--j13', action='store_true', help='enable J13 by entering the menu with its Escape key')
    args = ap.parse_args()
    out = ROOT / 'build/tests' / args.name
    out.mkdir(parents=True, exist_ok=True)
    segments, symbols = read(ROOT / 'build/wolf.elf')
    class Traced(Emu):
        def __init__(self):
            super().__init__()
            self.writes = {}
            self.trace = False
        def step(self):
            pc = (self.pb << 16) | self.pc
            if self.rd8(pc) != 0x54:
                return super().step()
            assert not self.xf, 'fixture supports native16-bit MVN only'
            self.f8()
            dest, source = self.f8(), self.f8()
            self.wr8((dest << 16) | self.y, self.rd8((source << 16) | self.x))
            self.db = dest
            self.x, self.y = (self.x+1) & 65535, (self.y+1) & 65535
            self.a = (self.a-1) & 65535
            if self.a != 65535: self.pc = (self.pc-3) & 65535
            self.count += 1
            self.cycles += 7
        def wr8(self, a, v):
            if 'InitScreenReadback' in symbols and memmap.WALL_COLUMNS <= a < (memmap.SHR_SHADOW+0x7d00):
                # This CPU-only fixture has no Mega II; model its pixel mirror.
                self.wr8(memmap.BANK_E1 | (a & 65535), v)
            if self.trace and memmap.SHR <= a < memmap.SHR_SCB:
                self.writes.setdefault(a, []).append(v & 255)
            super().wr8(a, v)
        def wr16(self, a, v):
            self.wr8(a, v)
            self.wr8(a+1, v >> 8)
    def fresh():
        e = Traced()
        for seg in segments:
            e.load(seg['address'], seg['data'])
        e.d, e.db = 0x1100, 0x3f
        return e
    def call(e, name, long=True):
        addr = symbols[name]
        e.call(addr >> 16, addr & 65535, long_return=long)
    def block(e):
        at = symbols['slotExt']
        return bytes(e.m[at:at+512])
    def valid(name=b'kept', quick=3, count=8):
        b = bytearray(512)
        b[:8] = b'WOLFSLT1'
        b[10:12] = bytes((quick, count))
        b[16:16+len(name)] = name
        b[8:10] = (sum(b[10:]) & 65535).to_bytes(2, 'little')
        return b
    def reset_image():
        return valid(b'', 255)
    assert symbols['slotExt'] == memmap.SLOT_NAMES
    e = fresh()
    assert block(e) == reset_image(), 'linked default extension'
    tests = []
    for case in ('valid', 'missing', 'magic', 'sum', 'quick-bit', 'count-bit', 'quick-range', 'count-range', 'reserved'):
        b = valid()
        if case == 'missing': b[:] = bytes(512)
        if case == 'magic': b[0] ^= 1
        if case == 'sum': b[17] ^= 1
        if case == 'quick-bit': b[10] ^= 1
        if case == 'count-bit': b[11] ^= 1
        if case == 'quick-range': b = valid(quick=8)
        if case == 'count-range': b = valid(count=10)
        if case == 'reserved':
            b[336] = 1
            b[8:10] = (sum(b[10:]) & 65535).to_bytes(2, 'little')
        e = fresh(); e.load(symbols['slotExt'], b)
        legacy = bytes((i * 17 + 7) & 255 for i in range(512))
        e.load(0x7c00, legacy)
        call(e, 'ExtCheck')
        assert block(e) == (b if case == 'valid' else reset_image()), case
        assert e.m[0x7c00:0x7e00] == legacy, (case, 'legacy changed')
        tests.append(case)
    for slot in range(11):
        for name in (b'', b'alpha\0ignored', b'W' * 32):
            e = fresh(); src = (memmap.SCALE5+0xc100)
            raw = (name or b'\0').ljust(32, b'!')
            e.load(src, raw); e.db = 5; e.a = slot; e.x = src & 65535; e.y = 0x5731
            e.c, e.z, e.n, e.v = 1, 1, 1, 1
            before = (e.db, e.x, e.y, e.getp(), e.s)
            call(e, 'SlotNameStore')
            assert (e.db, e.x, e.y, e.getp(), e.s) == before, ('registers', slot)
            wanted = raw.split(b'\0')[0][:31].ljust(32, b'\0')
            expect = reset_image()
            if slot < 8: expect[16+slot*32:48+slot*32] = wanted
            assert block(e) == expect, ('store', slot, name)
            e.a = slot; call(e, 'SlotName')
            got = bytes(e.m[symbols['slotNameBuf']:symbols['slotNameBuf']+32])
            assert got == (wanted if slot < 8 else bytes(32)), ('read', slot)
            assert e.a == int(bool(got[0]))
            tests.append(f'API-{slot}-{len(name)}')
    for slot in range(10):
        e = fresh(); e.a = slot; call(e, 'SlotQuickSet'); call(e, 'SlotQuick')
        assert e.a == (slot if slot < 8 else 255)
    for mode in (0, 1):
        for fail in (False, True):
            e = fresh(); e.load(symbols['slotExt'], valid())
            header = 0x7c00+232+3*32
            e.wr16(header, 1); e.wr16(header+30, 1)
            e.wr16(symbols['uiGameOn'], 1)
            routine = 'SaveWorld' if mode else 'RestoreSlot'
            e.load(symbols[routine], bytes((0x38 if fail else 0x18, 0x60)))
            e.load(symbols['CaptureSlot'], b'\x60')
            e.load(symbols['WriteSettings'], b'\x18\x60')
            before = block(e); e.a = mode
            call(e, 'QuickSlotScreen', False)
            assert e.a == (0 if fail else 2 if mode else 1), ('quick result', mode, fail)
            assert block(e) == before, ('quick name changed', mode, fail)
    # A full name in the last row must not touch the next object or require a prefix.
    e = fresh()
    for slot in range(8):
        header = 0x7c00+232+slot*32
        e.wr16(header, 1); e.wr16(header+30, 1)
        e.load(symbols['slotExt']+16+slot*32, bytes([65+slot])*31+b'\0')
    end = symbols['slotText']+256
    guard = bytes(e.m[end:end+96])
    call(e, 'BuildSlotTexts', False)
    for slot in range(8):
        at = symbols['slotText']+slot*32
        assert e.m[at:at+32] == bytes([65+slot])*31+b'\0'
    for i, original in enumerate(guard):
        if not symbols['slotNameBuf'] <= end+i < symbols['slotNameBuf']+32:
            assert e.m[end+i] == original, ('last row overrun', hex(end+i))
    # The editor composes the exact visible string once over saved gray pixels.
    from render import Face, Screen, blank
    from shared_gray import INK
    face = Face('BlackOpsOne-Regular.ttf', ROOT/'build/frontend/native', size=6)
    editor_cases = 0
    for row in (0, 7):
        for text in (b'', b'Wolf', b'W'*12, b'i'*31):
            e = fresh()
            e.load(memmap.FRONTEND_FONT, (ROOT/'build/assets/frontend-font.bin').read_bytes())
            e.wr16(symbols['menuDim'], 1)
            e.load(memmap.SNAP_PIX, b'\xdd'*32000)
            e.load(memmap.HEIGHT_TABLE, b'\xdd'*32000)
            e.load(memmap.SNAP_SCB, bytes(200)); e.load(memmap.SHR_SCB, bytes(200))
            e.load(memmap.SLOT_REC, bytes(range(256)))
            e.load(memmap.SHR, b'\xdd'*32000)
            if 'InitScreenReadback' in symbols:
                e.load(memmap.WALL_COLUMNS, b'\xdd'*32000)
            e.wr16(symbols['slotCur'], row)
            e.load(symbols['editorName'], text+b'\0')
            call(e, 'nameMeasure', False)
            # Wide legacy names are displayed intact; new input cannot exceed the limit.
            assert bytes(e.m[symbols['nameLine']:symbols['nameLine']+len(text)+2]) == text+b'_\0'
            before = bytes(e.m[memmap.SHR:memmap.SHR_SCB])
            e.trace = True
            call(e, 'nameDraw', False)
            e.trace = False
            ref = Screen(blank(320, 200, 0x123))
            face.draw(ref, (text+b'_').decode(), 40, 48+15*row, 'selected')
            expected = bytearray(b'\xdd'*32000)
            for y, pixels in enumerate(ref.rows):
                for x, color in enumerate(pixels):
                    if color in (0x123, 0x111): continue
                    ink = INK[color & 15]
                    at = y*160+x//2
                    expected[at] = ((expected[at]&15)|(ink<<4)) if x%2 == 0 else ((expected[at]&240)|ink)
            assert e.m[memmap.SHR:memmap.SHR_SCB] == expected, ('editor pixels', row, text)
            changed = {memmap.SHR+i for i, (a, b) in enumerate(zip(before, expected)) if a != b}
            # Wide strips use a block copy, including unchanged final bytes.
            allowed = {memmap.SHR+y*160+x for y in range(47+15*row, 57+15*row) for x in range(18, 156)}
            assert changed <= set(e.writes) <= allowed, 'editor wrote outside its strip'
            assert all(v == [expected[a-memmap.SHR]] for a, v in e.writes.items()), 'intermediate editor write'
            editor_cases += 1
    result = dict(linked_cases=len(tests), editor_cases=editor_cases, row_guard=True,
                  elf_sha256=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes()).hexdigest())
    if args.native:
        result['native'] = native(out, symbols, args.name, args.mame, args.j13)
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


def native(out, s, name, mame=None, j13=False):
    steps = ['wait=1','sleep=1','key=J13 Escape' if j13 else 'key=Esc','wait=2','sleep=1','key=Return','wait=15','sleep=1',
             'key=Return','wait=3','sleep=1','key=Return','wait=0','sleep=1',
             'key=F8','wait=4','sleep=1','key=Return','sleep=1','call=editor',
             'key=w','key=o','key=l','key=f','call=typed','key=Return','sleep=3','call=saved',
             'key=Esc','wait=2','key=Esc','wait=0','sleep=1',
             'key=F8','sleep=3','wait=0','call=quick-saved',
             'key=F9','sleep=3','wait=0','call=quick-loaded',
             'key=F2','wait=4','sleep=1','key=Return','sleep=1','key=y','sleep=2',
             'call=overwrite','key=Delete','key=Esc','sleep=2','call=cancelled',
             'key=Esc','wait=2','key=Esc','wait=0','end=']
    lua = memmap.fill('''CALLS={}
local quicks,saves,loads,leftQuick,playedQuick=0,0,0,-1,-1
local listReady,editReady=false,false
local tracing,traceDone,before,writes=false,false,{},{}
local function hook(address,label,fn)
 mem:install_read_tap(address,address,label,function(a,d,m)
  if cpu.state.PC.value==a+1 then fn() end
 end)
end
hook(QUICK,'quick',function() quicks=quicks+1;print('TRANSFER quick '..quicks) end)
hook(SAVE,'save',function() saves=saves+1;print('TRANSFER save '..saves) end)
hook(LOAD,'load',function() loads=loads+1;print('TRANSFER load '..loads) end)
hook(LEAVE,'leave',function() leftQuick=quicks end)
hook(CAST,'play',function() if leftQuick==quicks then playedQuick=quicks end end)
hook(PAGE,'list-page',function()
 listReady=false
 if saves==1 and not traceDone then
  tracing=true;before={};writes={}
  for a=@MM:SHR@,@MM:SHR+0x7cff@ do before[a]=mem:read_u8(a) end
 end
end)
hook(KEYDOWN,'key-consumed',function() listReady=false end)
hook(ASK,'editor-open',function() listReady=false;editReady=false end)
hook(EDITLOOP,'editor-ready',function() editReady=true end)
hook(ACCEPT,'editor-accept',function() editReady=false end)
hook(CANCEL,'editor-cancel',function() editReady=false end)
mem:install_write_tap(@MM:SHR@,@MM:SHR+0x7cff@,'save-page-writes',function(a,d,m)
 if tracing then local w=writes[a] or {};writes[a]=w;w[#w+1]=d&255 end
end)
hook(GETKEY,'list-ready',function()
 listReady=true
 if tracing then
  tracing=false;traceDone=true;local count=0
  for a,values in pairs(writes) do
   -- Whole-page publication may normalize old rows before copying the new
   -- frame. The editor's single-strip final pixels are checked separately.
   assert(values[#values]==mem:read_u8(a),'wrong final page store '..a)
   count=count+1
  end
  print('SAVE_PAGE_FINAL_STORES '..count)
 end
end)
local function namebytes() local t={};for i=0,31 do local b=mem:read_u8(EXT+16+i);if b==0 then break end;t[#t+1]=string.char(b) end;return table.concat(t) end
local function check(label,want)
 assert(namebytes()==want,label..' name: '..namebytes());print('NAMES '..label)
end
local function shot(label)
 local t={};for i=0,32767 do t[#t+1]=string.char(mem:read_u8(@MM:SHR@+i)) end
 local f=assert(io.open(OUT..'/'..label..'.shr','wb'));f:write(table.concat(t));f:close()
end
emu.register_frame_done(function()
 if manager.machine.time:as_double()>175 then
  print('FINALSTATE '..cpu.state.PC.value..' q='..quicks..' s='..saves..' l='..loads..' played='..playedQuick)
 end
end)
CALLS.editor=function() if not editReady then return false end;assert(mem:read_u16(LEN)==0,'empty editor');shot('empty-editor');print('NAMES editor') end
CALLS.typed=function() if not editReady then return false end;assert(mem:read_u16(LEN)==4,'typed length');shot('typed-editor');print('NAMES typed') end
CALLS.saved=function() if not listReady or not traceDone then return false end;check('saved','wolf');assert(mem:read_u8(EXT+10)==0,'quick slot');shot('saved-list') end
CALLS['quick-saved']=function() if saves<2 or playedQuick<2 then return false end;check('quick-saved','wolf') end
CALLS['quick-loaded']=function() if loads<1 or playedQuick<3 then return false end;check('quick-loaded','wolf') end
CALLS.overwrite=function() if not editReady then return false end;assert(mem:read_u16(LEN)==4,'existing editor');shot('overwrite-editor');print('NAMES overwrite') end
CALLS.cancelled=function() if not listReady then return false end;check('cancelled','wolf');shot('cancelled-list') end
''')
    lua = lua.replace('EXT', str(s['slotExt'])).replace('LEN', str(s['nameLen'])).replace('OUT', json.dumps(str(out)))
    for key, symbol in dict(QUICK='QuickSlotScreen', SAVE='SaveWorld', LOAD='RestoreSlot', LEAVE='UiLeave', CAST='castFrame', PAGE='ListPage', KEYDOWN='keyDown', ASK='AskSlotName', EDITLOOP='askLoop', ACCEPT='askAccept', CANCEL='askCancel', GETKEY='GetKey').items():
        lua = re.sub(r'\b'+key+r'\b', str(s[symbol]), lua)
    if j13:
        lua+='''
local loaded=CALLS['quick-loaded']
CALLS['quick-loaded']=function()
 if loaded()==false then return false end
 assert(mem:read_u16(%d)==2,'load did not restore J13 gameplay')
 assert(mem:read_u16(%d)==0 and mem:read_u16(%d)==0,'load left a controller timeout or input overflow')
 print('J13_SAVE_LOAD_PASS')
end
''' % (s['j13Mode'],s['j13Timeouts'],s['inputDropped'])
    (out/'observe.lua').write_text(lua)
    r = subprocess.run([sys.executable,'tools/ui_test.py','--name',name,'--hd','--debug','--seconds','180',
                        '--lua',str(out/'observe.lua'),'--steps',';'.join(steps)]+(['--mame',str(mame)] if mame else [])+(['--j13','both'] if j13 else []), cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    (out/'driver.log').write_text(r.stdout+r.stderr)
    log = (out/'mame.log').read_text()
    assert r.returncode == 0 and '[LUA ERROR]' not in log and 'TIMEOUT' not in log, log[-2500:]
    assert 'SAVE_PAGE_FINAL_STORES ' in log
    for case in ('editor','typed','saved','quick-saved','quick-loaded','overwrite','cancelled'):
        assert 'NAMES '+case in log, case
    from render import shr_screen
    from imaging import png
    for p in out.glob('*.shr'): png(p.with_name(p.stem+'@2x.png'), shr_screen(p.read_bytes()).rows, 2)
    if j13: assert 'J13_SAVE_LOAD_PASS' in log
    return dict(real_keys=True, saves=2, loads=1, overwrite_cancel=True,j13=j13)

if __name__ == '__main__':
    main()
