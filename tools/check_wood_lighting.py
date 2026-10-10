"""Check wood contrast in serialized atlases and a paired recorded replay."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import struct

from elf import read
from b1 import decode
from wolfdata import palette
from build_colors import CFG, LIGHT_GAINS
from wood_lighting import preserve_grain
import viewcolor as vc


def row_light(pair, colors):
    return [sum(w * vc.LIN[colors[k][channel]]
                for k in (byte >> 4, byte & 15)
                for channel, w in enumerate((.2126, .7152, .0722))) for byte in pair]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before-palettes', type=Path,
                    help='optional palette directory or gzipped JSON baseline for unchanged-color checks')
    ap.add_argument('--palettes', type=Path, default=Path('build/palettes'))
    ap.add_argument('--levels', type=Path, default=Path('build/levels'))
    ap.add_argument('--episode', type=Path, default=Path('build/assets/episode.bin'))
    ap.add_argument('--before', type=Path)
    ap.add_argument('--after', type=Path)
    ap.add_argument('--elf', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    previous = None
    if args.before_palettes:
        previous = (json.loads(gzip.decompress(args.before_palettes.read_bytes()))
                    if args.before_palettes.is_file() else
                    [json.loads((args.before_palettes/f'{n}.json').read_text()) for n in range(10)])
    source = palette()
    floors = []
    for floor in range(10):
        old = previous[floor] if previous else None
        new = json.loads((args.palettes / f'{floor}.json').read_text())
        if old:
            for key in old.keys() - {'wall_lights', 'wall_ab', 'sprite_lights', 'light_gains', 'palette_fit_gains'}:
                assert old[key] == new[key], (floor, key)
        common = {j:old['light_gains'].index(gain) for j,gain in enumerate(new['light_gains'])
                  if old and gain in old['light_gains']}
        for j,i in common.items():
            assert old['sprite_lights'][i]==new['sprite_lights'][j], (floor,'sprite light',j)
        table = (args.levels / str(floor) / 'art-tables.bin').read_bytes()
        changed = []
        for light in range(len(new['wall_lights'])):
            ramp = [sum(row_light(new['wall_lights'][light][c], new['palette']))
                    for c in range(223, 207, -1)]
            assert ramp == sorted(ramp), (floor, light, 'shade reversal')
            for c in range(256):
                pair = new['wall_lights'][light][c]
                assert bytes(pair) == table[16+c*16+light*2:18+c*16+light*2]
                if light in common and pair != old['wall_lights'][common[light]][c]:
                    assert 208 <= c < 224
                    changed.append((light, c))
            for grain in (218, 213):
                assert all(a > b for a, b in zip(row_light(new['wall_lights'][light][grain], new['palette']),
                                               row_light(new['wall_lights'][light][223], new['palette'])))
        for c in range(208, 224):
            means = [sum(row_light(light[c], new['palette'])) for light in new['wall_lights']]
            assert means == sorted(means), (floor, c, means)
        repeat = json.loads(json.dumps(new['wall_lights']))
        preserve_grain(repeat, source, [tuple(v//17 for v in c) for c in new['palette']], vc.Metric(CFG), LIGHT_GAINS)
        assert json.loads(json.dumps(repeat)) == new['wall_lights']
        # Alignment is a permutation: moving a fitted brown to another slot
        # must not change the converted RGB image. Keep the fixed black/white.
        permutations = 16
        for seed in range(permutations):
            order = list(range(2, 16))
            random.Random(floor*permutations+seed).shuffle(order)
            order = [0, 1]+order
            permuted = [new['palette'][i] for i in order]
            trial = [[[0, 0] for _ in range(256)] for _ in LIGHT_GAINS]
            preserve_grain(trial, source, [tuple(v//17 for v in c) for c in permuted], vc.Metric(CFG), LIGHT_GAINS)
            for light in range(len(new['wall_lights'])):
                for c in range(208, 224):
                    for a, b in zip(trial[light][c], new['wall_lights'][light][c]):
                        assert (permuted[a >> 4], permuted[a & 15]) == (new['palette'][b >> 4], new['palette'][b & 15]), (floor, seed, light, c)
        floors.append(dict(floor=floor, changed_entries=changed,
                           palette_permutations=permutations,
                           table_sha256=hashlib.sha256(table).hexdigest()))
    result = dict(floors=floors, all_floor_contrast=True, palette_permutations=160,
                  sprites_palette_other_wall_colors_unchanged=True if previous else None)
    episode = args.episode.read_bytes()
    manifest = json.loads(args.episode.with_suffix('.json').read_text())
    table_units = [r for r in manifest if r['asset'] == 'art-tables.bin']
    assert len(table_units) == 10
    for unit in table_units:
        start = unit['first_block']*512
        raw = episode[start:start+unit['blocks']*512]
        if unit['b1']:
            raw = decode(raw[2:], unit['bytes'])
        else:
            raw = raw[:unit['bytes']]
        assert raw == (args.levels/str(unit['level'])/'art-tables.bin').read_bytes()
    result['episode_table_units_exact'] = len(table_units)
    if args.before:
        assert args.after and args.elf and previous, 'replay comparison requires its palette baseline'
        before, after = args.before, args.after
        assert (before/'states.jsonl').read_bytes() == (after/'states.jsonl').read_bytes()
        rays = (before/'rays.bin').read_bytes()
        assert rays == (after/'rays.bin').read_bytes()
        states = [json.loads(line) for line in (before/'states.jsonl').read_text().splitlines()]
        a = (before/'frames.shr').read_bytes(); b = (after/'frames.shr').read_bytes()
        assert len(a) == len(b) == len(states)*32768
        segments, symbols = read(args.elf)
        heights = next(seg['data'][symbols['scaleHeight']-seg['address']:symbols['scaleHeight']-seg['address']+400]
                       for seg in segments if seg['address'] <= symbols['scaleHeight'] < seg['address']+len(seg['data']))
        index = (args.levels/'0/art-index.bin').read_bytes()
        old = previous[0]
        new = json.loads((args.palettes/'0.json').read_text())
        samples = changed = frames_changed = wood_samples = 0
        for frame, state in enumerate(states):
            assert state['floor'] == 0
            ar = [struct.unpack_from('<160H', rays, frame*1600+n*320) for n in range(5)]
            left = (160-state['width'])//2
            pa, pb = a[frame*32768:(frame+1)*32768], b[frame*32768:(frame+1)*32768]
            assert pa[25600:] == pb[25600:], ('HUD/SCB/palette', frame+1)
            different = 0
            for x in range(state['width']):
                h = struct.unpack_from('<H', heights, ar[0][x])[0]
                page = ar[3][x] >> 8
                light = ar[4][x] >> 11
                off = ((ar[3][x]&255)-16)*65536+ar[2][x]
                for y in range(160):
                    pixel = y*160+left+x
                    differs = pa[pixel] != pb[pixel]
                    if not differs and not (470 <= frame+1 <= 553 and y <= 80 and page in (22, 23)):
                        continue
                    if not max(left,80-h//2) <= y < min(160-left,80+h//2):
                        assert not differs
                        continue
                    tex = (y-(80-h//2))*64//h
                    c = index[(off+tex*2)//2]
                    ea, eb = old['wall_lights'][light][c][y&1], new['wall_lights'][light][c][y&1]
                    assert (pa[pixel],pb[pixel]) == (ea,eb), (frame+1,x,y,c,pa[pixel],pb[pixel],ea,eb)
                    if 470 <= frame+1 <= 553 and y <= 80 and page in (22, 23):
                        wood_samples += 1
                    if differs:
                        assert 208 <= c < 224
                        different += 1
                    elif 470 <= frame+1 <= 553:
                        samples += 1
            # All margins must be identical, too.
            for y in range(160):
                assert pa[y*160:y*160+left] == pb[y*160:y*160+left]
                assert pa[y*160+left+state['width']:(y+1)*160] == pb[y*160+left+state['width']:(y+1)*160]
            changed += different; frames_changed += bool(different)
        result['replay'] = dict(frames=len(states), states_and_rays_exact=True,
                                source_verified_changed_bytes=changed, changed_frames=frames_changed,
                                additional_source_verified_wood_bytes=samples,
                                wood_corridor_samples=wood_samples, unexpected_differences=0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='floors'}))


if __name__ == '__main__':
    main()
