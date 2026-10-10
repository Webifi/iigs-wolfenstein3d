"""Require every spawned actor state, item drop and weapon in each floor's art."""
import argparse
import json
from pathlib import Path

from wolfdata import ROOT, PROFILE, maps
from wolf_source import sprite_ids
import wolfsim as w


def coverage(floor):
    from floor_art import shapes
    actors, objects, weapons = shapes(maps()[floor])
    needed = actors | objects | weapons
    actual = set(map(int, json.loads((ROOT/f'build/levels/{floor}/sprites.json').read_text())))
    missing = sorted(needed-actual)
    return dict(floor=floor, required=len(needed), present=len(actual), missing_shapes=missing)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, default=ROOT / 'build/art-coverage.json')
    args = ap.parse_args()
    rows = [coverage(floor) for floor in range(PROFILE.floors)]
    args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))
    if any(row['missing_shapes'] for row in rows):
        raise SystemExit('floor art is missing reachable shapes')
