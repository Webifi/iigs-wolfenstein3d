"""Bounded MIDI and Wolf/Spear IMF score readers for offline audio recipes.

IMF supplies register writes, not MIDI orchestration. Patch keys identify the
programming of the two OPL operators; their output attenuation is excluded so
changes in playing level do not masquerade as different instruments.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
import math
import struct


def vlq(value):
    if not 0 <= value <= 0x0fffffff:
        raise ValueError('MIDI delta outside the four-byte VLQ range')
    out = [value & 127]
    while value > 127:
        value >>= 7
        out.insert(0, (value & 127) | 128)
    return bytes(out)


@dataclass
class Event:
    tick: int
    track: int
    raw: bytes
    offset: int = -1
    seconds: float = 0.0
    clock140: int = 0


def midi_read(data):
    """Return PPQN and events; offsets identify original message data bytes."""
    if len(data) < 14 or data[:4] != b'MThd':
        raise ValueError('missing MIDI header')
    size, form, tracks, division = struct.unpack_from('>IHHH', data, 4)
    if size < 6 or size + 8 > len(data) or form not in (0, 1):
        raise ValueError('unsupported or truncated MIDI header')
    if not tracks or (form == 0 and tracks != 1) or not division or division & 0x8000:
        raise ValueError('MIDI requires format 0/1 with PPQN timing')
    pos, events = size + 8, []
    for track in range(tracks):
        if data[pos:pos+4] != b'MTrk' or pos + 8 > len(data):
            raise ValueError('missing MIDI track')
        end = pos + 8 + struct.unpack_from('>I', data, pos+4)[0]
        pos += 8
        if end > len(data):
            raise ValueError('truncated MIDI track')

        def take(n):
            nonlocal pos
            if pos + n > end:
                raise ValueError('truncated MIDI event')
            result = data[pos:pos+n]
            pos += n
            return result

        def variable():
            result = 0
            for _ in range(4):
                byte = take(1)[0]
                result = result * 128 + (byte & 127)
                if not byte & 128:
                    return result
            raise ValueError('MIDI VLQ exceeds four bytes')

        tick, running, ended = 0, None, False
        while pos < end:
            tick += variable()
            byte = take(1)[0]
            if byte < 128:
                if running is None:
                    raise ValueError('MIDI running status without a channel status')
                status = running
                pos -= 1
            else:
                status = byte
            offset = pos
            if 0x80 <= status <= 0xef:
                running = status
                payload = take(1 if status & 0xf0 in (0xc0, 0xd0) else 2)
                if any(v > 127 for v in payload):
                    raise ValueError('MIDI channel data contains a status byte')
                raw = bytes([status]) + payload
            elif status in (0xf0, 0xf7, 0xff):
                running = None
                kind = take(1) if status == 0xff else b''
                length = variable()
                payload = take(length)
                raw = bytes([status]) + kind + vlq(length) + payload
                if kind == b'\x2f':
                    if length or pos != end:
                        raise ValueError('invalid MIDI end-of-track')
                    ended = True
            else:
                raise ValueError('unsupported system status in MIDI track')
            events.append(Event(tick, track, raw, offset))
        if not ended:
            raise ValueError('MIDI track has no end-of-track')
    if pos != len(data):
        raise ValueError('unexpected bytes after MIDI tracks')
    events.sort(key=lambda e: (e.tick, e.track))
    previous, seconds, tempo = 0, 0.0, 500000
    exact_seconds = Fraction(0)
    for event in events:
        exact_seconds += Fraction((event.tick - previous) * tempo, division * 1000000)
        seconds += (event.tick - previous) * tempo / (division * 1000000)
        previous, event.seconds = event.tick, seconds
        event.clock140 = (exact_seconds.numerator * 280 + exact_seconds.denominator) // (2 * exact_seconds.denominator)
        if event.raw[:2] == b'\xff\x51':
            if len(event.raw) != 6 or event.raw[2] != 3:
                raise ValueError('invalid MIDI tempo event')
            tempo = int.from_bytes(event.raw[3:], 'big')
            if not tempo:
                raise ValueError('zero MIDI tempo')
    return division, events


def midi_write(division, events):
    """Write a format-0 file, preserving order among events at the same tick."""
    output, previous = bytearray(), 0
    end = max((e.tick for e in events), default=0)
    for event in sorted(events, key=lambda e: e.tick):
        if event.raw[:2] == b'\xff\x2f':
            continue
        output += vlq(event.tick - previous) + event.raw
        previous = event.tick
    output += vlq(end - previous) + b'\xff\x2f\x00'
    return b'MThd' + struct.pack('>IHHH', 6, 0, 1, division) + b'MTrk' + struct.pack('>I', len(output)) + output


def midi_notes(data):
    _, events = midi_read(data)
    programs, banks = [0]*16, [[0, 0] for _ in range(16)]
    active, notes = defaultdict(deque), []
    for event in events:
        raw, tick = event.raw, event.tick
        status, channel = raw[0] & 0xf0, raw[0] & 15
        if status == 0xc0:
            programs[channel] = raw[1]
        elif status == 0xb0 and raw[1] in (0, 32):
            banks[channel][raw[1] == 32] = raw[2]
        elif status == 0x90 and raw[2]:
            active[channel, raw[1]].append(dict(start=event.seconds, tick=tick,
                clock140=event.clock140,
                channel=channel+1, key=raw[1], velocity=raw[2], program=programs[channel]+1,
                bank=tuple(banks[channel])))
        elif status == 0x80 or (status == 0x90 and not raw[2]):
            if active[channel, raw[1]]:
                note = active[channel, raw[1]].popleft()
                note.update(end=event.seconds, end_tick=tick)
                notes.append(note)
    if any(active.values()):
        raise ValueError('MIDI has unterminated notes')
    return sorted(notes, key=lambda n: (n['start'], n['channel'], n['key']))


OPERATORS = (0, 1, 2, 8, 9, 10, 16, 17, 18)
OPL_RATE = 3579545 / 72


def patch_bytes(registers, channel):
    op = OPERATORS[channel]
    return bytes([registers[base+slot] for base in (0x20, 0x40, 0x60, 0x80, 0xe0)
                  for slot in (op, op+3)] + [registers[0xc0+channel] & 15])


def patch_key(patch):
    out = bytearray(patch)
    out[3] &= 0xc0  # Carrier attenuation is playing level, not patch identity.
    if out[10] & 1:
        out[2] &= 0xc0  # Both operators are outputs in additive mode.
    return out.hex()


def imf_read(data):
    if len(data) < 2:
        raise ValueError('truncated length-prefixed IMF')
    size = struct.unpack_from('<H', data)[0]
    if not size or size % 4 or size + 2 > len(data):
        raise ValueError('invalid length-prefixed IMF')
    # DOS chunks may carry padding beyond the declared music length.
    tick, events = 0, []
    for register, value, delay in struct.iter_unpack('<BBH', data[2:2+size]):
        events.append((tick, register, value))
        tick += delay
    # The DOS player restarts on the interrupt after the final write; it does
    # not wait for that write's trailing delay (ID_SD.C SDL_ALService).
    return events, events[-1][0]+1


def imf_notes(data):
    events, end_tick = imf_read(data)
    registers = bytearray(256)
    active, notes, warnings = {}, [], set()

    def pitch(channel):
        high = registers[0xb0+channel]
        fnum = registers[0xa0+channel] | ((high & 3) << 8)
        hz = OPL_RATE * fnum * 2**(((high >> 2) & 7)-20)
        return 69 + 12*math.log2(hz/440) if hz else None

    def close(channel, tick):
        if channel in active:
            note = active.pop(channel)
            note.update(end=tick/700, end_tick=tick)
            if tick > note['tick']:
                notes.append(note)

    for tick, register, value in events:
        old = registers[register]
        registers[register] = value
        if register == 0xbd and value & 0x20:
            warnings.add('OPL hardware rhythm mode needs a separate decoder')
        if 0xb0 <= register <= 0xb8:
            channel = register-0xb0
            if old & 0x20 and not value & 0x20:
                close(channel, tick)
            elif value & 0x20 and not old & 0x20:
                key = pitch(channel)
                if key is None:
                    warnings.add('zero-frequency key-on')
                    continue
                patch = patch_bytes(registers, channel)
                active[channel] = dict(start=tick/700, tick=tick, channel=channel+1,
                    key=round(key), pitch=key, patch=patch_key(patch), raw_patch=patch.hex(),
                    attenuation=patch[3] & 63, bends=[])
        if 0xa0 <= register <= 0xa8 or 0xb0 <= register <= 0xb8:
            channel = register & 15
            if channel in active and pitch(channel) is not None:
                note = active[channel]
                bend = (tick, pitch(channel))
                if tick == note['tick']:
                    note['pitch'], note['key'] = bend[1], round(bend[1])
                elif note['bends'] and note['bends'][-1][0] == tick:
                    note['bends'][-1] = bend
                else:
                    note['bends'].append(bend)
        # Report timbre changes while a key is held; do not quietly drop them.
        for channel, note in active.items():
            if patch_key(patch_bytes(registers, channel)) != note['patch']:
                warnings.add('OPL patch changes during a held note')
    for channel in list(active):
        close(channel, end_tick)
    return sorted(notes, key=lambda n: (n['tick'], n['channel'])), end_tick, sorted(warnings)
