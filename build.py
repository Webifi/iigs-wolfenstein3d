#!/usr/bin/env python3
"""Portable entry point; use Python 3.9+ (Windows: py -3 build.py)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent/'tools'))
from consumer_build import main

if __name__ == '__main__':
    main()
