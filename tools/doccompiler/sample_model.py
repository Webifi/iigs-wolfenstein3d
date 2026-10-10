"""Verified aliases between performed programs and stored sample models."""
from functools import lru_cache
from pathlib import Path

from game_profile import read_toml

CONFIG = Path(__file__).resolve().parents[2] / 'profiles/audio/sample-models.toml'


@lru_cache(None)
def aliases():
    doc = read_toml(CONFIG)
    if doc['format'] != 1:
        raise ValueError('unsupported sample model mapping format')
    rows = {}
    for row in doc['alias']:
        key = row['soundfont_sha256'], row['bank'], row['performed_program'] - 1
        if key in rows or not row['reason'].strip():
            raise ValueError('duplicate or unexplained sample model alias')
        rows[key] = row['model_program'] - 1
    return rows


def resolve(font, bank, program, source_sha256=None):
    if (bank, program) in font.presets:
        return program
    mapped = aliases().get((source_sha256, bank, program))
    if mapped is None or (bank, mapped) not in font.presets:
        raise ValueError(f'missing SoundFont preset {bank,program}; no verified sample model alias')
    return mapped
