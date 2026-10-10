"""Prove paired native scene differences come only from the brown wall ramp."""
import argparse
from collections import Counter
import json
import re
from pathlib import Path
import struct

from elf import read


def check(before, after, palettes_before, palettes_after, levels, elf):
    segments, symbols = read(elf)
    address = symbols['scaleHeight']
    heights = next(s['data'][address-s['address']:address-s['address']+400]
                   for s in segments if s['address'] <= address < s['address']+len(s['data']))
    result_before = json.loads((before/'result.json').read_text())
    result_after = json.loads((after/'result.json').read_text())
    assert result_before['elf_sha256'] == result_after['elf_sha256']
    times = lambda path: re.findall(r'^(?:FRAME|CAST) \d+ [\d.]+$', (path/'mame.log').read_text(), re.M)
    assert times(before) == times(after)
    assert (before/'logic.json').read_bytes() == (after/'logic.json').read_bytes()
    states = sorted(before.glob('state*.json'), key=lambda p: int(p.stem[5:]))
    assert [p.name for p in states] == [p.name for p in sorted(after.glob('state*.json'), key=lambda p: int(p.stem[5:]))]
    counts, samples = Counter(), 0
    for state_file in states:
        name = state_file.name
        a = json.loads(state_file.read_text())
        b = json.loads((after/name).read_text())
        # Loading different compressed tables may move the absolute boot time.
        for field in a.keys()-{'emulated_time', 'doc_ticks'}:
            assert a[field] == b[field], (name, field)
        n = state_file.stem[5:]
        for family in ('hud', 'map'):
            assert (before/f'{family}{n}.bin').read_bytes() == (after/f'{family}{n}.bin').read_bytes(), (family, n)
        for family in ('objects', 'posts'):
            assert (before/f'{family}{n}.json').read_bytes() == (after/f'{family}{n}.json').read_bytes(), (family, n)
        floor = str(a['game']['levelIndex'])
        old = json.loads((palettes_before/(floor+'.json')).read_text())
        new = json.loads((palettes_after/(floor+'.json')).read_text())
        assert old['palette'] == new['palette']
        index = (levels/floor/'art-index.bin').read_bytes()
        posts = json.loads((before/f'posts{n}.json').read_text())
        p = (before/f'frame{n}.bin').read_bytes()
        q = (after/f'frame{n}.bin').read_bytes()
        assert len(p) == len(q) == 25600
        width = a['view_width']
        left = (160-width)//2
        for offset, (pa, pb) in enumerate(zip(p, q)):
            if pa == pb:
                continue
            y, x = divmod(offset, 160)
            assert left <= x < left+width, (n, x, y, 'margin')
            hi, src, bank, plane = posts[x-left]
            h = struct.unpack_from('<H', heights, hi)[0]
            assert max(left, 80-h//2) <= y < min(160-left, 80+h//2), (n, x, y, 'outside wall')
            texel = (y-(80-h//2))*64//h
            source_offset = ((bank & 255)-16)*65536+src
            color = index[(source_offset+texel*2)//2]
            assert 208 <= color < 224, (n, x, y, 'non-brown source', color)
            assert any((pa, pb) == (old['wall_lights'][light][color][y & 1],
                                   new['wall_lights'][light][color][y & 1])
                       for light in range(len(old['wall_lights']))), (n, x, y, color, pa, pb)
            counts[str(bank >> 8)] += 1
            samples += 1
    assert samples > 0, 'scene did not exercise the changed wall colors'
    return dict(frames=result_after['frames'], captured_frames=len(states),
                changed_wall_bytes=samples, changed_bytes_by_texture=dict(counts),
                states_objects_rays_hud_margins_exact=True, frame_times_exact=True,
                unexpected_differences=0, before=result_before, after=result_after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'palettes-before', 'palettes-after', 'levels', 'elf', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = check(args.before, args.after, args.palettes_before, args.palettes_after, args.levels, args.elf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('before', 'after')}))


if __name__ == '__main__':
    main()
