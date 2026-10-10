"""Preserve retained floor bytes and flagged walls; reject lossy plane conversion."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from build_assets import pack_level
from build_logic import LAYOUT, level_image
from native_map_format import native_plane_bytes, wall_material
import sourceview
from wolfdata import ROOT, maps, vswap


def check():
    pages, first_sprite, _ = vswap()
    levels = maps()
    with tempfile.TemporaryDirectory(prefix='native-map-') as temporary:
        for index, level in enumerate(levels[:10]):
            existing = ROOT / 'build/levels' / str(index)
            colors = json.loads((ROOT / f'build/palettes/{index}.json').read_text())
            out = Path(temporary) / str(index)
            packed, _, _ = pack_level(level, pages, first_sprite, colors['palette'], colors, out, index)
            for name in ('map.bin', 'column-dir.bin'):
                assert (out / name).read_bytes() == (existing / name).read_bytes(), (index, name)
            assert packed == json.loads((existing / 'map.json').read_text()), index
            assert (out / 'art-index.bin').read_bytes() == (existing / 'art-index.bin').read_bytes()[:packed['wall_index_bytes']]
            logic = (existing / 'logic.bin').read_bytes()
            for plane in (0, 1):
                start = LAYOUT[f'RAW{plane}']
                assert native_plane_bytes(level['planes'][plane], floor=index, plane=plane) == logic[start:start + 4096]

        colors = json.loads((ROOT / 'build/palettes/0.json').read_text())
        walls = [1] * 4096
        info = [0] * 4096
        walls[65] = walls[66] = 107
        walls[67] = 85
        info[65] = 20
        level = dict(name='Flagged wall', planes=[walls, info, [0] * 4096])
        out = Path(temporary) / 'flagged'
        packed, _, _ = pack_level(level, pages, first_sprite, colors['palette'], colors, out, 0)
        assert (out / 'map.bin').read_bytes()[3 * 64 + 1] == 85
        assert 40 in packed['textures'] and 41 in packed['textures']
        assert 42 not in packed['textures'], 'a flagged side is not a usable elevator switch'
        assert 168 not in packed['textures'] and 169 not in packed['textures']
        assert wall_material(85) == 21 and wall_material(101) is None

        resources = sourceview.resources()
        pose = dict(x=640, y=384, angle=0)
        with patch.object(sourceview, 'resources', return_value=([level], *resources[1:])):
            flagged, _ = sourceview.source_frame(0, pose, 240, status=False)
        walls[67] = 21
        with patch.object(sourceview, 'resources', return_value=([level], *resources[1:])):
            plain, _ = sourceview.source_frame(0, pose, 240, status=False)
        assert flagged == plain, 'door-side bit alone must preserve the wall picture'

        original = list(info)
        info[2 * 64 + 3] = 256
        with patch('build_logic.maps', return_value=[level]):
            try:
                level_image(0, bytes(65536))
            except ValueError as error:
                assert '256 at (3,2)' in str(error) and 'plane 1' in str(error), str(error)
            else:
                raise AssertionError('high source object word was silently discarded')
        assert info[2 * 64 + 3] == 256 and all(a == b for i, (a, b) in enumerate(zip(info, original)) if i != 131)
    print('Ten retained floor maps/art directories/raw planes unchanged; flagged material and 16-bit rejection checks pass.')


if __name__ == '__main__':
    check()
