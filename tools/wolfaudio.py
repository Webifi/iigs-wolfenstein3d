"""Original id audio containers; no DOS code or third-party synthesizer runs."""
import re
import struct
from wolfdata import DATA, ID, ROOT, PROFILE, source_data
from game_profile import read_toml
from effect_sources import source_effects
from functools import lru_cache

CATALOG = ROOT/'profiles/audio'/('effects-spear.toml' if PROFILE.spear else 'effects-wolf3d.toml')
_CATALOG = read_toml(CATALOG)['effect']
NAMES = [r['name'] for r in sorted(_CATALOG,key=lambda r:r['id'])]
MUSIC = [name+'_MUS' for name in PROFILE.music_names]
_digi_key = 'digitized_shareware' if PROFILE.public_game_data else 'digitized'
DIGI = {r['id']:r[_digi_key] for r in _CATALOG if r[_digi_key]>=0}
RESIDENT = tuple(range(49)) + (50,51,55,56,58,59,60,61,68,72)
AVAILABLE = {r['id'] for r in _CATALOG
             if not r.get('digitized_only', False) or r[_digi_key] >= 0}
MODIFIERS = (0,1,2,8,9,10,16,17,18)
OPL_RATE = 3579545 / 72
DOC_RATE = (14318180 / 2) / 8 / 34


def chunks():
    return source_data().audio()


@lru_cache(maxsize=1)
def effect_source_rows():
    return source_effects(source_data(),CATALOG)


def effects():
    out=[]
    for row in effect_source_rows():
        raw=row['adlib'];length=struct.unpack_from('<I',raw)[0]
        out.append(dict(id=row['id'],name=row['name'],priority=row['priority'],
                        patch=tuple(raw[6:17]),block=raw[22]&7,
                        notes=raw[23:23+length],pcm=row['pcm']))
    return out


def songs():
    out=[]
    for i,b in enumerate(chunks()[PROFILE.sounds*3:]):
        size=struct.unpack_from('<H',b)[0]
        if size%4 or size+2>len(b):
            raise ValueError('invalid IMF length')
        t=0;events=[]
        for reg,value,delay in struct.iter_unpack('<BBH',b[2:2+size]):
            events.append((t,reg,value));t+=delay
        out.append(dict(id=i,name=MUSIC[i],ticks=t,events=events))
    return out


def patch(registers, channel):
    m=MODIFIERS[channel]
    return tuple(registers[base+slot] for base in (0x20,0x40,0x60,0x80,0xe0)
                 for slot in (m,m+3))+(registers[0xc0+channel],)


def pitch(registers, channel):
    high=registers[0xb0+channel]
    fnum=registers[0xa0+channel]|((high&3)<<8)
    block=(high>>2)&7
    return fnum,block,OPL_RATE*fnum*2**(block-20)
