"""Linked save-name metadata contract checks; no MAME or disk writes."""
import memmap
import hashlib,json,struct,sys
from pathlib import Path
from elf import read
from emu816 import Emu
from mkdisk import setx_bytes
root=Path(__file__).resolve().parents[1]
elf=Path(sys.argv[1]) if len(sys.argv)>1 else root/'build/wolf.elf'
segments,s=read(elf);e=Emu()
for v in segments:e.load(v['address'],v['data'])
a=s['slotExt'];buf=s['slotNameBuf'];seed=setx_bytes();assert a==memmap.SLOT_NAMES and len(seed)==512
assert e.m[a:a+512]==seed and struct.unpack_from('<H',seed,8)[0]==sum(seed[10:])==263
assert buf>>16==0x3f
for name in ('SlotCount','SlotName','SlotNameStore','SlotQuick','SlotQuickSet','ExtSum','ExtCheck'):assert 0xfc000<=s[name]<0xfe000,name
legacy=bytes(range(256))*2;e.load(0x7c00,legacy)
def call(n,A=0,X=0):
 e.a=A;e.x=X;e.y=123;e.db=0x3f;e.d=0x1000;e.mf=e.xf=0;e.s=0x1fff
 e.call(s[n]>>16,s[n]&65535,long_return=True)
 assert e.s==0x1fff and e.db==0x3f,(n,e.s,e.db)
 return e.a
valid=bytearray(seed);valid[16:22]=b'Player';valid[10]=7;struct.pack_into('<H',valid,8,sum(valid[10:])&65535)
e.load(a,valid);call('ExtCheck');assert e.m[a:a+512]==valid
assert call('SlotQuick')==7 and call('SlotCount')==8
for offset in (0,8,10,11,16,335,511):
 bad=bytearray(valid);bad[offset]^=1;e.load(a,bad);call('ExtCheck');assert e.m[a:a+512]==seed,offset
reserved=list(range(12,16))+list(range(272,512))
for offset,value in [(10,8),(11,9)]+[(i,1) for i in reserved]:
 bad=bytearray(valid);bad[offset]=value;struct.pack_into('<H',bad,8,sum(bad[10:])&65535);e.load(a,bad);call('ExtCheck');assert e.m[a:a+512]==seed,offset
for slot in range(8):
 text=(f'Save {slot}'.encode()+b'\0').ljust(32,b'!');e.load((memmap.REGISTERED_MENU+0x1000),text)
 call('SlotNameStore',slot,0x1000);assert call('SlotName',slot)==1
 assert e.m[buf:buf+32]==(f'Save {slot}'.encode()+b'\0').ljust(32,b'\0')
 call('SlotQuickSet',slot);assert call('SlotQuick')==slot
call('SlotQuickSet',255);assert call('SlotQuick')==255
assert e.m[0x7c00:0x7e00]==legacy
out=dict(pass_checks=True,slots=8,invalid_images=9+len(reserved),placement=hex(a),bytes=512,checksum='10..511',buffer_bank=hex(buf>>16),apis='JSL/RTL in UiExtra',original_settings_unchanged=True,elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),native_game_test=False)
(root/'docs/evidence/frontend/slotmeta-placement/result.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
