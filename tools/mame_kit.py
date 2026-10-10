"""The one MAME build that every tool starts. A new kit is a change of tools/mame-local.json only.

Start it by this binary path with full arguments (never open, Finder or the Dock), headless and silent:
SDL_MAC_BACKGROUND_APP=1, SDL_VIDEODRIVER=dummy, SDL_AUDIODRIVER=dummy, -video none -sound none.
Timings of two kits are not compared: take a new baseline when this changes.

The kit is local to each machine. tools/mame-local.json (Git ignores it) or the environment
gives it: {"name": ..., "binary": ..., "rompath": ...} or WOLF_MAME_NAME, WOLF_MAME, WOLF_MAME_ROMPATH.
Without them the tools start `mame` with the ROM folder `roms`.
"""
import json
import os
from pathlib import Path

_local = Path(__file__).resolve().parent / 'mame-local.json'
_kit = json.loads(_local.read_text()) if _local.exists() else {}
NAME = os.environ.get('WOLF_MAME_NAME', _kit.get('name', 'mame'))
BINARY = os.environ.get('WOLF_MAME', _kit.get('binary', 'mame'))
ROMPATH = os.environ.get('WOLF_MAME_ROMPATH', _kit.get('rompath', 'roms'))
