"""Summarize paired captures without hiding changed visibility or activation.

Player/game fields, actor motion/combat, other flag bits and RNG values are
checked independently of visibility/activation and cached projection fields.
Pictures and wall arrays remain independent bug finders for a quality trial.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from demo_check import PLAYER_FIELDS, GAME_FIELDS, ACTOR_FIELDS


def states(folder):
    with (folder/'mame.log').open() as log:
        return [json.loads(line[6:]) for line in log if line.startswith('STATE ')]


def case(before, after, view, demo):
    folders = [Path('build/tests')/f'{prefix}-{view}-{demo}' for prefix in (before, after)]
    measures = [json.loads((folder/'measure.json').read_text()) for folder in folders]
    old, new = map(states, folders)
    assert len(old) == len(new) == measures[0]['frames'] == measures[1]['frames']
    differences = Counter()
    first = {}
    for frame, (a, b) in enumerate(zip(old, new), 1):
        fields = [(key, a[key] != b[key]) for key in PLAYER_FIELDS+GAME_FIELDS+('doors', 'pwall')]
        fields.append(('actor_count', len(a['actors']) != len(b['actors'])))
        for x, y in zip(a['actors'], b['actors']):
            if x == y:
                continue
            for index, name in enumerate(ACTOR_FIELDS):
                if index == 6:
                    fields.extend([('visibility_lost', bool(x[6] & 8) and not y[6] & 8),
                                   ('visibility_added', bool(y[6] & 8) and not x[6] & 8),
                                   ('actor_other_flags', (x[6] & ~8) != (y[6] & ~8))])
                else:
                    fields.append(('actor_'+name, x[index] != y[index]))
        for key, changed in fields:
            if changed:
                differences[key] += 1
                first.setdefault(key, frame)
    captures = [(folder/'frames.shr').read_bytes() for folder in folders]
    assert all(len(c) == len(old)*32768 for c in captures)
    geometry = []
    for i in range(len(old)):
        start = i*32768
        a, b = [c[start:start+32200] for c in captures]
        if a != b:
            geometry.append(dict(frame=i+1, changed_bytes=sum(x != y for x, y in zip(a, b))))
    walls = [(folder/'ray-posts.bin').read_bytes() for folder in folders]
    assert len(walls[0]) == len(walls[1]) == len(old)*view*4
    changed_wall_blocks = sum(walls[0][i:i+view] != walls[1][i:i+view]
                              for i in range(0, len(walls[0]), view))
    return dict(view=view, demo=demo, frames=len(old),
                before_top20_ms=measures[0]['worst20_mean_ms'],
                after_top20_ms=measures[1]['worst20_mean_ms'],
                gain_ms=measures[0]['worst20_mean_ms']-measures[1]['worst20_mean_ms'],
                before_mean_ms=measures[0]['mean_ms'], after_mean_ms=measures[1]['mean_ms'],
                changed_fields=dict(differences), first_changes=first,
                changed_geometry=geometry, changed_wall_blocks=changed_wall_blocks,
                quality=measures[1]['quality'],
                before_phases=measures[0]['top20_phases'], after_phases=measures[1]['top20_phases'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('before')
    ap.add_argument('after')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    cases = [case(args.before, args.after, view, demo) for view in (214, 320) for demo in range(4)]
    result = dict(before=args.before, after=args.after,
                  mean_top20_gain_ms=sum(c['gain_ms'] for c in cases)/8, cases=cases)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    for c in cases:
        print(c['view'], c['demo'], round(c['gain_ms'], 3), 'ms; geometry',
              c['changed_geometry'], 'state changes', c['changed_fields'])


if __name__ == '__main__':
    main()
