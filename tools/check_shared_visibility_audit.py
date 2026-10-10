"""Mutation checks for the explicit shared-visibility comparison contract."""

from copy import deepcopy

import demo_check as d


def main():
    base = dict(frame=1, doors=[], pwall=[0, 0, 0],
                actors=[[0, 0, 0, 0, 0, 100, 1, 0, 1, 'stand', 0, 0, 0]])
    base.update({key:0 for key in d.PLAYER_FIELDS + d.GAME_FIELDS})
    checks = 0
    for index, name in enumerate(d.ACTOR_FIELDS):
        changed = deepcopy(base)
        changed['actors'][0][index] = 'walk' if name == 'state' else changed['actors'][0][index] + 1
        allowed = name in ('active', 'centered', 'transx')
        assert bool(d.audit_shared_visibility([changed], [base])['unexpected']) != allowed, name
        checks += 1
    for bit in range(16):
        changed = deepcopy(base)
        changed['actors'][0][6] ^= 1 << bit
        assert bool(d.audit_shared_visibility([changed], [base])['unexpected']) == (bit != 3), bit
        checks += 1
    for key in d.PLAYER_FIELDS + d.GAME_FIELDS + ('frame',):
        changed = deepcopy(base)
        changed[key] += 1
        assert d.audit_shared_visibility([changed], [base])['unexpected'], key
        checks += 1
    changed = deepcopy(base)
    changed['actors'][0][7] = 2
    assert d.audit_shared_visibility([changed], [base])['unexpected']
    assert d.audit_shared_visibility([], [base])['unexpected']
    assert not d.audit_shared_visibility([base], [base])['unexpected']
    # The automatic shared-cast comparator must use the same activation guard.
    for actual, expected in ((0, 1), (1, 0), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2)):
        native, model = deepcopy(base), deepcopy(base)
        native['actors'][0][7], model['actors'][0][7] = actual, expected
        frame, diffs = d.compare([native], [model], shared_visibility=True)
        assert bool(diffs) == (actual != expected and 2 in (actual, expected)), (actual, expected, frame, diffs)
        checks += 1
    print(f'{checks + 3} shared-visibility mutation checks passed')


if __name__ == '__main__':
    main()
