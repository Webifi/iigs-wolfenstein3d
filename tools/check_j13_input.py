"""Linked-code checks of capture, source ownership and guarded row replies.

The controller here is a small deterministic I/O fixture, not a firmware or
hardware acceptance test. Native matrix tests separately exercise the MCU.
"""
import memmap
import json
from pathlib import Path
from elf import read
from emu816 import Emu
ROOT=Path(__file__).resolve().parents[1]
segments,S=read(ROOT/'build/wolf.elf')
class InputCPU(Emu):
    def rd8(self, addr):
        value=super().rd8(addr)
        if addr==memmap.KBDSTRB:
            self.m[memmap.KBD]&=127
        return value

def fresh():
    e=InputCPU()
    for seg in segments:e.load(seg['address'],seg['data'])
    e.load(S['I_GetTime'],bytes.fromhex('a92a00a200006b'))
    e.db=S['J13Init']>>16;e.d=0x1000
    e.wr16(S['j13Matrix'],1);e.wr16(S['j13Mode'],2)
    return e

def call(e,n,long=False):
    e.mf=e.xf=0
    a=S[n];e.call(a>>16,a&65535,long_return=long)

def sample(e,ascii=None,down=True,mods=0):
    e.db=S['J13Init']>>16
    if ascii is not None:e.wr8(memmap.KBD,ascii|128)
    e.wr8(memmap.KBDSTRB,128 if down else 0)
    e.wr8(memmap.KEYMODREG,mods)
    call(e,'J13Sample')

def consume(e):
    e.db=2;call(e,'ReadKeys')

e=fresh();sample(e,ord('w'));consume(e)
assert e.rd8(S['keyHeld']+13)==2
assert e.rd16(S['heldCommand'])&1
sample(e,8);consume(e)
assert e.rd8(S['keyHeld']+59)==2
assert e.rd8(S['keyHeld']+13)==2
# A completed, unambiguous left-row read releases only Left.
e.db=S['J13Init']>>16;e.wr16(S['j13State'],4);e.wr16(S['j13Owner'],1)
e.wr16(S['rowAddress'],0x39);e.wr16(S['rowExpected'],0x80)
e.wr16(S['rowGeneration'],e.rd16(S['j13Generation']))
e.wr8(memmap.KMSTATUS,0x20);e.wr8(memmap.DATAREG,255)
call(e,'J13Pump');consume(e)
assert e.rd8(S['keyHeld']+59)==0 and e.rd8(S['keyHeld']+13)==2
sample(e,down=False);consume(e)
assert e.rd16(S['heldCommand'])==0
# Tap shorter than a poll still latches the action.
e=fresh();sample(e,ord('w'),down=False);consume(e)
assert e.rd16(S['keyCommand'])&1 and e.rd8(S['keyHeld']+13)==0
# Source-tagged releases cannot clear the other keyboard.
e=fresh();sample(e,ord('w'));consume(e)
def adb(e,raw):
    h=e.rd16(S['inputHead']);p=S['inputRing']+h
    e.wr16(p,42);e.wr16(p+2,0);e.wr16(p+4,raw)
    e.wr16(S['inputHead'],(h+8)&1023);consume(e)
adb(e,13);assert e.rd8(S['keyHeld']+13)==3
adb(e,13|128);assert e.rd8(S['keyHeld']+13)==2
adb(e,13);sample(e,down=False);consume(e)
assert e.rd8(S['keyHeld']+13)==1
adb(e,13|128);assert e.rd8(S['keyHeld']+13)==0
# Backpressure must not acknowledge an unread C000 character.
e=fresh();e.wr16(S['inputHead'],(1024-32));e.wr8(memmap.KBD,ord('w')|128)
sample(e);assert e.rd8(memmap.KBD)&128
# A row reply from an older generation cannot release a fresh press.
e=fresh();sample(e,ord('w'));sample(e,8)
e.db=S['J13Init']>>16;e.wr16(S['j13State'],4);e.wr16(S['rowAddress'],0x39)
e.wr16(S['rowExpected'],128);e.wr16(S['rowGeneration'],0)
e.wr8(memmap.KMSTATUS,32);e.wr8(memmap.DATAREG,255)
call(e,'J13Pump');consume(e);assert e.rd8(S['keyHeld']+59)==2
# Unknown MCU firmware must use the documented one-ordinary-key fallback.
e=fresh();e.wr16(S['j13Matrix'],0)
sample(e,ord('w'));consume(e)
sample(e,8);consume(e)
assert e.rd8(S['keyHeld']+13)==0 and e.rd8(S['keyHeld']+59)==2
e.db=S['J13Init']>>16;call(e,'scheduleRow')
assert e.rd16(S['j13Owner'])==0 and e.rd16(S['j13State'])==0
sample(e,down=False);consume(e)
assert e.rd8(S['keyHeld']+59)==0
# A P3 reply after all-up must not search endlessly for a held row.
e=fresh();sample(e,ord('w'));sample(e,8)
assert e.rd16(S['knownCount'])==2
sample(e,down=False);consume(e)
assert e.rd16(S['knownCount'])==0
e.db=S['J13Init']>>16;e.wr16(S['rowValue'],7)
call(e,'pumpPhysicalReply')
assert e.rd16(S['j13State'])==0 and e.rd16(S['j13Owner'])==0
assert e.rd16(S['heldCommand'])==0

def transitions(e):
    return [e.rd16(S['inputRing']+p+4) for p in range(0,e.rd16(S['inputHead']),8)]

def physical_reply(e,mods,generation=None):
    e.db=S['J13Init']>>16;e.wr16(S['rowValue'],mods^7)
    e.wr16(S['rowGeneration'],e.rd16(S['j13Generation']) if generation is None else generation)
    call(e,'pumpPhysicalReply')

# Idle C025 updates supersede an older P3 cache. Beginning movement while
# Control remains down must not synthesize a release/repress pair.
e=fresh();e.wr16(S['physicalValid'],1);e.wr16(S['physicalMods'],0)
sample(e,down=False,mods=0x22)
assert e.rd16(S['physicalValid'])==0
sample(e,23,mods=2)
assert transitions(e)==[54,13]
physical_reply(e,0,generation=0)
assert transitions(e)==[54,13]

# AKD clears before firmware replaces the old character's C025 modifiers.
# That interval must release the ordinary key without reviving Control.
physical_reply(e,0)
sample(e,down=False,mods=2)
assert transitions(e)==[54,13,182,141]
sample(e,down=False,mods=0x20)
physical_reply(e,2)
assert transitions(e)==[54,13,182,141]
assert e.rd16(S['physicalValid'])==0
consume(e);assert e.rd16(S['heldCommand'])==0

# A newly typed character carries fresher modifiers than the previous P3
# sample. A reply begun before that character cannot undo the release.
e=fresh();sample(e,23,mods=2);physical_reply(e,2)
old_generation=e.rd16(S['j13Generation'])
sample(e,8,mods=0)
physical_reply(e,2,generation=old_generation)
assert transitions(e)==[54,13,182,59]

# A firmware repeat still cannot translate its unreliable Shift/Control bits
# into new modifier presses or a new ordinary-key press.
e=fresh();sample(e,23,mods=2);physical_reply(e,2)
sample(e,23,mods=9)
assert transitions(e)==[54,13]

# An AKD rise can precede ASCII. If acknowledging C010 clears the later
# strobe, the unchanged character byte still belongs to a fresh press.
e=fresh();sample(e,ord('w'));sample(e,down=False,mods=0x20)
sample(e,down=True,mods=0x20)
assert transitions(e)==[13,141]
e.wr16(S['I_GetTime']+1,44)
sample(e,down=True,mods=0)
assert transitions(e)==[13,141,13]
sample(e,down=True,mods=0)
assert transitions(e)==[13,141,13]
sample(e,down=False,mods=0x20)
assert transitions(e)==[13,141,13,141]

# A completed tap retains the pending identity even if the next observed
# register snapshot is already all-up with idle modifier flags.
e=fresh();sample(e,ord('w'));sample(e,down=False,mods=0x20)
sample(e,down=True,mods=0x20)
e.wr16(S['I_GetTime']+1,44)
sample(e,down=False,mods=0x20)
assert transitions(e)==[13,141,13,141]
consume(e);assert e.rd8(S['keyHeld']+13)==0

# Do not recover on the AKD edge itself: C025 can still describe the old
# character. Doom records the edge, then considers recovery on a later poll.
e=fresh();sample(e,ord('w'));sample(e,down=False,mods=0)
sample(e,down=True,mods=0)
assert transitions(e)==[13,141]
sample(e,8,mods=0)
assert transitions(e)==[13,141,59]

# A mode reset acknowledges a still-held key. Its AKD snapshot is the new
# baseline, not a fabricated all-up edge that can revive the menu key.
e=fresh();sample(e,27)
e.db=S['J13Init']>>16;call(e,'J13Reset',long=True)
before=transitions(e)
sample(e,down=True,mods=0);sample(e,down=True,mods=0)
assert transitions(e)==before

# The MCU can publish the new character after the first C000 read and before
# recovery sees associated metadata. Recover from the ordered later read.
e=fresh();sample(e,ord('w'));sample(e,down=False,mods=0x20)
sample(e,down=True,mods=0x20)
read_before=e.rd8
def publish_character(addr):
    if addr==memmap.KEYMODREG:e.wr8(memmap.KBD,8)
    return read_before(addr)
e.rd8=publish_character
e.wr16(S['I_GetTime']+1,44)
sample(e,down=True,mods=0)
assert transitions(e)==[13,141,59]

# Complete the selected controller read in this deterministic register model.
# Native tests separately exercise the MCU's actual replies and scheduling.
def row_reply(e, value):
    e.db=S['J13Init']>>16
    e.wr16(S['j13State'],4);e.wr16(S['j13Owner'],1)
    e.wr8(memmap.KMSTATUS,0x20);e.wr8(memmap.DATAREG,value)
    call(e,'J13Pump')

def physical_reply(e, value=7):
    e.wr16(S['rowAddress'],0xe8)
    e.wr16(S['rowGeneration'],e.rd16(S['j13Generation']))
    row_reply(e,value)

# Steady-held sampling must accept a second key, all-up, and a later repress.
e=fresh();sample(e,ord('w'));physical_reply(e)
for _ in range(8):sample(e,down=True)
assert transitions(e)==[13]
sample(e,8);assert transitions(e)==[13,59]
sample(e,down=False,mods=0x20)
assert transitions(e)==[13,59,141,187]
sample(e,down=True,mods=0x20)
e.wr16(S['I_GetTime']+1,44);sample(e,down=True,mods=0)
assert transitions(e)==[13,59,141,187,59]

# P3 continues to publish live modifiers while the character remains held.
e=fresh();sample(e,ord('w'));physical_reply(e,3)
assert e.rd16(S['j13Mods'])==4
sample(e,down=True,mods=0)
assert e.rd16(S['j13Mods'])==4
physical_reply(e,7);assert e.rd16(S['j13Mods'])==0

# Menus resume ordinary modifier sampling while preserving held identities.
e=fresh();sample(e,ord('w'));physical_reply(e,3)
e.wr16(S['j13Available'],1);e.db=S['J13Init']>>16
call(e,'J13Menu',long=True);sample(e,down=True,mods=0x20)
assert e.rd16(S['j13Mode'])==1 and e.rd16(S['j13Mods'])==0

# A P3 reply must leave a pending same-character recovery active.
e=fresh();sample(e,ord('w'));e.db=S['J13Init']>>16
call(e,'restoreHeldSample');e.wr16(S['sampleRecover'],1)
e.wr16(S['recoverTime'],44);physical_reply(e)
e.wr16(S['I_GetTime']+1,44);sample(e,down=True,mods=0)
assert transitions(e)==[13,141,13]

# One shared row reply releases Z while A stays held.
e=fresh();sample(e,ord('a'));sample(e,ord('z'))
e.db=S['J13Init']>>16;call(e,'cacheRows')
assert e.rd16(S['rowListSize'])==2
e.wr16(S['rowsLeft'],1);physical_reply(e)
assert e.rd16(S['rowAddress'])==0x31
row_reply(e,0xfb);consume(e)
assert e.rd8(S['keyHeld'])==2 and e.rd8(S['keyHeld']+6)==0
assert e.rd16(S['j13State'])==0 and e.rd16(S['j13Owner'])==0

# Every distinct held row is checked once, without inventing transitions.
e=fresh()
for c in 'awb':sample(e,ord(c))
e.db=S['J13Init']>>16;call(e,'cacheRows')
assert e.rd16(S['rowListSize'])==6
e.wr16(S['rowsLeft'],3);physical_reply(e)
seen=[]
for _ in range(3):
    seen.append(e.rd16(S['rowAddress']))
    row_reply(e,e.rd16(S['rowExpected'])^255)
assert len(set(seen))==3 and transitions(e)==[0,13,11]
assert e.rd16(S['j13State'])==0 and e.rd16(S['j13Owner'])==0

print(json.dumps({'checks':['overlap','partial-release','all-up','short-tap','same-key-two-sources','ring-backpressure','stale-row-generation','unknown-firmware-fallback','reply-after-all-up','idle-cache-handoff','stale-character-modifiers-at-all-up','late-modifier-reply','fresh-character-modifiers','repeat-modifiers','same-ascii-strobe-recovery','completed-recovery-tap','deferred-recovery-edge','mode-reset-held-key','ordered-recovery-snapshot','steady-held-repress','steady-held-live-modifiers','steady-held-menu-transition','pending-recovery-with-P3','same-row-independent-release','three-row-batch']}))
