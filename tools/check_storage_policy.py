"""Check bank-safe packing and the bytes of every unique mixed-codec unit."""
import memmap
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import storage_codec


def check_boundaries():
    import build_registered_episode as packer
    original_root = packer.ROOT
    noise = bytes(v for a in range(256) for b in range(a, 256)
                  for v in ((a,) if a == b else (a, b)))
    with tempfile.TemporaryDirectory(prefix='wolf-storage-') as folder:
        root = Path(folder)
        (root/'profiles/storage').mkdir(parents=True)
        shutil.copy2(original_root/'profiles/storage/stock.toml', root/'profiles/storage/stock.toml')
        try:
            packer.ROOT = root
            store = packer.Store(0)
            source = noise[:65535]
            records = store.units([dict(data=source, address=(memmap.ART_BRIGHT+0x20001))], 'boundary')
            assert len(records) == 2, 'Incompressible unaligned output must split safely'
            full = store.units([dict(data=noise, address=(memmap.ART_BRIGHT+0x30000))], 'full-bank')
            store.finish_packing()
            assert len(full) == 1 and not full[0][1] & 0x100
            output = bytearray()
            for item in store.manifest[:2]:
                start = item['first_block']*512
                payload = store.data[start:start+item['blocks']*512]
                output.extend(storage_codec.decode(payload, item['bytes'], item['codec']))
                assert (item['address'] & 65535) + item['bytes'] <= 65536
            assert output == source
        finally:
            packer.ROOT = original_root


def check_store(path):
    data = path.read_bytes()
    manifest = json.loads(path.with_suffix('.json').read_text())
    seen = set()
    for item in manifest:
        start = item['first_block']*512
        if start in seen:
            continue
        seen.add(start)
        payload = data[start:start+item['blocks']*512]
        raw = (storage_codec.decode_sparse(payload, item['bytes'], Path(item['asset']).read_bytes())
               if item['codec']=='sparse' else storage_codec.decode(payload, item['bytes'], item['codec']))
        assert hashlib.sha256(raw).hexdigest() == item['sha256'], item
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path)
    args = parser.parse_args()
    check_boundaries()
    print('Storage boundary checks passed: full bank and exact unaligned tail')
    if args.store:
        print('Verified unique stored units:', check_store(args.store))


if __name__ == '__main__':
    main()
