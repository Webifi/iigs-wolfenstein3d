"""Apply established instrument choices before optional recipe overrides.

MIDI defaults match the complete timed score, independently of its instrument
assignments or container metadata. IMF defaults match the original source and
its part, so a patch used for different roles cannot overwrite a chosen voice.
"""
from collections import defaultdict, deque
import hashlib
import json

from game_profile import fields, integer
from music_score import Event, midi_read, midi_write, midi_notes
from music_mapping import MAPPING_FIELDS, compare, identity


def digest(data):
    return hashlib.sha256(data).hexdigest()


def score_identity(data):
    # Velocity and controls remain in the input performance. Neither changes
    # the identity of an already orchestrated part. No source notes are stored
    # in the shipped defaults catalog.
    score = [(n['channel'], n['key'], round(n['start']*1000000),
              round(n['end']*1000000)) for n in midi_notes(data)]
    return digest(json.dumps(score, separators=(',', ':')).encode())


def validate_defaults(doc):
    fields(doc, ('format', 'song'), 'instrument defaults')
    integer(doc['format'], 1, 1, 'instrument defaults format')
    midi_seen, imf_seen = set(), set()
    for song in doc['song']:
        fields(song, ('name', 'authority', 'imf_sha256', 'midi_sha256',
                      'midi_score_sha256', 'midi', 'imf'), 'default song')
        for key in ('imf_sha256', 'midi_sha256', 'midi_score_sha256'):
            value = song[key]
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('invalid defaults '+key)
        if song['midi_score_sha256'] in midi_seen or song['imf_sha256'] in imf_seen:
            raise ValueError('duplicate source in instrument defaults')
        midi_seen.add(song['midi_score_sha256']); imf_seen.add(song['imf_sha256'])
        starts = defaultdict(list)
        for part in song['midi']:
            fields(part, ('channel', 'first_note', 'program', 'bank_msb', 'bank_lsb'), 'MIDI default')
            integer(part['channel'], 1, 16, 'default channel')
            integer(part['first_note'], 1, 10000000, 'default first_note')
            starts[part['channel']].append(part['first_note'])
            validate_instrument(part)
        for values in starts.values():
            if values[0] != 1 or values != sorted(set(values)):
                raise ValueError('default MIDI runs must start at note 1 and increase')
        parts = set()
        for part in song['imf']:
            fields(part, ('patch', 'opl_channel')+MAPPING_FIELDS, 'IMF default')
            integer(part['opl_channel'], 1, 9, 'default opl_channel')
            if not isinstance(part['patch'], str) or len(part['patch']) != 22 or any(c not in '0123456789abcdef' for c in part['patch']):
                raise ValueError('invalid default IMF patch')
            key = part['patch'], part['opl_channel']
            if key in parts:
                raise ValueError('duplicate IMF default part')
            parts.add(key)
            validate_instrument(part)
            integer(part['drum_key'], -1, 127, 'default drum_key')
            integer(part['transpose'], -48, 48, 'default transpose')
    return doc


def validate_instrument(part):
    integer(part['program'], 1, 128, 'default program')
    integer(part['bank_msb'], 0, 127, 'default bank_msb')
    integer(part['bank_lsb'], 0, 127, 'default bank_lsb')


def default_song(pair, raw, selected, fm):
    """Extract choices from a selected arrangement, without choosing new ones."""
    if digest(raw) != pair['imf_sha256'] or digest(selected) != pair['midi_sha256']:
        raise ValueError('default reference differs from the selected source hashes')
    notes = midi_notes(selected)
    counters, last, parts = defaultdict(int), {}, []
    for note in notes:
        ch = note['channel']; counters[ch] += 1
        choice = note['program'], *note['bank']
        if last.get(ch) != choice:
            parts.append(dict(channel=ch, first_note=counters[ch], program=choice[0],
                              bank_msb=choice[1], bank_lsb=choice[2]))
            last[ch] = choice
    report = compare(fm, notes, pair['name'], pair['authority'], pair['part'])
    observed = defaultdict(set)
    for observation in report['observations']:
        key = observation['patch'], observation['opl_channel']
        observed[key].update(identity(c) for c in observation['candidates'])
    imf = [dict(patch=patch, opl_channel=channel, **dict(zip(MAPPING_FIELDS, next(iter(choices)))))
           for (patch, channel), choices in sorted(observed.items(), key=lambda row: (row[0][1], row[0][0]))
           if len(choices) == 1]
    return dict(name=pair['name'], authority=pair['authority'], imf_sha256=digest(raw),
                midi_sha256=digest(selected), midi_score_sha256=score_identity(selected),
                midi=sorted(parts, key=lambda part: (part['channel'], part['first_note'])), imf=imf), report


def imf_defaults(raw, defaults):
    source_hash = digest(raw)
    for song in defaults['song']:
        if song['imf_sha256'] == source_hash:
            return {(part['patch'], part['opl_channel']): {key: part[key] for key in MAPPING_FIELDS}
                    for part in song['imf']}, song['name']
    return {}, None


def midi_defaults(data, defaults, song_name=None):
    source_score = score_identity(data)
    song = next((s for s in defaults['song'] if s['midi_score_sha256'] == source_score), None)
    expected = next((s for s in defaults['song'] if s['name'] == song_name), None)
    if expected is not None and song is not expected:
        raise ValueError(song_name+': alternate MIDI score does not match its established instrument defaults; '
                         'use the selected MIDI source or provide a paired custom --instrument-defaults catalog')
    if song is None:
        return data, None
    runs = defaultdict(list)
    for part in song['midi']:
        runs[part['channel']].append(part)
    counters, targets, run_indexes = defaultdict(int), defaultdict(deque), defaultdict(int)
    used_runs = set()
    for note in midi_notes(data):
        ch = note['channel']; counters[ch] += 1
        if ch not in runs:
            raise ValueError('instrument defaults omit a MIDI channel')
        index = run_indexes[ch]
        while index+1 < len(runs[ch]) and runs[ch][index+1]['first_note'] <= counters[ch]:
            index += 1
        run_indexes[ch] = index; used_runs.add((ch, index))
        part = runs[ch][index]
        targets[note['tick'], ch-1, note['key']].append((part['program']-1, part['bank_msb'], part['bank_lsb']))
    if len(used_runs) != sum(map(len, runs.values())):
        raise ValueError('instrument defaults contain a run outside the MIDI score')

    division, events = midi_read(data)
    current = [[0, 0, 0] for _ in range(16)]
    offsets = [[None, None, None] for _ in range(16)]
    edits, desired, rebuild = {}, {}, False
    for index, event in enumerate(events):
        raw = event.raw; kind, ch = raw[0] & 0xf0, raw[0] & 15
        if kind == 0xc0:
            current[ch][0] = raw[1]; offsets[ch][0] = event.offset
        elif kind == 0xb0 and raw[1] in (0, 32):
            slot = 1 if raw[1] == 0 else 2
            current[ch][slot] = raw[2]; offsets[ch][slot] = event.offset+1
        elif kind == 0x90 and raw[2]:
            choice = targets[event.tick, ch, raw[1]].popleft()
            desired[index] = choice
            for slot, value in enumerate(choice):
                offset = offsets[ch][slot]
                if offset is None:
                    rebuild |= current[ch][slot] != value
                elif offset in edits and edits[offset] != value:
                    rebuild = True
                else:
                    edits[offset] = value
    if not rebuild:
        mapped = bytearray(data)
        for offset, value in edits.items():
            mapped[offset] = value
        return bytes(mapped), song['name']

    # A source may omit program messages or reuse one across two chosen
    # instruments. Insert only the required selections before their note-ons.
    output, last = [], {}
    for index, event in enumerate(events):
        raw = event.raw; kind, ch = raw[0] & 0xf0, raw[0] & 15
        if kind == 0xc0 or (kind == 0xb0 and raw[1] in (0, 32)):
            continue
        if index in desired and last.get(ch) != desired[index]:
            program, msb, lsb = desired[index]
            output.extend(Event(event.tick, 0, bytes(message)) for message in
                          ((0xb0+ch, 0, msb), (0xb0+ch, 32, lsb), (0xc0+ch, program)))
            last[ch] = desired[index]
        output.append(event)
    return midi_write(division, output), song['name']
