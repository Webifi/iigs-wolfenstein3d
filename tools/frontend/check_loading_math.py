"""Run the linked progress code and loader copy on byte-exact 65816 fixtures."""
import json,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import memmap
from elf import read
from emu816 import Emu
segments,s=read(ROOT/'build/wolf.elf')
e=Emu()
for p in segments:e.load(p['address'],p['data'])
def call(name,value):
 e.a=value;e.x=0xa125;e.y=0x7284;e.db=0x27;e.d=0x8200;e.setp(0xc3)
 before=(e.a,e.x,e.y,e.db,e.d,e.s,e.getp())
 address=s[name];e.call(address>>16,address&65535,True)
 assert (e.a,e.x,e.y,e.db,e.d,e.s,e.getp())==before,name
rng=random.Random(451)
rows=0
for total in (224,256,456,640,716,1400,4096,8000,16000,65534):
 for step in ((1,4,7,28,113) if total<8000 else (113,997)):
  e.wr16(s['progressExtra'],0);e.wr16(s['progressDone'],0);e.wr16(s['busyProgress'],0)
  e.wr16(s['busyShown'],1);e.wr16(s['busyKind'],0)
  original=bytes(rng.randrange(256)&0x77 for _ in range(32768));e.load(memmap.SHR,original)
  call('ProgressPlan',total)
  done=0;last=0
  while done<total:
   credit=min(step,total-done);call('ProgressAdd',credit);done+=credit
   px=e.rd16(s['busyProgress']);assert last<=px<=160
   assert abs(px-min(160,done*160//total))<=2,(total,done,px)
   last=px
  call('ProgressFinish',0);assert e.rd16(s['busyProgress'])==160
  expected=bytearray(original)
  for y in (109,110,111):expected[y*160+40:y*160+120]=b'\x11'*80
  assert e.m[memmap.SHR:memmap.RAW_PLANES]==expected,'bar wrote outside its line'
  rows+=1
# A discovered save size changes the remaining slope without moving its prefix.
for done,remaining in ((320,300),(510,2800),(900,1700),(998,300)):
 e.wr16(s['progressExtra'],0);e.wr16(s['progressDone'],0);e.wr16(s['busyProgress'],0)
 call('ProgressPlan',1000);call('ProgressAdd',done)
 before=e.rd16(s['busyProgress']);call('ProgressRemaining',remaining)
 assert e.rd16(s['busyProgress'])==before
 elapsed=0
 while elapsed<remaining:
  credit=min(18,remaining-elapsed);call('ProgressAdd',credit);elapsed+=credit
  px=e.rd16(s['busyProgress'])
  assert abs(px-(before+elapsed*(160-before)//remaining))<=2,(done,remaining,elapsed,px)
 assert e.rd16(s['busyProgress'])==160
# The legacy fraction helper must handle products that overflow sixteen bits.
for numerator,denominator in [(1,3),(451,902),(65534,65535),(0,0),(800,800)]:
 e.a=numerator;e.x=denominator;e.db=s['ProgressRatio']>>16
 e.call(e.db,s['ProgressRatio']&65535)
 expected=min(160,numerator*160//denominator) if denominator else 0
 assert 0<=expected-e.a<=2
# Constant entry points save the caller once, rather than wrapping ProgressAdd.
costs={}
for credit in (1,2,3,4,6,7,16,20,22,26):
 e.wr16(s['progressDone'],0);e.wr16(s['busyShown'],0)
 call('ProgressPlan',8000);start=e.cycles
 call('Progress'+str(credit),0x924f)
 assert e.rd16(s['progressDone'])==credit
 costs[str(credit)]=e.cycles-start
loader,ls=read(ROOT/'build/boot/loader.elf')
for p in loader:e.load(p['address'],p['data'])
# Banks and aligned endpoints used by both raw and compressed loading.
for bank in (1,0x0b,0x29,0x3e,0x41):
 for offset in (0,0x7e00,0xfe00):
  data=rng.randbytes(512);e.load(ls['BUF'],data);e.wr16(ls['DEST'],offset);e.wr8(ls['DEST']+2,bank)
  e.db=0;e.d=0;e.setp(0x20);e.call(0,ls['copyBlock'])
  assert e.m[(bank<<16)+offset:(bank<<16)+offset+512]==data
  assert e.rd16(ls['DEST'])==(offset+512)&65535
  assert e.rd8(ls['DEST']+2)==bank+(offset==0xfe00)
print(json.dumps(dict(progress_cases=rows,copy_cases=15,constant_credit_cycles=costs,result='PASS')))
