"""Selected DOS data for build tools; codecs and profiles are host independent."""
import os
import pathlib
import struct
import functools

from dos_data import DosData, carmack, rlew, sprite
from game_profile import profile

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = pathlib.Path(os.environ.get('WOLF_DOS_DATA', str(ROOT / 'game-data' / 'shareware'))).resolve()
SHARED_DATA = os.environ.get('WOLF_SHARED_DATA') or None
PROFILE = profile(os.environ.get('WOLF_PROFILE', 'shareware'))
CONVERSION = PROFILE.conversion
_bundled_reference = ROOT / 'data/reference'
ID = pathlib.Path(os.environ.get('WOLF_REFERENCE_SOURCE', str(_bundled_reference)))


def source_data():
    return DosData(DATA, PROFILE, SHARED_DATA)


@functools.lru_cache(maxsize=1)
def _maps():
    return source_data().maps()


def maps():
    return [dict(name=m['name'], planes=[p[:] for p in m['planes']]) for m in _maps()]


@functools.lru_cache(maxsize=1)
def _vswap():
    return source_data().vswap()


def vswap():
    pages, sprites, sounds = _vswap()
    return list(pages), sprites, sounds


@functools.lru_cache(maxsize=1)
def _graphics():
    return source_data().graphics()


def graphics():
    return list(_graphics())


def palette():
    # GAMEPAL.OBJ is an OMF data object, not a downloaded executable.
    raw = (ID/'WOLFSRC/OBJ/GAMEPAL.OBJ').read_bytes()
    pos, out = 0, bytearray(768)
    found = 0
    while pos < len(raw):
        kind, size = struct.unpack_from('<BH',raw,pos)
        record = raw[pos+3:pos+2+size]
        pos += size+3
        if kind == 0xa0:  # LEDATA: segment index, 16-bit segment offset, bytes
            index_len = 2 if record[0]&128 else 1
            offset = struct.unpack_from('<H',record,index_len)[0]
            body = record[index_len+2:]
            if offset+len(body)>768:
                raise ValueError('palette object data exceeds 768 bytes')
            out[offset:offset+len(body)] = body; found += len(body)
    if found != 768:
        raise ValueError('palette object has incomplete data')
    # Spear replaces the last two purple shades with dark greens.
    if PROFILE.spear:
        out[166*3:168*3] = bytes((0, 14, 0, 0, 10, 0))
    return [tuple(v*4 for v in out[i:i+3]) for i in range(0,768,3)]



if __name__ == '__main__':
    levels = maps(); pages,sprites,sounds = vswap()
    print('maps:', ', '.join(m['name'] for m in levels))
    print('palette entries:',len(palette()), 'walls:',sprites, 'sprites:',sounds-sprites)
