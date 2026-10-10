"""Pack connected sprite frames into single source banks, retaining all texels.

Frames sharing a column command stay together. Run payloads are deduplicated
within each assigned bank; row bias remains in the command's source pointer.
"""
from collections import defaultdict

FRAME_BANK_TABLE = 0x1ff00  # final 256 bytes of the two reserved command banks


def pack(frames, walls, base, size):
    parents = {i: i for i, _, keys, _ in frames if not keys[0][0]}

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    first = {}
    for i, _, keys, _ in frames:
        if i not in parents:
            continue
        for key in keys:
            if key[1]:
                other = first.setdefault(key, i)
                parents[find(i)] = find(other)
    groups = defaultdict(list)
    payloads = defaultdict(set)
    for i, _, keys, _ in frames:
        if i in parents:
            group = find(i)
            groups[group].append(i)
            payloads[group].update(raw for _, runs in keys for _, _, raw in runs)
    # Leave room for the largest ordinary source-row bias (63*2).
    starts = [max(128, min(65536, 2*len(walls)-bank*65536))
              for bank in range(size//65536)]
    free = [65536-start for start in starts]
    frame_banks = {}
    bank_payloads = [set() for _ in starts]
    for group in sorted(groups, key=lambda g: (-sum(2*len(p) for p in payloads[g]), g)):
        costs = [sum(2*len(p) for p in payloads[group]-bank_payloads[b]) for b in range(len(starts))]
        choices = [b for b in range(len(starts)) if costs[b] <= free[b]]
        if not choices:
            raise ValueError(f'sprite component {groups[group]} cannot fit one source bank')
        bank = min(choices, key=lambda b: (free[b]-costs[b], b))
        free[bank] -= costs[bank]
        bank_payloads[bank].update(payloads[group])
        for i in groups[group]:
            frame_banks[i] = bank
    index = bytearray(walls)
    addresses = {}
    for bank, blobs in enumerate(bank_payloads):
        offset = bank*65536+starts[bank]
        for raw in sorted(blobs):
            addresses[bank, raw] = base+offset
            stop = offset//2+len(raw)
            if len(index) < stop:
                index.extend(bytes(stop-len(index)))
            index[offset//2:stop] = raw
            offset += 2*len(raw)
        assert offset <= (bank+1)*65536
    command_banks = {}
    for i, _, keys, _ in frames:
        if i in frame_banks:
            for key in keys:
                if key[1]:
                    assert command_banks.setdefault(key, frame_banks[i]) == frame_banks[i]
    return index, frame_banks, command_banks, addresses
