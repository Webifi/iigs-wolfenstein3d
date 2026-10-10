"""Floppy layout plan: which floors go on which disk so that a floor load reads one disk.

Each data disk holds the complete loads of consecutive floors (in play order): the floor's
units, its weapon groups (all views) and game group, the demo inputs of its floors, and one
copy of the groups any floor's play may load (view weights, the in-game pause pages, the
title-menu UI and the songs that no floor loads). A unit that several floors of one disk
load is stored once on that disk.

Usage: python3 tools/disk_plan.py [episode.json] [--capacity BLOCKS] [--limit DISKS]
The store build (build_registered_episode.py) calls plan() and fails over the limit.
"""
import collections
import json
import sys
from pathlib import Path

from registered_loads import AUX_WEAPONS_BASE, AUX_UI, AUX_GAME_BASE, AUX_DEMOS_BASE

DISK_DATA_BLOCKS = 1577          # tools/mkdisk.py: data blocks of a data disk
LIST_BLOCKS = 3                  # record lists for one floor and its groups


def plan(rows, floors=60, capacity=DISK_DATA_BLOCKS, demo_floors=()):
    """rows: store manifest rows (group, first_block, blocks). Returns the packs."""
    size, groups = {}, collections.defaultdict(set)
    for r in rows:
        size[r['first_block']] = r['blocks']
        groups[r['group']].add(r['first_block'])
    local = set()
    per_floor = set()
    for f in range(floors):
        per_floor |= {f'aux/{AUX_WEAPONS_BASE + f * 4 + v}' for v in range(4)} | {f'aux/{AUX_GAME_BASE + f}'}
    for g in groups:
        kind, n = g.split('/')
        n = int(n)
        if g.startswith('floor/') or g in per_floor or (kind == 'aux' and AUX_DEMOS_BASE <= n < AUX_DEMOS_BASE + 4):
            continue
        if kind == 'music' and any(g2.startswith('floor/') for g2 in groups if groups[g2] & groups[g]):
            continue
        local |= groups[g]
    demos = collections.defaultdict(set)
    for d, f in enumerate(demo_floors):
        demos[f] |= groups.get(f'aux/{AUX_DEMOS_BASE + d}', set())

    def load(f):
        s = set(groups[f'floor/{f}']) | groups[f'aux/{AUX_GAME_BASE + f}'] | demos[f]
        for v in range(4):
            s |= groups[f'aux/{AUX_WEAPONS_BASE + f * 4 + v}']
        return s

    def cost(units, count):
        return sum(size[k] for k in units | local) + LIST_BLOCKS * count + 2

    packs, current, members = [], set(), []
    for f in range(floors):
        units = load(f)
        if members and cost(current | units, len(members) + 1) > capacity:
            packs.append(dict(floors=members, blocks=cost(current, len(members))))
            current, members = set(), []
        current |= units
        members.append(f)
        if cost(current, len(members)) > capacity:
            packs.append(dict(floors=members, blocks=cost(current, len(members)), over=True))
            current, members = set(), []
    if members:
        packs.append(dict(floors=members, blocks=cost(current, len(members))))
    return dict(packs=packs, local_blocks=sum(size[k] for k in local),
                floor_blocks={f: sum(size[k] for k in load(f)) for f in range(floors)})


def main():
    args = sys.argv[1:]
    path = Path(args[0]) if args and not args[0].startswith('--') else Path('build/assets/episode.json')
    capacity = int(args[args.index('--capacity') + 1]) if '--capacity' in args else DISK_DATA_BLOCKS
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else None
    demo_floors = ()
    source = Path('build/assets/demo-source.json')
    if source.exists():
        demo_floors = tuple(d['floor'] for d in json.loads(source.read_text())['demos'])
    from wolfdata import PROFILE
    result = plan(json.loads(path.read_text()), floors=PROFILE.floors, capacity=capacity, demo_floors=demo_floors)
    packs = result['packs']
    print(f'data disks {len(packs)} (+ the boot disk); copies on each disk: {result["local_blocks"]} blocks')
    for i, p in enumerate(packs):
        print(f'  disk {i + 2}: floors {p["floors"][0] + 1}-{p["floors"][-1] + 1}, {p["blocks"]} blocks' + (' OVER ONE DISK' if p.get('over') else ''))
    sizes = sorted(result['floor_blocks'].values())
    print(f'one floor load: {sizes[0]}-{sizes[-1]} blocks, median {sizes[len(sizes) // 2]}')
    if limit is not None and len(packs) + 1 > limit:
        sys.exit(f'{len(packs) + 1} disks, more than the limit {limit}')


if __name__ == '__main__':
    main()
