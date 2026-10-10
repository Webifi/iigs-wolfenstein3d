"""Wolf and Spear class records keyed by source class IDs and state names.

The 32-byte records are read only when spawning, changing behavior or taking
damage. The ordinary movement/state dispatch retains its existing tables.
"""
import re
import struct
import math
from wolfdata import ID, PROFILE
from wolf_source import wolf_only

BASE = 0xd600
SIZE = 32
FIELDS = dict(C_STAND=0, C_PATROL=2, C_CHASE=4, C_SHOOT=6, C_PAIN=8,
              C_PAIN1=10, C_DIE=12, C_SIGHT=14, C_SCREAM=16,
              C_MULT=18, C_POINTS=20, C_DROP=22, C_HP=24)

# class: (state prefix, source enemy index, sight sound, death sound,
#         chase speed multiplier, score, dropped item)
# Negative sound/item IDs mean no request. Guard death chooses its RNG sound;
# SS death chooses a machine gun or clip according to the player's weapon.
CLASSES = {
    3: ('grd', 0, 'HALTSND', None, 3, 100, 14),
    4: ('ofc', 1, 'SPIONSND', 'NEINSOVASSND', 5, 400, 14),
    5: ('ss', 2, 'SCHUTZADSND', 'LEBENSND', 4, 500, 14),
    6: ('dog', 3, 'DOGBARKSND', 'DOGDEATHSND', 2, 200, -1),
    7: ('boss', 4, 'GUTENTAGSND', 'MUTTISND', 3, 5000, 5),
    8: ('schabb', 5, 'SCHABBSHASND', 'MEINGOTTSND', 3, 5000, -1),
    9: ('fake', 6, 'TOT_HUNDSND', 'HITLERHASND', 3, 2000, -1),
    10: ('mecha', 7, 'DIESND', 'SCHEISTSND', 3, 5000, -1),
    11: ('mut', 8, None, 'AHHHGSND', 3, 700, 14),
    15: ('blinky', 9, None, None, 2, 0, -1),
    16: ('hitler', None, 'DIESND', 'EVASND', 5, 5000, -1),
    17: ('gretel', 13, 'KEINSND', 'MEINSND', 3, 5000, 5),
    18: ('gift', 14, 'EINESND', 'DONNERSND', 3, 5000, -1),
    19: ('fat', 15, 'ERLAUBENSND', 'ROSESND', 3, 5000, -1),
}
if PROFILE.spear:
    CLASSES = {k:v for k,v in CLASSES.items() if k in (3,4,5,6,11)}
    CLASSES.update({
        21: ('spectre', 16, 'GHOSTSIGHTSND', 'GHOSTFADESND', 2, 200, -1),
        22: ('angel', 17, 'ANGELSIGHTSND', 'ANGELDEATHSND', 3, 5000, -1),
        23: ('trans', 18, 'TRANSSIGHTSND', 'TRANSDEATHSND', 3, 5000, 5),
        24: ('uber', 19, None, 'UBERDEATHSND', 3, 5000, 5),
        25: ('will', 20, 'WILHELMSIGHTSND', 'WILHELMDEATHSND', 3, 5000, 5),
        26: ('death', 21, 'KNIGHTSIGHTSND', 'KNIGHTDEATHSND', 3, 5000, 5),
    })
CLASS_COUNT = 29 if PROFILE.spear else 21
GHOST_STATES = BASE + CLASS_COUNT * SIZE
PROJECTILE_TANGENTS = GHOST_STATES + 8


def hitpoints():
    from wolf_source import engine_only
    text = engine_only((ID / 'WOLFSRC/WL_ACT2.C').read_text(), spear=PROFILE.spear)
    body = text[text.index('starthitpoints[4][NUMENEMIES]'):].split('};', 1)[0]
    body = re.sub(r'//[^\n]*|/\*.*?\*/', '', body, flags=re.S)
    rows = [list(map(int, re.findall(r'\d+', row))) for row in re.findall(r'\{([^{}]+)\}', body)]
    assert len(rows) == 4 and all(len(row) == 22 for row in rows)
    return rows


def records(states, sounds):
    hp = hitpoints()
    data = bytearray(CLASS_COUNT * SIZE)
    for kind, (prefix, enemy, sight, scream, mult, points, drop) in CLASSES.items():
        state = lambda suffix: states.get('s_' + prefix + suffix, 0)
        values = [state('stand'), state('path1'), state('chase1'), state('shoot1'),
                  state('pain'), state('pain1'), state('die1'),
                  sounds[sight] if sight else 65535, sounds[scream] if scream else 65535,
                  mult, points, drop & 65535]
        if PROFILE.spear:
            if kind == 21: values[0] = states['s_spectrewait1']
            if kind in (23,24): values[6] = state('die0')
        values.extend(hp[d][enemy] if enemy is not None else (500, 700, 800, 900)[d] for d in range(4))
        struct.pack_into('<16H', data, kind * SIZE, *values)
    data += (bytes(8) if PROFILE.spear else struct.pack('<4H', *(states['s_' + name + 'chase1'] for name in ('blinky', 'clyde', 'pinky', 'inky'))))
    # Q0.32 thresholds retain the original one-degree aim without a floating
    # point library or a large table. They are read only when firing a missile.
    data += struct.pack('<45I', *(math.ceil(math.tan(math.radians(a)) * 2**32)
                                  for a in range(45)))
    assert BASE + len(data) <= 0xdc00
    return data


def include():
    return '\n'.join(['CLASS_DATA .equ 0x%04x' % BASE,
                      'GHOST_STATES .equ 0x%04x' % GHOST_STATES,
                      'PROJECTILE_TANGENTS .equ 0x%04x' % PROJECTILE_TANGENTS] +
                     [f'{name} .equ {value}' for name, value in FIELDS.items()]) + '\n'
