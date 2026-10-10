"""Verify music bytes on packed disks against this build's selected audio."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import struct

import b1
from episode_directory import floor_records
from music_pack import inspect_song
from game_profile import profile


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Media:
    def __init__(self, disk):
        disk = Path(disk)
        self.paths = [disk]
        self.images = [disk.read_bytes()]
        first = self.images[0][512:1024]
        if len(first) != 512 or first[:7] != b'WOLFGS\x01' or not 1 <= first[7] <= 8:
            raise ValueError('Invalid boot disk header')
        for number in range(2, first[7] + 1):
            name = 'disk'+str(number)+'.po' if disk.name == 'disk1.po' else disk.stem+str(number)+disk.suffix
            path = disk.with_name(name)
            raw = path.read_bytes()
            head = raw[512:1024]
            if (len(head) != 512 or head[:8] != b'WOLFGS'+bytes((number, first[7]))
                    or head[368:436] != first[368:436]):
                raise ValueError('Mismatched supplemental disk: '+str(path))
            self.paths.append(path)
            self.images.append(raw)
        self.headers = [raw[512:1024] for raw in self.images]
        # Each header lists the store blocks of its disk after its segments (tools/mkdisk.py
        # volume); a block on several disks must be the same on each.
        blocks = {}
        for number, (raw, head) in enumerate(zip(self.images, self.headers), 1):
            at = 16 + 8*head[8]
            while at + 8 <= 368:
                low, count, physical, disk, high = struct.unpack_from('<3H2B', head, at)
                if not count:
                    break
                if disk != number:
                    raise ValueError('Store run of another disk on disk '+str(number))
                for i in range(count):
                    part = raw[(physical+i)*512:(physical+i+1)*512]
                    if len(part) != 512:
                        raise ValueError('Truncated episode disk mapping')
                    if blocks.setdefault((low | high << 16) + i, part) != part:
                        raise ValueError('Copies of store block %d differ' % ((low | high << 16) + i))
                at += 8
        if sorted(blocks) != list(range(len(blocks))):
            raise ValueError('Incomplete episode disk mapping')
        store = b''.join(blocks[b] for b in range(len(blocks)))
        if store[:8] not in (b'WOLFEP02', b'WOLFEP03', b'WOLFEP04', b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08'):
            raise ValueError('Missing supported episode store')
        self.store = bytes(store)

    def resident(self, address, size):
        """Read the boot loader's final bytes, including B1-compressed runs."""
        result, filled = bytearray(size), bytearray(size)
        for raw, header in zip(self.images, self.headers):
            if header[8] > 44:
                raise ValueError('Invalid resident segment count')
            for index in range(header[8]):
                destination, block, count = struct.unpack_from('<IHH', header, 16+index*8)
                start, flags = destination & 0xffffff, destination >> 24
                # Raw boot runs can span bank boundaries after adjacent
                # resident ranges are merged by the disk packer.
                if start >= address + size:
                    continue
                payload = raw[block*512:(block+count)*512]
                if len(payload) != count*512:
                    raise ValueError('Truncated resident segment')
                if flags & 2:
                    length = struct.unpack_from('<H', payload)[0] or 65536
                    if start + length <= address:
                        continue
                    payload = b1.decode(payload[2:], length)
                left, right = max(address, start), min(address+size, start+len(payload))
                if right > left:
                    result[left-address:right-address] = payload[left-start:right-start]
                    filled[left-address:right-address] = b'\x01'*(right-left)
        return bytes(result) if all(filled) else None

    def halves(self, first, second, size):
        """A WOLFMS03 song: its first 32 KB, then the rest; each half raw or packed."""
        import storage_codec
        data = b''
        for record, part in ((first, min(size, 0x8000)), (second, size - 0x8000)):
            if part <= 0:
                break
            low, flags, block, count = record
            if flags & 255 != memmap.MUSIC_BASE >> 16 or low != len(data):
                raise ValueError('Music half address differs')
            block |= (flags >> 15) << 16
            payload = self.store[block*512:(block+count)*512]
            if flags & 0x100:
                codec = 'lz16' if payload[2] == 0 else 'hlz' if payload[2] == 3 else 'lzsa1'
                data += storage_codec.decode(payload, part, codec)
            else:
                data += payload[:part]
        return data

    def bank(self, record, size):
        low, flags, block, count = record
        if low != 0 or flags & 0x7fff != 0x3e or count != (size+511)//512:
            raise ValueError('Music directory address or size differs from selected bank')
        block |= ((flags >> 15) << 16) if self.store[:8] in (b'WOLFEP05', b'WOLFEP06', b'WOLFEP07', b'WOLFEP08') else 0
        raw = self.store[block*512:block*512+size]
        if len(raw) != size:
            raise ValueError('Truncated music bank in episode store')
        return raw


def check(disk, audio):
    """Return a receipt only when directory, floor and resident banks match."""
    media = Media(disk)
    expected = audio['songs']
    if not expected or len({s['id'] for s in expected}) != len(expected):
        raise ValueError('Expected distinct selected songs')
    if len(expected) != audio['required_songs']:
        raise ValueError('Incomplete selected music catalog')
    if media.store[1024:1032] not in (b'WOLFMS01', b'WOLFMS02', b'WOLFMS03'):
        raise ValueError('Missing music directory')
    verified, records, identities = [], set(), set()
    for song in expected:
        sid, size = song['id'], song['bytes']
        if not 0 <= sid < 56:
            raise ValueError('Music index outside directory')
        pairs = media.store[1024:1032] == b'WOLFMS03'
        record = struct.unpack_from('<4H', media.store, 1024+64+sid*(16 if pairs else 8))
        if pairs and record[3]:
            second = struct.unpack_from('<4H', media.store, 1024+64+sid*16+8)
            data = media.halves(record, second, size)
            records.add((record, second) if second[3] else (record,))
            location = 'episode'
        elif record[3]:
            data = media.bank(record, size)
            records.add(record)
            location = 'episode'
        elif sid == 7 and media.store[:8] == b'WOLFEP02':
            data = media.resident(memmap.TITLE_SONG, size)
            location = 'resident'
        else:
            raise ValueError('Missing music directory entry: '+song['name'])
        if data is None or digest(data) != song['sha256']:
            raise ValueError('Packed music differs from selected build: '+song['name'])
        inspect_song(data)
        identities.add(song['sha256'])
        verified.append(dict(id=sid, name=song['name'], bytes=size, sha256=digest(data), location=location))
        # The title song also has a permanent boot copy beside cached UI art.
        if sid == 7 and media.store[:8] == b'WOLFEP02' and media.resident(memmap.TITLE_SONG, size) != data:
            raise ValueError('Resident title music differs from selected build')
    floors = struct.unpack_from('<H', media.store, 8)[0]
    for floor in range(floors):
        rows, _ = floor_records(media.store, floor)
        songs = [r for r in rows if r[1] & 255 == memmap.MUSIC_BASE >> 16]
        found = tuple(songs) if media.store[1024:1032] == b'WOLFMS03' else (songs[0] if len(songs) == 1 else None)
        if found not in records:
            raise ValueError('Floor music differs from verified directory: '+str(floor))
    header = media.resident(memmap.MUSIC_BASE, 32)
    initial = None
    if header is None and media.store[:8] != b'WOLFEP02':
        pass                # boot reads no song (tools/registered_loads.py boot_rows)
    else:
        if header is None or header[:4] not in (b'WDP2', b'WDP3'):
            raise ValueError('Missing initial resident music bank')
        packed_at = struct.unpack_from('<H', header, 10 if header[:4] == b'WDP2' else 20)[0]
        length = packed_at + struct.unpack_from('<H', header, 12)[0]
        initial = media.resident(memmap.MUSIC_BASE, length)
        if initial is None or digest(initial) not in identities:
            raise ValueError('Initial resident music differs from selected build')
    return dict(format=1, status='verified', profile=audio['profile'], songs=verified,
                floor_references_verified=floors, initial_bank_sha256=digest(initial) if initial else None,
                images=[dict(file=p.name, sha256=digest(raw)) for p, raw in zip(media.paths, media.images)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('disk', type=Path)
    parser.add_argument('--audio-input', type=Path, default=Path('build/gen/audio-input.json'))
    parser.add_argument('--out', type=Path, default=Path('build/media-audio.json'))
    args = parser.parse_args()
    args.out.unlink(missing_ok=True)
    result = check(args.disk, json.loads(args.audio_input.read_text()))
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print('Verified packed music: '+str(len(result['songs']))+' songs and '+str(result['floor_references_verified'])+' floor references')


if __name__ == '__main__':
    main()
