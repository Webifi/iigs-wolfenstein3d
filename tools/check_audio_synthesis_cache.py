"""Check process-local hash reuse and invalidation during audio builds."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from audio_build_cache import checked_digest, digest, inputs


class DigestTests(unittest.TestCase):
    def test_export_rechecks_authenticated_package(self):
        from audio_provenance import snapshot, begin, complete, validate
        from doc_preview import BindingChecks
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'score.mid'
            source.write_bytes(b'score')
            package = root/'pack'
            identity = snapshot('fixture', None, [source], root)
            begin(package, identity)
            bank = package/'bank.bin'
            bank.write_bytes(b'bank')
            complete(package, identity, root)
            with patch('doc_preview.validate', side_effect=lambda p: validate(p, root)):
                checks = BindingChecks()
                checks.package(package/'audio-build.json')
                bank.write_bytes(b'edit')
                with self.assertRaises(ValueError):
                    checks.verify()

    def test_recording_measurements_follow_the_wav_hash(self):
        from audio_compare import recording_info, _wav_info
        _wav_info.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'recording.wav'
            def write(sample):
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(48000)
                    wav.writeframes(sample.to_bytes(2, 'little', signed=True)*480)
            write(100)
            first_hash = digest(path)
            first = recording_info(path, first_hash)
            with patch('audio_compare.wave.open', side_effect=AssertionError('WAV reread')):
                self.assertEqual(recording_info(path, first_hash), first)
            write(1000)
            second = recording_info(path, digest(path))
            self.assertAlmostEqual(second['peak_dbfs']-first['peak_dbfs'], 20)
            self.assertAlmostEqual(second['rms_dbfs']-first['rms_dbfs'], 20)
            self.assertEqual(second['frames'], 480)

    def test_generated_code_cache_is_not_an_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'compiler.py').write_text('source')
            before = inputs([root], exclude_dirs=('build',))
            (root/'build/host').mkdir(parents=True)
            artifact = root/'build/host/compiler.so'
            artifact.write_bytes(b'generated')
            self.assertEqual(before, inputs([root], exclude_dirs=('build',)))
            self.assertIn(str(artifact.resolve()), inputs([artifact], exclude_dirs=('build',))['files'])

    def test_reuse_and_changes(self):
        checked_digest.cache_clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'audio.bin'
            path.write_bytes(b'original')
            first = digest(path)
            self.assertEqual(digest(path), first)
            self.assertEqual(checked_digest.cache_info().hits, 1)
            old = path.stat()
            path.write_bytes(b'changed!')
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
            self.assertEqual(digest(path), hashlib.sha256(b'changed!').hexdigest())
            self.assertNotEqual(digest(path), first)
            replacement = path.with_suffix('.new')
            replacement.write_bytes(b'replaced')
            os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
            replacement.replace(path)
            self.assertEqual(digest(path), hashlib.sha256(b'replaced').hexdigest())
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                digest(path)


if __name__ == '__main__':
    unittest.main()
