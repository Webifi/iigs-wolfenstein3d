"""Portable parser/profile regression checks; no commercial assets are required."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from dos_data import DosData, carmack, detect, rlew, sprite
from game_profile import PROFILE_DIR, PROFILES, load_profile


def literal_huffman():
    nodes = []
    def tree(values):
        if len(values) == 1:
            return values[0]
        midpoint = len(values) // 2
        left, right = tree(values[:midpoint]), tree(values[midpoint:])
        nodes.append((left, right))
        return 255 + len(nodes)
    assert tree(list(range(256))) == 510
    nodes.append((0, 0))
    return struct.pack('<512H', *(value for pair in nodes for value in pair))


def literal_stream(raw):
    return bytes(int(f'{value:08b}'[::-1], 2) for value in raw)


def fixture(folder):
    """One small, legal map plus minimal graphics, sound and page containers."""
    folder.mkdir()
    tag = 0xabcd
    streams = [struct.pack('<5H', 8, 8192, tag, 4096, value) for value in (107, 0, 0)]
    header = struct.pack('<3I3H2H16s', 38, 48, 58, 10, 10, 10, 64, 64, b'Test floor')
    (folder/'MAPHEAD.TEST').write_bytes(struct.pack('<HI', tag, 0))
    (folder/'GAMEMAPS.TEST').write_bytes(header + b''.join(streams))
    pages = [bytes(4096), struct.pack('<4H', 0, 0, 6, 0), b'\x80\x81', struct.pack('<2H', 0, 2)]
    offsets, pos = [], 6 + 6 * len(pages)
    for page in pages:
        offsets.append(pos)
        pos += len(page)
    swap = struct.pack('<3H', len(pages), 1, 2) + struct.pack('<4I', *offsets)
    swap += struct.pack('<4H', *(len(page) for page in pages)) + b''.join(pages)
    (folder/'VSWAP.TEST').write_bytes(swap)
    graphics = [struct.pack('<2H', 4, 1), b'', b'', b'\x00\x01\x02\x03', bytes(64)]
    raw, offsets = bytearray(), []
    for index, chunk in enumerate(graphics):
        offsets.append(len(raw))
        if index != 4:
            raw += struct.pack('<I', len(chunk))
        raw += literal_stream(chunk)
    offsets.append(len(raw))
    (folder/'VGAGRAPH.TEST').write_bytes(raw)
    (folder/'VGAHEAD.TEST').write_bytes(b''.join(value.to_bytes(3, 'little') for value in offsets))
    (folder/'VGADICT.TEST').write_bytes(literal_huffman())
    audio = [struct.pack('<IH', 1, 1) + b'\x01', struct.pack('<IH', 1, 1) + bytes(17) + b'\x01', b'', b'\x00\x00']
    raw, offsets = bytearray(), [0]
    for chunk in audio:
        raw += chunk
        offsets.append(len(raw))
    (folder/'AUDIOT.TEST').write_bytes(raw)
    (folder/'AUDIOHED.TEST').write_bytes(struct.pack('<5I', *offsets))
    config = folder/'custom.toml'
    quality = (PROFILE_DIR/'conversion/stock.toml').as_posix()
    config.write_text('''format = 1
id = "custom-test"
title = "Custom test source"
engine = "wolf3d"
publication = "user-supplied"
conversion = ''' + json.dumps(quality) + '''
[files]
MAPHEAD = "MAPHEAD.TEST"
GAMEMAPS = "GAMEMAPS.TEST"
VSWAP = "VSWAP.TEST"
VGADICT = "VGADICT.TEST"
VGAHEAD = "VGAHEAD.TEST"
VGAGRAPH = "VGAGRAPH.TEST"
AUDIOHED = "AUDIOHED.TEST"
AUDIOT = "AUDIOT.TEST"
[maps]
episodes = 1
count = 1
width = 64
height = 64
compression = "carmack-rlew"
[audio]
sounds = 1
music = 1
song_names = ["TEST"]
floor_songs = ["TEST"]
[audio.events]
title = "TEST"
[[graphics.layouts]]
name = "custom-layout"
chunks = 5
pictures = 1
first_picture = 3
tile8_count = 1
[graphics.layouts.roles]
example_picture = 3
''', encoding='utf-8')
    return config


class Profiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root/'DOS data with spaces'
        self.config = fixture(self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def source(self):
        return DosData(self.data, self.config)

    def test_custom_profile_decodes_all_containers(self):
        report = self.source().inspect()
        self.assertEqual((report['floors'], report['walls'], report['sprites'], report['pictures']), (1, 1, 1, 1))
        self.assertFalse(report['full_game_runtime_verified'])
        self.assertEqual(self.source().maps()[0]['planes'][0], [107] * 4096)
        self.assertEqual(self.source().graphics()[3], bytes(range(4)))

    def test_lowercase_filenames(self):
        for path in self.data.glob('*.TEST'):
            temporary = path.with_suffix('.moving')
            path.rename(temporary)
            temporary.rename(path.with_name(path.name.lower()))
        self.assertEqual(self.source().inspect()['floors'], 1)

    def test_custom_repeated_map_is_reported_without_dropping_its_identity(self):
        self.config.write_text(self.config.read_text().replace('count = 1', 'count = 2', 1)
                               .replace('floor_songs = ["TEST"]', 'floor_songs = ["TEST", "TEST"]'))
        p = self.data/'MAPHEAD.TEST'; p.write_bytes(p.read_bytes()+struct.pack('<I',0))
        report = self.source().inspect()
        self.assertEqual(report['floors'],2)
        self.assertEqual(report['levels'][1]['same_geometry_and_objects_as'],0)
        self.assertNotEqual(report['levels'][0]['index'],report['levels'][1]['index'])

    def test_shared_files_need_no_renaming(self):
        shared = self.root/'original game'
        shared.mkdir()
        for stem in ('AUDIOT', 'AUDIOHED', 'VGAGRAPH', 'VGAHEAD', 'VGADICT'):
            shutil.move(str(self.data/(stem+'.TEST')), shared/(stem+'.TEST'))
        self.assertEqual(DosData(self.data, self.config, shared).inspect()['floors'], 1)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.source()

    def test_conflicting_shared_files_fail(self):
        shared = self.root/'other copy'
        shared.mkdir()
        (shared/'MAPHEAD.TEST').write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'different copies'):
            DosData(self.data, self.config, shared)

    def test_missing_file_names_exact_input(self):
        (self.data/'VSWAP.TEST').unlink()
        with self.assertRaisesRegex(ValueError, 'VSWAP.TEST'):
            self.source()

    def test_bad_map_offset(self):
        (self.data/'MAPHEAD.TEST').write_bytes(struct.pack('<HI', 0xabcd, 0xffffffff))
        with self.assertRaisesRegex(ValueError, 'missing map header'):
            self.source().maps()

    def test_bad_vswap_offset(self):
        path = self.data/'VSWAP.TEST'
        raw = bytearray(path.read_bytes())
        struct.pack_into('<I', raw, 6, len(raw) + 1)
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'outside payload'):
            self.source().vswap()

    def test_bad_graphics_length(self):
        path = self.data/'VGAGRAPH.TEST'
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'offsets'):
            self.source().graphics()

    def test_wrong_graphics_layout(self):
        self.config.write_text(self.config.read_text().replace('chunks = 5', 'chunks = 6'))
        with self.assertRaisesRegex(ValueError, 'unsupported .* graphics layout'):
            self.source().graphics()

    def test_bad_audio_offset(self):
        path = self.data/'AUDIOHED.TEST'
        raw = bytearray(path.read_bytes())
        struct.pack_into('<I', raw, 8, 0xffffffff)
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'audio offsets'):
            self.source().audio()

    def test_unknown_profile_field_is_not_silently_ignored(self):
        self.config.write_text(self.config.read_text().replace('count = 1', 'coutn = 1', 1))
        with self.assertRaisesRegex(ValueError, 'unknown coutn'):
            load_profile(self.config)

    def test_unknown_quality_field_is_not_silently_ignored(self):
        quality = self.root/'my quality.toml'
        quality.write_text((PROFILE_DIR/'conversion/stock.toml').read_text().replace('dither_amount', 'dither_amunt', 1))
        text = self.config.read_text()
        old = next(line for line in text.splitlines() if line.startswith('conversion ='))
        self.config.write_text(text.replace(old, 'conversion = '+json.dumps(quality.as_posix())))
        with self.assertRaisesRegex(ValueError, 'unknown dither_amunt'):
            load_profile(self.config)

    def test_named_mission_profiles_keep_shared_spear_inputs(self):
        for mission in (2, 3):
            item = PROFILES[f'spear-mission{mission}']
            self.assertEqual(item.floors, 21)
            self.assertEqual(item.files['GAMEMAPS'], f'GAMEMAPS.SD{mission}')
            self.assertEqual(item.files['VSWAP'], f'VSWAP.SD{mission}')
            self.assertEqual(item.files['VGAGRAPH'], 'VGAGRAPH.SOD')
            self.assertFalse(item.public_game_data)

    def test_auto_detection_rejects_ambiguity(self):
        for item in (PROFILES['shareware'], PROFILES['wolf3d']):
            for name in item.files.values():
                (self.data/name).touch()
        with self.assertRaisesRegex(ValueError, 'explicitly'):
            detect(self.data)

    def test_cli_custom_profile_from_another_directory(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('wolf_image.py')),
                                 'inspect', '--profile', str(self.config), '--data', str(self.data)],
                                cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['profile'], 'custom-test')

    def test_truncated_codecs_fail(self):
        for raw in (b'', b'\x01\x00', struct.pack('<2H', 2, 0xa701)):
            with self.assertRaises(ValueError):
                carmack(raw)
        for words in ([], [1], [2], [2, 0xabcd]):
            with self.assertRaises(ValueError):
                rlew(words, 0xabcd)

    def test_mission_sprite_runs_may_descend(self):
        # Two one-pixel runs, y=4 then y=1, as in the official mission data.
        raw = struct.pack('<3H', 0, 0, 6) + struct.pack('<7H', 10, 16, 8, 4, 20, 2, 0) + b'\x31\x42'
        self.assertEqual(sprite(raw)['columns'][0], [(4, 5, b'\x31'), (1, 2, b'\x42')])


if __name__ == '__main__':
    unittest.main()
