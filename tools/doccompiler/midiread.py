"""Standard MIDI files to the shared music tools' 140 Hz event interface."""
from collections import Counter
from fractions import Fraction
from pathlib import Path
import argparse
import hashlib
import json
import struct


def _vlq(data, pos, end):
    value = 0
    for _ in range(4):
        if pos >= end:
            raise ValueError('truncated variable-length quantity')
        byte = data[pos]
        pos += 1
        value = value * 128 + (byte & 127)
        if byte < 128:
            return value, pos
    raise ValueError('variable-length quantity exceeds four bytes')


def read_midi(source):
    """Return (groups, length, metadata), retaining track order at equal times.

    Groups are (tic, [(kind, channel, a, b)]); kinds match dmxmus.parse_mus.
    Bend a is the exact 14-bit value divided by 128, centred at 64. The
    fractional part retains the MIDI LSB while old MSB consumers still work.
    All controllers, including RPN, expression and sustain, are preserved.
    Interpretation belongs to the converter, not the file reader.
    """
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    if data[:4] != b'MThd' or len(data) < 14:
        raise ValueError('missing MIDI header')
    size = int.from_bytes(data[4:8], 'big')
    if size < 6 or size + 8 > len(data):
        raise ValueError('invalid MIDI header length')
    fmt, tracks, division = struct.unpack_from('>HHH', data, 8)
    if fmt not in (0, 1) or not tracks or (fmt == 0 and tracks != 1):
        raise ValueError('only synchronous SMF formats 0 and 1 are supported')
    if not division:
        raise ValueError('zero MIDI clock division')
    frame_clock = None
    if division & 0x8000:
        fps, subframes = 256 - (division >> 8), division & 255
        if fps not in (24, 25, 29, 30) or not subframes:
            raise ValueError('invalid SMPTE clock division')
        frame_clock = (Fraction(30000, 1001) if fps == 29 else fps) * subframes
    pos = 8 + size
    events = []
    texts = []
    excluded = Counter()
    track_ends = []
    sysex = []
    for track in range(tracks):
        if data[pos:pos+4] != b'MTrk' or pos + 8 > len(data):
            raise ValueError('missing MIDI track')
        end = pos + 8 + int.from_bytes(data[pos+4:pos+8], 'big')
        pos += 8
        if end > len(data):
            raise ValueError('truncated MIDI track')
        tick = order = 0
        running = None
        ended = False
        while pos < end:
            delta, pos = _vlq(data, pos, end)
            tick += delta
            if pos >= end:
                raise ValueError('missing MIDI event')
            status = data[pos]
            if status >= 128:
                pos += 1
                running = status if status < 0xf0 else None
            elif running is not None:
                status = running
            else:
                raise ValueError('MIDI data byte without running status')
            order += 1
            if status == 0xff:
                if pos >= end:
                    raise ValueError('missing meta-event type')
                meta = data[pos]
                count, pos = _vlq(data, pos + 1, end)
                payload = data[pos:pos+count]
                pos += count
                if pos > end:
                    raise ValueError('truncated meta-event')
                if meta == 0x51:
                    if count != 3 or not int.from_bytes(payload, 'big'):
                        raise ValueError('invalid tempo event')
                    events.append((tick, track, order, ('tempo', int.from_bytes(payload, 'big'))))
                elif meta == 0x2f:
                    if count:
                        raise ValueError('invalid end-of-track event')
                    ended = True
                    pos = end
                elif 1 <= meta <= 9:
                    texts.append(dict(track=track, tick=tick, type=meta, text=payload.decode('latin1')))
                continue
            if status in (0xf0, 0xf7):
                count, pos = _vlq(data, pos, end)
                payload = data[pos:pos+count]
                pos += count
                if pos > end:
                    raise ValueError('truncated system-exclusive event')
                sysex.append(dict(track=track, tick=tick, status=status, hex=payload.hex()))
                continue
            if not 0x80 <= status <= 0xef:
                raise ValueError(f'unsupported MIDI status {status:02x}')
            command, channel = status >> 4, status & 15
            count = 1 if command in (12, 13) else 2
            payload = data[pos:pos+count]
            pos += count
            if pos > end or any(byte >= 128 for byte in payload):
                raise ValueError('invalid MIDI channel data')
            a, b = payload[0], payload[1] if count == 2 else 0
            if command == 8 or command == 9 and b == 0:
                event = ('off', channel, a, 0)
            elif command == 9:
                event = ('on', channel, a, b)
            elif command == 11:
                event = ('ctl', channel, a, b)
            elif command == 12:
                event = ('prog', channel, a, 0)
            elif command == 14:
                event = ('bend', channel, b + a / 128, 0)
            else:
                excluded[f'pressure_{command:x}'] += 1
                continue
            events.append((tick, track, order, event))
        if not ended:
            raise ValueError('track has no end-of-track marker')
        track_ends.append(tick)
    if pos != len(data):
        raise ValueError('data follows the declared MIDI tracks')
    events.sort(key=lambda item: item[:3])
    final_tick = max(track_ends)
    events.append((final_tick, tracks, 0, ('end',)))
    elapsed = Fraction(0)
    previous = 0
    tempo = 500000
    groups = []
    tempos = []
    max_error = Fraction(0)
    counts = Counter()
    for tick, track, order, event in events:
        elapsed += Fraction(tick - previous, frame_clock) if frame_clock else Fraction((tick - previous) * tempo, division * 1000000)
        previous = tick
        tic = (elapsed.numerator * 140 * 2 + elapsed.denominator) // (2 * elapsed.denominator)
        max_error = max(max_error, abs(Fraction(tic, 140) - elapsed))
        if event[0] == 'tempo':
            tempo = event[1]
            tempos.append(dict(tick=tick, track=track, microseconds_per_quarter=tempo))
        elif event[0] != 'end':
            if not groups or groups[-1][0] != tic:
                groups.append((tic, []))
            groups[-1][1].append(event)
            counts[event[0]] += 1
    metadata = dict(format=fmt, tracks=tracks, division=division, source_ticks=final_tick,
                    seconds=float(elapsed), tics=tic, max_quantization_ms=float(max_error * 1000),
                    events=dict(counts), tempos=tempos, texts=texts, sysex=sysex,
                    excluded=dict(excluded), sha256=hashlib.sha256(data).hexdigest())
    return groups, tic, metadata


def parse_midi(source):
    """The (groups, length) return convention of dmxmus.parse_mus."""
    groups, length, _ = read_midi(source)
    return groups, length


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('midi', type=Path)
    ap.add_argument('--events', action='store_true')
    args = ap.parse_args()
    groups, length, report = read_midi(args.midi)
    if args.events:
        report['groups'] = groups
    print(json.dumps(report, indent=2))
