#!/usr/bin/env python3
"""Build this game from game-data/ with optional output/source-build overrides."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'tools'))
from consumer_build import main
if __name__ == '__main__':
    sys.argv[1:1] = ['--game', 'wolf3d']
    main()
