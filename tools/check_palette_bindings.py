"""Reject floor art and display palettes that assign different colors to slots."""
import argparse
import json
from pathlib import Path
import struct


def check(root, floors):
    root = Path(root)
    failures = []
    checked = 0
    for floor in floors:
        receipt = json.loads((root/f'build/palettes/{floor}.json').read_text())
        palette = receipt['palette']
        metadata = json.loads((root/f'build/levels/{floor}/map.json').read_text())
        if metadata['palette'] != palette:
            failures.append(f'floor {floor+1}: map palette differs from the art palette receipt')
        if len(palette) != 16 or any(len(c) != 3 or any(v < 0 or v > 255 or v % 17 for v in c) for c in palette):
            failures.append(f'floor {floor+1}: expected sixteen 12-bit colors')
            continue
        words = [(r//17 << 8) | (g//17 << 4) | b//17 for r,g,b in palette]
        expected = struct.pack('<16H', *words)
        tints = (root/f'build/palettes/tints-{floor+1}.bin').read_bytes()
        if tints[:32] != expected:
            failures.append(f'floor {floor+1}: display palette differs from the art palette receipt')
        local = root/'build/assets/gray-local'
        if local.exists():
            from frontend.gray_pair import pair_table, preview_bytes, words_of
            copies = [local/f'floor-{floor:02d}-tints.bin', local/f'floor-{floor:02d}.bin']
            if any(not p.exists() or p.read_bytes()[:320] != tints for p in copies):
                failures.append(f'floor {floor+1}: packaged display tints are stale; rebuild the gray catalog')
            records = b''.join(pair_table(words_of(tints[i:i+32])) +
                               preview_bytes(words_of(tints[i:i+32])) for i in range(0,320,32))
            record_path = local/f'floor-{floor:02d}-records.bin'
            if not record_path.exists() or record_path.read_bytes()[:len(records)] != records:
                failures.append(f'floor {floor+1}: packaged menu conversion is stale; rebuild the gray catalog')
        checked += 1
    if failures:
        raise ValueError('\n'.join(failures) + '\nRegenerate the affected floor assets, art, weapons and tints together before packing images.')
    return dict(floors=checked, matching_map_and_display_palettes=True)


def main():
    from wolfdata import ROOT, PROFILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--floors', type=int, nargs='+', help='zero-based source floor indexes')
    args = parser.parse_args()
    floors = range(PROFILE.floors) if args.floors is None else args.floors
    print(json.dumps(check(ROOT, floors), indent=2))


if __name__ == '__main__':
    main()
