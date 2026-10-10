"""Export encoded DOC samples and register-stream tags for host previews.

Tags use MIDI channel 1..16, or 128 plus the drum key.
"""
import argparse
import json
import sys
from pathlib import Path

import convert, musbank, mussc, muspan, sf2
from midiread import read_midi


def tag_of(note):
    if note.preset[0] == 128:
        return 128 + note.key
    return note.ch + 1


def doc_image(s):
    doc = bytearray([128]) * (256 * (244 - s.low))

    def place(page, table):
        offset = (page - s.low) * 256
        assert offset >= 0 and offset + len(table) <= len(doc)
        doc[offset:offset + len(table)] = table
    for i, zone in enumerate(s.zones):
        place(s.pages[i], zone.table)
        if zone.kind == 'attack':
            place(s.lpages[i], zone.ltable)
    for zone in s.extra_tables:
        place(zone.page, zone.table)
    return doc
