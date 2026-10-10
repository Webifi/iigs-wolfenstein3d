"""Store each effect sample once: per-floor descriptor header plus shared clusters.

Runs after build_sound.py, before the art packer (which excludes the effect
loads). Samples used on exactly the same set of floors form one cluster file,
loaded at a floor-specific address. The 87 descriptors keep every field except
the sample address. Raw cluster loads pad to 512-byte blocks, so no cluster
crosses a bank and each sub-range keeps 512 bytes free at its end.
"""
import memmap
from collections import defaultdict
import hashlib
import json
import struct

from wolfdata import ROOT

OUT = ROOT / 'build/sound'
SFX_BASE = memmap.SFX_BASE
DESCRIPTORS = 87 * 16
PART = 32768


def floor_ram(loads):
    ram = {}
    for row in loads:
        data = (OUT / row['file']).read_bytes()
        assert len(data) == row['bytes']
        ram[row['address']] = data
    def read(address, size):
        for start, data in ram.items():
            if start <= address and address + size <= start + len(data):
                return data[address - start:address - start + size]
        raise ValueError(f'effect data at {address:#x} is not loaded')
    return read


def main():
    doc = json.loads((OUT / 'effects-floors.json').read_text())
    ranges = doc['ranges']
    floors = doc['floors']
    samples, headers, users = {}, {}, defaultdict(set)
    for entry in floors:
        read = floor_ram(entry['loads'])
        primary = (OUT / entry['loads'][0]['file']).read_bytes()
        assert entry['loads'][0]['address'] == SFX_BASE
        plan_end = doc['plan_offset'] + doc['plan_stride'] * doc['plan_records_per_bank']
        header = bytearray(primary[:plan_end])
        headers[entry['floor']] = header
        for e in range(87):
            address, size = struct.unpack_from('<IH', header, e * 16)
            if address:
                data = read(address, size)
                assert samples.setdefault(e, data) == data, e
                users[e].add(entry['floor'])
    by_set = defaultdict(list)
    for e in sorted(users):
        by_set[frozenset(users[e])].append(e)
    clusters = []
    def close(floor_set, blob, offsets):
        n = len(clusters)
        (OUT / f'effects-cluster-{n:02d}.bin').write_bytes(blob)
        clusters.append(dict(floors=floor_set, ids=sorted(offsets), data=bytes(blob), offsets=offsets))
    for floor_set, ids in sorted(by_set.items(), key=lambda kv: min(kv[1])):
        # Parts of at most PART bytes, split at sample boundaries, so every part fits a span.
        blob, offsets, seen = bytearray(), {}, {}
        for e in ids:
            if samples[e] not in seen:
                if blob and len(blob) + len(samples[e]) > PART:
                    close(floor_set, blob, offsets)
                    blob, offsets, seen = bytearray(), {}, {}
                seen[samples[e]] = len(blob)
                blob += samples[e]
            offsets[e] = seen[samples[e]]
        close(floor_set, blob, offsets)
    for entry in floors:
        floor = entry['floor']
        header = headers[floor]
        spans = []
        for r in ranges:
            start = r['start'] + (len(header) if r['start'] == SFX_BASE else 0)
            while start < r['end']:
                stop = min(r['end'], (start & ~0xffff) + 0x10000)
                spans.append([start, stop - (512 if r['start'] == SFX_BASE else 0)])
                start = stop
        mine = [n for n, c in enumerate(clusters) if floor in c['floors']]
        placed = {}
        for n in sorted(mine, key=lambda n: (-len(clusters[n]['data']), n)):
            for span in spans:
                if span[0] + len(clusters[n]['data']) <= span[1]:
                    placed[n] = span[0]
                    span[0] += len(clusters[n]['data'])
                    break
            else:
                raise ValueError(f'floor {floor + 1}: effect cluster {n} ({len(clusters[n]["data"])} bytes) does not fit')
        for e in range(87):
            address, size = struct.unpack_from('<IH', header, e * 16)
            if address:
                n = next(n for n in mine if e in clusters[n]['offsets'])
                struct.pack_into('<I', header, e * 16, placed[n] + clusters[n]['offsets'][e])
        name = f'effects-floor-{floor:02d}.bin'
        (OUT / name).write_bytes(header)
        loads = [dict(file=name, address=SFX_BASE, bytes=len(header), sha256=hashlib.sha256(header).hexdigest())]
        for n in sorted(mine, key=lambda n: placed[n]):
            data = clusters[n]['data']
            loads.append(dict(file=f'effects-cluster-{n:02d}.bin', address=placed[n], bytes=len(data),
                              sha256=hashlib.sha256(data).hexdigest()))
        # Every resident descriptor must point at its original sample bytes.
        read = floor_ram(loads)
        for e in range(87):
            address, size = struct.unpack_from('<IH', header, e * 16)
            if address:
                assert read(address, size) == samples[e], (floor, e)
        (OUT / f'effects-floor-{floor:02d}-loads.json').write_text(json.dumps(loads, indent=2) + '\n')
        entry.update(loads=loads, bytes=len(header), resident_bytes=sum(r['bytes'] for r in loads))
    doc['shared_clusters'] = len(clusters)
    doc['maximum_resident_bytes'] = max(e['resident_bytes'] for e in floors)
    (OUT / 'effects-floors.json').write_text(json.dumps(doc, indent=2) + '\n')
    total = sum(len(c['data']) for c in clusters)
    print(f'effects: {len(clusters)} shared clusters, {total} sample bytes stored once')


if __name__ == '__main__':
    main()
