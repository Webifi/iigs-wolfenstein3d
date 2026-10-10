"""Compare decoded sprite streams after relocating their command addresses."""
import memmap
import argparse
import hashlib
import json
import struct
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode(data, frame, column):
    ptr = struct.unpack_from('<H', data, frame + column * 2)[0]
    bank = data[frame + 128 + column]
    pos = (bank - 0x29) * 65536 + ptr
    start = pos
    while True:
        assert 0 <= pos <= len(data) - 2
        if data[pos:pos + 2] == b'\0\0':
            pos += 2
            break
        assert pos + 6 <= len(data)
        pos += 6
    assert start // 65536 == (pos - 1) // 65536
    return start, data[start:pos]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    rows = []
    art = json.loads((args.before / 'art-hashes.json').read_text())
    for floor in range(10):
        old_dir, new_dir = args.before / str(floor), args.after / str(floor)
        old = (old_dir / 'spritecmd.bin').read_bytes()
        new = (new_dir / 'spritecmd.bin').read_bytes()
        stats = json.loads((old_dir / 'sprite-stats.json').read_text())
        assert 65536 < len(new) <= 131072
        header_end = stats['shapes'] * stats['frame_bytes']
        assert header_end <= 65536
        assert not any(new[header_end:65536])
        streams = {}
        for frame in range(0, header_end, stats['frame_bytes']):
            assert old[frame + 192:frame + 260] == new[frame + 192:frame + 260]
            for column in range(64):
                _, old_stream = decode(old, frame, column)
                start, new_stream = decode(new, frame, column)
                assert start >= 65536
                assert old_stream == new_stream, (floor, frame, column)
                streams[start] = new_stream
        end = 65536
        for start, stream in sorted(streams.items()):
            assert start == end
            end += len(stream)
        assert end == len(new)
        art_hash = sha((new_dir / 'art-index.bin').read_bytes())
        assert art_hash == art[floor]['art_index_sha256']
        rows.append(dict(floor=floor + 1, shapes=stats['shapes'],
                         exact_columns=stats['shapes'] * 64,
                         unique_streams=len(streams), stream_bytes=end - 65536,
                         end_exclusive=hex(memmap.OLD_SPRITE_CMDS + end),
                         before_sha256=sha(old), after_sha256=sha(new),
                         art_index_sha256=art_hash))
    args.receipt.write_text(json.dumps(dict(floors=rows), indent=2) + '\n')
    print('All ten floors: headers, decoded runs and source art match.')
    print('Largest run bank:', max(r['stream_bytes'] for r in rows), 'bytes')


if __name__ == '__main__':
    main()
