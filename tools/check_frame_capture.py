"""Check capture retention without launching an emulator."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from frame_capture import FRAME_BYTES, capture_index, compact_capture


class CaptureRetention(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / 'hashes'

    def case(self, name, raw=None, wrong=0):
        if raw is None:
            raw = bytes(range(256)) * (FRAME_BYTES // 256) * 2
        folder = self.root / name / 'd0-v214'
        folder.mkdir(parents=True)
        (folder / 'frames.pixels').write_bytes(raw)
        result = dict(frames=2, seconds=0.2,
                      frame_times=[dict(frame=1, ns=100000000), dict(frame=2, ns=100000000)])
        (folder / 'result.json').write_text(json.dumps(result))
        (folder.parent / 'summary.json').write_text(json.dumps(dict(cases=[
            dict(demo=0, view=214, wrong_bytes=wrong, exposed_bytes=wrong)])))
        return folder / 'frames.pixels'

    def compare(self, before, after, *extra):
        # Redirect only the test's hash store; the comparison still runs its real CLI.
        code = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                'import frame_capture;'
                'frame_capture.compact_capture.__defaults__=(frame_capture.Path(sys.argv.pop(1)),);'
                'import paint_write_compare;paint_write_compare.main()')
        return subprocess.run([sys.executable, '-c', code, str(Path(__file__).parent),
                               str(self.store), str(before.parent.parent), str(after.parent.parent),
                               '--out', str(self.root/'comparison.json'), *extra],
                              capture_output=True, text=True)

    def test_success_keeps_exact_hashes_and_inputs(self):
        before, after = self.case('before'), self.case('after')
        expected = capture_index(before)
        media = before.parent / 'wolf-hd.po'
        audio = before.parent / 'audio.wav'
        media.write_bytes(b'original disk'); audio.write_bytes(b'original audio')
        self.assertEqual(self.compare(before, after).returncode, 0)
        self.assertFalse(before.exists()); self.assertFalse(after.exists())
        self.assertEqual(capture_index(before), expected)
        self.assertEqual(capture_index(after), expected)
        self.assertEqual(len(list(self.store.glob('*.json'))), 1)
        self.assertEqual(media.read_bytes(), b'original disk')
        self.assertEqual(audio.read_bytes(), b'original audio')
        self.assertEqual(self.compare(before, after).returncode, 0)

    def test_failed_comparison_retains_raw(self):
        before = self.case('before')
        changed = bytearray(before.read_bytes()); changed[10] ^= 1
        after = self.case('after', changed)
        self.assertNotEqual(self.compare(before, after).returncode, 0)
        self.assertTrue(before.exists()); self.assertTrue(after.exists())
        row = json.loads((self.root/'comparison.json').read_text())['cases'][0]
        self.assertEqual(row['differing_frames'], [dict(frame=1, bytes=1)])

    def test_hash_reference_detects_change_without_invented_byte_count(self):
        before = self.case('before')
        changed = bytearray(before.read_bytes()); changed[10] ^= 1
        compact_capture(before, self.store)
        after = self.case('after', changed)
        self.assertNotEqual(self.compare(before, after).returncode, 0)
        self.assertTrue(after.exists())
        row = json.loads((self.root/'comparison.json').read_text())['cases'][0]
        self.assertEqual(row['differing_frames'], [dict(frame=1, bytes=None)])

    def test_transient_failure_keeps_raw(self):
        before, after = self.case('before'), self.case('after', wrong=1)
        self.assertEqual(self.compare(before, after).returncode, 0)
        self.assertTrue(before.exists()); self.assertTrue(after.exists())

    def test_keep_override(self):
        before, after = self.case('before'), self.case('after')
        self.assertEqual(self.compare(before, after, '--keep-captures').returncode, 0)
        self.assertTrue(before.exists()); self.assertTrue(after.exists())

    def test_partial_or_missing_frames_are_not_removed(self):
        for name, raw in [('partial', b'x'), ('short', bytes(FRAME_BYTES))]:
            path = self.case(name, raw)
            with self.assertRaises(ValueError): compact_capture(path, self.store)
            self.assertEqual(path.read_bytes(), raw)

    def test_corrupt_index_cannot_discard_raw(self):
        first, second = self.case('first'), self.case('second')
        compact_capture(first, self.store)
        index = next(self.store.glob('*.json'))
        data = json.loads(index.read_text()); data['frame_sha256'][0] = '0'*64
        index.write_text(json.dumps(data))
        with self.assertRaises(ValueError): capture_index(first)
        with self.assertRaises(ValueError): compact_capture(second, self.store)
        self.assertTrue(second.exists())


if __name__ == '__main__':
    unittest.main()
