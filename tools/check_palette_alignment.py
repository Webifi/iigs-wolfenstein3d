"""Verify that palette alignment preserves the RGB of the real picture assets."""
import json
import struct
from pathlib import Path

from shared_gray import align_palette, neutral, picture, preview, remap, tally
from frontend.native_assets import unpack_block

ROOT = Path(__file__).resolve().parents[1]


def palette(raw, offset):
    return struct.unpack_from('<16H', raw, offset)


def check_palette(colors, keep=1):
    aligned = align_palette(colors, keep)
    assert set(colors) <= set(aligned), 'alignment replaced a color'
    assert len(set(colors)) == 16 or len(set(aligned)) == 16 or len(set(colors[:keep])) < keep, 'a copied slot is still a copy'
    assert list(colors[:keep]) == aligned[:keep], 'fixed prefix moved'
    mapping = remap(colors, aligned)
    assert all(color == aligned[mapping[i]] for i, color in enumerate(colors))
    grays = 16 - len(set(colors)) + sum(1 for c in set(colors[keep:]) if neutral(c))
    if grays >= 2 and keep <= 13:
        assert neutral(aligned[13]) and neutral(aligned[14]), 'loading sign slots 13 and 14 are not gray'


def check_picture(path, *, victory=False, boot=False):
    source = path.read_bytes()
    aligned = picture(source, victory, boot)
    count = 0
    for p in range(16):
        check_palette(palette(source, 32256 + p * 32), 9 if boot and p == 15 else 1)
    for y in range(160 if victory else 200):
        old = palette(source, 32256 + (source[32000 + y] & 15) * 32)
        new = palette(aligned, 32256 + (aligned[32000 + y] & 15) * 32)
        for a, b in zip(source[y * 160:(y + 1) * 160], aligned[y * 160:(y + 1) * 160]):
            assert old[a >> 4] == new[b >> 4], (path.name, y)
            assert old[a & 15] == new[b & 15], (path.name, y)
            count += 2
    return count


def check_preview(path):
    source = path.read_bytes()
    aligned = preview(source)
    before = unpack_block(source, 130, 64)
    after = unpack_block(aligned, 130, 64)
    count = 0
    for y, (old_row, new_row) in enumerate(zip(before, after)):
        old = palette(source, 2 + (source[66 + y] - 13) * 32)
        new = palette(aligned, 2 + (aligned[66 + y] - 13) * 32)
        for a, b in zip(old_row, new_row):
            assert (a is None) == (b is None), (path.name, 'alpha changed')
            if a is not None:
                assert old[a] == new[b], (path.name, y)
                count += 1
    return count


def check_tally(path):
    source = path.read_bytes()
    before = json.loads(path.with_name('constants.json').read_text())
    after = dict(before)
    aligned = tally(source, after)
    count = 0
    for p in range(3):
        old = palette(source, 160 + p * 32)
        new = palette(aligned, 160 + p * 32)
        assert set(old) <= set(new), 'tally alignment replaced a color'
        assert old[0] == new[0]
        assert sorted(old[1:4]) == sorted(new[9:12]), 'tally lettering occupies neutral roles'
        for slot in (9, 10, 11):
            assert new[slot] == palette(aligned, 160)[slot], 'tally glyph roles differ between bands'
    for key, top, width, height in (
            ('TALLY_BJ1', 16, 52, 88),
            ('TALLY_BJ2', 16 + before['TALLY_BJ2_Y'], before['TALLY_BJ2_W'], before['TALLY_BJ2_H'])):
        for y in range(height):
            p = (0, 13, 14).index(source[top + y])
            old = palette(source, 160 + p * 32)
            destination = (0, 13, 14).index(aligned[top + y])
            new = palette(aligned, 160 + destination * 32)
            at = before[key] + y * width
            for a, b in zip(source[at:at + width], aligned[at:at + width]):
                assert old[a >> 4] == new[b >> 4], (key, y)
                assert old[a & 15] == new[b & 15], (key, y)
                count += 2
    # The same glyph bytes are used under all three palette bands.
    at = before['TALLY_GLYPHS'] + 39 * 2
    for p in range(3):
        old = palette(source, 160 + p * 32)
        new = palette(aligned, 160 + p * 32)
        for a, b in zip(source[at:before['TALLY_BYTES']], aligned[at:after['TALLY_BYTES']]):
            assert old[a >> 4] == new[b >> 4], ('glyph', p)
            assert old[a & 15] == new[b & 15], ('glyph', p)
            count += 2
    # The actual loading-box rows must use neutral overlay roles. This
    # catches a chromatic sign even when every background RGB is preserved.
    for y in range(83, 117):
        p = (0, 13, 14).index(aligned[y])
        pal = palette(aligned, 160 + p * 32)
        for slot in (1, 12, 13, 14, 15):
            channels = [(pal[slot] >> shift) & 15 for shift in (8, 4, 0)]
            assert max(channels) - min(channels) <= 2, ('tally loading ink', y, slot, pal[slot])
    for y in range(160):
        old = palette(source, 160 + (0, 13, 14).index(source[y]) * 32)
        new = palette(aligned, 160 + (0, 13, 14).index(aligned[y]) * 32)
        assert old[before['TALLY_FILL'] & 15] == new[after['TALLY_FILL'] & 15]
    return count


def main():
    provenance = json.loads((ROOT / 'build/assets/frontend-source.json').read_text())
    pages = ROOT / 'build/frontend/native/pages' / (provenance['inputs']['profile'] + '-' + provenance['cache_identity'])
    pictures = {}
    for name in ('title', 'credits', 'pg13', 'victory', 'end1', 'end2'):
        path = pages / f'{name}.bin'
        pictures[name] = check_picture(path, victory=name == 'victory')
    boot = ROOT / 'build/assets/boot-picture.shr'
    pictures['boot'] = check_picture(boot, boot=True)
    assert picture(boot.read_bytes(), boot=True) == (ROOT / 'build/assets/boot-shared.shr').read_bytes()
    pictures['tally'] = check_tally(pages / 'tally.bin')
    previews = {p.stem: check_preview(p) for p in sorted((ROOT / 'data/frontend-previews').glob('*.bin'))}
    for p in (ROOT / 'build/palettes').glob('[0-9].json'):
        colors = json.loads(p.read_text())['palette']
        check_palette([sum((c // 17) << s for c, s in zip(rgb, (8, 4, 0))) for rgb in colors], 2)
    print(json.dumps(dict(pictures=pictures, previews=previews,
                         rgb_pixels_preserved=sum(pictures.values()) + sum(previews.values()),
                         changed_rgb_pixels=0), indent=2))


if __name__ == '__main__':
    main()
