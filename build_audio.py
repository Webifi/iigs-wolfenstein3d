#!/usr/bin/env python3
"""Produce music, portable intermediaries, native images and listening comparisons."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'tools'))
from audio_complete import main

if __name__ == '__main__':
    main()
