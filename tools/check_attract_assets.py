"""Check selected-source slideshow provenance and exact packed DOS demos."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from dos_data import DosData
from game_profile import profile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check(source, assets=None, generated=None):
    demos = source.demos()
    chunks = source.graphics()
    result = dict(profile=source.profile.key, layout=source.graphics_layout['name'], demos=[])
    for i, row in enumerate(demos):
        chunk = chunks[row['chunk']]
        length = struct.unpack_from('<H', chunk, 1)[0]
        expected = chunk[4:length]
        assert row['data'] == expected and row['mapon'] == chunk[0]
        result['demos'].append(dict(index=i, chunk=row['chunk'], floor=chunk[0],
                                    packets=len(expected)//3, packet_sha256=sha(expected)))
    if assets is None:
        return result
    directory = (assets/'demos.bin').read_bytes()
    for i, row in enumerate(demos):
        offset, count, floor = struct.unpack_from('<3H', directory, i*6)
        assert count*3 == len(row['data']) and floor == row['mapon']
        packed = (assets/f'demo-{i}.bin').read_bytes()
        assert packed == row['data'], f'demo {i} packets differ from selected source'
    demo_receipt = json.loads((assets/'demo-source.json').read_text())
    assert demo_receipt['demos'] == result['demos']
    assert demo_receipt['graphics_sha256'] == sha(source.read('VGAGRAPH'))
    front = json.loads((assets/'frontend-source.json').read_text())
    for name, digest in front['inputs']['source_files'].items():
        assert digest == sha(source.read(name)), name
    assert front['inputs']['layout'] == source.graphics_layout
    for name, row in front['source_chunks'].items():
        assert row['sha256'] == sha(chunks[row['chunk']]), name
    menu = (assets/'menu.bin').read_bytes()
    constants = (generated/'menu.inc').read_text()
    for name, digest in front['converted_pages'].items():
        match = re.search(r'(?m)^LUMP_'+name.upper()+r'\s+\.equ\s+(\d+)', constants)
        assert match, name
        first, count, _, size = struct.unpack_from('<4H', menu, 8+int(match[1])*8)
        # Page records are block aligned; these are the bytes StreamScreen loads.
        page = menu[first*512:(first+count)*512]
        assert sha(page) == digest, f'{name}: packed page differs from its conversion receipt'
    result['packed_pages'] = front['converted_pages']
    result['cache_identity'] = front['cache_identity']
    result['packed_demos_equal_source'] = True
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--data', type=Path, required=True)
    ap.add_argument('--shared-data', type=Path)
    ap.add_argument('--assets', type=Path)
    ap.add_argument('--generated', type=Path, default=Path('build/gen'))
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    result = check(DosData(args.data, profile(args.profile), args.shared_data), args.assets, args.generated)
    text = json.dumps(result, indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text)


if __name__ == '__main__':
    main()
