"""Rooms grown by merging neighbouring cells with similar proof rows.

Cost of merging rooms A and B: proven bits lost in the merged row, counted
only for cells near the room (Chebyshev distance <= NEAR), times the room
sizes. Greedy, cheapest merge first, until TARGET rooms remain. Rooms stay
connected (4-neighbour). Uses no recorded queries.
"""
import heapq


def cluster(cells, num, rows, target, near=8):
    return cluster_many(cells, num, rows, [target], near)[target]


def cluster_many(cells, num, rows, targets, near=8):
    """The same greedy merge sequence supplies every requested room limit."""
    pos = {x * 64 + y: (x, y) for x, y in cells}
    columns = [[0] * 65 for _ in range(64)]
    for c, (x, y) in pos.items():
        columns[x][y+1] = 1 << num[c]
    for column in columns:
        for y in range(1, 65):
            column[y] |= column[y-1]
    near_mask = {}
    for c, (x, y) in pos.items():
        m = 0
        for u in range(max(0, x-near), min(64, x+near+1)):
            m |= columns[u][min(64, y+near+1)] ^ columns[u][max(0, y-near)]
        near_mask[c] = m
    parent = {c: c for c in pos}
    both = {c: rows[num[c]] for c in pos}
    size = {c: 1 for c in pos}
    nearm = dict(near_mask)
    adj = {c: set() for c in pos}
    for c, (x, y) in pos.items():
        for d in ((x + 1) * 64 + y, x * 64 + y + 1):
            if d in pos:
                adj[c].add(d); adj[d].add(c)
    version = {c: 0 for c in pos}

    def cost(a, b):
        merged = both[a] & both[b]
        lost_a = bin((both[a] & ~merged) & (nearm[a] | nearm[b])).count('1')
        lost_b = bin((both[b] & ~merged) & (nearm[a] | nearm[b])).count('1')
        return lost_a * size[a] + lost_b * size[b]

    heap = []
    for a in pos:
        for b in adj[a]:
            if a < b:
                heapq.heappush(heap, (cost(a, b), a, b, 0, 0))
    def snapshot():
        ids, room = {}, {}
        for c in pos:
            r = c
            while parent[r] != r:
                r = parent[r]
            room[c] = ids.setdefault(r, len(ids) + 1)
        return room

    targets = set(targets)
    results = {}
    rooms = len(pos)
    for target in targets:
        if target >= rooms:
            results[target] = snapshot()
    while rooms > min(targets) and heap:
        c, a, b, va, vb = heapq.heappop(heap)
        if parent[a] != a or parent[b] != b or version[a] != va or version[b] != vb:
            continue
        parent[b] = a
        both[a] &= both[b]
        size[a] += size[b]
        nearm[a] |= nearm[b]
        adj[a] = (adj[a] | adj[b]) - {a, b}
        for n in adj[b]:
            adj[n].discard(b)
            if n != a:
                adj[n].add(a)
        version[a] += 1
        rooms -= 1
        for n in adj[a]:
            heapq.heappush(heap, (cost(a, n), a, n, version[a], version[n]) if a < n else (cost(n, a), n, a, version[n], version[a]))
        if rooms in targets:
            results[rooms] = snapshot()
    for target in targets - results.keys():
        results[target] = snapshot()
    return results
