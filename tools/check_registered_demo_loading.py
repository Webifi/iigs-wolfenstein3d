"""Check automatic registered-demo loading without firmware or display timing.

Assembles the unmodified StartDemo..demoFloor source block and the complete
registered overlay controller. Floor setup, media availability, packet reads
and clock/logic calls are fixtures; control flow and controller copies execute
in Emu816. Missing automatic-demo media must return before any payload load.
"""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from elf import read
from emu816 import Emu


def build(root, out, assembler, linker):
    out.mkdir(parents=True, exist_ok=True)
    source = (root/'src/iigs/lglue.s').read_text()
    block = source[source.index('\nStartDemo:')+1:source.index(';;; Floor assets replace')]
    (out/'demo.s').write_text('''#include "logic.inc"
              .section gamecode, text, root, noreorder
              .public StartDemo, StartDemoPrompt
              .extern demoPrompt, demoNumber, demoTmp, demoPtr, demoEnd, floorWanted
              .extern levelIndex, demoMode, ProbeFloorData, UiFwKeep, LoadFloorAssets
              .extern LogicNewGame, ApplyLevel, I_GetTime, ResetTics
TIME .equ 0x10
LASTTIC .equ 0x12
'''+block)
    data = ['demoPrompt','demoNumber','demoTmp','demoPtr','demoEnd','floorWanted',
            'levelIndex','demoMode','weaponViewIndex']
    fixture = ['              .section testdata, data, root']
    for name in data:
        fixture += ['              .public '+name, name+': .word 0']
    fixture += ['''              .section fixturegame, text, root
              .public LoadFloorAssets, ApplyLevel, ResetTics
              .extern EnsureGameplayAssets
LoadFloorAssets:
              sta long:levelIndex
              jsl long:EnsureGameplayAssets
              sec
              rts
ApplyLevel:   rts
ResetTics:    rts
              .section fixturelong, text, root
              .public ProbeFloorData, UiFwKeep, LoadAuxData, I_GetTime, LogicNewGame
ProbeFloorData: .byte 0xdb
UiFwKeep:     .byte 0xdb
LoadAuxData:  .byte 0xdb
I_GetTime:    .byte 0xdb
LogicNewGame: .byte 0xdb
''']
    (out/'fixture.s').write_text('\n'.join(fixture))
    (out/'logic.inc').write_text('#define WOLF_REGISTERED 1\n')
    (out/'campaign.inc').write_text('CAMPAIGN_FLOORS .equ 60\n')
    (out/'overlay_groups.inc').write_text('AUX_WEIGHTS_BASE .equ 0\nAUX_WEAPONS_BASE .equ 4\nAUX_UI .equ 244\nAUX_GAME_BASE .equ 245\nAUX_DEMOS_BASE .equ 305\n')
    layout = out/'test.scm'
    layout.write_text('''(define memories '(
(memory Game (address (#x020000 . #x025fff)) (section gamecode))
(memory GameFixture (address (#x026000 . #x027fff)) (section fixturegame))
(memory Data (address (#x028000 . #x028fff)) (section testdata))
(memory LongFixture (address (#x029000 . #x029fff)) (section fixturelong))
(memory Overlay (address (#x3f0000 . #x3f1fff)) (section registeredmenu))))
''')
    objects = []
    for path in (out/'demo.s', root/'src/iigs/ui_overlays.s', out/'fixture.s'):
        obj=out/(path.stem+'.o')
        subprocess.run([assembler,'--code-model=large','--data-model=medium','-I',str(out),
                        '-o',str(obj),str(path)],check=True)
        objects.append(str(obj))
    executable=out/'demos.elf'
    subprocess.run([linker,'-o',str(executable),str(layout),*objects,'--hosted'],check=True)
    return executable


class Bench(Emu):
    def __init__(self, executable):
        super().__init__()
        segments, self.sym=read(executable)
        for seg in segments:self.load(seg['address'],seg['data'])
        self.events=[];self.missing_floor=False;self.missing_packets=False;self.extra_p=0
        self.screen=bytes((i*29+3)&255 for i in range(0x8000))
        self.load(memmap.SHR,self.screen)
        self.wr16(self.sym['overlayWeightView'],1)
        self.wr16(self.sym['overlayWeaponKey'],1)
        self.wr16(self.sym['weaponViewIndex'],2)
        self.wr16(self.sym['overlayGameCold'],0)
        self.load(memmap.BOOT_STAGE,b'\x5a'*65536)
        for i in range(4):
            self.wr16(memmap.DEMOS+i*6,0x8030)
            self.wr16((memmap.DEMOS+0x2)+i*6,10)
            self.wr16((memmap.DEMOS+0x4)+i*6,0)

    def getp(self):return super().getp()|self.extra_p
    def setp(self,p):self.extra_p=p&12;super().setp(p)
    def rtl(self):self.pc=(self.pop16()+1)&65535;self.pb=self.pop8()
    def step(self):
        pc=self.pb<<16|self.pc;s=self.sym
        if pc==s['ProbeFloorData']:
            aux=bool(self.a&0x1000)
            self.events.append(['aux-probe' if aux else 'floor-probe',self.a&0xfff])
            self.c=int(self.missing_packets if aux else self.missing_floor)
            self.a,self.x,self.y=0xdead,0xbeef,0xcafe
            self.rtl();return
        if pc==s['UiFwKeep']:
            self.a,self.x,self.y=0xffff,0x1000,0xfc00
            self.rtl();return
        if pc==s['LoadAuxData']:
            group=self.a;self.events.append(['payload',group])
            self.load(memmap.BOOT_STAGE,b'\xcc'*65536)
            self.load((memmap.SHR+0x6200),b'\xdd'*0x1e00)
            if 245<=group<305:self.load(memmap.BOOT_STAGE,bytes([group-245])*65536)
            self.wr16(s['overlayGameCold'],1)
            self.a,self.x,self.y=0xdead,0xbeef,0xcafe;self.c=0
            self.rtl();return
        if pc==s['LoadFloorAssets']:self.events.append(['floor-assets',self.a])
        if pc in (s['LogicNewGame'],s['I_GetTime']):
            self.a=0;self.rtl();return
        opcode=self.rd8(pc)
        if opcode==0x58:self.extra_p&=~4
        elif opcode==0x78:self.extra_p|=4
        elif opcode==0xd8:self.extra_p&=~8
        elif opcode==0xf8:self.extra_p|=8
        super().step()

    def invoke(self,name,a=0,flags=0):
        self.a,self.x,self.y=a,0x1234,0x5678
        self.d,self.db,self.s=0x1000,2,0x1fff
        self.setp(flags)
        at=self.sym[name]
        self.call(at>>16,at&65535,long_return=name=='ProbeDemoAssets',limit=100000)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--assembler',default='as65816');ap.add_argument('--linker',default='ln65816')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--expect-regression',action='store_true')
    args=ap.parse_args();root=Path(__file__).resolve().parents[1]
    exe=build(root,args.out.resolve(),args.assembler,args.linker)
    cases=[]
    for demo in range(4):
        for same in (False,True):
            for prompt in (False,True):
                for absent in ('none','floor','packets','both'):
                    b=Bench(exe);floor=0 if same else 2
                    b.wr16((memmap.DEMOS+0x4)+demo*6,floor)
                    b.missing_floor=absent in ('floor','both')
                    b.missing_packets=absent in ('packets','both')
                    b.invoke('StartDemoPrompt' if prompt else 'StartDemo',demo)
                    blocked=not prompt and (b.missing_packets or (not same and b.missing_floor))
                    payload=[e for e in b.events if e[0]=='payload']
                    if args.expect_regression:
                        cases.append(dict(demo=demo,same_floor=same,prompt=prompt,absent=absent,
                                          loaded_despite_missing_automatic_media=bool(blocked and payload),events=b.events))
                        continue
                    if blocked:
                        assert b.c==0 and not payload,(demo,same,prompt,absent,b.events)
                        assert bytes(b.m[memmap.BOOT_STAGE:memmap.BOOT_STAGE_END])==b'\x5a'*65536
                        assert b.rd16(b.sym['overlayGameCold'])==0
                        assert b.rd16(b.sym['overlayUICold'])==0
                    else:
                        assert b.c==1,(demo,same,prompt,absent,b.events)
                        assert ['payload',305+demo] in b.events
                        assert b.events.index(['payload',305+demo])<b.events.index(['floor-assets',floor])
                        assert b.events[-1]==['payload',245+floor],b.events
                        assert bytes(b.m[memmap.BOOT_STAGE:memmap.BOOT_STAGE_END])==bytes([floor])*65536
                        if prompt:assert all('probe' not in e[0] for e in b.events)
                    assert bytes(b.m[memmap.SHR:memmap.RAW_PLANES])==b.screen
                    cases.append(dict(demo=demo,same_floor=same,prompt=prompt,absent=absent,events=b.events))
    status_cases=0
    if not args.expect_regression:
        b=Bench(exe)
        for flags in range(256):
            for present in (False,True):
                for demo in range(4):
                    b.events=[];b.missing_packets=not present
                    b.invoke('ProbeDemoAssets',demo,flags)
                    assert (b.a,b.x,b.y,b.db,b.d,b.s)==(demo,0x34 if flags&16 else 0x1234,0x78 if flags&16 else 0x5678,2,0x1000,0x1fff)
                    assert b.getp()==((flags&254)|int(not present))
                    assert b.events==[['aux-probe',305+demo]]
                    assert b.rd16(b.sym['overlayGameCold'])==0
                    status_cases+=1
        for demo in (4,65535):
            b=Bench(exe);b.invoke('ProbeDemoAssets',demo)
            assert b.c==1 and not b.events
        # Empty directory entries must not initiate either a probe or payload read.
        b=Bench(exe);b.wr16(memmap.DEMOS,0);b.invoke('StartDemo')
        assert b.c==0 and b.events==[]
    failures=sum(bool(c.get('loaded_despite_missing_automatic_media')) for c in cases)
    if args.expect_regression:assert failures>0
    report=dict(scope=__doc__,source_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest()
                 for f in ('src/iigs/lglue.s','src/iigs/ui_overlays.s')},
                cases=len(cases),probe_status_cases=status_cases,regressions=failures,results=cases)
    (args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))


if __name__=='__main__':main()
