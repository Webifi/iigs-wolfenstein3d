"""Demo block for $0B:8000: a directory, then the original demo packets.

The selected profile names the original VGAGRAPH demo chunks. A benchmark demo recorded
with the original RecordDemo format can follow as demo 4. Each directory
entry is three words: the packet offset in this bank, the packet count and
the floor (mapon).
"""
import memmap
import struct
import json
import hashlib
from wolfdata import ROOT, PROFILE, source_data

BASE = 0x8000
OUT = ROOT / 'build/assets'


def main():
    source = source_data()
    originals = source.demos()
    if len(originals) != 4:
        raise ValueError('The native Wolf title loop requires four original demos')
    demos = [(d['mapon'], d['data']) for d in originals]
    provenance = dict(profile=PROFILE.key, layout=source.graphics_layout['name'],
                      graphics_sha256=hashlib.sha256(source.read('VGAGRAPH')).hexdigest(),
                      demos=[dict(index=i, chunk=d['chunk'], floor=d['mapon'], packets=len(d['data']) // 3,
                                  packet_sha256=hashlib.sha256(d['data']).hexdigest())
                             for i, d in enumerate(originals)])
    extra = ROOT / 'data/benchmark.dem'
    if not PROFILE.spear and extra.exists():
        raw = extra.read_bytes()
        length = struct.unpack_from('<H', raw, 1)[0]
        demos.append((raw[0], raw[4:length]))
    directory = bytearray()
    body = bytearray()
    start = BASE + 8 * 6
    groups = []
    for index, (mapon, data) in enumerate(demos):
        packets = len(data) // 3
        raw = data[:packets * 3]
        if start + len(raw) > 0xb000:
            raise ValueError('active demo exceeds its packet buffer')
        path = OUT/f'demo-{index}.bin'
        path.write_bytes(raw)
        groups.append([dict(file=str(path.relative_to(ROOT)), address=memmap.DEMO_BANK+start, bytes=len(raw))])
        directory += struct.pack('<3H', start, packets, mapon)
    directory += struct.pack('<3H', 0, 0, 0)
    directory = directory.ljust(8 * 6, b'\0')[:8 * 6]
    blob = directory + body
    if BASE + len(blob) > 0x10000:
        raise ValueError('demos exceed bank $0B')
    (OUT / 'demos.bin').write_bytes(blob)
    (OUT / 'demo-source.json').write_text(json.dumps(provenance, indent=2) + '\n')
    if groups:
        (OUT/'demo-loads.json').write_text(json.dumps(groups, indent=2)+'\n')
    print('demos:', len(demos), 'packets', [len(d) // 3 for _, d in demos])


if __name__ == '__main__':
    main()
