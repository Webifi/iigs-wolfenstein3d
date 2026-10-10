"""Bank $30 image for the exact game logic, one per floor.

The tables come from wolfsim.py, so the native logic and the Python model
use the same bytes. The renderer's level block at $F700 keeps the layout
that ApplyLevel reads.
"""
import memmap
import json
import struct
from wolfdata import ROOT, PROFILE, maps
from wolf_source import random_table, statics, states, sprite_ids
from buildconfig import config
import wolfsim
from line_regions import encode as encode_regions
from native_map_format import native_plane_bytes

OUT = ROOT / 'build/assets'
GEN = ROOT / 'build/gen'

# Bank $30 layout. Mutable state first; the level source and tables follow.
LAYOUT = dict(
    TILEMAP=0x0000,      # [x*64+y] bytes, the original tilemap
    ACTORAT=0x1000,      # [x*64+y] words: 0, wall/door/static value, or a record address
    OBJLIST=0x3000,      # 150 records of OBJSIZE bytes; record 0 is the player
    STATICS=0x5600,      # 400 records of 8 bytes
    DOORPOS=0x6300,      # doorposition[64]
    DOORTILE=0x6380,     # tilex*64+tiley per door
    DOORVERT=0x6400,
    DOORLOCK=0x6480,
    DOORACT=0x6500,
    DOORTICS=0x6580,
    AREACONNECT=0x6600,  # [37][37] bytes
    AREABYPLAYER=0x6b80, # 64 bytes
    VARS=0x6c00,         # game state words
    AREAQUEUE=0x6e00,    # ConnectAreas' flood queue
    MAP0=0x7000,         # [y*64+x] bytes, mutable area plane
    MAP1=0x8000,         # [y*64+x] bytes, mutable info plane
    SPOTVIS=0x9000,      # [x*64+y] bytes
    RAW0=0xa000,         # level source planes
    RAW1=0xb000,
    FINETAN=0xc000,      # 900 longs
    SINTAB=0xce10,       # 451 sign-magnitude longs; costable = SINTAB+360
    STATES=0xd600,       # STATESIZE-byte records
    RNDTABLE=0xdc00,
    DIV20=0xdd00,        # |anglefrac| / 20 for 0..1023 (bytes)
    DEG1024=0xe100,      # renderer angle (1024 units) for each degree
    RAYANGLE=0xe3d0,     # byte offsets into the 8-byte fine-angle descriptors
    STATINFO=0xe410,     # 49 x (shapenum, item) words
    ATTACKINFO=0xe580,   # 4 weapons x 4 frames x (tics, attack, frame) words
    FOCALCOS=0xe600,     # FixedByFrac(focallength, costable[a]) for 0..359, longs
    FOCALSIN=0xec00,     # FixedByFrac(focallength, sintable[a]) for 0..359, longs
    DIV6=0xf200,         # n/6 and n/12 for 0..255 (bytes)
    DIV12=0xf300,
    MOD20=0xf400,        # n%20 for 0..255: SpawnNewObj's roll for 20-tic states
    DEATHATAN=0xf500,    # atan(minor/major) in 1024ths of a turn, 16x16 bytes
    FLOORCONFIG=0xfa00,  # flat-color operand patches, filled after linking for disk loads
    RNGLOG=0xfc00,       # legacy probe name; runtime logging is external
    ROOMRECTS=0xfc00,    # count and packed x/y bounds in the retired log space
    LEVELBLOCK=0xf700,   # the renderer's level block (ApplyLevel)
)
REGISTERED = True
# Source planes are read during setup, restart and save comparison only.
# Moving them keeps the larger state table in the logic data bank, so actor
# dispatch retains its existing absolute indexed loads on every game tick.
RAW_PLANES_ADDRESS = memmap.RAW_PLANES
LAYOUT['STATES'] = LAYOUT['RAW0']
OBJSIZE = 64
STATESIZE = 12
MAXACTORS = 150
MAXSTATS = 400
LOGIC_WIDTH = 240
LOGIC_RAYS = list(range(4, LOGIC_WIDTH, 8))

FIELDS = dict(O_X=0, O_Y=4, O_DIST=8, O_TRANSX=12, O_STATE=16, O_TICS=18, O_FLAGS=20,
              O_DIR=22, O_TILEX=24, O_TILEY=26, O_AREA=28, O_CLASS=30, O_ACTIVE=32,
              O_HP=34, O_SPEED=36, O_TEMP2=38, O_VIEWX=40, O_NEXT=42, O_PREV=44, O_CELL=46,
              O_SHAPE=48, O_ANGLE=50, O_MARKED=52)
STATE_FIELDS = dict(ST_ROTATE=0, ST_SHAPE=2, ST_TICS=4, ST_THINK=6, ST_ACTION=8, ST_NEXT=10)
THINKS = ['NULL', 'T_Stand', 'T_Path', 'T_Chase', 'T_DogChase', 'T_Player', 'T_Attack', 'T_BJRun', 'T_BJJump']
ACTIONS = ['NULL', 'A_DeathScream', 'T_Shoot', 'T_Bite', 'T_BJYell', 'T_BJDone']
if PROFILE.spear:
    THINKS += ['T_Ghosts', 'T_Projectile', 'T_Will']
    ACTIONS += ['A_Breathing', 'A_Dormant', 'A_Relaunch', 'A_Slurpie', 'A_Smoke',
                'A_StartAttack', 'A_Victory', 'T_Launch', 'T_UShoot']
else:
    THINKS += ['T_Fake', 'T_Fat', 'T_Ghosts', 'T_Gift', 'T_Projectile', 'T_Schabb']
    ACTIONS += ['A_HitlerMorph', 'A_MechaSound', 'A_Slurpie', 'A_Smoke',
                'A_StartDeathCam', 'T_FakeFire', 'T_GiftThrow', 'T_Projectile', 'T_SchabbThrow']

# Words in the VARS block, in order.
VARS = ['difficulty', 'mapon', 'score', 'score_hi', 'nextextra', 'nextextra_hi', 'lives', 'health',
        'ammo', 'keys', 'bestweapon', 'weapon', 'chosenweapon', 'faceframe', 'attackframe',
        'attackcount', 'weaponframe', 'secretcount', 'treasurecount', 'killcount', 'secrettotal',
        'treasuretotal', 'killtotal', 'victoryflag', 'playstate', 'rndindex', 'anglefrac',
        'facecount', 'thrustspeed', 'thrustspeed_hi', 'madenoise', 'controlx', 'controly', 'tics',
        'gotgatgun', 'pwallstate', 'pwallpos', 'pwallx', 'pwally', 'pwalldir', 'plux', 'pluy',
        'lastobj', 'objfreelist', 'laststat', 'doornum', 'killerobj', 'lastattacker',
        'viewx', 'viewx_hi', 'viewy', 'viewy_hi', 'viewangle', 'midangle', 'viewsin', 'viewsin_hi',
        'viewcos', 'viewcos_hi', 'focaltx', 'focalty', 'damagecount', 'bonuscount', 'events',
        'facedirty', 'statusdirty', 'mapdirty', 'framecount', 'demoptr', 'demoend', 'demoplayback',
        'sound', 'gatling', 'damageflash', 'controlstrafe', 'spotstamp', 'oldscore', 'oldscore_hi']
VARS += ['killx', 'killx_hi', 'killy', 'killy_hi', 'deathcam_phase', 'deathcam_actor']
if PROFILE.spear:
    VARS += ['spearflag', 'ouchface']
BUTTONS = 0x100  # buttonstate[8] words at VARS+0x100, buttonheld[8] at VARS+0x110


def state_table():
    rows = states(None)
    if PROFILE.spear:
        voiced = {'s_transdie01':105, 's_uberdie01':70, 's_willdie2':70,
                  's_deathdie2':105, 's_angeldie11':105}
        rows = [(name, (row[0], row[1], voiced.get(name, row[2]), *row[3:]))
                for name, row in rows]
    else:
        # DOS SpawnSchabbs/Gift/Fat/Fake/Hitler select 140 tics for these
        # voiced death stages when DigiMode is enabled. This port always
        # plays effects as DOC samples; muting volume does not change timing.
        voiced_deaths = {'s_schabbdie2', 's_giftdie2', 's_fatdie2', 's_hitlerdie2'}
        rows = [(name, (row[0], row[1], 140, *row[3:]))
                if name in voiced_deaths else (name, row) for name, row in rows]
        source = dict(rows)
        for prefix, terminal in (('schabb', '6'), ('hitler', '10'), ('gift', '6'), ('fat', '6')):
            name = 's_' + prefix + 'waitcam'
            shape = source['s_' + prefix + 'die' + terminal][1]
            rows.append((name, (0, shape, 0, 'NULL', 'NULL', name)))
    bj = []
    names = [name for name, _ in rows] + ['s_player', 's_attack'] + [name for name, _ in bj]
    address = {name: LAYOUT['STATES'] + i * STATESIZE for i, name in enumerate(names)}
    blob = bytearray()
    for name, (rotate, shape, tics, think, action, nxt) in rows:
        blob += struct.pack('<6H', rotate, shape, tics, THINKS.index(think) * 2,
                            ACTIONS.index(action) * 2, address[nxt] if nxt else 0)
    blob += struct.pack('<6H', 0, 0, 0, THINKS.index('T_Player') * 2, 0, 0)
    blob += struct.pack('<6H', 0, 0, 0, THINKS.index('T_Attack') * 2, 0, 0)
    for name, (rotate, shape, tics, think, action, nxt) in bj:
        blob += struct.pack('<6H', rotate, shape, tics, THINKS.index(think)*2,
                            ACTIONS.index(action)*2, address[nxt] if nxt else 0)
    return blob, address


def tables_blob():
    radtoint, finetangent, sintable = wolfsim.build_tables()
    image = bytearray(0x10000)

    def put(name, data):
        start = LAYOUT[name]
        image[start:start + len(data)] = data

    put('FINETAN', b''.join(struct.pack('<i', v) for v in finetangent))
    put('SINTAB', b''.join(struct.pack('<I', v & 0xffffffff) for v in sintable))
    blob, address = state_table()
    assert LAYOUT['STATES'] + len(blob) <= (LAYOUT['FINETAN'])
    put('STATES', blob)
    import native_actors
    sound_ids = {row.split()[0]: int(row.split()[-1]) for row in sounds().splitlines()}
    class_data = native_actors.records(address, sound_ids)
    image[native_actors.BASE:native_actors.BASE + len(class_data)] = class_data
    put('RNDTABLE', bytes(random_table()))
    put('DIV20', bytes(v // 20 for v in range(1024)))
    put('DIV6', bytes(v // 6 for v in range(256)))
    put('DIV12', bytes(v // 12 for v in range(256)))
    put('MOD20', bytes(v % 20 for v in range(256)))
    import math
    put('DEATHATAN', bytes(round(math.atan2(minor, major) * 1024 / math.tau) if major else 0
                           for major in range(16) for minor in range(16)))
    put('DEG1024', b''.join(struct.pack('<H', round(d * 1024 / 360) % 1024) for d in range(360)))
    game = wolfsim.Game.__new__(wolfsim.Game)
    game.radtoint = radtoint
    game.set_view(LOGIC_WIDTH)
    put('RAYANGLE', b''.join(struct.pack('<h', game.pixelangle[c]*8) for c in LOGIC_RAYS))
    ids = sprite_ids()
    from build_world import PICKUPS
    info = [(ids[pic], PICKUPS[kind]) for pic, kind in statics()]
    put('STATINFO', b''.join(struct.pack('<2H', s, i) for s, i in info))
    put('ATTACKINFO', b''.join(struct.pack('<3h', *row) for weapon in wolfsim.ATTACKINFO for row in weapon))
    focal = wolfsim.FOCALLENGTH
    put('FOCALCOS', b''.join(struct.pack('<i', wolfsim.fixed_by_frac(focal, sintable[a + 90])) for a in range(360)))
    put('FOCALSIN', b''.join(struct.pack('<i', wolfsim.fixed_by_frac(focal, sintable[a])) for a in range(360)))
    return image, address, game


def level_image(level_index, base):
    image = bytearray(base)
    level = maps()[level_index]
    map0, map1 = level['planes'][0], level['planes'][1]
    raw0 = native_plane_bytes(map0, floor=level_index, plane=0, extended_info=REGISTERED)
    raw1 = native_plane_bytes(map1, floor=level_index, plane=1, extended_info=REGISTERED)
    (ROOT / 'build/levels' / str(level_index) / 'source-planes.bin').write_bytes(raw0 + raw1)
    old = (ROOT / 'build/levels' / str(level_index) / 'world.bin').read_bytes()
    start = LAYOUT['LEVELBLOCK']
    block = old[start:start + 0x900]
    image[start:start + len(block)] = block
    tilemap=bytearray(map0[y*64+x] if map0[y*64+x]<106 else 0
                      for x in range(64) for y in range(64))
    door=0
    for y in range(64):
        for x in range(64):
            tile=map0[y*64+x]
            if 90<=tile<=101:
                tilemap[x*64+y]=128+door;door+=1
                step=1 if tile%2==0 else 64
                tilemap[x*64+y-step]|=64
                tilemap[x*64+y+step]|=64
    packed,_,_=encode_regions(tilemap,allow_partial=True)
    image[LAYOUT['ROOMRECTS']:]=packed
    assert len(image) == 0x10000
    return image


def include(address, game):
    from logic_sound_timing import face_sound
    lines = ['#define WOLF_REGISTERED %d' % REGISTERED,
             'RAW0_ADDRESS .equ 0x%06x' % RAW_PLANES_ADDRESS,
             'RAW1_ADDRESS .equ 0x%06x' % (RAW_PLANES_ADDRESS + 4096)]
    if PROFILE.spear:
        lines += ['#define WOLF_SPEAR 1', 'SPEAR_STATIC_COUNT .equ '+str(len(statics()))]
    lines += ['%s .equ 0x%04x' % (k, v) for k, v in LAYOUT.items()]
    import native_actors
    lines += native_actors.include().splitlines()
    lines += ['%s .equ %d' % (k, v) for k, v in FIELDS.items()]
    lines += ['%s .equ %d' % (k, v) for k, v in STATE_FIELDS.items()]
    lines += ['GATLINGTICS .equ %d' % face_sound()['ticks']]
    lines += ['OBJSIZE .equ %d' % OBJSIZE, 'STATESIZE .equ %d' % STATESIZE,
              'MAXACTORS .equ %d' % MAXACTORS, 'MAXSTATS .equ %d' % MAXSTATS,
              'LOGICRAYS .equ %d' % len(LOGIC_RAYS),
              'LOGIC_CENTERX .equ %d' % game.centerx, 'LOGIC_SHOOTDELTA .equ %d' % game.shootdelta,
              'LOGIC_SCALE .equ %d' % game.scale,
              'RAYANGLE_LEFT .equ %d' % game.pixelangle[0], 'RAYANGLE_RIGHT .equ %d' % game.pixelangle[-1]]
    for i, name in enumerate(VARS):
        lines.append('V_%s .equ 0x%04x' % (name, LAYOUT['VARS'] + 2 * i))
    lines.append('V_buttonstate .equ 0x%04x' % (LAYOUT['VARS'] + BUTTONS))
    lines.append('V_weaponchoice .equ 0x%04x' % (LAYOUT['VARS'] + BUTTONS + 8))
    lines.append('V_buttonheld .equ 0x%04x' % (LAYOUT['VARS'] + BUTTONS + 16))
    assert 2 * len(VARS) <= BUTTONS
    for name, value in address.items():
        lines.append('%s .equ 0x%04x' % (name, value))
    for i, name in enumerate(THINKS):
        lines.append('TH_%s .equ %d' % (name, 2 * i))
    for i, name in enumerate(ACTIONS):
        lines.append('AC_%s .equ %d' % (name, 2 * i))
    return '\n'.join(lines) + '\n'


def sounds():
    from wolf_source import sound_ids
    return ''.join('%s .equ %d\n' % item for item in sound_ids(spear=PROFILE.spear).items())


def main():
    base, address, game = tables_blob()
    for level in range(PROFILE.floors):
        image = level_image(level, base)
        (ROOT / 'build/levels' / str(level) / 'logic.bin').write_bytes(image)
    selected = config()['floor'] - 1
    (OUT / 'logic.bin').write_bytes((ROOT / 'build/levels' / str(selected) / 'logic.bin').read_bytes())
    (OUT / 'source-planes.bin').write_bytes((ROOT / 'build/levels' / str(selected) / 'source-planes.bin').read_bytes())
    (GEN / 'logic.inc').write_text(include(address, game))
    (GEN / 'logic_sounds.inc').write_text(sounds())
    from logic_sound_timing import gate_assembly
    (GEN / 'logic_sound_gate.inc').write_text(gate_assembly())
    (OUT / 'logic.json').write_text(json.dumps(dict(layout=LAYOUT, fields=FIELDS, vars=VARS,
                                                    buttons=BUTTONS, states=address, objsize=OBJSIZE,
                                                    statesize=STATESIZE, rays=LOGIC_RAYS,
                                                    width=LOGIC_WIDTH, floor=selected)) + '\n')
    print('logic bank: tables, states', len(address), 'rays', len(LOGIC_RAYS))


if __name__ == '__main__':
    main()
