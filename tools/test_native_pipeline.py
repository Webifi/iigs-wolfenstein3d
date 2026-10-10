"""Cold source scheduling must produce inputs before starting their consumers."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from native_pipeline import source_assets


class SourceDependencies(unittest.TestCase):
    def check_palette_order(self, unknown=False):
        names = ['prepare_profile', 'build_colors']
        if unknown:
            names.append('custom_asset')
        names.append('build_sprites')
        steps = [dict(arguments=['tools/' + name + '.py']) for name in names]
        with tempfile.TemporaryDirectory() as folder:
            palette = Path(folder) / 'palette.json'
            groups = Path(folder) / 'groups.json'

            def execute(step):
                name = Path(step['arguments'][0]).stem
                if name == 'build_colors':
                    time.sleep(0.05)
                    palette.write_text('fitted')
                elif name == 'build_sprites':
                    self.assertEqual(groups.read_text(), 'fitted')

            def sprite_groups():
                groups.write_text(palette.read_text())

            with patch.dict(os.environ, {'WOLF_JOBS': '3'}):
                source_assets(steps, execute, sprite_groups=sprite_groups)

    def test_cold_parallel_palette_consumer(self):
        self.check_palette_order()

    def test_unknown_recipe_keeps_palette_before_groups(self):
        self.check_palette_order(unknown=True)


if __name__ == '__main__':
    unittest.main()
