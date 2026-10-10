"""Check that omitting fully hidden world runs preserves restoration coverage."""
import json
import random


def check(scenes=100000):
    seed = 0x5041494e54
    rng = random.Random(seed)
    skipped = 0
    for _ in range(scenes):
        covered, ghosts, weapon, world = [], set(), set(), set()
        for owner in range(rng.randrange(1, 18)):
            direct = owner == 0 and rng.randrange(3) == 0
            edges = sorted(rng.sample(range(161), 2 * rng.randrange(1, 9)))
            for top, bottom in zip(edges[::2], edges[1::2]):
                rows = set(range(top, bottom))
                (weapon if direct else world).update(rows)
                if any(a <= top and b >= bottom for a, b in covered):
                    skipped += 1
                    continue
                covered.append((top, bottom))
                if not direct:
                    ghosts.update(rows)
        # Weapon restoration remembers its own old opaque runs separately.
        assert world <= ghosts | weapon
    return dict(seed=seed, scenes=scenes, hidden_runs_skipped=skipped,
                unremembered_old_world_rows=0)


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
