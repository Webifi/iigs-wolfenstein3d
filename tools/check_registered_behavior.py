"""Native registered-Wolf combat and state-machine checks against DOS source.

Builds the current actor sources in a routine-test layout. Rendering, UI and
firmware callbacks are explicit fixtures; tested actor/combat code is real.
No game image, frame-rate or hardware acceptance is implied.
"""
import memmap
import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
from pathlib import Path
from collections import Counter
from elf import read
from emu816 import Emu
from wolfdata import ROOT, ID
import build_logic

FILES = ['lregistered','lboss','lprojectile','ldeathcam','lact','lplay','lsetup',
         'lagent','lsight','ui_deathcam','continue']
PREFIX = {3:'grd',4:'ofc',5:'ss',6:'dog',7:'boss',8:'schabb',9:'fake',
          10:'mecha',11:'mut',15:'blinky',16:'hitler',17:'gretel',18:'gift',19:'fat'}
ENEMY = {3:0,4:1,5:2,6:3,7:4,8:5,9:6,10:7,11:8,15:9,17:13,18:14,19:15}
LB, DP = memmap.LOGIC_BASE, 0x1100

# These callbacks are outside the actor unit. Unknown execution fails closed.
LOGIC_STUBS = ['CastLogicView','MouseAngleDivide','RefreshWallRuns','SpawnBJVictory',
               'T_BJDone','T_BJJump','T_BJRun','T_BJYell','VictorySpin']
GAME_STUBS = ['ApplyLevel','EndShow','LoadFloorAssets','LogicPublish','ResetTics',
              'ShowView','TallyOpen','TallyTick','TallyWait','VictoryShow','setView']
LONG_STUBS = ['I_GetTime','InitFlash','MarkFloorVisited','MenuReturnTitle',
              'Progress1','Progress16','Progress2','Progress20','Progress22',
              'Progress26','Progress3','Progress4','Progress6','Progress7',
              'RegisteredDeathNotice','PrepareMusic','StartPreparedMusic','SelectMusic','UiLoadDone','UiPublishGame',
              'UiResetInput','UiShowView','WaitBlank','gsCapture']
DATA_STUBS = ['deathPhase','doorPosition','floorRearm','flowAck','flowPhase','flowStep',
              'inputSerial','staticRevision','levelIndex','levelState','musicRequest','nextFloor',
              'pwallPosition','screenHold','tallyKill','tallySec','tallySecret',
              'tallyTreasure','wallDirty','weaponViewIndex']


def build(out, assembler, linker):
    assert build_logic.REGISTERED, 'Set WOLF_PROFILE=wolf3d'
    out.mkdir(parents=True,exist_ok=True)
    tables, states, game = build_logic.tables_blob()
    (out/'logic.inc').write_text(build_logic.include(states,game))
    (out/'logic_sounds.inc').write_text(build_logic.sounds())
    from logic_sound_timing import gate_assembly
    (out/'logic_sound_gate.inc').write_text(gate_assembly())
    (out/'logic-tables.bin').write_bytes(tables)
    fixture=[]
    for section,names in [('fixturelogic',LOGIC_STUBS),('fixturegame',GAME_STUBS),('fixturelong',LONG_STUBS)]:
        fixture.append('              .section '+section+', text, root')
        for name in names:
            fixture += ['              .public '+name,name+': .byte 0xdb']
    fixture.append('              .section fixturedata, data, root')
    for name in DATA_STUBS:
        fixture += ['              .public '+name,name+': .space 256']
    (out/'fixture.s').write_text('\n'.join(fixture)+'\n')
    (out/'test.scm').write_text('''(define memories '(
(memory Logic (address (#x0d0000 . #x0d6fff)) (section logiccode))
(memory Registered (address (#x0d8000 . #x0dfeef)) (section registeredlogic registereddata))
(memory LogicFixture (address (#x0d7000 . #x0d77ff)) (section fixturelogic))
(memory LongFixture (address (#x0d7800 . #x0d7eff)) (section fixturelong))
(memory Flow (address (#x020000 . #x026fff)) (section flowcode gamecode))
(memory GameFixture (address (#x027000 . #x027fff)) (section fixturegame))
(memory DataFixture (address (#x028000 . #x02ffff)) (section fixturedata gamedata))))
''')
    objects=[]
    for name in FILES+['fixture']:
        source=out/'fixture.s' if name=='fixture' else ROOT/'src/iigs'/f'{name}.s'
        obj=out/f'{name}.o'
        subprocess.run([assembler,'--code-model=large','--data-model=medium','-I',str(out),
                        '-I',str(ROOT/'build/gen'),'-I',str(ROOT/'src/iigs'),
                        '-o',str(obj),str(source)],check=True)
        objects.append(str(obj))
    exe=out/'actors.elf'
    subprocess.run([linker,'-o',str(exe),str(out/'test.scm'),*objects,'--hosted'],check=True)
    return exe


class Rig(Emu):
    def __init__(self,exe):
        super().__init__()
        segments,self.sym=read(exe)
        for seg in segments:self.load(seg['address'],seg['data'])
        self.load(LB,(exe.parent/'logic-tables.bin').read_bytes())
        # The native word-product routines use complete byte-product rows.
        self.load(memmap.WORD_PRODUCTS,b''.join(struct.pack('<H',a*b) for a in range(128) for b in range(256)))
        self.load((memmap.WORD_PRODUCTS+0x10000),b''.join(struct.pack('<H',a*b) for a in range(128,256) for b in range(256)))
        for a in range(256):self.wr16(memmap.RAY_PRODUCTS_DIRECTORY+a*2,(memmap.WORD_PRODUCTS+a*512)>>8)
        self.base=bytes(self.m)
        self.hooks={};self.events=[];self.sounds=[]
        self.fixture={self.sym[n]:n for n in LOGIC_STUBS+GAME_STUBS+LONG_STUBS}

    def reset(self):
        self.m[:]=self.base;self.hooks={};self.events=[];self.sounds=[]
        self.w('V_health',1000);self.w('V_nextextra',0xffff);self.w('V_nextextra_hi',0x7fff)
        self.w('V_laststat',self.sym['STATICS']);self.w('V_difficulty',2)
        self.load(LB+self.sym['MAP0'],bytes([107])*4096)
        self.load(LB+self.sym['AREABYPLAYER'],bytes([1])*64)
        self.call('InitActorList')
        self.pose(self.sym['OBJLIST'],32*65536+32768,32*65536+32768)
        self.w('V_plux',(32*65536+32768)>>8);self.w('V_pluy',(32*65536+32768)>>8)
        self.w('V_tics',1);self.w('V_sound',65535)

    def w(self,name,value=None,base=LB):
        address=base+self.sym[name]
        if value is None:return self.rd16(address)
        self.wr16(address,value&65535)

    def field(self,ob,name,value=None):return self.w(name,value,LB+ob)
    def long(self,ad,value=None):
        if value is None:return struct.unpack_from('<I',self.m,ad)[0]
        struct.pack_into('<I',self.m,ad,value&0xffffffff)
    def pose(self,ob,x,y):
        self.long(LB+ob+self.sym['O_X'],x);self.long(LB+ob+self.sym['O_Y'],y)
        self.field(ob,'O_TILEX',x>>16);self.field(ob,'O_TILEY',y>>16)
        self.field(ob,'O_AREA',0)
    def actor(self,kind=8):
        self.call('GetNewActor');ob=self.x
        self.field(ob,'O_CLASS',kind);self.field(ob,'O_FLAGS',1|16)
        self.field(ob,'O_STATE',self.sym['s_'+PREFIX[kind]+'chase1'])
        self.field(ob,'O_SPEED',512);self.field(ob,'O_DIR',8)
        self.pose(ob,34*65536+32768,32*65536+32768)
        self.w('L_OB',ob,DP)
        return ob
    def ret(self,long=False):
        self.pc=(self.pop16()+1)&65535
        if long:self.pb=self.pop8()
    def step(self):
        pc=self.pb<<16|self.pc
        if pc==self.sym['LogicSound']:self.sounds.append((self.a,self.x))
        if pc in self.hooks:
            self.events.append(pc);self.hooks[pc](self);return
        if pc in self.fixture:raise AssertionError('unexpected fixture '+self.fixture[pc])
        super().step()
    def stub(self,name,long=False,callback=None):
        def fn(e):
            if callback:callback(e)
            e.ret(long)
        self.hooks[self.sym[name]]=fn
    def call(self,name,a=0,x=0,y=0,long=False,game=False):
        self.d,self.db,self.mf,self.xf,self.s= (0x1000 if game else DP),(2 if game else LB>>16),0,0,0x1fff
        self.a,self.x,self.y=a,x,y
        address=self.sym[name]
        super().call(address>>16,address&65535,long_return=long,sentinel=(memmap.LOGIC_TAIL+0x727),limit=3_000_000)


class Checks:
    def __init__(self):self.failures=[];self.counts=Counter()
    def eq(self,group,got,want,context=None):
        self.counts[group]+=1
        if got!=want:self.failures.append(dict(group=group,got=got,want=want,context=context))


def source_hp():
    text=(ID/'WOLFSRC/WL_ACT2.C').read_text()
    body=text.split('starthitpoints[4][NUMENEMIES]',1)[1].split('};',1)[0]
    body=re.sub(r'//[^\n]*|/\*.*?\*/','',body,flags=re.S)
    return [list(map(int,re.findall(r'\d+',x))) for x in re.findall(r'\{([^{}]+)\}',body)]


def hp_and_morph(r,c):
    hp=source_hp()
    for kind in PREFIX:
        for difficulty in range(4):
            r.reset();ob=r.actor(kind);r.w('V_difficulty',difficulty)
            r.call('ClassHitPoints',x=ob)
            expected=(500,700,800,900)[difficulty] if kind==16 else hp[difficulty][ENEMY[kind]]
            c.eq('hitpoints',r.field(ob,'O_HP'),expected,[kind,difficulty])
    for difficulty in range(4):
        r.reset();ob=r.actor(10);r.w('V_difficulty',difficulty)
        r.pose(ob,0x218765,0x223456);r.field(ob,'O_DIR',3);r.field(ob,'O_FLAGS',128|16)
        r.long(LB+ob+r.sym['O_DIST'],0x8765);r.w('V_rndindex',37)
        r.call('A_HitlerMorph');new=r.w('V_lastobj')
        got=[r.field(new,n) for n in ('O_CLASS','O_SPEED','O_HP','O_FLAGS','O_DIR','O_TILEX','O_TILEY','O_STATE')]
        want=[16,2560,(500,700,800,900)[difficulty],145,3,33,34,r.sym['s_hitlerchase1']]
        c.eq('morph',got,want,difficulty)
        c.eq('morph',[r.long(LB+new+r.sym[n]) for n in ('O_X','O_Y','O_DIST')],[0x218765,0x223456,0x8765],difficulty)
        c.eq('morph',r.w('V_rndindex'),38,difficulty)
        c.eq('morph',r.field(new,'O_TICS'),r.rd8(LB+r.sym['RNDTABLE']+38)%6,difficulty)
        c.eq('morph',r.w('V_killtotal'),0,difficulty)


def shots(r,c):
    # Source WL_ACT2 T_Shoot: Gretel takes the default NAZIFIRESND case.
    sound={5:'SSFIRESND',7:'BOSSFIRESND',10:'BOSSFIRESND',16:'BOSSFIRESND',
           18:'MISSILEFIRESND',19:'MISSILEFIRESND',8:'SCHABBSTHROWSND',9:'FLAMETHROWERSND'}
    for kind in (3,4,5,7,8,9,10,11,16,17,18,19):
        r.reset();ob=r.actor(kind)
        r.stub('CheckLine',callback=lambda e:setattr(e,'c',1))
        for dist in (0,1,2,3,4,8,16,31):
            r.field(ob,'O_TILEX',32+dist)
            for visible in (False,True):
                r.field(ob,'O_FLAGS',1|16|(8 if visible else 0))
                for running in (False,True):
                    r.w('V_thrustspeed',r.sym['RUNSPEED'] if running else 0)
                    for seed in (0,1,7,19,37,63,95,127,151,183,211,239,254,255):
                        r.w('V_rndindex',seed);r.w('V_health',1000);r.w('V_damageflash',0);r.w('V_lastattacker',0)
                        r.w('V_sound',65535);r.sounds=[]
                        distance=dist*2//3 if kind in (5,7) else dist
                        chance=(160 if running else 256)-distance*(16 if visible else 8)
                        index=(seed+1)&255;roll=r.rd8(LB+r.sym['RNDTABLE']+index)
                        damage=0;hit=roll<chance
                        if hit:
                            index=(index+1)&255
                            damage=r.rd8(LB+r.sym['RNDTABLE']+index)>>(2 if distance<2 else 3 if distance<4 else 4)
                        r.call('T_Shoot')
                        c.eq('hitscan',[r.w('V_health'),r.w('V_rndindex'),r.w('V_lastattacker')],
                             [1000-damage,index,ob if hit else 0],[kind,dist,visible,running,seed])
                        if dist==0 and not visible and not running and seed==0:
                            c.eq('shot_sound',r.w('V_sound'),r.sym[sound.get(kind,'NAZIFIRESND')],kind)
        # Area and line gating consume no RNG and request no sound.
        for connected,line in ((0,True),(1,False)):
            r.w('AREABYPLAYER',connected);r.stub('CheckLine',callback=lambda e,line=line:setattr(e,'c',int(line)))
            r.w('V_rndindex',55);r.w('V_sound',65535);r.call('T_Shoot')
            c.eq('attack_gates',[r.w('V_rndindex'),r.w('V_sound')],[55,65535],[kind,connected,line])


def projectile_damage(r,c):
    for kind in (12,13,20):
        for difficulty in range(4):
            r.reset();ob=r.actor(8);r.field(ob,'O_CLASS',kind);r.field(ob,'O_SPEED',0)
            r.field(ob,'O_ANGLE',0);r.w('V_difficulty',difficulty)
            for dx in (-0xc001,-0xc000,-0xbfff,0,0xbfff,0xc000,0xc001):
                for dy in (0,0xbfff,0xc000):
                    for seed in (0,37,127,254,255):
                        px=r.long(LB+r.sym['OBJLIST']+r.sym['O_X']);py=r.long(LB+r.sym['OBJLIST']+r.sym['O_Y'])
                        r.pose(ob,px+dx,py+dy);r.field(ob,'O_STATE',r.sym['s_rocket']);r.field(ob,'O_TICS',2)
                        r.w('V_health',1000);r.w('V_rndindex',seed);r.w('V_lastattacker',0)
                        hit=abs(dx)<0xc000 and abs(dy)<0xc000
                        index=(seed+int(hit))&255
                        damage=(r.rd8(LB+r.sym['RNDTABLE']+index)>>3)+(20 if kind==12 else 30 if kind==20 else 0) if hit else 0
                        if difficulty==0:damage>>=2
                        r.call('T_Projectile')
                        c.eq('projectile_hit',[r.w('V_health'),r.w('V_rndindex'),r.field(ob,'O_STATE'),r.field(ob,'O_TICS')],
                             [1000-damage,index,0 if hit else r.sym['s_rocket'],2],[kind,difficulty,dx,dy,seed])


def drops_and_pain(r,c):
    points={3:100,4:400,5:500,6:200,7:5000,8:5000,9:2000,10:5000,11:700,16:5000,17:5000,18:5000,19:5000}
    for kind,award in points.items():
        for weapon in (1,2):
            r.reset();ob=r.actor(kind);r.w('V_bestweapon',weapon);r.field(ob,'O_FLAGS',1|16|64)
            r.pose(ob,0x228765,0x233456);r.field(ob,'O_TILEX',36);r.field(ob,'O_TILEY',37)
            r.call('KillActor',x=ob)
            drop=15 if kind==5 and weapon<2 else 14 if kind in (3,4,5,11) else 5 if kind in (7,17) else None
            c.eq('kill',[r.w('V_score'),r.w('V_killcount'),r.field(ob,'O_FLAGS'),r.field(ob,'O_STATE')],
                 [award,1,16|64|128,r.sym['s_'+PREFIX[kind]+'die1']],[kind,weapon])
            c.eq('drops',r.w('V_laststat'),r.sym['STATICS']+(8 if drop is not None else 0),[kind,weapon])
            if drop is not None:
                c.eq('drops',[r.rd16(LB+r.sym['STATICS']),r.rd16(LB+r.sym['STATICS']+6)],[34*64+35,drop],[kind,weapon])
            if kind in (8,16,18,19):
                c.eq('kill_camera',[r.w('V_killx'),r.w('V_killx_hi'),r.w('V_killy'),r.w('V_killy_hi')],[32768,32,32768,32],kind)
            c.eq('kill',r.rd16(LB+r.sym['ACTORAT']+(34*64+35)*2),0,kind)
    for kind in (4,8,9,10,11,16,17,18,19):
        for hp in (50,51):
            for alert in (False,True):
                r.reset();ob=r.actor(kind);r.field(ob,'O_HP',hp);r.field(ob,'O_FLAGS',1|(16 if alert else 0))
                r.call('DamageActor',a=3,x=ob)
                left=hp-(3 if alert else 6)
                state='s_'+PREFIX[kind]+('pain' if left&1 else 'pain1') if kind in (4,11) else 's_'+PREFIX[kind]+'chase1'
                c.eq('pain',[r.field(ob,'O_HP'),r.field(ob,'O_STATE'),r.w('V_madenoise')],[left,r.sym[state],1],[kind,hp,alert])



def spawn_fields(r,c):
    for code,kind,north in ((197,17,True),(196,8,False),(160,9,True),(178,10,False),(215,18,True),(179,19,False)):
        for difficulty in range(4):
            r.reset();r.w('V_difficulty',difficulty);r.w('L_SX',17,DP);r.w('L_SY',23,DP)
            r.call('RegisteredInfo',a=code);ob=r.w('V_lastobj')
            c.eq('boss_spawn',[r.c,r.field(ob,'O_CLASS'),r.field(ob,'O_DIR'),r.field(ob,'O_SPEED'),r.field(ob,'O_FLAGS'),r.w('V_killtotal')],
                 [1,kind,2 if north else 6,512,65,1],[code,difficulty])
    # Digitized effects are the port's playback path, even at zero volume.
    for prefix in ('schabb','gift','fat','hitler'):
        r.reset();c.eq('death_voice_wait',r.rd16(LB+r.sym['s_'+prefix+'die2']+r.sym['ST_TICS']),140,prefix)


def source_states():
    # Preprocess the original C rather than reuse the converter's state parser.
    source=(ID/'WOLFSRC/WL_ACT2.C').read_text()
    source=re.sub(r'^\s*#\s*include[^\n]*','',source,flags=re.M)
    text=subprocess.run(['cc','-E','-P','-x','c','-'],input=source,capture_output=True,text=True,check=True).stdout
    rows={}
    for name,body in re.findall(r'statetype\s+(s_\w+)\s*=\s*\{([^}]+)\}',text):
        rotate,shape,tics,think,action,nxt=[v.strip() for v in body.split(',')]
        rows[name]=(int({'true':'1','false':'0'}.get(rotate,rotate)),int(tics),think,action,nxt.lstrip('&'))
    for prefix in ('schabb','gift','fat','hitler'):
        name='s_'+prefix+'die2';row=list(rows[name]);row[1]=140;rows[name]=tuple(row)
    return rows


def dispatch(r,c):
    rows=source_states()
    # Verify compiled table indices land on the named native procedures.
    for name,(rotate,tics,think,action,nxt) in rows.items():
        if name not in r.sym:continue
        state=LB+r.sym[name]
        values=struct.unpack_from('<6H',r.m,state)
        c.eq('state_table',[values[0],values[2],values[5]],[rotate,tics,r.sym[nxt] if nxt!='NULL' else 0],name)
        for index,table,target in ((values[3],'thinkTable',think),(values[4],'actionTable',action)):
            c.eq('dispatch_pointer',r.rd16(r.sym[table]+index) if index else 0,r.sym[target]&65535 if target!='NULL' else 0,[name,table])
    # Execute DoActor with callbacks observed but isolated. Separate tests
    # below execute the actual combat/actions, including allocating missiles.
    active={n:v for n,v in rows.items() if n in r.sym}
    callbacks={row[i] for row in active.values() for i in (2,3) if row[i]!='NULL'}
    for name,row in active.items():
        for entry,elapsed in (('DoActor',1),('DoActor',4),('DoActor',64),('actorOneTic',1)):
            r.reset();ob=r.actor(8);r.field(ob,'O_FLAGS',4)
            for proc in callbacks:r.stub(proc)
            r.field(ob,'O_STATE',r.sym[name]);r.field(ob,'O_TICS',row[1]);r.w('V_tics',elapsed)
            current=name;left=row[1];events=[]
            if left:
                left-=elapsed
                while left<=0:
                    action=active[current][3]
                    if action!='NULL':events.append(r.sym[action])
                    current=active[current][4]
                    if current=='NULL':break
                    nexttime=active[current][1]
                    if not nexttime:left=0;break
                    left+=nexttime
            if current!='NULL':
                think=active[current][2]
                if think!='NULL':events.append(r.sym[think])
            r.events=[];r.call(entry,x=ob)
            c.eq('state_execution',r.events,events,[name,entry,elapsed])
            c.eq('state_execution',r.field(ob,'O_STATE'),r.sym[current] if current!='NULL' else 0,[name,entry,elapsed])
            if current!='NULL':c.eq('state_execution',r.field(ob,'O_TICS'),left&65535,[name,entry,elapsed])


def launches(r,c):
    for proc,kind,state,speed,flags,sound in (
        ('T_SchabbThrow',12,'s_needle1',0x2000,128,'SCHABBSTHROWSND'),
        ('T_GiftThrow',20,'s_rocket',0x2000,128,'MISSILEFIRESND'),
        ('T_FakeFire',13,'s_fire1',0x1200,4,'FLAMETHROWERSND')):
        for px,py in ((32,32),(36,32),(34,30),(34,35),(30,31),(37,36)):
            r.reset();ob=r.actor(8);r.pose(r.sym['OBJLIST'],(px<<16)+32768,(py<<16)+32768)
            r.w('V_rndindex',45);r.call(proc);new=r.w('V_lastobj')
            angle=math.atan2(32-py,px-34)
            if angle<0:angle+=2*math.pi
            expected=int(angle*360/(2*math.pi))
            c.eq('launch',[r.field(new,n) for n in ('O_CLASS','O_STATE','O_SPEED','O_FLAGS','O_ACTIVE','O_TICS','O_DIR','O_ANGLE','O_TILEX','O_TILEY')],
                 [kind,r.sym[state],speed,flags,1,1,8,expected,34,32],[proc,px,py])
            c.eq('launch',[r.long(LB+new+r.sym['O_X']),r.long(LB+new+r.sym['O_Y']),r.w('V_sound'),r.w('V_rndindex')],
                 [(34<<16)+32768,(32<<16)+32768,r.sym[sound],45],proc)
    r.reset();ob=r.actor(8);r.call('A_Smoke');new=r.w('V_lastobj')
    c.eq('smoke',[r.field(new,n) for n in ('O_CLASS','O_STATE','O_FLAGS','O_ACTIVE','O_TICS','O_TILEX','O_TILEY')],
         [2,r.sym['s_smoke1'],4,1,6,34,32])


def ghosts(r,c):
    dirs=[(1,0),(1,-1),(0,-1),(-1,-1),(-1,0),(-1,1),(0,1),(1,1)]
    for difficulty in range(4):
        r.reset();ob=r.actor(15);r.w('V_difficulty',difficulty);r.w('V_tics',7)
        for direction,(vx,vy) in enumerate(dirs):
            for dx in (-65537,-65536,0,65536,65537):
                for dy in (-65537,-65536,0,65536,65537):
                    origin=32*65536+32768
                    before=(origin+dx-vx*512,origin+dy-vy*512)
                    r.pose(ob,*before);r.field(ob,'O_DIR',direction)
                    r.long(DP+r.sym['L_MOVE'],512);r.long(LB+ob+r.sym['O_DIST'],65536)
                    r.w('V_health',1000);r.w('V_lastattacker',0);r.w('V_rndindex',77)
                    r.call('MoveObj',x=ob)
                    contact=abs(dx)<=65536 and abs(dy)<=65536
                    damage=(14>>2 if difficulty==0 else 14) if contact else 0
                    want=before if contact else (origin+dx,origin+dy)
                    c.eq('ghost_contact',[r.long(LB+ob+r.sym['O_X']),r.long(LB+ob+r.sym['O_Y']),r.w('V_health'),r.w('V_rndindex')],
                         [*want,1000-damage,77],[difficulty,direction,dx,dy])


def boss_choices(r,c):
    for proc,kind,factor in (('T_Schabb',8,8),('T_Gift',18,8),('T_Fat',19,8),('T_Fake',9,2)):
        for elapsed in (1,4,32,64):
            for seed in range(256):
                r.reset();ob=r.actor(kind);r.field(ob,'O_SPEED',0);r.field(ob,'O_DIR',0)
                r.w('V_tics',elapsed);r.w('V_rndindex',seed)
                r.stub('CheckLine',callback=lambda e:setattr(e,'c',1))
                state=r.field(ob,'O_STATE');roll=r.rd8(LB+r.sym['RNDTABLE']+((seed+1)&255))
                r.call(proc)
                wanted=r.sym['s_'+PREFIX[kind]+'shoot1'] if roll<elapsed*factor else state
                c.eq('boss_attack_rng',[r.field(ob,'O_STATE'),r.w('V_rndindex')],[wanted,(seed+1)&255],[proc,elapsed,seed])


def camera_and_victory(r,c):
    for kind in (8,16,18,19):
        for blocked in (False,True):
            r.reset();ob=r.actor(kind);r.w('V_killx',32768);r.w('V_killx_hi',32);r.w('V_killy',32768);r.w('V_killy_hi',32)
            r.call('A_StartDeathCam')
            c.eq('death_camera',[r.w('V_deathcam_phase'),r.w('V_victoryflag'),r.w('V_deathcam_actor'),r.field(r.sym['OBJLIST'],'O_STATE'),r.field(ob,'O_STATE')],
                 [1,1,ob,r.sym['s_deathcam'],r.sym['s_'+PREFIX[kind]+'waitcam']],kind)
            if blocked:r.wr16(LB+r.sym['ACTORAT']+(33*64+32)*2,1)
            for callback in ('InitFlash','WaitBlank','RegisteredDeathNotice','LogicFinish','UiPublishGame','UiShowView','UiResetInput'):
                r.stub(callback,long=True)
            r.events=[];r.call('DeathCamFrame',long=True,game=True)
            c.eq('death_camera',r.events,[r.sym['InitFlash']]+[r.sym['WaitBlank']]*100+[r.sym[n] for n in ('RegisteredDeathNotice','LogicFinish','UiPublishGame','UiShowView','UiResetInput')],[kind,blocked])
            distance=0x14000
            cosine=r.long(LB+r.sym['SINTAB']+90*4)&65535
            while True:
                x=34*65536+32768-((distance*cosine)>>16)
                if not blocked or (x+0x5800)>>16<33:break
                distance+=0x1000
            c.eq('camera_position',[r.long(LB+r.sym['OBJLIST']+r.sym['O_X']),r.long(LB+r.sym['OBJLIST']+r.sym['O_Y']),r.field(r.sym['OBJLIST'],'O_ANGLE'),r.w('V_deathcam_phase'),r.field(ob,'O_STATE')],
                 [x,32*65536+32768,0,2,r.sym['s_'+PREFIX[kind]+'deathcam']],[kind,blocked])
            c.eq('camera_context',[r.d,r.db,r.s],[0x1000,2,0x1fff],kind)
            r.w('L_OB',ob,DP);r.call('A_StartDeathCam');c.eq('death_camera',r.w('V_deathcam_phase'),3,kind)
            r.events=[];r.call('DeathCamFrame',long=True,game=True)
            c.eq('death_camera',[r.w('V_playstate'),r.w('V_deathcam_phase')],[6,0],kind)
            c.eq('death_camera',r.events,[r.sym['InitFlash']]+[r.sym['WaitBlank']]*100,kind)
    for floor in range(60):
        r.reset();r.wr16(r.sym['levelIndex'],floor);r.wr16(r.sym['levelState'],6)
        r.w('V_playstate',6);r.w('V_victoryflag',1);r.call('LevelFlow',game=True)
        ending=floor%10==8
        c.eq('victory_route',[r.rd16(r.sym['flowPhase']),r.w('V_playstate'),r.w('V_victoryflag')],
             [1,6,1] if ending else [0,0,0],floor)


def face_sound_gate(r,c):
    from logic_sound_timing import face_sound
    source = face_sound()
    c.eq('face_sound_duration', r.sym['GATLINGTICS'], (source['adlib_bytes']+1)//2)
    for ident in range(87):
        for timer in (0, source['ticks']):
            r.reset();r.w('V_gatling',timer)
            r.call('LogicSound',a=ident,x=1234,y=5678)
            c.eq('face_sound_registers',[r.a,r.x,r.y],[ident,1234,5678],ident)
            c.eq('face_sound_request',r.w('V_sound'),ident)
            c.eq('face_sound_preemption',r.w('V_gatling'),
                 0 if ident in source['preempt'] else timer,ident)
    r.reset();r.w('V_gatling',source['ticks']);r.w('V_tics',4)
    for packet in range(1,(source['ticks']+3)//4+1):
        r.call('playerCounts')
        c.eq('face_sound_countdown',r.w('V_gatling'),max(0,source['ticks']-4*packet),packet)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assembler',default='as65816');p.add_argument('--linker',default='ln65816')
    p.add_argument('--out',type=Path,default=ROOT/'build/actor-behavior')
    args=p.parse_args();exe=build(args.out.resolve(),args.assembler,args.linker)
    r,c=Rig(exe),Checks()
    for test in (hp_and_morph,shots,projectile_damage,drops_and_pain,spawn_fields,dispatch,launches,ghosts,boss_choices,camera_and_victory,face_sound_gate):
        test(r,c);print(test.__name__,dict(c.counts),'failures',len(c.failures),flush=True)
    result=dict(counts=c.counts,failures=c.failures,scope=__doc__,source_sha256={n:hashlib.sha256((ID/'WOLFSRC'/n).read_bytes()).hexdigest() for n in ('WL_ACT2.C','WL_STATE.C','WL_AGENT.C','WL_PLAY.C')})
    (args.out/'behavior-checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(counts=c.counts,failures=c.failures[:20]),indent=2))
    return bool(c.failures)

if __name__=='__main__':raise SystemExit(main())
