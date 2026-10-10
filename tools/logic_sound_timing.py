"""Source sound timing that affects Wolf's game logic, independent of PCM quality."""
from functools import lru_cache
import struct

from effect_sources import source_effects
from wolfdata import PROFILE, source_data


@lru_cache(maxsize=1)
def face_sound():
    effects = source_effects(source_data())
    pickup = next(row for row in effects if row['name'] == 'GETGATLINGSND')
    length = struct.unpack_from('<I', pickup['adlib'])[0]
    # The source AdLib service consumes one byte at 140 Hz; gameplay is 70 Hz.
    ticks = (length + 1) // 2
    if PROFILE.spear and pickup['digitized'] >= 0:
        # SB digitized playback does not set the AdLib SoundNumber queried by UpdateFace.
        return dict(id=pickup['id'], ticks=0, priority=pickup['priority'],
                    preempt=[], adlib_bytes=length)
    if not 0 < ticks <= 32767 or pickup['digitized'] >= 0:
        raise ValueError('unsupported source chaingun face-sound timing')
    preempt = [row['id'] for row in effects if row['digitized'] < 0 and
               row['priority'] >= pickup['priority'] and row['id'] != pickup['id']]
    return dict(id=pickup['id'], ticks=ticks, priority=pickup['priority'],
                preempt=preempt, adlib_bytes=length)


def gate_assembly():
    lines = [';;; Only accepted non-digitized requests replace DOS SoundNumber.']
    for ident in face_sound()['preempt']:
        lines += ['              cmp ##%d' % ident,
                  '              beq soundGateStop']
    lines += ['              bra soundGateDone',
              'soundGateStop:stz abs:V_gatling']
    return '\n'.join(lines) + '\n'
