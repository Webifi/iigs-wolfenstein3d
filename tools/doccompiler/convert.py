"""Build Wolf sampled music with read-only shared SoundFont conversion tools."""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import sys

from midiread import read_midi
import mussc, musbank, muspan, sf2


def adapt(groups, captured=False, performed_pan=False):
    """Apply the MIDI controls absent from the MUS-only consumer interface."""
    from audio_performance_pan import dynamic_keys
    dynamic=dynamic_keys(groups)
    if dynamic and not performed_pan:
        raise ValueError("dynamic drum pan needs complete-track PCM pan observations")
    volume = [100] * 16
    expression = [127] * 16
    bend_range = [2.] * 16
    bend_semitones,bend_cents=[2]*16,[0]*16
    bends = [64.] * 16
    parameter = [{True: [127, 127], False: [127, 127]} for _ in range(16)]
    registered_parameter = [True] * 16
    output = []
    kits = {0}
    drum_pan = {}
    played_drums = set()
    for tic, events in groups:
        converted = []
        for kind, ch, a, b in events:
            if kind == 'prog' and ch == 9:
                if played_drums and a not in kits:
                    raise ValueError('drum-kit changes after song start need per-note kit allocation')
                kits = {a}
            if kind == 'ctl':
                if a==121:
                    expression[ch]=127
                    bends[ch]=64.
                    parameter[ch]={True:[127,127],False:[127,127]}
                    registered_parameter[ch]=True
                    converted.extend([('ctl',ch,7,volume[ch]),('ctl',ch,1,0),('bend',ch,64.,0)])
                    continue
                if a in (7, 11):
                    (volume if a == 7 else expression)[ch] = b
                    converted.append(('ctl', ch, 7, volume[ch] * expression[ch] / 127))
                    continue
                if a in (98, 99, 100, 101):
                    registered_parameter[ch] = a in (100, 101)
                    parameter[ch][registered_parameter[ch]][0 if a in (99, 101) else 1] = b
                if a in (6,38):
                    registered = registered_parameter[ch]
                    msb, lsb = parameter[ch][registered]
                    if registered and (msb, lsb) == (0, 0):
                        (bend_semitones if a==6 else bend_cents)[ch]=b
                        bend_range[ch] = bend_semitones[ch]+bend_cents[ch]/100.
                        converted.append(('bend', ch, 64 + (bends[ch]-64) * bend_range[ch]/2, 0))
                    elif not registered and ch == 9 and msb == 28 and a==6:
                        if lsb not in dynamic:drum_pan[lsb] = b
                    elif captured and not registered and msb in (24,26,28,29):
                        # Played key pitch/level/reverb are already in its
                        # actual emulator capture, grouped by NRPN context.
                        pass
                    elif (msb, lsb) != (127, 127):
                        raise ValueError(f'unhandled parameter data at {tic}: {ch,msb,lsb,registered,b}')
                if a == 64 and b:
                    raise ValueError('sustain pedal needs deferred note-off adapter')
            if kind == 'bend':
                bends[ch] = a
                a = 64 + (a - 64) * bend_range[ch] / 2
            if kind == 'on' and ch == 9:
                played_drums.add(a)
            converted.append((kind, ch, a, b))
        if converted:
            output.append((tic, converted))
    return output, next(iter(kits)), drum_pan


class Font:
    def __init__(self, font, kit, drum_pan, source_sha256=None):
        self.font, self.kit, self.drum_pan = font, kit, drum_pan
        self.source_sha256 = source_sha256
        self.model_aliases = {}

    def __getattr__(self, name):
        return getattr(self.font, name)

    def regions(self, bank, program, key, velocity):
        if bank == 128:
            program = self.kit
        from sample_model import resolve
        modeled = resolve(self.font, bank, program, self.source_sha256)
        if modeled != program:
            self.model_aliases[bank, program] = modeled
        program = modeled
        regions = self.font.regions(bank, program, key, velocity)
        if bank == 128 and key in self.drum_pan:
            for r in regions:
                r.pan = (self.drum_pan[key] - 64) / 128
        return regions


class WolfSong(mussc.ScSong):
    def layout(self):
        """Keep native DOC table alignment below page $F4."""
        items = []
        self.pages = [None] * len(self.zones)
        self.lpages = [None] * len(self.zones)
        for index, zone in enumerate(self.zones):
            if getattr(zone, 'alias_of', None) is not None:
                continue
            items.append((zone.size//256, len(zone.table), self.pages, index))
            if zone.kind == 'attack':
                items.append((zone.loop_len//256, len(zone.ltable), self.lpages, index))
        extras = [None] * len(self.extra_tables)
        items += [(1, len(zone.table), extras, i) for i, zone in enumerate(self.extra_tables)]
        occupied = 0
        for alignment, count, array, index in sorted(items, key=lambda item: (-item[0], -item[1])):
            pages = (count + 255)//256
            mask = (1 << pages) - 1
            for page in range(((244-pages)//alignment)*alignment, -1, -alignment):
                if not occupied & (mask << page):
                    occupied |= mask << page
                    array[index] = page
                    break
            else:
                raise ValueError('instrument image exceeds DOC RAM')
        for zone, page in zip(self.extra_tables, extras):
            zone.page = page
        for i, zone in enumerate(self.zones):
            alias = getattr(zone, 'alias_of', None)
            if alias is not None:
                self.pages[i] = self.lpages[i] = self.lpages[self.zones.index(alias)]
        for zone in self.zones:
            for member in getattr(zone, 'morph_family', []):
                if getattr(member, 'extra_page', False) and getattr(member, 'alias_of', None) is not None:
                    member.page = self.lpages[self.zones.index(member.alias_of)]
        self.low = (occupied & -occupied).bit_length()-1 if occupied else 244
