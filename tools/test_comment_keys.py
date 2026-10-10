"""Documentation changes preserve code keys; literal data stays byte keyed."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from step_cache import StepCache

TOOLS = Path(__file__).resolve().parent
PROGRAM = '''"""Module documentation."""
from pathlib import Path
class Value:
    """Class documentation."""
    def get(self):
        """Method documentation."""
        def inner():
            """Nested documentation."""
            return b"literal # data"
        return inner()
Path('build/result').write_bytes(Value().get())
'''


class CommentKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(TOOLS, self.root/'tools', ignore=shutil.ignore_patterns('__pycache__', 'build'))
        (self.root/'build').mkdir()
        self.path = self.root/'tools/example.py'
        self.path.write_text(PROGRAM)
        self.environment = patch.dict(os.environ, WOLF_SHARED_CACHE='0', PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.tmp.cleanup()

    def build(self):
        cache = StepCache(self.root, log=lambda line: None)
        with (self.root/'run.log').open('w') as log:
            ran = cache.python([sys.executable, 'tools/example.py'], dict(os.environ), log)
        cache.finish()
        return ran

    def test_comments_and_nested_docstrings(self):
        self.assertTrue(self.build())
        self.path.write_text('# Additional comment.\n'+PROGRAM.replace('documentation.', 'documentation changed.'))
        self.assertFalse(self.build())
        self.assertEqual((self.root/'build/result').read_bytes(), b'literal # data')
        self.path.write_text(PROGRAM.replace('literal # data', 'changed # data'))
        self.assertTrue(self.build())

    def test_explicit_source_bytes_remain_inputs(self):
        text="from pathlib import Path\nPath('build/result').write_bytes(Path(__file__).read_bytes())\n"
        self.path.write_text(text)
        self.assertTrue(self.build())
        self.path.write_text(text+'# This comment is output data.\n')
        self.assertTrue(self.build())
        self.assertEqual((self.root/'build/result').read_bytes(), self.path.read_bytes())

    def test_declared_code_and_config_fingerprints(self):
        helper = self.root/'tools/helper.py'
        config = self.root/'settings.toml'
        helper.write_text('"""Docs."""\nVALUE = 1\n')
        config.write_text('value = 1\n')
        self.path.write_text("from pathlib import Path\nimport sys\n"
                            "sys.path.insert(0, str(Path('tools/doccompiler/..').absolute()))\n"
                            "from source_identity import source_digest\n"
                            "Path('build/result').write_text(source_digest('tools/helper.py')+source_digest('settings.toml'))\n")
        self.assertTrue(self.build())
        helper.write_text('# Comment.\n"""Revised docs."""\nVALUE = 1\n')
        config.write_text('# Comment.\nvalue = 1 # Units.\n')
        self.assertFalse(self.build())
        helper.write_text('VALUE = 2\n')
        self.assertTrue(self.build())
        config.write_text('value = 2\n')
        self.assertTrue(self.build())

    def test_generated_function_source(self):
        helper = self.root/'tools/helper.py'
        helper.write_text('def value():\n    """Docs."""\n    return b"value"\n')
        self.path.write_text("from pathlib import Path\nfrom source_identity import function_source\n"
                            "import helper\nnamespace={}\nexec(function_source(helper.value),namespace)\n"
                            "Path('build/result').write_bytes(namespace['value']())\n")
        self.assertTrue(self.build())
        helper.write_text('# Comment.\ndef value():\n    """Revised docs."""\n    return b"value"\n')
        self.assertFalse(self.build())
        helper.write_text('def value():\n    return b"new"\n')
        self.assertTrue(self.build())

    def test_completed_outputs_survive_old_producer(self):
        cache = StepCache(self.root, log=lambda line: None)
        old = [sys.executable, 'tools/example.py', '--workers', '8']
        new = [sys.executable, 'tools/example.py', '--workers', '3']
        consumer = [sys.executable, 'tools/consumer.py']
        with (self.root/'run.log').open('w') as log:
            cache.python(old, dict(os.environ), log)
        product = self.root/'build/result'
        cache.completed_outputs([product])
        cache.set_plan([new, consumer])
        cache.hide_later(consumer)
        self.assertTrue(product.is_file())
        cache.drop_old_steps()
        self.assertEqual(product.read_bytes(), b'literal # data')

    def test_previous_format_producer_ownership(self):
        old = StepCache(self.root, log=lambda line: None)
        old.identity['format'] = 2
        command = [sys.executable, 'tools/example.py']
        consumer = [sys.executable, 'tools/consumer.py']
        with (self.root/'run.log').open('w') as log:
            old.python(command, dict(os.environ), log)
        cache = StepCache(self.root, log=lambda line: None)
        cache.set_plan([command, consumer])
        cache.mark(command)
        cache.hide_later(consumer)
        self.assertTrue((self.root/'build/result').is_file())


if __name__ == '__main__':
    unittest.main()
