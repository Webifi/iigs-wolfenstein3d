"""Preserved conversion inputs for known, selected MIDI performances."""
import hashlib
import json
from pathlib import Path

from game_profile import read_toml, fields, integer, number
from music_score import midi_notes, midi_read

DEFAULTS = Path(__file__).resolve().parents[1]/'profiles/audio/conversion-defaults.toml'


def performance_identity(data):
    notes = [[n[k] for k in ('channel','key','velocity','program','bank','clock140','start','end')]
             for n in midi_notes(data)]
    controls = [(e.clock140,e.raw.hex()) for e in midi_read(data)[1]
                if e.raw[0]&0xf0 in (0xb0,0xe0) or e.raw[0] in (0xf0,0xf7)]
    return hashlib.sha256(json.dumps([notes,controls],separators=(',',':')).encode()).hexdigest()


def conversion_default(data, name, path=DEFAULTS):
    doc = read_toml(path)
    fields(dict({'loop_layout':'full'},**doc),('format','song','loop_layout'),'conversion defaults')
    layout=doc.get('loop_layout','full')
    if layout not in ('full','repeated-endpoint'):raise ValueError('unknown conversion loop layout')
    integer(doc['format'],1,1,'conversion defaults format')
    identity = performance_identity(data)
    for row in doc['song']:
        fields(dict({'levels':{},'pan':{},'capture':[],'song_gain_steps':None,'quality':{}},**row),('name','performance_sha256','levels','pan','capture','song_gain_steps','quality'),'conversion song')
        if row['name'] != name or row['performance_sha256'] != identity:
            continue
        for key,value in row.get('levels',{}).items():
            if not (key.startswith('ch') or key.startswith('k')):
                raise ValueError('invalid conversion level key: '+key)
            number(value,-48,48,'conversion level')
        for value in row.get('pan',{}).values():
            integer(value,0,127,'conversion pan')
        if 'song_gain_steps' in row:
            integer(row['song_gain_steps'],0,126,'song gain')
        return dict(row,loop_layout=layout)
    return None
