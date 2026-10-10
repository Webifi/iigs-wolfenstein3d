"""Reject stale banks in music directories, floor references and boot copies."""
import memmap
import json
from pathlib import Path
import struct
import tempfile
import unittest

from check_media_audio import Media, check, digest
from check_music_packs import bank


class PackedMusic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.song = bank()
        self.blocks = (len(self.song)+511)//512
        self.report = dict(profile='wolf3d', required_songs=1, songs=[dict(
            id=3, name='GETTHEM', bytes=len(self.song), sha256=digest(self.song))])
        self.store = bytearray((5+self.blocks)*512)
        self.store[:8] = b'WOLFEP05'
        struct.pack_into('<2H', self.store, 8, 1, 1)
        struct.pack_into('<3H', self.store, 12, 3, 1, 0)
        self.store[1024:1032] = b'WOLFMS02'
        record = (0, 0x3e, 5, self.blocks)
        struct.pack_into('<4H', self.store, 1024+64+3*8, *record)
        struct.pack_into('<4H', self.store, 1536, *record)
        self.store[2560:2560+len(self.song)] = self.song
        self.disk = self.root/'wolf-hd.po'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, second=False, initial=None):
        head = bytearray(512)
        head[:8] = b'WOLFGS'+bytes((1, 2 if second else 1))
        head[8] = 1
        struct.pack_into('<IHH', head, 16, memmap.MUSIC_BASE, 2, self.blocks)
        n = len(self.store)//512
        first_count = 5 if second else n
        struct.pack_into('<3H2B', head, 24, 0, first_count, 2+self.blocks, 1, 0)
        raw = bytearray(512)+head+(initial or self.song).ljust(self.blocks*512,b'\0')+self.store[:first_count*512]
        self.disk.write_bytes(raw)
        if second:
            head[6], head[8] = 2, 0
            head[16:32] = bytes(16)
            struct.pack_into('<3H2B', head, 16, 5, n-5, 2, 2, 0)
            (self.root/'wolf-hd2.po').write_bytes(bytearray(512)+head+self.store[first_count*512:])

    def test_single_and_multiple_volumes(self):
        for second in (False, True):
            self.write(second)
            result = check(self.disk, self.report)
            self.assertEqual(result['songs'][0]['sha256'], digest(self.song))
            self.assertEqual(len(result['images']), 2 if second else 1)

    def test_resident_data_inside_a_run_crossing_banks(self):
        head=bytearray(512);head[8]=1
        struct.pack_into('<IHH',head,16,memmap.TEST_MARKERS,2,2)
        payload=bytes(range(256))*4
        media=Media.__new__(Media)
        media.headers=[head];media.images=[bytes(1024)+payload]
        self.assertEqual(media.resident(0x400000,512),payload[256:768])
        self.assertEqual(media.resident(0x4002f0,16),payload[-16:])
        self.assertIsNone(media.resident(0x400300,1))

    def test_selected_bank_changed(self):
        self.write()
        self.report['songs'][0]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Packed music differs'):
            check(self.disk, self.report)

    def test_disk_bank_changed(self):
        self.store[2600] ^= 1
        self.write(True)
        with self.assertRaisesRegex(ValueError, 'Packed music differs'):
            check(self.disk, self.report)

    def test_floor_references_old_bank(self):
        struct.pack_into('<H', self.store, 1536+4, 4)
        self.write()
        with self.assertRaisesRegex(ValueError, 'Floor music differs'):
            check(self.disk, self.report)

    def test_resident_copy_is_old(self):
        different = bytearray(self.song)
        different[40] ^= 1
        self.write(initial=different)
        with self.assertRaisesRegex(ValueError, 'Initial resident music differs'):
            check(self.disk, self.report)

    def test_missing_second_disk(self):
        self.write(True)
        (self.root/'wolf-hd2.po').unlink()
        with self.assertRaises(FileNotFoundError):
            check(self.disk, self.report)

    def test_mismatched_second_disk(self):
        self.write(True)
        path = self.root/'wolf-hd2.po'
        data = bytearray(path.read_bytes())
        data[512+432] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'Mismatched supplemental'):
            check(self.disk, self.report)


if __name__ == '__main__':
    unittest.main()
