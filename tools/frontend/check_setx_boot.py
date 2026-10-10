"""Compare resident boot writes before/after splitting out the name seedling."""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import memmap
from b1 import decode

SETX = memmap.SLOT_NAMES
LIMIT = memmap.STORE_CACHE


def inspect(paths):
    memory = bytearray(LIMIT)
    written = bytearray(LIMIT)
    hits = []
    media = []
    for path in paths:
        disk = path.read_bytes()
        header = disk[512:1024]
        assert header[:6] == b'WOLFGS'
        count = header[8]
        assert count <= 44
        for i in range(count):
            target, block, blocks = struct.unpack_from('<IHH', header, 16 + i * 8)
            flags, addr = target >> 24, target & 0xffffff
            if addr >= LIMIT:
                continue
            payload = disk[block * 512:(block + blocks) * 512]
            if flags & 2:
                length = int.from_bytes(payload[:2], 'little') or 65536
                payload = bytes(decode(payload[2:], length))
            if flags & 1:
                ordered = bytearray(len(payload))
                for j, dest in enumerate(header[448:512]):
                    ordered[dest * 512:(dest + 1) * 512] = payload[j * 512:(j + 1) * 512]
                payload = ordered
            end = addr + len(payload)
            assert end <= LIMIT
            memory[addr:end] = payload
            written[addr:end] = b'\1' * len(payload)
            if addr < SETX + 512 and end > SETX:
                hits.append(dict(disk=path.name, address=hex(addr), length=len(payload), flags=flags))
        volume = disk[1028:1067]
        bitmap = int.from_bytes(volume[35:37], 'little')
        total = int.from_bytes(volume[37:39], 'little')
        free = sum(bool(disk[bitmap * 512 + (i >> 3)] & (0x80 >> (i & 7))) for i in range(total))
        media.append(dict(file=path.name, segments=count, free_blocks=free,
                          sha256=hashlib.sha256(disk).hexdigest(),
                          build=f'{int.from_bytes(header[432:436], "little"):08X}'))
    assert memory[SETX:SETX + 8] == b'WOLFSLT1'
    assert int.from_bytes(memory[SETX + 8:SETX + 10], 'little') == sum(memory[SETX + 10:SETX + 512]) == 263
    return memory, written, dict(setx_writes=hits, media=media)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('before', type=Path)
    ap.add_argument('after', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    report = {}
    for label, files in [('floppies', [f'disk{i}.po' for i in range(1, 6)]), ('hd', ['wolf-hd.po'])]:
        old, old_mask, before = inspect([args.before / f for f in files])
        new, new_mask, after = inspect([args.after / f for f in files])
        assert old == new, f'{label}: resident bytes changed'
        assert old_mask == new_mask, f'{label}: resident coverage changed'
        assert len(before['setx_writes']) == 2
        assert after['setx_writes'] == [dict(disk=files[0], address=hex(SETX), length=512, flags=0)]
        report[label] = dict(before=before, after=after,
                             identical_resident_bytes=sum(new_mask),
                             resident_sha256=hashlib.sha256(new).hexdigest())
    old_elf = (args.before / 'wolf.elf').read_bytes()
    new_elf = (args.after / 'wolf.elf').read_bytes()
    assert old_elf == new_elf, 'ELF changed'
    report['elf_sha256'] = hashlib.sha256(new_elf).hexdigest()
    report['pass'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, elf=report['elf_sha256'], output=str(args.output))))


if __name__ == '__main__':
    main()
