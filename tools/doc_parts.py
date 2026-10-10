"""Authenticate instrument ownership against compiled DOC commands."""
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'doccompiler'))
import unit2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def music_writes(writes):
    return [(r, v) for r, v in writes if 4 <= (r & 31) < 28]


def decode_groups(unit, master):
    player = unit2.Player(unit, master)
    groups = []
    for _ in range(1000000):
        _, writes = player.wake()
        writes = music_writes(writes)
        if writes:
            groups.append(writes)
        if not player.y:
            return groups
    raise ValueError('compiled song did not loop')


def tagged_oracle(unit, ledger, notes, master):
    """Authenticate historical part labels against the actual compiled bank.

    The compiler can reorder independent oscillator writes within one wake.
    Compare each oscillator in order, then label the compiled order. Never
    identify a part by its GM program or substitute that program's sample.
    """
    events, onsets = defaultdict(list), defaultdict(dict)
    for line in ledger.read_text().splitlines():
        kind, tick, reg, value = line.split()
        reg, value, tick = int(reg), int(value), int(tick)
        if kind == 'W' and 4 <= (reg & 31) < 28:
            events[tick].append((reg, value))
    channels = set()
    for note in json.loads(notes.read_text()):
        channel = note['ch'] + 1
        channels.add(channel)
        for oscillator in ((note['voice'] & ~1) + 4, (note['voice'] & ~1) + 5):
            onsets[note['tic'] * 5][oscillator] = channel
    unscaled, scaled = decode_groups(unit, 15), decode_groups(unit, master)
    require(len(events) == len(unscaled) == len(scaled), 'part ledger has different wake groups')
    labels, result = {}, bytearray()
    for (tick, source), original, actual in zip(sorted(events.items()), unscaled, scaled):
        for oscillator in range(4, 28):
            require([w for w in source if w[0] & 31 == oscillator] ==
                    [w for w in original if w[0] & 31 == oscillator],
                    f'part ledger differs at tick {tick}, oscillator {oscillator}')
        labels.update(onsets[tick])
        require(len(actual) == len(original), 'master volume changed command count')
        for (reg, value), (original_reg, _) in zip(actual, original):
            require(reg == original_reg, 'master volume changed register order')
            channel = labels.get(reg & 31, 0)
            require(channel or not (0x40 <= reg < 0x60 and value),
                    'audible write has no authenticated part label')
            result.extend((reg, value, channel))
    return bytes(result), sorted(channels)


def trace_labels(writes, start, unit, ledger, notes, master):
    """Label actual engine writes; reject stale or differently ordered metadata."""
    oracle, channels = tagged_oracle(unit, ledger, notes, master)
    rows = list(zip(oracle[::3], oracle[1::3], oracle[2::3]))
    labels, index = [], 0
    for tick, reg, value in writes:
        channel = 0
        if tick >= start and 4 <= reg & 31 < 28:
            require(index < len(rows), 'engine emitted more music writes than the part ledger')
            expected_reg, expected_value, channel = rows[index]
            require((reg,value)==(expected_reg,expected_value),
                    'engine write differs from authenticated part ledger at '+str(index))
            index += 1
        labels.append(channel)
    require(index == len(rows), 'engine emitted fewer music writes than the part ledger')
    return labels, channels
