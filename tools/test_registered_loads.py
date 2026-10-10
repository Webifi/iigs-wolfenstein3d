"""Derived spans stay complete while independent checks read them."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import memmap
import registered_loads


class PublishedSpans(unittest.TestCase):
    def test_parallel_art_banks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            floor = root / 'build/levels/0'
            floor.mkdir(parents=True)
            raw = bytes(range(256)) * 128
            (floor / 'art.bin').write_bytes(raw)
            (floor / 'registered-art-loads.json').write_text(json.dumps([
                dict(file='art.bin', address=memmap.BOOT_STAGE, bytes=len(raw))]))
            expected = raw.ljust(65536, b'\0')

            def check_bank(_):
                for _ in range(50):
                    rows = registered_loads.art_rows(0)
                    self.assertEqual((root / rows[0]['file']).read_bytes(), expected)

            with patch.object(registered_loads, 'ROOT', root):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(check_bank, range(3)))

    def test_parallel_gray_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            raw = bytes(range(256)) * 48
            (assets / 'menu-cache.json').write_text('{"regions": []}')
            (assets / 'graytables.bin').write_bytes(raw)
            (assets / 'gray-local.json').write_text(json.dumps(dict(shared_bytes=len(raw))))

            def check_body(_):
                for _ in range(50):
                    registered_loads.ui_rows()
                    self.assertEqual((assets / 'gray-shared-body.bin').read_bytes(), raw[0x800:])

            with patch.object(registered_loads, 'ASSETS', assets):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(check_body, range(3)))


if __name__ == '__main__':
    unittest.main()
