"""Exact model of the original game logic for demo playback checks.

Follows WOLFSRC v1.4: WL_PLAY (PlayLoop, DoActor, PollControls), WL_AGENT,
WL_ACT1, WL_ACT2 (E1 actors), WL_STATE, WL_GAME (SetupGameLevel), WL_MAIN
(BuildTables, CalcProjection) and the visibility parts of WL_DRAW and
WL_DR_A. C int is 16 bits, long 32 bits; division truncates toward zero.
Spotvis comes from the original ray caster at a chosen view width.
"""
import argparse
import json
import math
import struct
from wolfdata import maps, graphics
from wolf_source import random_table, statics, states, sprite_ids


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    v &= 0xffffffff
    return v - 0x100000000 if v & 0x80000000 else v


def cdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


PI = 3.141592657
TILEGLOBAL = 0x10000
MINDIST = 0x5800
MINACTORDIST = 0x10000
MINSIGHT = 0x18000
FOCALLENGTH = 0x5700
AREATILE = 107
AMBUSHTILE = 106
ELEVATORTILE = 21
ALTELEVATORTILE = 107
PUSHABLETILE = 98
EXITTILE = 99
ICONARROWS = 90
ANGLES = 360
FINEANGLES = 3600
SPDPATROL = 512
SPDDOG = 1500
RUNSPEED = 6000
OPENTICS = 300
DEMOTICS = 4

(EAST, NORTHEAST, NORTH, NORTHWEST, WEST, SOUTHWEST, SOUTH, SOUTHEAST, NODIR) = range(9)
OPPOSITE = [WEST, SOUTHWEST, SOUTH, SOUTHEAST, EAST, NORTHEAST, NORTH, NORTHWEST, NODIR]
DIAGONAL = [[NODIR] * 9 for _ in range(9)]
DIAGONAL[EAST][NORTH] = NORTHEAST; DIAGONAL[EAST][SOUTH] = SOUTHEAST
DIAGONAL[NORTH][EAST] = NORTHEAST; DIAGONAL[NORTH][WEST] = NORTHWEST
DIAGONAL[WEST][NORTH] = NORTHWEST; DIAGONAL[WEST][SOUTH] = SOUTHWEST
DIAGONAL[SOUTH][EAST] = SOUTHEAST; DIAGONAL[SOUTH][WEST] = SOUTHWEST

FL_SHOOTABLE, FL_BONUS, FL_NEVERMARK, FL_VISABLE = 1, 2, 4, 8
FL_ATTACKMODE, FL_FIRSTATTACK, FL_AMBUSH, FL_NONMARK = 16, 32, 64, 128

(NOTHING, PLAYEROBJ, INERTOBJ, GUARDOBJ, OFFICEROBJ, SSOBJ, DOGOBJ, BOSSOBJ) = range(8)
EN_GUARD, EN_OFFICER, EN_SS, EN_DOG, EN_BOSS = 0, 1, 2, 3, 4
DR_OPEN, DR_CLOSED, DR_OPENING, DR_CLOSING = range(4)
BT_ATTACK, BT_STRAFE, BT_RUN, BT_USE = 0, 1, 2, 3
WP_KNIFE, WP_PISTOL, WP_MACHINEGUN, WP_CHAINGUN = range(4)
EX_STILLPLAYING, EX_COMPLETED, EX_DIED, EX_SECRETLEVEL = 0, 1, 2, 9

ITEMS = ('dressing', 'block', 'bo_gibs', 'bo_alpo', 'bo_firstaid', 'bo_key1', 'bo_key2', 'bo_key3',
         'bo_key4', 'bo_cross', 'bo_chalice', 'bo_bible', 'bo_crown', 'bo_clip', 'bo_clip2',
         'bo_machinegun', 'bo_chaingun', 'bo_food', 'bo_fullheal', 'bo_25clip', 'bo_spear')
ITEM = {name: n for n, name in enumerate(ITEMS)}

ATTACKINFO = [
    [(6, 0, 1), (6, 2, 2), (6, 0, 3), (6, -1, 4)],
    [(6, 0, 1), (6, 1, 2), (6, 0, 3), (6, -1, 4)],
    [(6, 0, 1), (6, 1, 2), (6, 3, 3), (6, -1, 4)],
    [(6, 0, 1), (6, 1, 2), (6, 4, 3), (6, -1, 4)],
]
# starthitpoints[difficulty][guard, officer, ss, dog, hans]
STARTHP = [[25, 50, 100, 1, 850], [25, 50, 100, 1, 950], [25, 50, 100, 1, 1050], [25, 50, 100, 1, 1200]]


class SimError(Exception):
    pass


class State:
    __slots__ = ('name', 'rotate', 'shapenum', 'tictime', 'think', 'action', 'next')


class Obj:
    __slots__ = ('index', 'active', 'ticcount', 'obclass', 'state', 'flags', 'distance', 'dir',
                 'x', 'y', 'tilex', 'tiley', 'areanumber', 'viewx', 'viewheight', 'transx',
                 'transy', 'angle', 'hitpoints', 'speed', 'temp1', 'temp2', 'temp3', 'next', 'prev')

    def __init__(self, index):
        self.index = index
        self.clear()

    def clear(self):
        for f in self.__slots__[1:]:
            setattr(self, f, 0)
        self.state = None
        self.next = self.prev = None


def build_tables():
    radtoint = f32(f32(3600.0) / 2 / PI)
    finetangent = [0] * (FINEANGLES // 4)
    for i in range(FINEANGLES // 8):
        tang = math.tan((i + 0.5) / radtoint)
        finetangent[i] = int(tang * TILEGLOBAL)
        finetangent[FINEANGLES // 4 - 1 - i] = int(1 / tang * TILEGLOBAL)
    sintable = [0] * (ANGLES + ANGLES // 4 + 1)  # the source loop writes one entry past its table
    angle = 0.0
    anglestep = f32(PI / 2 / (ANGLES // 4))
    for i in range(ANGLES // 4 + 1):
        value = int(TILEGLOBAL * math.sin(angle))
        sintable[i] = sintable[i + ANGLES] = sintable[ANGLES // 2 - i] = value
        sintable[ANGLES - i] = sintable[ANGLES // 2 + i] = value | 0x80000000
        angle = f32(angle + anglestep)
    return radtoint, finetangent, sintable


def fixed_by_frac(a, b):
    neg = bool((b >> 16) & 0x8000)
    a &= 0xffffffff
    if a & 0x80000000:
        a = (-a) & 0xffffffff
        neg = not neg
    frac = b & 0xffff
    result = (((a & 0xffff) * frac) >> 16) + (a >> 16) * frac
    result &= 0xffffffff
    if neg:
        result = (-result) & 0xffffffff
    return s32(result)


def partial_by_step(step, partial):
    """xpartialbyystep: signed long by unsigned word, truncated toward zero."""
    if step < 0:
        return -((-step * partial) >> 16)
    return (step * partial) >> 16


class Game:
    def __init__(self, mapon, difficulty=3, viewwidth=240, trace=None):
        self.radtoint, self.finetangent, self.sintable = build_tables()
        self.rndtable = random_table()
        self.rndindex = 0
        self.statinfo = [(sprite_ids()[pic], ITEM[kind]) for pic, kind in statics()]
        self.make_states()
        self.set_view(viewwidth)
        self.trace = trace
        self.new_game(difficulty, mapon)
        self.setup_level()

    # ------------------------------------------------------------ tables
    def make_states(self):
        rows = states("grd|dog|ss|boss|ofc")
        self.states = {}
        for name, (rotate, shape, tics, think, action, nxt) in rows:
            s = State()
            s.name, s.rotate, s.shapenum, s.tictime = name, rotate, shape, tics
            s.think = None if think == 'NULL' else think
            s.action = None if action == 'NULL' else action
            s.next = nxt
            self.states[name] = s
        for s in self.states.values():
            s.next = self.states[s.next] if s.next else None
        self.s_player = State()
        self.s_player.name, self.s_player.rotate, self.s_player.shapenum = 's_player', 0, 0
        self.s_player.tictime, self.s_player.think, self.s_player.action, self.s_player.next = 0, 'T_Player', None, None
        self.s_attack = State()
        self.s_attack.name, self.s_attack.rotate, self.s_attack.shapenum = 's_attack', 0, 0
        self.s_attack.tictime, self.s_attack.think, self.s_attack.action, self.s_attack.next = 0, 'T_Attack', None, None

    def set_view(self, width):
        self.viewwidth = width & ~15
        self.centerx = self.viewwidth // 2 - 1
        self.shootdelta = self.viewwidth // 10
        facedist = float(FOCALLENGTH + MINDIST)
        halfview = self.viewwidth // 2
        self.scale = int(halfview * facedist / (0x10000 // 2))
        self.heightnumerator = (TILEGLOBAL * self.scale) >> 6
        self.pixelangle = [0] * self.viewwidth
        for i in range(halfview):
            tang = ((i * 0x10000) // self.viewwidth) / facedist
            angle = f32(math.atan(tang))
            intang = int(angle * self.radtoint)
            self.pixelangle[halfview - 1 - i] = intang
            self.pixelangle[halfview + i] = -intang
        self.focallength = FOCALLENGTH
        self.ray_columns = list(range(self.viewwidth))
        self.vis_model = 'rays'
        self.aim_neighbors = True

    def rnd(self):
        self.rndindex = (self.rndindex + 1) & 0xff
        return self.rndtable[self.rndindex]

    # ------------------------------------------------------------ setup
    def new_game(self, difficulty, mapon):
        self.difficulty = difficulty
        self.mapon = mapon
        self.score = 0
        self.nextextra = 40000
        self.lives = 3
        self.health = 100
        self.ammo = 8
        self.keys = 0
        self.weapon = self.bestweapon = self.chosenweapon = WP_PISTOL
        self.faceframe = 0
        self.attackframe = self.attackcount = self.weaponframe = 0
        self.secretcount = self.treasurecount = self.killcount = 0
        self.secrettotal = self.treasuretotal = self.killtotal = 0
        self.victoryflag = False
        self.playstate = EX_STILLPLAYING

    def setup_level(self):
        self.pwallstate = self.pwallpos = self.pwallx = self.pwally = self.pwalldir = 0
        self.anglefrac = 0
        self.facecount = 0
        self.thrustspeed = 0
        self.madenoise = False
        self.buttonstate = [False] * 8
        self.buttonheld = [False] * 8
        self.controlx = self.controly = 0
        self.tics = DEMOTICS
        self.gotgatgun = 0
        self.gatling = 0
        from logic_sound_timing import face_sound
        self.gatling_ticks = face_sound()['ticks']
        self.damagecount = self.bonuscount = 0
        self.spotvis = bytearray(4096)
        self.frame = 0
        self.killerobj = None
        self.lastattacker = None
        level = maps()[self.mapon]
        self.map0 = list(level['planes'][0])
        self.map1 = list(level['planes'][1])
        self.rndindex = 0
        self.tilemap = bytearray(4096)
        self.actorat = [0] * 4096
        for y in range(64):
            for x in range(64):
                tile = self.map0[y * 64 + x]
                if tile < AREATILE:
                    self.tilemap[x * 64 + y] = tile & 0xff
                    self.actorat[x * 64 + y] = tile
        self.init_actor_list()
        self.doors = []
        self.doorposition = [0] * 64
        self.areaconnect = [[0] * 37 for _ in range(37)]
        self.areabyplayer = [False] * 37
        self.statobjs = []
        for y in range(64):
            for x in range(64):
                tile = self.map0[y * 64 + x]
                if 90 <= tile <= 101:
                    if tile % 2 == 0:
                        self.spawn_door(x, y, True, (tile - 90) // 2)
                    else:
                        self.spawn_door(x, y, False, (tile - 91) // 2)
        self.scan_info_plane()
        for y in range(64):
            for x in range(64):
                i = y * 64 + x
                if self.map0[i] == AMBUSHTILE:
                    self.tilemap[x * 64 + y] = 0
                    if self.actorat[x * 64 + y] == AMBUSHTILE:
                        self.actorat[x * 64 + y] = 0
                    tile = AMBUSHTILE
                    if self.map0[i + 1] >= AREATILE:
                        tile = self.map0[i + 1]
                    if self.map0[i - 64] >= AREATILE:
                        tile = self.map0[i - 64]
                    if self.map0[i + 64] >= AREATILE:
                        tile = self.map0[i + 64]
                    if self.map0[i - 1] >= AREATILE:
                        tile = self.map0[i - 1]
                    self.map0[i] = tile

    def init_actor_list(self):
        self.objlist = [Obj(i) for i in range(150)]
        for i in range(150):
            self.objlist[i].prev = self.objlist[i + 1] if i < 149 else None
            self.objlist[i].next = None
        self.objfreelist = self.objlist[0]
        self.lastobj = None
        self.get_new_actor()
        self.player = self.new

    def get_new_actor(self):
        if self.objfreelist is None:
            raise SimError('GetNewActor: No free spots in objlist')
        new = self.objfreelist
        self.objfreelist = new.prev
        new.clear()
        if self.lastobj is not None:
            self.lastobj.next = new
        new.prev = self.lastobj
        new.active = 0
        self.lastobj = new
        self.new = new

    def remove_obj(self, gone):
        if gone is self.player:
            raise SimError('RemoveObj: Tried to remove the player')
        gone.state = None
        if gone is self.lastobj:
            self.lastobj = gone.prev
        else:
            gone.next.prev = gone.prev
        gone.prev.next = gone.next
        gone.prev = self.objfreelist
        self.objfreelist = gone

    def spawn_door(self, x, y, vertical, lock):
        n = len(self.doors)
        if n == 64:
            raise SimError('64+ doors on level')
        self.doorposition[n] = 0
        self.doors.append(dict(tilex=x, tiley=y, vertical=vertical, lock=lock, action=DR_CLOSED, ticcount=0))
        self.actorat[x * 64 + y] = n | 0x80
        self.tilemap[x * 64 + y] = n | 0x80
        i = y * 64 + x
        if vertical:
            self.map0[i] = self.map0[i - 1]
            self.tilemap[x * 64 + y - 1] |= 0x40
            self.tilemap[x * 64 + y + 1] |= 0x40
        else:
            self.map0[i] = self.map0[i - 64]
            self.tilemap[(x - 1) * 64 + y] |= 0x40
            self.tilemap[(x + 1) * 64 + y] |= 0x40

    def scan_info_plane(self):
        hard, medium = self.difficulty >= 3, self.difficulty >= 2
        for y in range(64):
            for x in range(64):
                tile = self.map1[y * 64 + x]
                if not tile:
                    continue
                if 19 <= tile <= 22:
                    self.spawn_player(x, y, tile - 19)
                elif 23 <= tile <= 74:
                    self.spawn_static(x, y, tile - 23)
                elif tile == 98:
                    self.secrettotal += 1
                elif tile == 124:
                    self.spawn_dead_guard(x, y)
                elif tile == 214:
                    self.spawn_boss(x, y)
                else:
                    for base, which, patrol in ((108, EN_GUARD, False), (112, EN_GUARD, True),
                                                (116, EN_OFFICER, False), (120, EN_OFFICER, True),
                                                (126, EN_SS, False), (130, EN_SS, True),
                                                (134, EN_DOG, False), (138, EN_DOG, True)):
                        for shift, allowed in ((72, hard), (36, medium), (0, True)):
                            if base + shift <= tile < base + shift + 4:
                                if allowed:
                                    if patrol:
                                        self.spawn_patrol(which, x, y, tile - shift - base)
                                    else:
                                        self.spawn_stand(which, x, y, tile - shift - base)
                                break
                    else:
                        continue

    def spawn_player(self, tilex, tiley, direction):
        p = self.player
        p.obclass = PLAYEROBJ
        p.active = 1
        p.tilex, p.tiley = tilex, tiley
        p.areanumber = self.map0[tiley * 64 + tilex] & 0xff
        p.x = (tilex << 16) + TILEGLOBAL // 2
        p.y = (tiley << 16) + TILEGLOBAL // 2
        p.state = self.s_player
        p.angle = (1 - direction) * 90
        if p.angle < 0:
            p.angle += ANGLES
        p.flags = FL_NEVERMARK
        self.thrust(0, 0)
        self.areabyplayer = [False] * 37
        self.areabyplayer[p.areanumber] = True

    def spawn_static(self, tilex, tiley, kind):
        shape, item = self.statinfo[kind]
        st = dict(tilex=tilex, tiley=tiley, shapenum=shape, flags=0, itemnumber=0)
        if item == ITEM['block']:
            self.actorat[tilex * 64 + tiley] = 1
        elif item != ITEM['dressing']:
            if item in (ITEM['bo_cross'], ITEM['bo_chalice'], ITEM['bo_bible'], ITEM['bo_crown'], ITEM['bo_fullheal']):
                self.treasuretotal += 1
            st['flags'] = FL_BONUS
            st['itemnumber'] = item
        self.statobjs.append(st)
        if len(self.statobjs) == 400:
            raise SimError('Too many static objects')

    def place_item_type(self, itemtype, tilex, tiley):
        for kind, (shape, item) in enumerate(self.statinfo):
            if item == itemtype:
                break
        else:
            raise SimError("PlaceItemType: couldn't find type")
        for spot in self.statobjs:
            if spot['shapenum'] == -1:
                break
        else:
            if len(self.statobjs) == 400:
                return
            spot = dict()
            self.statobjs.append(spot)
        spot.update(shapenum=shape, tilex=tilex, tiley=tiley, flags=FL_BONUS, itemnumber=item)

    def spawn_new_obj(self, tilex, tiley, state):
        self.get_new_actor()
        new = self.new
        new.state = state
        new.ticcount = self.rnd() % state.tictime if state.tictime else 0
        new.tilex, new.tiley = tilex, tiley
        new.x = (tilex << 16) + TILEGLOBAL // 2
        new.y = (tiley << 16) + TILEGLOBAL // 2
        new.dir = NODIR
        self.actorat[tilex * 64 + tiley] = new
        new.areanumber = (self.map0[tiley * 64 + tilex] - AREATILE) & 0xff

    def spawn_stand(self, which, tilex, tiley, direction):
        names = {EN_OFFICER: 's_ofcstand', EN_GUARD: 's_grdstand', EN_SS: 's_ssstand'}
        if which not in names:
            raise SimError('SpawnStand without a spawn for enemy %d' % which)
        self.spawn_new_obj(tilex, tiley, self.states[names[which]])
        new = self.new
        new.speed = SPDPATROL
        self.killtotal += 1
        i = tiley * 64 + tilex
        if self.map0[i] == AMBUSHTILE:
            self.tilemap[tilex * 64 + tiley] = 0
            tile = None
            if self.map0[i + 1] >= AREATILE:
                tile = self.map0[i + 1]
            if self.map0[i - 64] >= AREATILE:
                tile = self.map0[i - 64]
            if self.map0[i + 64] >= AREATILE:
                tile = self.map0[i + 64]
            if self.map0[i - 1] >= AREATILE:
                tile = self.map0[i - 1]
            if tile is None:
                raise SimError('ambush tile without an area neighbor')
            self.map0[i] = tile
            new.areanumber = (tile - AREATILE) & 0xff
            new.flags |= FL_AMBUSH
        new.obclass = GUARDOBJ + which
        new.hitpoints = STARTHP[self.difficulty][which]
        new.dir = direction * 2
        new.flags |= FL_SHOOTABLE

    def spawn_dead_guard(self, tilex, tiley):
        self.spawn_new_obj(tilex, tiley, self.states['s_grddie4'])
        self.new.obclass = INERTOBJ

    def spawn_boss(self, tilex, tiley):
        self.spawn_new_obj(tilex, tiley, self.states['s_bossstand'])
        new = self.new
        new.speed = SPDPATROL
        new.obclass = BOSSOBJ
        new.hitpoints = STARTHP[self.difficulty][EN_BOSS]
        new.dir = SOUTH
        new.flags |= FL_SHOOTABLE | FL_AMBUSH
        self.killtotal += 1

    def spawn_patrol(self, which, tilex, tiley, direction):
        names = {EN_OFFICER: 's_ofcpath1', EN_GUARD: 's_grdpath1', EN_SS: 's_sspath1', EN_DOG: 's_dogpath1'}
        if which not in names:
            raise SimError('SpawnPatrol without a spawn for enemy %d' % which)
        self.spawn_new_obj(tilex, tiley, self.states[names[which]])
        new = self.new
        new.speed = SPDDOG if which == EN_DOG else SPDPATROL
        self.killtotal += 1
        new.obclass = GUARDOBJ + which
        new.dir = direction * 2
        new.hitpoints = STARTHP[self.difficulty][which]
        new.distance = TILEGLOBAL
        new.flags |= FL_SHOOTABLE
        new.active = 1
        self.actorat[new.tilex * 64 + new.tiley] = 0
        if direction == 0:
            new.tilex += 1
        elif direction == 1:
            new.tiley -= 1
        elif direction == 2:
            new.tilex -= 1
        elif direction == 3:
            new.tiley += 1
        self.actorat[new.tilex * 64 + new.tiley] = new

    # ------------------------------------------------------------ helpers
    def actor_at(self, x, y):
        return self.actorat[x * 64 + y]

    @staticmethod
    def as_unsigned(check):
        if isinstance(check, Obj):
            return 0x1000 + check.index * 64
        return check & 0xffff

    def new_state(self, ob, name):
        ob.state = self.states[name] if isinstance(name, str) else name
        ob.ticcount = ob.state.tictime

    # ------------------------------------------------------------ player
    def thrust(self, angle, speed):
        self.thrustspeed += speed
        if speed >= MINDIST * 2:
            speed = MINDIST * 2 - 1
        xmove = fixed_by_frac(speed, self.sintable[angle + ANGLES // 4])
        ymove = -fixed_by_frac(speed, self.sintable[angle])
        p = self.player
        self.clip_move(p, xmove, ymove)
        p.tilex = p.x >> 16
        p.tiley = p.y >> 16
        offset = p.tiley * 64 + p.tilex
        p.areanumber = (self.map0[offset] - AREATILE) & 0xff
        if self.map1[offset] == EXITTILE:
            self.victory_tile()

    def victory_tile(self):
        raise SimError('VictoryTile reached; BJ victory actor is not modeled')

    def try_move(self, ob):
        xl = (ob.x - MINDIST) >> 16
        yl = (ob.y - MINDIST) >> 16
        xh = (ob.x + MINDIST) >> 16
        yh = (ob.y + MINDIST) >> 16
        for y in range(yl, yh + 1):
            for x in range(xl, xh + 1):
                check = self.actor_at(x, y)
                if check and not isinstance(check, Obj):
                    return False
        if yl > 0:
            yl -= 1
        if yh < 63:
            yh += 1
        if xl > 0:
            xl -= 1
        if xh < 63:
            xh += 1
        for y in range(yl, yh + 1):
            for x in range(xl, xh + 1):
                check = self.actor_at(x, y)
                if isinstance(check, Obj) and check is not self.player and check.flags & FL_SHOOTABLE:
                    deltax = ob.x - check.x
                    if deltax < -MINACTORDIST or deltax > MINACTORDIST:
                        continue
                    deltay = ob.y - check.y
                    if deltay < -MINACTORDIST or deltay > MINACTORDIST:
                        continue
                    return False
        return True

    def clip_move(self, ob, xmove, ymove):
        basex, basey = ob.x, ob.y
        ob.x = s32(basex + xmove)
        ob.y = s32(basey + ymove)
        if self.try_move(ob):
            return
        ob.x = s32(basex + xmove)
        ob.y = basey
        if self.try_move(ob):
            return
        ob.x = basex
        ob.y = s32(basey + ymove)
        if self.try_move(ob):
            return
        ob.x, ob.y = basex, basey

    def control_movement(self, ob):
        self.thrustspeed = 0
        if self.buttonstate[BT_STRAFE]:
            if self.controlx > 0:
                angle = ob.angle - ANGLES // 4
                if angle < 0:
                    angle += ANGLES
                self.thrust(angle, self.controlx * 150)
            elif self.controlx < 0:
                angle = ob.angle + ANGLES // 4
                if angle >= ANGLES:
                    angle -= ANGLES
                self.thrust(angle, -self.controlx * 150)
        else:
            self.anglefrac = s16(self.anglefrac + self.controlx)
            angleunits = cdiv(self.anglefrac, 20)
            self.anglefrac = s16(self.anglefrac - angleunits * 20)
            ob.angle = s16(ob.angle - angleunits)
            if ob.angle >= ANGLES:
                ob.angle -= ANGLES
            if ob.angle < 0:
                ob.angle += ANGLES
        if self.controly < 0:
            self.thrust(ob.angle, -self.controly * 150)
        elif self.controly > 0:
            angle = ob.angle + ANGLES // 2
            if angle >= ANGLES:
                angle -= ANGLES
            self.thrust(angle, self.controly * 100)

    def update_face(self):
        if self.gatling > 0:
            return
        self.facecount = s16(self.facecount + self.tics)
        if self.facecount > self.rnd():
            self.faceframe = self.rnd() >> 6
            if self.faceframe == 3:
                self.faceframe = 1
            self.facecount = 0

    def check_weapon_change(self):
        if not self.ammo:
            return
        for i in range(WP_KNIFE, self.bestweapon + 1):
            if self.buttonstate[4 + i]:
                self.weapon = self.chosenweapon = i
                return

    def cmd_fire(self):
        self.buttonheld[BT_ATTACK] = True
        self.weaponframe = 0
        self.player.state = self.s_attack
        self.attackframe = 0
        self.attackcount = ATTACKINFO[self.weapon][0][0]
        self.weaponframe = ATTACKINFO[self.weapon][0][2]

    def cmd_use(self):
        p = self.player
        if p.angle < ANGLES // 8 or p.angle > 7 * ANGLES // 8:
            checkx, checky, direction, elevatorok = p.tilex + 1, p.tiley, 1, True
        elif p.angle < 3 * ANGLES // 8:
            checkx, checky, direction, elevatorok = p.tilex, p.tiley - 1, 0, False
        elif p.angle < 5 * ANGLES // 8:
            checkx, checky, direction, elevatorok = p.tilex - 1, p.tiley, 3, True
        else:
            checkx, checky, direction, elevatorok = p.tilex, p.tiley + 1, 2, False
        doornum = self.tilemap[checkx * 64 + checky]
        if self.map1[checky * 64 + checkx] == PUSHABLETILE:
            self.push_wall(checkx, checky, direction)
            return
        if not self.buttonheld[BT_USE] and doornum == ELEVATORTILE and elevatorok:
            self.buttonheld[BT_USE] = True
            self.tilemap[checkx * 64 + checky] += 1
            if self.map0[p.tiley * 64 + p.tilex] == ALTELEVATORTILE:
                self.playstate = EX_SECRETLEVEL
            else:
                self.playstate = EX_COMPLETED
        elif not self.buttonheld[BT_USE] and doornum & 0x80:
            self.buttonheld[BT_USE] = True
            self.operate_door(doornum & ~0x80)

    def take_damage(self, points, attacker):
        self.lastattacker = attacker
        if self.victoryflag:
            return
        if self.difficulty == 0:
            points >>= 2
        self.health -= points
        if self.health <= 0:
            self.health = 0
            self.playstate = EX_DIED
            self.killerobj = attacker
            self.gatling = 0  # PLAYERDEATHSND replaces the source AdLib sound.
        self.damagecount += points
        self.gotgatgun = 0

    def heal_self(self, points):
        self.health = min(100, self.health + points)
        self.gotgatgun = 0

    def give_extra_man(self):
        if self.lives < 9:
            self.lives += 1

    def give_points(self, points):
        self.score += points
        while self.score >= self.nextextra:
            self.nextextra += 40000
            self.give_extra_man()

    def give_ammo(self, ammo):
        if not self.ammo and not self.attackframe:
            self.weapon = self.chosenweapon
        self.ammo = min(99, self.ammo + ammo)

    def give_weapon(self, weapon):
        self.give_ammo(6)
        if self.bestweapon < weapon:
            self.bestweapon = self.weapon = self.chosenweapon = weapon

    def get_bonus(self, check):
        item = check['itemnumber']
        if item == ITEM['bo_firstaid']:
            if self.health == 100:
                return
            self.heal_self(25)
        elif item in (ITEM['bo_key1'], ITEM['bo_key2'], ITEM['bo_key3'], ITEM['bo_key4']):
            self.keys |= 1 << (item - ITEM['bo_key1'])
            self.gatling = 0  # GETKEYSND preempts the source AdLib pickup.
        elif item == ITEM['bo_cross']:
            self.give_points(100); self.treasurecount += 1
        elif item == ITEM['bo_chalice']:
            self.give_points(500); self.treasurecount += 1
        elif item == ITEM['bo_bible']:
            self.give_points(1000); self.treasurecount += 1
        elif item == ITEM['bo_crown']:
            self.give_points(5000); self.treasurecount += 1
        elif item == ITEM['bo_clip']:
            if self.ammo == 99:
                return
            self.give_ammo(8)
        elif item == ITEM['bo_clip2']:
            if self.ammo == 99:
                return
            self.give_ammo(4)
        elif item == ITEM['bo_machinegun']:
            self.give_weapon(WP_MACHINEGUN)
        elif item == ITEM['bo_chaingun']:
            self.give_weapon(WP_CHAINGUN)
            self.facecount = 0
            self.gotgatgun = 1
            self.gatling = self.gatling_ticks
        elif item == ITEM['bo_fullheal']:
            self.heal_self(99); self.give_ammo(25); self.give_extra_man(); self.treasurecount += 1
        elif item == ITEM['bo_food']:
            if self.health == 100:
                return
            self.heal_self(10)
        elif item == ITEM['bo_alpo']:
            if self.health == 100:
                return
            self.heal_self(4)
        elif item == ITEM['bo_gibs']:
            if self.health > 10:
                return
            self.heal_self(1)
        self.bonuscount = 18
        check['shapenum'] = -1
        self.log('bonus', item=ITEMS[item], tile=(check['tilex'], check['tiley']))

    def knife_attack(self, ob):
        dist, closest = 0x7fffffff, None
        check = ob.next
        while check is not None:
            if check.flags & FL_SHOOTABLE and check.flags & FL_VISABLE and abs(check.viewx - self.centerx) < self.shootdelta:
                if check.transx < dist:
                    dist, closest = check.transx, check
            check = check.next
        if closest is None or dist > 0x18000:
            return
        self.damage_actor(closest, self.rnd() >> 4)

    def gun_attack(self, ob):
        self.madenoise = True
        viewdist, closest = 0x7fffffff, None
        while True:
            oldclosest = closest
            check = ob.next
            while check is not None:
                if check.flags & FL_SHOOTABLE and check.flags & FL_VISABLE and abs(check.viewx - self.centerx) < self.shootdelta:
                    if check.transx < viewdist:
                        viewdist, closest = check.transx, check
                check = check.next
            if closest is oldclosest:
                return
            if self.check_line(closest):
                break
        p = self.player
        dx = abs(closest.tilex - p.tilex)
        dy = abs(closest.tiley - p.tiley)
        dist = max(dx, dy)
        if dist < 2:
            damage = self.rnd() // 4
        elif dist < 4:
            damage = self.rnd() // 6
        else:
            if self.rnd() // 12 < dist:
                return
            damage = self.rnd() // 6
        self.damage_actor(closest, damage)

    def T_Attack(self, ob):
        self.update_face()
        if self.victoryflag:
            raise SimError('victory spin is not modeled')
        if self.buttonstate[BT_USE] and not self.buttonheld[BT_USE]:
            self.buttonstate[BT_USE] = False
        if self.buttonstate[BT_ATTACK] and not self.buttonheld[BT_ATTACK]:
            self.buttonstate[BT_ATTACK] = False
        self.control_movement(ob)
        p = self.player
        self.plux = (p.x >> 8) & 0xffff
        self.pluy = (p.y >> 8) & 0xffff
        p.tilex = p.x >> 16
        p.tiley = p.y >> 16
        self.attackcount -= self.tics
        while self.attackcount <= 0:
            tics_, attack, frame = ATTACKINFO[self.weapon][self.attackframe]
            if attack == -1:
                ob.state = self.s_player
                if not self.ammo:
                    self.weapon = WP_KNIFE
                elif self.weapon != self.chosenweapon:
                    self.weapon = self.chosenweapon
                self.attackframe = self.weaponframe = 0
                return
            fire = False
            if attack == 4:
                if self.ammo:
                    if self.buttonstate[BT_ATTACK]:
                        self.attackframe -= 2
                    fire = True
            elif attack == 1:
                fire = True
            elif attack == 2:
                self.knife_attack(ob)
            elif attack == 3:
                if self.ammo and self.buttonstate[BT_ATTACK]:
                    self.attackframe -= 2
            if fire:
                if not self.ammo:
                    self.attackframe += 1
                else:
                    self.gun_attack(ob)
                    self.ammo -= 1
            self.attackcount += tics_
            self.attackframe += 1
            self.weaponframe = ATTACKINFO[self.weapon][self.attackframe][2]

    def T_Player(self, ob):
        if self.victoryflag:
            raise SimError('victory spin is not modeled')
        self.update_face()
        self.check_weapon_change()
        if self.buttonstate[BT_USE]:
            self.cmd_use()
        if self.buttonstate[BT_ATTACK] and not self.buttonheld[BT_ATTACK]:
            self.cmd_fire()
        self.control_movement(ob)
        p = self.player
        self.plux = (p.x >> 8) & 0xffff
        self.pluy = (p.y >> 8) & 0xffff
        p.tilex = p.x >> 16
        p.tiley = p.y >> 16

    # ------------------------------------------------------------ doors
    def open_door(self, door):
        d = self.doors[door]
        if d['action'] == DR_OPEN:
            d['ticcount'] = 0
        else:
            d['action'] = DR_OPENING

    def close_door(self, door):
        d = self.doors[door]
        tilex, tiley = d['tilex'], d['tiley']
        if self.actor_at(tilex, tiley):
            return
        p = self.player
        if p.tilex == tilex and p.tiley == tiley:
            return

        def obj_at(x, y):
            check = self.actor_at(x, y)
            if check and not isinstance(check, Obj):
                raise SimError('CloseDoor reads a wall or static as an actor')
            return check

        if d['vertical']:
            if p.tiley == tiley:
                if ((p.x + MINDIST) >> 16) == tilex:
                    return
                if ((p.x - MINDIST) >> 16) == tilex:
                    return
            check = obj_at(tilex - 1, tiley)
            if check and ((check.x + MINDIST) >> 16) == tilex:
                return
            check = obj_at(tilex + 1, tiley)
            if check and ((check.x - MINDIST) >> 16) == tilex:
                return
        else:
            if p.tilex == tilex:
                if ((p.y + MINDIST) >> 16) == tiley:
                    return
                if ((p.y - MINDIST) >> 16) == tiley:
                    return
            check = obj_at(tilex, tiley - 1)
            if check and ((check.y + MINDIST) >> 16) == tiley:
                return
            check = obj_at(tilex, tiley + 1)
            if check and ((check.y - MINDIST) >> 16) == tiley:
                return
        d['action'] = DR_CLOSING
        self.actorat[tilex * 64 + tiley] = door | 0x80

    def operate_door(self, door):
        lock = self.doors[door]['lock']
        if 1 <= lock <= 4 and not self.keys & (1 << (lock - 1)):
            return
        action = self.doors[door]['action']
        if action in (DR_CLOSED, DR_CLOSING):
            self.open_door(door)
        else:
            self.close_door(door)

    def door_areas(self, door):
        d = self.doors[door]
        i = d['tiley'] * 64 + d['tilex']
        if d['vertical']:
            area1, area2 = self.map0[i + 1], self.map0[i - 1]
        else:
            area1, area2 = self.map0[i - 64], self.map0[i + 64]
        return area1 - AREATILE, area2 - AREATILE

    def connect_areas(self):
        self.areabyplayer = [False] * 37
        start = self.player.areanumber
        self.areabyplayer[start] = True
        self.recursive_connect(start)

    def recursive_connect(self, area):
        for i in range(37):
            if self.areaconnect[area][i] and not self.areabyplayer[i]:
                self.areabyplayer[i] = True
                self.recursive_connect(i)

    def move_doors(self):
        if self.victoryflag:
            return
        for door, d in enumerate(self.doors):
            if d['action'] == DR_OPEN:
                d['ticcount'] = s16(d['ticcount'] + self.tics)
                if d['ticcount'] >= OPENTICS:
                    self.close_door(door)
            elif d['action'] == DR_OPENING:
                position = self.doorposition[door]
                if not position:
                    area1, area2 = self.door_areas(door)
                    self.areaconnect[area1][area2] += 1
                    self.areaconnect[area2][area1] += 1
                    self.connect_areas()
                position += self.tics << 10
                if position >= 0xffff:
                    position = 0xffff
                    d['ticcount'] = 0
                    d['action'] = DR_OPEN
                    self.actorat[d['tilex'] * 64 + d['tiley']] = 0
                self.doorposition[door] = position
            elif d['action'] == DR_CLOSING:
                tilex, tiley = d['tilex'], d['tiley']
                p = self.player
                if self.as_unsigned(self.actor_at(tilex, tiley)) != (door | 0x80) or (p.tilex == tilex and p.tiley == tiley):
                    self.open_door(door)
                    continue
                position = self.doorposition[door] - (self.tics << 10)
                if position <= 0:
                    position = 0
                    d['action'] = DR_CLOSED
                    area1, area2 = self.door_areas(door)
                    self.areaconnect[area1][area2] -= 1
                    self.areaconnect[area2][area1] -= 1
                    self.connect_areas()
                self.doorposition[door] = position

    # ------------------------------------------------------------ push walls
    def push_wall(self, checkx, checky, direction):
        if self.pwallstate:
            return
        oldtile = self.tilemap[checkx * 64 + checky]
        if not oldtile:
            return
        dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[direction]
        tx, ty = checkx + dx, checky + dy
        if self.actor_at(tx, ty):
            return
        self.actorat[tx * 64 + ty] = oldtile
        self.tilemap[tx * 64 + ty] = oldtile
        self.secretcount += 1
        self.pwallx, self.pwally, self.pwalldir = checkx, checky, direction
        self.pwallstate = 1
        self.pwallpos = 0
        self.tilemap[checkx * 64 + checky] |= 0xc0
        self.map1[checky * 64 + checkx] = 0
        self.log('pushwall', tile=(checkx, checky), dir=direction)

    def move_pwalls(self):
        if not self.pwallstate:
            return
        oldblock = self.pwallstate // 128
        self.pwallstate = (self.pwallstate + self.tics) & 0xffff
        if self.pwallstate // 128 != oldblock:
            x, y = self.pwallx, self.pwally
            oldtile = self.tilemap[x * 64 + y] & 63
            self.tilemap[x * 64 + y] = 0
            self.actorat[x * 64 + y] = 0
            self.map0[y * 64 + x] = self.player.areanumber + AREATILE
            if self.pwallstate > 256:
                self.pwallstate = 0
                return
            dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[self.pwalldir]
            self.pwallx, self.pwally = x + dx, y + dy
            nx, ny = self.pwallx + dx, self.pwally + dy
            if self.actor_at(nx, ny):
                self.pwallstate = 0
                return
            self.actorat[nx * 64 + ny] = oldtile
            self.tilemap[nx * 64 + ny] = oldtile
            self.tilemap[self.pwallx * 64 + self.pwally] = oldtile | 0xc0
        self.pwallpos = (self.pwallstate // 2) & 63

    # ------------------------------------------------------------ actors
    def try_walk(self, ob):
        doornum = -1
        x, y = ob.tilex, ob.tiley

        def blocked_diag(tx, ty):
            temp = self.as_unsigned(self.actor_at(tx, ty))
            if temp:
                if temp < 256:
                    return True
                if self.actor_at(tx, ty).flags & FL_SHOOTABLE:
                    return True
            return False

        def side(tx, ty):
            nonlocal doornum
            temp = self.as_unsigned(self.actor_at(tx, ty))
            if temp:
                if temp < 128:
                    return True
                if temp < 256:
                    doornum = temp & 63
                elif self.actor_at(tx, ty).flags & FL_SHOOTABLE:
                    return True
            return False

        d = ob.dir
        if ob.obclass == INERTOBJ:
            raise SimError('inert actor walked')
        if d in (NORTH, EAST, SOUTH, WEST):
            dx, dy = {NORTH: (0, -1), EAST: (1, 0), SOUTH: (0, 1), WEST: (-1, 0)}[d]
            if ob.obclass == DOGOBJ:
                if blocked_diag(x + dx, y + dy):
                    return False
            else:
                if side(x + dx, y + dy):
                    return False
            ob.tilex, ob.tiley = x + dx, y + dy
        elif d in (NORTHEAST, SOUTHEAST, SOUTHWEST, NORTHWEST):
            dx, dy = {NORTHEAST: (1, -1), SOUTHEAST: (1, 1), SOUTHWEST: (-1, 1), NORTHWEST: (-1, -1)}[d]
            if blocked_diag(x + dx, y + dy) or blocked_diag(x + dx, y) or blocked_diag(x, y + dy):
                return False
            ob.tilex, ob.tiley = x + dx, y + dy
        elif d == NODIR:
            return False
        else:
            raise SimError('Walk: Bad dir')
        if doornum != -1:
            self.open_door(doornum)
            ob.distance = -doornum - 1
            return True
        ob.areanumber = (self.map0[ob.tiley * 64 + ob.tilex] - AREATILE) & 0xff
        ob.distance = TILEGLOBAL
        return True

    def select_dodge_dir(self, ob):
        if ob.flags & FL_FIRSTATTACK:
            turnaround = NODIR
            ob.flags &= ~FL_FIRSTATTACK
        else:
            turnaround = OPPOSITE[ob.dir]
        p = self.player
        deltax = p.tilex - ob.tilex
        deltay = p.tiley - ob.tiley
        dirtry = [NODIR] * 5
        if deltax > 0:
            dirtry[1], dirtry[3] = EAST, WEST
        else:
            dirtry[1], dirtry[3] = WEST, EAST
        if deltay > 0:
            dirtry[2], dirtry[4] = SOUTH, NORTH
        else:
            dirtry[2], dirtry[4] = NORTH, SOUTH
        if abs(deltax) > abs(deltay):
            dirtry[1], dirtry[2] = dirtry[2], dirtry[1]
            dirtry[3], dirtry[4] = dirtry[4], dirtry[3]
        if self.rnd() < 128:
            dirtry[1], dirtry[2] = dirtry[2], dirtry[1]
            dirtry[3], dirtry[4] = dirtry[4], dirtry[3]
        dirtry[0] = DIAGONAL[dirtry[1]][dirtry[2]]
        for i in range(5):
            if dirtry[i] == NODIR or dirtry[i] == turnaround:
                continue
            ob.dir = dirtry[i]
            if self.try_walk(ob):
                return
        if turnaround != NODIR:
            ob.dir = turnaround
            if self.try_walk(ob):
                return
        ob.dir = NODIR

    def select_chase_dir(self, ob):
        olddir = ob.dir
        turnaround = OPPOSITE[olddir]
        p = self.player
        deltax = p.tilex - ob.tilex
        deltay = p.tiley - ob.tiley
        d = [NODIR, NODIR, NODIR]
        if deltax > 0:
            d[1] = EAST
        elif deltax < 0:
            d[1] = WEST
        if deltay > 0:
            d[2] = SOUTH
        elif deltay < 0:
            d[2] = NORTH
        if abs(deltay) > abs(deltax):
            d[1], d[2] = d[2], d[1]
        if d[1] == turnaround:
            d[1] = NODIR
        if d[2] == turnaround:
            d[2] = NODIR
        if d[1] != NODIR:
            ob.dir = d[1]
            if self.try_walk(ob):
                return
        if d[2] != NODIR:
            ob.dir = d[2]
            if self.try_walk(ob):
                return
        if olddir != NODIR:
            ob.dir = olddir
            if self.try_walk(ob):
                return
        if self.rnd() > 128:
            order = (NORTH, NORTHWEST, WEST)
        else:
            order = (WEST, NORTHWEST, NORTH)
        for tdir in order:
            if tdir != turnaround:
                ob.dir = tdir
                if self.try_walk(ob):
                    return
        if turnaround != NODIR:
            ob.dir = turnaround
            if ob.dir != NODIR:
                if self.try_walk(ob):
                    return
        ob.dir = NODIR

    def move_obj(self, ob, move):
        dx, dy = {NORTH: (0, -1), NORTHEAST: (1, -1), EAST: (1, 0), SOUTHEAST: (1, 1),
                  SOUTH: (0, 1), SOUTHWEST: (-1, 1), WEST: (-1, 0), NORTHWEST: (-1, -1)}.get(ob.dir, (None, None))
        if ob.dir == NODIR:
            return
        if dx is None:
            raise SimError('MoveObj: bad dir')
        ob.x = s32(ob.x + dx * move)
        ob.y = s32(ob.y + dy * move)
        if self.areabyplayer_at(ob.areanumber):
            p = self.player
            deltax = ob.x - p.x
            if not (deltax < -MINACTORDIST or deltax > MINACTORDIST):
                deltay = ob.y - p.y
                if not (deltay < -MINACTORDIST or deltay > MINACTORDIST):
                    ob.x = s32(ob.x - dx * move)
                    ob.y = s32(ob.y - dy * move)
                    return
        ob.distance = s32(ob.distance - move)

    def areabyplayer_at(self, area):
        if area >= 37:
            raise SimError('areabyplayer read outside the table (area %d)' % area)
        return self.areabyplayer[area]

    def kill_actor(self, ob):
        ob.tilex = ob.x >> 16
        ob.tiley = ob.y >> 16
        tilex, tiley = ob.tilex, ob.tiley
        if ob.obclass == GUARDOBJ:
            self.give_points(100)
            self.new_state(ob, 's_grddie1')
            self.place_item_type(ITEM['bo_clip2'], tilex, tiley)
        elif ob.obclass == OFFICEROBJ:
            self.give_points(400)
            self.new_state(ob, 's_ofcdie1')
            self.place_item_type(ITEM['bo_clip2'], tilex, tiley)
        elif ob.obclass == SSOBJ:
            self.give_points(500)
            self.new_state(ob, 's_ssdie1')
            if self.bestweapon < WP_MACHINEGUN:
                self.place_item_type(ITEM['bo_machinegun'], tilex, tiley)
            else:
                self.place_item_type(ITEM['bo_clip2'], tilex, tiley)
        elif ob.obclass == DOGOBJ:
            self.give_points(200)
            self.new_state(ob, 's_dogdie1')
        elif ob.obclass == BOSSOBJ:
            self.give_points(5000)
            self.new_state(ob, 's_bossdie1')
            self.place_item_type(ITEM['bo_key1'], tilex, tiley)
        else:
            raise SimError('KillActor class %d' % ob.obclass)
        self.killcount += 1
        ob.flags &= ~FL_SHOOTABLE
        self.actorat[ob.tilex * 64 + ob.tiley] = 0
        ob.flags |= FL_NONMARK
        self.log('kill', actor=ob.index)

    def damage_actor(self, ob, damage):
        self.madenoise = True
        if not ob.flags & FL_ATTACKMODE:
            damage <<= 1
        ob.hitpoints = s16(ob.hitpoints - damage)
        self.log('hit', actor=ob.index, damage=damage)
        if ob.hitpoints <= 0:
            self.kill_actor(ob)
        else:
            if not ob.flags & FL_ATTACKMODE:
                self.first_sighting(ob)
            if ob.obclass == GUARDOBJ:
                self.new_state(ob, 's_grdpain' if ob.hitpoints & 1 else 's_grdpain1')
            elif ob.obclass == OFFICEROBJ:
                self.new_state(ob, 's_ofcpain' if ob.hitpoints & 1 else 's_ofcpain1')
            elif ob.obclass == SSOBJ:
                self.new_state(ob, 's_sspain' if ob.hitpoints & 1 else 's_sspain1')

    def check_line(self, ob):
        x1 = s16(ob.x >> 8)
        y1 = s16(ob.y >> 8)
        xt1 = x1 >> 8
        yt1 = y1 >> 8
        x2 = s16(self.plux)
        y2 = s16(self.pluy)
        xt2 = self.player.tilex
        yt2 = self.player.tiley
        xdist = abs(xt2 - xt1)
        if xdist > 0:
            if xt2 > xt1:
                partial = 256 - (x1 & 0xff)
                xstep = 1
            else:
                partial = x1 & 0xff
                xstep = -1
            deltafrac = abs(s16(x2 - x1))
            delta = s16(y2 - y1)
            ltemp = cdiv(delta << 8, deltafrac)
            ystep = 0x7fff if ltemp > 0x7fff else -0x7fff if ltemp < -0x7fff else ltemp
            yfrac = s16(y1 + ((ystep * partial) >> 8))
            x = xt1 + xstep
            xt2 += xstep
            while True:
                y = yfrac >> 8
                yfrac = s16(yfrac + ystep)
                value = self.tilemap[(x * 64 + y) & 0xfff] if 0 <= x < 64 and 0 <= y < 64 else self.oob(x, y)
                x += xstep
                if value:
                    if value < 128 or value > 256:
                        return False
                    value &= ~0x80
                    intercept = (yfrac - cdiv(ystep, 2)) & 0xffff
                    if intercept > self.door_position_at(value):
                        return False
                if x == xt2:
                    break
        ydist = abs(yt2 - yt1)
        if ydist > 0:
            if yt2 > yt1:
                partial = 256 - (y1 & 0xff)
                ystep = 1
            else:
                partial = y1 & 0xff
                ystep = -1
            deltafrac = abs(s16(y2 - y1))
            delta = s16(x2 - x1)
            ltemp = cdiv(delta << 8, deltafrac)
            xstep = 0x7fff if ltemp > 0x7fff else -0x7fff if ltemp < -0x7fff else ltemp
            xfrac = s16(x1 + ((xstep * partial) >> 8))
            y = yt1 + ystep
            yt2 += ystep
            while True:
                x = xfrac >> 8
                xfrac = s16(xfrac + xstep)
                value = self.tilemap[(x * 64 + y) & 0xfff] if 0 <= x < 64 and 0 <= y < 64 else self.oob(x, y)
                y += ystep
                if value:
                    if value < 128 or value > 256:
                        return False
                    value &= ~0x80
                    intercept = (xfrac - cdiv(xstep, 2)) & 0xffff
                    if intercept > self.door_position_at(value):
                        return False
                if y == yt2:
                    break
        return True

    def oob(self, x, y):
        raise SimError('CheckLine left the map at %d,%d' % (x, y))

    def door_position_at(self, value):
        if value >= 64:
            raise SimError('CheckLine read doorposition[%d] for a moving wall' % value)
        return self.doorposition[value]

    def check_sight(self, ob):
        if not self.areabyplayer_at(ob.areanumber):
            return False
        p = self.player
        deltax = p.x - ob.x
        deltay = p.y - ob.y
        if -MINSIGHT < deltax < MINSIGHT and -MINSIGHT < deltay < MINSIGHT:
            return True
        if ob.dir == NORTH and deltay > 0:
            return False
        if ob.dir == EAST and deltax < 0:
            return False
        if ob.dir == SOUTH and deltay < 0:
            return False
        if ob.dir == WEST and deltax > 0:
            return False
        return self.check_line(ob)

    def first_sighting(self, ob):
        if ob.obclass == GUARDOBJ:
            self.new_state(ob, 's_grdchase1')
            ob.speed *= 3
        elif ob.obclass == OFFICEROBJ:
            self.new_state(ob, 's_ofcchase1')
            ob.speed *= 5
        elif ob.obclass == SSOBJ:
            self.new_state(ob, 's_sschase1')
            ob.speed *= 4
        elif ob.obclass == DOGOBJ:
            self.new_state(ob, 's_dogchase1')
            ob.speed *= 2
        elif ob.obclass == BOSSOBJ:
            self.new_state(ob, 's_bosschase1')
            ob.speed = SPDPATROL * 3
        else:
            raise SimError('FirstSighting class %d' % ob.obclass)
        if ob.distance < 0:
            ob.distance = 0
        ob.flags |= FL_ATTACKMODE | FL_FIRSTATTACK
        self.log('sight', actor=ob.index)

    def sight_player(self, ob):
        if ob.flags & FL_ATTACKMODE:
            raise SimError('An actor in ATTACKMODE called SightPlayer')
        if ob.temp2:
            ob.temp2 = s16(ob.temp2 - self.tics)
            if ob.temp2 > 0:
                return False
            ob.temp2 = 0
        else:
            if not self.areabyplayer_at(ob.areanumber):
                return False
            if ob.flags & FL_AMBUSH:
                if not self.check_sight(ob):
                    return False
                ob.flags &= ~FL_AMBUSH
            else:
                if not self.madenoise and not self.check_sight(ob):
                    return False
            if ob.obclass == GUARDOBJ:
                ob.temp2 = 1 + self.rnd() // 4
            elif ob.obclass == OFFICEROBJ:
                ob.temp2 = 2
            elif ob.obclass == SSOBJ:
                ob.temp2 = 1 + self.rnd() // 6
            elif ob.obclass == DOGOBJ:
                ob.temp2 = 1 + self.rnd() // 8
            elif ob.obclass == BOSSOBJ:
                ob.temp2 = 1
            return False
        self.first_sighting(ob)
        return True

    def T_Stand(self, ob):
        self.sight_player(ob)

    def T_Chase(self, ob):
        if self.victoryflag:
            return
        dodge = False
        if self.check_line(ob):
            p = self.player
            dx = abs(ob.tilex - p.tilex)
            dy = abs(ob.tiley - p.tiley)
            dist = max(dx, dy)
            if not dist or (dist == 1 and ob.distance < 0x4000):
                chance = 300
            else:
                chance = (self.tics << 4) // dist
            if self.rnd() < chance:
                shoot = {OFFICEROBJ: 's_ofcshoot1', GUARDOBJ: 's_grdshoot1', SSOBJ: 's_ssshoot1', BOSSOBJ: 's_bossshoot1'}
                if ob.obclass in shoot:
                    self.new_state(ob, shoot[ob.obclass])
                return
            dodge = True
        if ob.dir == NODIR:
            if dodge:
                self.select_dodge_dir(ob)
            else:
                self.select_chase_dir(ob)
            if ob.dir == NODIR:
                return
        move = ob.speed * self.tics
        while move:
            if ob.distance < 0:
                door = -ob.distance - 1
                self.open_door(door)
                if self.doors[door]['action'] != DR_OPEN:
                    return
                ob.distance = TILEGLOBAL
            if move < ob.distance:
                self.move_obj(ob, move)
                break
            ob.x = (ob.tilex << 16) + TILEGLOBAL // 2
            ob.y = (ob.tiley << 16) + TILEGLOBAL // 2
            move -= ob.distance
            if dodge:
                self.select_dodge_dir(ob)
            else:
                self.select_chase_dir(ob)
            if ob.dir == NODIR:
                return

    def T_DogChase(self, ob):
        if ob.dir == NODIR:
            self.select_dodge_dir(ob)
            if ob.dir == NODIR:
                return
        move = ob.speed * self.tics
        p = self.player
        while move:
            dx = abs(p.x - ob.x) - move
            if dx <= MINACTORDIST:
                dy = abs(p.y - ob.y) - move
                if dy <= MINACTORDIST:
                    self.new_state(ob, 's_dogjump1')
                    return
            if move < ob.distance:
                self.move_obj(ob, move)
                break
            ob.x = (ob.tilex << 16) + TILEGLOBAL // 2
            ob.y = (ob.tiley << 16) + TILEGLOBAL // 2
            move -= ob.distance
            self.select_dodge_dir(ob)
            if ob.dir == NODIR:
                return

    def select_path_dir(self, ob):
        spot = (self.map1[ob.tiley * 64 + ob.tilex] - ICONARROWS) & 0xffff
        if spot < 8:
            ob.dir = spot
        ob.distance = TILEGLOBAL
        if not self.try_walk(ob):
            ob.dir = NODIR

    def T_Path(self, ob):
        if self.sight_player(ob):
            return
        if ob.dir == NODIR:
            self.select_path_dir(ob)
            if ob.dir == NODIR:
                return
        move = ob.speed * self.tics
        while move:
            if ob.distance < 0:
                door = -ob.distance - 1
                self.open_door(door)
                if self.doors[door]['action'] != DR_OPEN:
                    return
                ob.distance = TILEGLOBAL
            if move < ob.distance:
                self.move_obj(ob, move)
                break
            if ob.tilex > 64 or ob.tiley > 64:
                raise SimError('T_Path hit a wall')
            ob.x = (ob.tilex << 16) + TILEGLOBAL // 2
            ob.y = (ob.tiley << 16) + TILEGLOBAL // 2
            move -= ob.distance
            self.select_path_dir(ob)
            if ob.dir == NODIR:
                return

    def T_Shoot(self, ob):
        if not self.areabyplayer_at(ob.areanumber):
            return
        if not self.check_line(ob):
            return
        p = self.player
        dx = abs(ob.tilex - p.tilex)
        dy = abs(ob.tiley - p.tiley)
        dist = max(dx, dy)
        if ob.obclass in (SSOBJ, BOSSOBJ):
            dist = dist * 2 // 3
        if self.thrustspeed >= RUNSPEED:
            hitchance = 160 - dist * (16 if ob.flags & FL_VISABLE else 8)
        else:
            hitchance = 256 - dist * (16 if ob.flags & FL_VISABLE else 8)
        if self.rnd() < hitchance:
            if dist < 2:
                damage = self.rnd() >> 2
            elif dist < 4:
                damage = self.rnd() >> 3
            else:
                damage = self.rnd() >> 4
            self.take_damage(damage, ob)
            self.log('shot', actor=ob.index, damage=damage)

    def T_Bite(self, ob):
        p = self.player
        dx = abs(p.x - ob.x) - TILEGLOBAL
        if dx <= MINACTORDIST:
            dy = abs(p.y - ob.y) - TILEGLOBAL
            if dy <= MINACTORDIST:
                if self.rnd() < 180:
                    damage = self.rnd() >> 4
                    self.take_damage(damage, ob)
                    self.log('bite', actor=ob.index, damage=damage)

    def A_DeathScream(self, ob):
        # The source's non-UPLOAD branch: an extra roll on floor 10 only.
        if self.mapon == 9 and not self.rnd() and ob.obclass in (GUARDOBJ, OFFICEROBJ, SSOBJ, DOGOBJ):
            return
        if ob.obclass == GUARDOBJ:
            self.rnd()

    def call(self, name, ob):
        getattr(self, name)(ob)

    def do_actor(self, ob):
        if not ob.active and not self.areabyplayer_at(ob.areanumber):
            return
        if not ob.flags & (FL_NONMARK | FL_NEVERMARK):
            self.actorat[ob.tilex * 64 + ob.tiley] = 0
        if not ob.ticcount:
            if ob.state.think:
                self.call(ob.state.think, ob)
                if ob.state is None:
                    self.remove_obj(ob)
                    return
            self.mark_actor(ob)
            return
        ob.ticcount = s16(ob.ticcount - self.tics)
        while ob.ticcount <= 0:
            if ob.state.action:
                self.call(ob.state.action, ob)
                if ob.state is None:
                    self.remove_obj(ob)
                    return
            ob.state = ob.state.next
            if ob.state is None:
                self.remove_obj(ob)
                return
            if not ob.state.tictime:
                ob.ticcount = 0
                break
            ob.ticcount = s16(ob.ticcount + ob.state.tictime)
        if ob.state.think:
            self.call(ob.state.think, ob)
            if ob.state is None:
                self.remove_obj(ob)
                return
        self.mark_actor(ob)

    def mark_actor(self, ob):
        if ob.flags & FL_NEVERMARK:
            return
        if ob.flags & FL_NONMARK and self.actor_at(ob.tilex, ob.tiley):
            return
        self.actorat[ob.tilex * 64 + ob.tiley] = ob

    # ------------------------------------------------------------ refresh
    def wall_refresh(self):
        p = self.player
        self.viewangle = p.angle
        self.midangle = self.viewangle * (FINEANGLES // ANGLES)
        self.viewsin = self.sintable[self.viewangle]
        self.viewcos = self.sintable[self.viewangle + ANGLES // 4]
        self.viewx = s32(p.x - fixed_by_frac(self.focallength, self.viewcos))
        self.viewy = s32(p.y + fixed_by_frac(self.focallength, self.viewsin))
        self.focaltx = self.viewx >> 16
        self.focalty = self.viewy >> 16
        spotvis = bytearray(4096)
        if self.vis_model == 'rays':
            for pixx in self.ray_columns:
                self.cast_ray(self.midangle + self.pixelangle[pixx], spotvis)
        self.spotvis = spotvis

    def aimed_visible(self, tx, ty):
        """Visibility model 'aim': one exact ray toward the tile center."""
        dx = ((tx << 16) + 0x8000 - self.viewx) / 65536
        dy = ((ty << 16) + 0x8000 - self.viewy) / 65536
        angle = round(math.atan2(-dy, dx) * FINEANGLES / math.tau) % FINEANGLES
        right = (self.midangle + self.pixelangle[-1]) % FINEANGLES
        width = self.pixelangle[0] - self.pixelangle[-1]
        if (angle - right) % FINEANGLES > width:
            return False
        marks = bytearray(4096)
        self.cast_ray(angle, marks)
        return bool(marks[tx * 64 + ty])

    def cast_ray(self, angle, spotvis):
        """One AsmRefresh ray at a fine angle; marks every passed cell."""
        tilemap = self.tilemap
        ft = self.finetangent
        xpartialdown = self.viewx & 0xffff
        xpartialup = (TILEGLOBAL - xpartialdown) & 0xffff
        ypartialdown = self.viewy & 0xffff
        ypartialup = (TILEGLOBAL - ypartialdown) & 0xffff
        if angle < 0:
            angle += FINEANGLES
        elif angle >= FINEANGLES:
            angle -= FINEANGLES
        if angle < 900:
            xtilestep, ytilestep = 1, -1
            xstep = ft[900 - 1 - angle]
            ystep = -ft[angle]
            xpartial, ypartial = xpartialup, ypartialdown
        elif angle < 1800:
            xtilestep, ytilestep = -1, -1
            xstep = -ft[angle - 900]
            ystep = -ft[1800 - 1 - angle]
            xpartial, ypartial = xpartialdown, ypartialdown
        elif angle < 2700:
            xtilestep, ytilestep = -1, 1
            xstep = -ft[2700 - 1 - angle]
            ystep = ft[angle - 1800]
            xpartial, ypartial = xpartialdown, ypartialup
        else:
            xtilestep, ytilestep = 1, 1
            xstep = ft[angle - 2700]
            ystep = ft[3600 - 1 - angle]
            xpartial, ypartial = xpartialup, ypartialup
        yintercept = s32(partial_by_step(ystep, xpartial) + self.viewy)
        xtile = self.focaltx + xtilestep
        xintercept = s32(partial_by_step(xstep, ypartial) + self.viewx)
        ytile = self.focalty + ytilestep
        doorposition, pwallpos = self.doorposition, self.pwallpos
        label = 'vertcheck'
        while True:
            if label == 'vertcheck':
                # vertop is jle for ytilestep -1 and jge for +1 (signed words)
                yint = s16(yintercept >> 16)
                if (yint <= ytile) if ytilestep < 0 else (yint >= ytile):
                    label = 'horizentry'
                else:
                    label = 'vertentry'
            elif label == 'vertentry':
                yint = s16(yintercept >> 16)
                xspot = ((xtile << 6) + yint) & 0xffff
                if xspot >= 4096:
                    self.oob(xtile, yint)
                tile = tilemap[xspot]
                if not tile:
                    label = 'passvert'
                elif not tile & 0x80:
                    break
                elif tile & 0x40:
                    part = s32((ystep * pwallpos) & 0xffffffff) >> 6
                    if (s32(yintercept + part) >> 16) != (yintercept >> 16):
                        label = 'passvert'
                    else:
                        break
                else:
                    mid = s32(yintercept + (ystep >> 1))
                    if (mid >> 16) != (yintercept >> 16) or (mid & 0xffff) < doorposition[tile & 0x7f]:
                        label = 'passvert'
                    else:
                        break
            elif label == 'passvert':
                spotvis[xspot] = 1
                xtile += xtilestep
                yintercept = s32(yintercept + ystep)
                label = 'vertcheck'
            elif label == 'horizcheck':
                xint = s16(xintercept >> 16)
                if (xint <= xtile) if xtilestep < 0 else (xint >= xtile):
                    label = 'vertentry'
                else:
                    label = 'horizentry'
            elif label == 'horizentry':
                xint = s16(xintercept >> 16)
                yspot = ((xint << 6) + ytile) & 0xffff
                if yspot >= 4096:
                    self.oob(xint, ytile)
                tile = tilemap[yspot]
                if not tile:
                    label = 'passhoriz'
                elif not tile & 0x80:
                    break
                elif tile & 0x40:
                    part = s32((xstep * pwallpos) & 0xffffffff) >> 6
                    if (s32(xintercept + part) >> 16) != (xintercept >> 16):
                        label = 'passhoriz'
                    else:
                        break
                else:
                    mid = s32(xintercept + (xstep >> 1))
                    if (mid >> 16) != (xintercept >> 16) or (mid & 0xffff) < doorposition[tile & 0x7f]:
                        label = 'passhoriz'
                    else:
                        break
            else:
                spotvis[yspot] = 1
                ytile += ytilestep
                xintercept = s32(xintercept + xstep)
                label = 'horizcheck'

    def transform_actor(self, ob):
        gx = s32(ob.x - self.viewx)
        gy = s32(ob.y - self.viewy)
        gxt = fixed_by_frac(gx, self.viewcos)
        gyt = fixed_by_frac(gy, self.viewsin)
        nx = s32(gxt - gyt - 0x4000)
        gxt = fixed_by_frac(gx, self.viewsin)
        gyt = fixed_by_frac(gy, self.viewcos)
        ny = s32(gyt + gxt)
        ob.transx, ob.transy = nx, ny
        if nx < MINDIST:
            ob.viewheight = 0
            return
        ob.viewx = s16(self.centerx + cdiv(s32(ny * self.scale), nx))
        ob.viewheight = self.height_div(nx)

    def height_div(self, nx):
        divisor = s16(nx >> 8)
        q = cdiv(self.heightnumerator, divisor)
        if not -0x8000 <= q <= 0x7fff:
            raise SimError('height divide overflow')
        return q & 0xffff

    def transform_tile(self, tx, ty):
        gx = s32((tx << 16) + 0x8000 - self.viewx)
        gy = s32((ty << 16) + 0x8000 - self.viewy)
        gxt = fixed_by_frac(gx, self.viewcos)
        gyt = fixed_by_frac(gy, self.viewsin)
        nx = s32(gxt - gyt - 0x2000)
        gxt = fixed_by_frac(gx, self.viewsin)
        gyt = fixed_by_frac(gy, self.viewcos)
        ny = s32(gyt + gxt)
        if nx < MINDIST:
            return False, 0
        height = self.height_div(nx)
        return (nx < TILEGLOBAL and -TILEGLOBAL // 2 < ny < TILEGLOBAL // 2), height

    def tile_seen(self, tx, ty):
        if self.vis_model == 'rays':
            return self.spotvis[tx * 64 + ty]
        return self.aimed_visible(tx, ty)

    def draw_scaleds(self):
        tilemap = self.tilemap
        for st in self.statobjs:
            if st['shapenum'] == -1:
                continue
            if self.vis_model == 'rays' and not self.spotvis[st['tilex'] * 64 + st['tiley']]:
                continue
            grab, height = self.transform_tile(st['tilex'], st['tiley'])
            if grab and st['flags'] & FL_BONUS and self.tile_seen(st['tilex'], st['tiley']):
                self.get_bonus(st)
        ob = self.player.next
        while ob is not None:
            if ob.state.shapenum:
                spot = ob.tilex * 64 + ob.tiley
                seen = self.tile_seen(ob.tilex, ob.tiley)
                if not seen and self.aim_neighbors:
                    for d in (-1, 1, -65, -64, -63, 65, 64, 63):
                        n = spot + d
                        if not tilemap[n] and self.tile_seen(n >> 6, n & 63):
                            seen = True
                            break
                if seen:
                    if not ob.active:
                        self.log('active', actor=ob.index)
                    ob.active = 1
                    self.transform_actor(ob)
                    if ob.viewheight:
                        ob.flags |= FL_VISABLE
                else:
                    ob.flags &= ~FL_VISABLE
            ob = ob.next

    # ------------------------------------------------------------ loop
    def log(self, kind, **fields):
        if self.trace is not None:
            self.trace.append(dict(frame=self.frame, kind=kind, **fields))

    def play_frame(self, buttons, controlx, controly):
        self.gatling = max(0, self.gatling - self.tics)
        self.buttonheld = list(self.buttonstate)
        self.buttonstate = [bool(buttons >> i & 1) for i in range(8)]
        self.controlx = controlx * self.tics
        self.controly = controly * self.tics
        self.madenoise = False
        self.move_doors()
        self.move_pwalls()
        ob = self.player
        while ob is not None:
            self.do_actor(ob)
            ob = ob.next
        self.bonuscount = max(0, self.bonuscount - self.tics) if self.bonuscount else 0
        self.damagecount = max(0, self.damagecount - self.tics) if self.damagecount else 0
        self.wall_refresh()
        self.draw_scaleds()
        self.frame += 1

    def snapshot(self):
        p = self.player
        actors = []
        ob = p.next
        while ob is not None:
            actors.append(dict(index=ob.index, cls=ob.obclass, state=ob.state.name if ob.state else None,
                               x=ob.x, y=ob.y, tilex=ob.tilex, tiley=ob.tiley, dir=ob.dir, hp=ob.hitpoints,
                               flags=ob.flags, active=ob.active, ticcount=ob.ticcount, distance=ob.distance))
            ob = ob.next
        return dict(frame=self.frame, x=p.x, y=p.y, angle=p.angle, tilex=p.tilex, tiley=p.tiley,
                    area=p.areanumber, health=self.health, ammo=self.ammo, score=self.score,
                    lives=self.lives, keys=self.keys, weapon=self.weapon, bestweapon=self.bestweapon,
                    killcount=self.killcount, secretcount=self.secretcount, treasurecount=self.treasurecount,
                    rndindex=self.rndindex, playstate=self.playstate, doors=list(self.doorposition[:len(self.doors)]),
                    pwall=(self.pwallstate, self.pwallx, self.pwally), actors=actors)


def demo_chunks():
    from wolfdata import source_data
    return source_data().demos()


def play_demo(data, mapon, viewwidth=240, trace=None, every=None):
    game = Game(mapon, viewwidth=viewwidth, trace=trace)
    frames = []
    for n in range(0, len(data) - len(data) % 3, 3):
        buttons = data[n]
        cx = data[n + 1] - 256 if data[n + 1] > 127 else data[n + 1]
        cy = data[n + 2] - 256 if data[n + 2] > 127 else data[n + 2]
        if n + 3 == len(data):
            game.playstate = EX_COMPLETED
        game.play_frame(buttons, cx, cy)
        if every and game.frame % every == 0:
            frames.append(game.snapshot())
        if game.playstate:
            break
    return game, frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('demo', type=int, choices=range(4))
    ap.add_argument('--width', type=int, default=240)
    ap.add_argument('--trace', action='store_true')
    ap.add_argument('--every', type=int)
    args = ap.parse_args()
    demo = demo_chunks()[args.demo]
    trace = [] if args.trace else None
    game, frames = play_demo(demo['data'], demo['mapon'], args.width, trace, args.every)
    end = game.snapshot()
    end.pop('actors')
    print(json.dumps(dict(demo=args.demo, mapon=demo['mapon'], width=args.width, packets=len(demo['data']) // 3, end=end)))
    for row in trace or []:
        print(json.dumps(row))
    for row in frames:
        row.pop('actors')
        print(json.dumps(row))


if __name__ == '__main__':
    main()
