"""Prepared-music input checks using synthetic banks, without game data."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from check_dos_profiles import fixture
from game_profile import PROFILES
from music_pack import MusicPack, decode_lz, inspect_song


def literals(data):
    return b''.join(bytes([len(data[i:i + 128]) - 1]) + data[i:i + 128]
                    for i in range(0, len(data), 128))


def bank(blocks=False):
    hot = bytearray(0x601)
    struct.pack_into('<4s4H4BI', hot, 0, b'WDM2', 0x600, 1, len(hot), 256, 0xf3, 24, 1, 1, 140)
    hot[-1] = 0xe0
    waves = bytes([128]) * 256
    packed = literals(hot)
    header = bytearray(32)
    if blocks:
        delta = literals(bytes([128]) + bytes(255))
        struct.pack_into('<4s10H', header, 0, b'WDP3', 0xf300, 256, 1024, len(delta),
                         len(packed), len(hot), 0, 1024, 1024 + len(delta), 2)
        return bytes(header) + bytes(1024 - 32) + delta + packed
    struct.pack_into('<4s6H', header, 0, b'WDP2', 0xf300, 256, 32, 32 + len(waves), len(packed), len(hot))
    return bytes(header) + waves + packed


class Packs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = fixture(self.root/'DOS inputs')
        self.folder = self.root/'music pack with spaces'
        self.folder.mkdir()
        self.song = self.folder/'song-00.bin'
        self.song.write_bytes(bank())
        self.config = self.folder/'pack.toml'
        self.write_pack()

    def tearDown(self):
        self.temporary.cleanup()

    def write_pack(self, **changes):
        values = dict(catalog='wolf3d', name='TEST', file='song-00.bin',
                      sha256=hashlib.sha256(self.song.read_bytes()).hexdigest())
        values.update(changes)
        self.config.write_text('format = 1\nplayer = "wdm2"\ncatalog = ' + json.dumps(values['catalog']) +
                               '\n[[songs]]\n' + '\n'.join(key + ' = ' + json.dumps(values[key])
                                                          for key in ('name', 'file', 'sha256')) + '\n')

    def load(self):
        return MusicPack(self.folder, self.profile)

    def test_pack_is_usable_without_synthesizer(self):
        report = self.load().inspect()
        self.assertEqual(report['required_songs'], 1)
        self.assertFalse(report['synthesizer_required'])
        self.assertFalse(report['audio_quality_verified'])
        self.assertEqual(self.load().songs[0].data, self.song.read_bytes())

    def test_wdp2_and_wdp3_decode_identically(self):
        raw, packed = inspect_song(bank()), inspect_song(bank(True))
        self.assertEqual(raw['hot_sha256'], packed['hot_sha256'])
        self.assertEqual(raw['wave_sha256'], packed['wave_sha256'])
        self.assertEqual(raw['doc_bytes'], 256)

    def test_existing_json_manifest(self):
        self.config.unlink()
        (self.folder/'manifest.json').write_text(json.dumps([dict(id=0, song='TEST', name='TEST_MUS', format='WDM2',
                                     cold_sha256=hashlib.sha256(self.song.read_bytes()).hexdigest())]))
        self.assertEqual(self.load().songs[0].report['id'], 0)

    def test_changed_hash(self):
        self.song.write_bytes(bank()[:-1] + b'\xff')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.load()

    def test_wrong_catalog(self):
        self.write_pack(catalog='spear')
        with self.assertRaisesRegex(ValueError, 'catalog/player'):
            self.load()

    def test_wrong_song(self):
        self.write_pack(name='WRONG')
        with self.assertRaisesRegex(ValueError, 'not in the selected catalog'):
            self.load()

    def test_duplicate_song(self):
        text = self.config.read_text()
        self.config.write_text(text + '\n[[songs]]' + text.split('[[songs]]')[1])
        with self.assertRaisesRegex(ValueError, 'duplicate music song'):
            self.load()

    def test_missing_song(self):
        text = self.profile.read_text().replace('music = 1', 'music = 2').replace(
            'song_names = ["TEST"]', 'song_names = ["TEST", "ENDING"]').replace('title = "TEST"', 'title = "ENDING"')
        self.profile.write_text(text)
        with self.assertRaisesRegex(ValueError, 'missing songs.*ENDING'):
            self.load()

    def test_unknown_setting(self):
        self.config.write_text(self.config.read_text() + 'sh256 = "typo"\n')
        with self.assertRaisesRegex(ValueError, 'unknown sh256'):
            self.load()

    def test_portable_relative_paths(self):
        for name in ('../song.bin', '/song.bin', 'C:/song.bin', 'nested\\song.bin'):
            with self.subTest(name=name):
                self.write_pack(file=name)
                with self.assertRaises(ValueError):
                    self.load()
        nested = self.folder/'nested'
        nested.mkdir()
        self.song.rename(nested/'song.bin')
        self.song = nested/'song.bin'
        self.write_pack(file='nested/song.bin')
        self.assertEqual(len(self.load().songs), 1)

    def test_bank_limit(self):
        self.song.write_bytes(bank() + bytes(65536))
        self.write_pack()
        with self.assertRaisesRegex(ValueError, 'exceeds 65536'):
            self.load()

    def test_doc_overlap(self):
        data = bytearray(bank())
        struct.pack_into('<H', data, 4, 0xf400)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            inspect_song(data)

    def test_unsupported_huffman(self):
        data = bytearray(bank(True))
        struct.pack_into('<H', data, 22, 1)
        with self.assertRaisesRegex(ValueError, 'kind 2'):
            inspect_song(data)

    def test_truncated_and_oversized_lz(self):
        for data, size in ((b'', 1), (b'\x00', 1), (b'\x80\x00', 3), (b'\x80\x00\x00', 3), (b'\x01ab', 1)):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    decode_lz(data, 0, len(data), size)

    def test_unread_input_overlap(self):
        # A long backward match would overwrite the next, unread literal.
        data = b'\x00A\xff\x01\x00\x00B'
        with self.assertRaisesRegex(ValueError, 'overwrites unread input'):
            decode_lz(data, 0, len(data), 132)

    def test_hot_header_mismatch(self):
        data = bytearray(bank())
        start = struct.unpack_from('<H', data, 10)[0]
        data[start + 1 + 12] = 0x40
        with self.assertRaisesRegex(ValueError, 'headers disagree'):
            inspect_song(data)

    def test_cli_from_another_directory(self):
        command = [sys.executable, str(Path(__file__).with_name('wolf_image.py')), 'inspect-music',
                   '--profile', str(self.profile), '--music-pack', str(self.folder)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['required_songs'], 1)

    def test_original_game_coverage(self):
        self.assertEqual(len(PROFILES['shareware'].required_music), 11)
        self.assertEqual(len(PROFILES['wolf3d'].required_music), 23)
        for name in ('spear', 'spear-mission2', 'spear-mission3'):
            self.assertEqual(len(PROFILES[name].required_music), 24)
            self.assertEqual(PROFILES[name].music_names[7], 'XTHEEND')
        self.assertEqual(PROFILES['wolf3d'].music_names[7], 'NAZI_NOR')


if __name__ == '__main__':
    unittest.main()
