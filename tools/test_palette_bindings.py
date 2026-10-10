"""Palette-slot regression checks without native images or licensed assets."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from build_colors import ordered_colors, seed_colors
from check_palette_bindings import check
from shared_gray import floor_record


class PaletteBindings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'build/palettes').mkdir(parents=True)
        (self.root/'build/levels/0').mkdir(parents=True)
        self.colors = [(0,0,0),(13,13,13),(14,2,2),(8,0,0),(11,13,2),
                       (13,8,5),(8,5,3),(5,3,1),(3,3,3),(0,8,8),
                       (2,2,2),(0,0,9),(9,9,9),(7,7,7),(5,5,5),(0,0,4)]
        self.palette = [[v*17 for v in c] for c in ordered_colors(self.colors)]
        self.receipt = self.root/'build/palettes/0.json'
        self.receipt.write_text(json.dumps(dict(floor=1,palette=self.palette)))
        self.metadata = self.root/'build/levels/0/map.json'
        self.metadata.write_text(json.dumps(dict(palette=self.palette)))
        self.tints = self.root/'build/palettes/tints-1.bin'
        self.tints.write_bytes(struct.pack('<16H', *((r//17<<8)|(g//17<<4)|b//17 for r,g,b in self.palette))*10)

    def test_consistent(self):
        self.assertEqual(check(self.root,[0])['floors'],1)

    def test_reordered_receipt_is_rejected(self):
        palette = self.palette[:]
        palette[6],palette[12] = palette[12],palette[6]
        self.receipt.write_text(json.dumps(dict(floor=1,palette=palette)))
        with self.assertRaisesRegex(ValueError,'map palette differs'):
            check(self.root,[0])

    def test_stale_display_palette_is_rejected(self):
        raw = bytearray(self.tints.read_bytes())
        raw[12:14],raw[24:26] = raw[24:26],raw[12:14]
        self.tints.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'display palette differs'):
            check(self.root,[0])

    def test_final_order_preserves_every_color(self):
        self.assertCountEqual(ordered_colors(self.colors),self.colors)

    def local_packet(self):
        from frontend.gray_pair import pair_table, preview_bytes, words_of
        local = self.root/'build/assets/gray-local'
        local.mkdir(parents=True)
        tints = self.tints.read_bytes()
        record = pair_table(words_of(tints[:32])) + preview_bytes(words_of(tints[:32]))
        (local/'floor-00-tints.bin').write_bytes(tints)
        (local/'floor-00.bin').write_bytes(tints + bytes(192) + record*10)
        (local/'floor-00-records.bin').write_bytes(record*10 + bytes(192))
        return local

    def test_current_packaged_palette(self):
        self.local_packet()
        self.assertEqual(check(self.root,[0])['floors'],1)

    def test_stale_packaged_palette_is_rejected(self):
        local = self.local_packet()
        (local/'floor-00-tints.bin').write_bytes(bytes(320))
        with self.assertRaisesRegex(ValueError,'packaged display tints are stale'):
            check(self.root,[0])

    def test_stale_menu_conversion_is_rejected(self):
        local = self.local_packet()
        (local/'floor-00-records.bin').write_bytes(bytes(3072))
        with self.assertRaisesRegex(ValueError,'packaged menu conversion is stale'):
            check(self.root,[0])

    def test_seed_anchors_can_have_moved_during_alignment(self):
        palette = self.palette[:]
        palette[1],palette[12] = palette[12],palette[1]
        colors = seed_colors(palette)
        self.assertEqual(colors[:2],[(0,0,0),(13,13,13)])
        self.assertCountEqual(colors,self.colors)

    def test_asset_consumer_keeps_generator_order(self):
        before = self.receipt.read_bytes()
        floor_record(self.receipt)
        self.assertEqual(self.receipt.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
