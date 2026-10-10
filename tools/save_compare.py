#!/usr/bin/env python3
"""Compatibility entry point for tools/check_saved_world.py.

Both commands use one cold-save comparison, with the same first frame
in both runs. python3 tools/save_compare.py hd|flop2|flop1 runs it under the name
save-compare-MEDIA; the code stops are the labels gsPhaseSave, gsPhaseLoad,
gsPhaseDone and gsWorldRestored of src/iigs/gamesave.s.
"""
import subprocess
import sys
from pathlib import Path

if len(sys.argv) != 2 or sys.argv[1] not in ("hd", "flop2", "flop1"):
    raise SystemExit("media is hd, flop2 or flop1")
here = Path(__file__).resolve().parent
sys.exit(subprocess.call([sys.executable, str(here / "check_saved_world.py"), sys.argv[1], "--name", "save-compare-" + sys.argv[1]]))
