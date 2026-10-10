"""Linked 65816 checks of DOS cheat inventory, chords and disabled hooks.

The CPU fixture checks arithmetic and state contracts. Physical keyboard and
whole-game timing checks belong to the separate native MAME runs.
"""
import json
from pathlib import Path
from elf import read
from emu816 import Emu
import memmap
ROOT = Path(__file__).resolve().parents[1]
segments,S = read(ROOT/'build/wolf.elf')
LB = memmap.LOGIC_BASE
spear = 'V_ouchface' in S

def fresh():
    e=Emu()
    for seg in segments:e.load(seg['address'],seg['data'])
    e.load(LB,(ROOT/'build/assets/logic.bin').read_bytes())
    e.load(memmap.UI,(ROOT/'build/assets/ui.bin').read_bytes())
    for label in ('DebugAck','PlaySound'):
        if label in S:e.wr8(S[label],0x6b)
    return e

def call(e,name,a=0,x=0,long=True,byte=False,db=2,d=memmap.GAME_DP):
    e.a,e.x,e.y,e.db,e.d,e.s,e.mf,e.xf=a,x,0,db,d,0x1fff,int(byte),0
    addr=S[name]
    e.call(addr>>16,addr&65535,long_return=long,limit=2_000_000)

def var(e,name,value=None):
    addr=LB+S['V_'+name]
    if value is not None:e.wr16(addr,value)
    return e.rd16(addr)

def inventory(e):
    for name,value in dict(health=41,ammo=7,keys=0,score=1234,score_hi=1,nextextra=40000,nextextra_hi=0,lives=3,bestweapon=1,weapon=1,chosenweapon=1,difficulty=2,victoryflag=0,gatling=0).items():var(e,name,value)

def press(e,raw):
    e.wr16(S['keySource'],1)
    call(e,'applyRawKey',a=raw,long=False,byte=True)

checks=[]
e=fresh();inventory(e);call(e,'DebugLogic',a=1)
assert {n:var(e,n) for n in ('health','ammo','keys','score','score_hi','bestweapon','weapon','chosenweapon')}==dict(health=100,ammo=99,keys=3,score=0,score_hi=0,bestweapon=3,weapon=3,chosenweapon=3)
checks.append('MLI: health, ammo, keys, score and chaingun')
e=fresh();inventory(e);var(e,'score',1);var(e,'score_hi',0);call(e,'DebugLogic',a=ord('I'))
assert var(e,'score')+(var(e,'score_hi')<<16)==100001
assert (var(e,'lives'),var(e,'nextextra'),var(e,'nextextra_hi'))==(5,120000&65535,1)
assert (var(e,'health'),var(e,'ammo'),var(e,'bestweapon'))==(100,63,2)
call(e,'DebugLogic',a=ord('I'));assert(var(e,'ammo'),var(e,'bestweapon'))==(99,3)
checks.append('I: 100000 points, extra lives, health, next weapon, capped ammo')
for diff,damage in ((0,4),(1,16),(2,16),(3,16)):
 e=fresh();inventory(e);var(e,'difficulty',diff);call(e,'DebugLogic',a=ord('H'))
 assert var(e,'health')==41-damage
checks.append('H: ordinary TakeDamage, including baby difficulty')
e=fresh();inventory(e);original=bytes(e.m[S['debugDamageOp']:S['debugDamageOp']+2]);call(e,'debugGodToggle',long=False,db=0x3f,d=memmap.UI_DP)
assert e.rd16(S['debugGod'])==1
call(e,'DebugLogic',a=ord('H'));assert var(e,'health')==41 and var(e,'damageflash')==16
call(e,'debugGodToggle',long=False,db=0x3f,d=memmap.UI_DP)
assert bytes(e.m[S['debugDamageOp']:S['debugDamageOp']+2])==original
checks.append('G: damage immunity, damage flash and exact restored instruction')
e=fresh();call(e,'DebugLogic',a=ord('E'));assert var(e,'playstate')==1
checks.append('E: ordinary completed-floor state')
for keys,action in (([0x2e,0x25,0x22],1),([0x0b,0,0x11],2),([0x38,0x3a,0x33],3),([0x30,5],ord('G')),([5,0x30],ord('G')),([0x30,0x2d],ord('N') if spear else 0)):
 e=fresh()
 for key in keys:press(e,key)
 assert e.rd16(S['debugAction'])==action,(keys,e.rd16(S['debugAction']),action)
 if action:assert e.rd8(S['keyAction'])==0xfe
for raw,letter in ((11,'B'),(8,'C'),(14,'E'),(3,'F'),(5,'G'),(4,'H'),(34,'I'),(46,'M'),(35,'P'),(12,'Q'),(1,'S'),(17,'T'),(9,'V'),(13,'W'),(7,'X')):
 for order in ((0x30,raw),(raw,0x30)):
  e=fresh()
  for key in order:press(e,key)
  assert e.rd16(S['debugAction'])==ord(letter),(order,letter,e.rd16(S['debugAction']))
checks.append('MLI, BAT, enable chord, Tab order and edition-specific N')
for flag in ('demoMode','levelState'):
 e=fresh();e.wr16(S[flag],1)
 for key in (0x30,5):press(e,key)
 assert e.rd16(S['debugAction'])==0
checks.append('Cheats ignored during demos and non-playing states')
e=fresh();inventory(e);var(e,'difficulty',2);var(e,'health',5);call(e,'DebugLogic',a=ord('H'));assert var(e,'health')==0 and var(e,'playstate')==2
checks.append('H can kill through the normal death state')
e=fresh();call(e,'debugSlowToggle',long=False,db=0x3f,d=memmap.UI_DP);assert e.rd16(S['debugFrameJump']+1)==(S['DebugFrame']&65535)
call(e,'debugSlowToggle',long=False,db=0x3f,d=memmap.UI_DP);assert e.rd16(S['debugFrameJump']+1)==(S['frameLoop']&65535)
checks.append('S restores the original frame jump when disabled')
if spear:
 e=fresh();call(e,'debugClipToggle',long=False,db=0x3f,d=memmap.UI_DP);assert e.rd16(S['debugClipCall']+1)==(S['DebugTryMove']&65535)
 call(e,'debugClipToggle',long=False,db=0x3f,d=memmap.UI_DP);assert e.rd16(S['debugClipCall']+1)==(S['TryMove']&65535)
 checks.append('Spear N restores the collision call when disabled')
 e=fresh();e.load(S['TryMove'],bytes.fromhex('1860'))
 for x,y,allowed in ((2*65536,3*65536,0),(2*65536+1,3*65536,1),(63*65536,3*65536,0),(62*65536+65535,3*65536,1),(3*65536,2*65536,0),(3*65536,63*65536,0)):
  e.wr16(LB+S['OBJLIST']+S['O_X'],x&65535);e.wr16(LB+S['OBJLIST']+S['O_X']+2,x>>16)
  e.wr16(LB+S['OBJLIST']+S['O_Y'],y&65535);e.wr16(LB+S['OBJLIST']+S['O_Y']+2,y>>16)
  call(e,'DebugTryMove',long=False,db=LB>>16,d=S['LOGICDP'])
  assert e.c==allowed,(x,y,allowed)
 checks.append('Spear noclip retains the original strict map bounds')
 e=fresh();before=bytes(e.m[memmap.UI:memmap.UI_END]);face=bytes(e.m[S['hudHealthFace']:S['hudHealthFace']+3])
 call(e,'debugGodToggle',long=False,db=0x3f,d=memmap.UI_DP)
 assert bytes(e.m[memmap.UI:memmap.UI_END])!=before
 call(e,'debugGodToggle',long=False,db=0x3f,d=memmap.UI_DP)
 assert bytes(e.m[memmap.UI:memmap.UI_END])==before
 assert bytes(e.m[S['hudHealthFace']:S['hudHealthFace']+3])==face
 checks.append('Spear god-face swap and HUD instruction restore exactly')

report={'profile':'spear' if spear else 'wolf3d/shareware','checks':checks,'cold_segments':[{k:seg[k] for k in ('address','size') if k in seg} for seg in segments if seg['address'] in (memmap.SEG_DEBUG,memmap.SEG_DEBUG_AUX)]}
(ROOT/'build/debug-keys.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
