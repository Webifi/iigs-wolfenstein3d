"""Check source-level evidence without running synthesis or changing a bank."""
import array
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from audio_compile import wav_write
from audio_preview import compare_solos, raw_levels, write_model_wav
from audio_fit import DOC_RATE


def read_float(path):
    data = path.read_bytes()
    assert struct.unpack_from('<I', data, 4)[0] == len(data)-8
    position = 12
    while position+8 <= len(data):
        kind, length = struct.unpack_from('<4sI', data, position)
        body = data[position+8:position+8+length]
        if kind == b'fmt ':
            format_, channels, rate = struct.unpack_from('<HHI', body)
            assert format_ == 3
        if kind == b'data':
            values = struct.unpack('<'+'f'*(length//4), body)
            return rate, [values[c::channels] for c in range(channels)]
        position += 8+length+(length&1)
    raise AssertionError('missing WAV samples')


class PreviewChecks(unittest.TestCase):
    def test_synthesis_cannot_inherit_legacy_gain_policy(self):
        from audio_levels import conversion_level_mode
        cfg = dict(capture_source='instrument-track')
        self.assertEqual(conversion_level_mode(cfg), 'source')
        with self.assertRaisesRegex(ValueError, 'full synthesis requires'):
            conversion_level_mode(dict(cfg, level_mode='legacy'))
        with self.assertRaisesRegex(ValueError, 'complete instrument-track'):
            conversion_level_mode({})
        self.assertEqual(conversion_level_mode({}, preserved=True), 'legacy')
        self.assertEqual(conversion_level_mode(dict(level_mode='source'), preserved=True), 'source')

    def test_reference_receipt_rejects_changed_or_missing_source(self):
        from audio_levels import source_reference_receipt
        from audio_recipes import sha
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); (folder/'reference').mkdir()
            sampler = SimpleNamespace(out=folder, notes=[dict(channel=1)], data=b'selected',
                doc=dict(render=dict(reset='gs', end='release')), renderer_sha256='renderer',
                rom_inputs={'rom': 'hash'}, romset='test')
            for stem in ('full', 'channel-01'):
                wav = folder/'reference'/(stem+'.wav')
                wav.write_bytes(b'unchanged reference')
                wav.with_suffix('.mid').write_bytes(b'rendered MIDI')
                wav.with_suffix('.json').write_text(json.dumps(dict(
                    wav_sha256=sha(wav.read_bytes()), midi_sha256=sha(b'rendered MIDI'),
                    render_requested_midi_sha256=sha(b'requested MIDI'), renderer_sha256='renderer',
                    rom_inputs=sampler.rom_inputs, romset='test', render_policy=sampler.doc['render'])))
            with patch('audio_recipes.debug_midi', return_value=b'requested MIDI'):
                report = source_reference_receipt(sampler)
                self.assertEqual(len(report['references']), 2)
                self.assertEqual(report['post_render_gain'], 1)
                self.assertFalse(report['normalization'])
                wav.write_bytes(b'normalized reference')
                with self.assertRaisesRegex(ValueError, 'differs from the selected source'):
                    source_reference_receipt(sampler)
                wav.unlink()
                with self.assertRaisesRegex(ValueError, 'missing complete Roland reference'):
                    source_reference_receipt(sampler)

    def test_static_gain_keeps_envelope_transitions_and_silence(self):
        from audio_levels import adjust_track_levels
        original=[24,24,28,28,32,None,127,'done']
        values=original.copy()
        tracks=[[(0,7,SimpleNamespace(ch=5,key=60),None,values,16)]]
        adjust_track_levels(tracks,{'ch06':20*math.log10(2)/8})
        self.assertEqual(values,[23,23,27,27,31,None,127,'done'])
        self.assertEqual([i for i in range(1,8) if values[i]!=values[i-1]],
                         [i for i in range(1,8) if original[i]!=original[i-1]])

    def test_source_fitting_keeps_the_difference_between_loud_and_quiet_songs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'reference').mkdir()
            count=1024
            tone=[math.sin(2*math.pi*i/32) for i in range(count)]
            for name in ['stored.bin','unit.bin','waves.bin','stereo.txt']:
                (folder/name).write_bytes(b'unchanged')
            (folder/'notes.json').write_text('[]')
            corrections=[]
            for amplitude in [.125,.0625]:
                ref=[[v*amplitude for v in tone]]*2
                for name in ['full','channel-01']:
                    wav_write(folder/'reference'/f'{name}.wav',DOC_RATE,ref)
                before={p:p.read_bytes() for p in (folder/'reference').glob('*.wav')}
                with patch('audio_preview.render_parts',return_value={1:[[v*.5 for v in tone]]*2}):
                    report=compare_solos(folder,dict(seconds=count/DOC_RATE),source_levels=True)
                corrections.append(report['parts'][0]['level_correction_db'])
                self.assertIsNotNone(report['level_policy'])
                for p,data in before.items():self.assertEqual(p.read_bytes(),data)
            self.assertAlmostEqual(corrections[0]-corrections[1],20*math.log10(2),places=2)

    def test_source_level_is_measured_before_resampling(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'reference').mkdir();count=1024
            tone=[math.sin(2*math.pi*i/32) for i in range(count)]
            for name in ['stored.bin','unit.bin','waves.bin','stereo.txt']:
                (folder/name).write_bytes(b'unchanged')
            (folder/'notes.json').write_text('[]')
            for name in ['full','channel-01']:
                wav_write(folder/'reference'/f'{name}.wav',DOC_RATE,[[v*.125 for v in tone]]*2)
            errors=[]
            for retained in [1.,.1]:
                with patch('audio_preview.render_parts',return_value={1:[[v*.5 for v in tone]]*2}), \
                     patch('audio_resample.resample',side_effect=lambda values,*a,**k:[v*retained for v in values]):
                    report=compare_solos(folder,dict(seconds=count/DOC_RATE),source_levels=True)
                errors.append(report['parts'][0]['source_level_error_db'])
            self.assertAlmostEqual(*errors,places=10)

    def test_float_keeps_overrange_and_channel_balance(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'model.wav'
            samples = [[2.25, -1.5, 0.], [.125, -.25, 0.]]
            write_model_wav(path, 44100, samples)
            rate, result = read_float(path)
            self.assertEqual(rate, 44100)
            self.assertEqual([list(c) for c in result], samples)

    def test_comparison_never_changes_source_or_bank_or_matches_volume(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'reference').mkdir()
            count = 1024
            tone = [math.sin(2*math.pi*i/32) for i in range(count)]
            ref = [[v*.125 for v in tone], [v*.0625 for v in tone]]
            for name in ['full', 'channel-01', 'channel-02']:
                wav_write(folder/'reference'/f'{name}.wav', DOC_RATE, ref)
            for name in ['stored.bin', 'unit.bin', 'waves.bin', 'stereo.txt']:
                (folder/name).write_bytes(b'unchanged '+name.encode())
            (folder/'notes.json').write_text('[]')
            protected = {p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            for amplitude in [1., 2.]:
                parts = {1:[[v*amplitude for v in tone], [v*.5*amplitude for v in tone]],
                         2:[[v*.25 for v in tone], [v*.125 for v in tone]]}
                with patch('audio_preview.render_parts', return_value=parts):
                    report = compare_solos(folder, dict(seconds=count/DOC_RATE), write_diagnostics=True)
                _, result = read_float(folder/'doc-model-raw-full.wav')
                self.assertAlmostEqual(max(result[0]), amplitude+.25, places=6)
                self.assertAlmostEqual(max(result[1]), (amplitude+.25)*.5, places=6)
                self.assertEqual(report['output']['gain'], 1.)
                self.assertFalse(report['output']['native_game_capture'])
                self.assertFalse(report['output']['source_level_acceptance'])
                self.assertTrue(all(row['preview_gain'] == 1. for row in report['parts']))
                self.assertGreater(report['raw_levels']['doc_model']['samples_above_full_scale'], 0)
                self.assertEqual(report['files']['stored.bin'], hashlib.sha256(protected[folder/'stored.bin']).hexdigest())
                for path, data in protected.items():
                    self.assertEqual(path.read_bytes(), data)

    def test_default_emits_no_model_wav_and_preserves_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'reference').mkdir()
            for name in ['full','channel-01']:
                wav_write(folder/'reference'/f'{name}.wav', DOC_RATE, [[.25]*8,[.25]*8])
            for name in ['stored.bin','unit.bin','waves.bin','stereo.txt']:
                (folder/name).write_bytes(b'unchanged')
            (folder/'notes.json').write_text('[]')
            (folder/'doc-full.wav').write_bytes(b'legacy preview')
            with patch('audio_preview.render_parts', return_value={1:[[.5]*8,[.5]*8]}):
                report = compare_solos(folder, dict(seconds=8/DOC_RATE))
            self.assertFalse(list(folder.glob('doc-*.wav')))
            self.assertEqual(next((folder/'model-diagnostics/legacy').glob('*.wav')).read_bytes(),b'legacy preview')
            self.assertFalse(report['output']['diagnostic_wavs_written'])

    def test_missing_part_reference_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'reference').mkdir()
            (folder/'notes.json').write_text('[]')
            wav_write(folder/'reference/full.wav', DOC_RATE, [[0.]*8, [0.]*8])
            with patch('audio_preview.render_parts', return_value={1:[[0.]*8,[0.]*8]}):
                with self.assertRaisesRegex(ValueError, 'missing Roland instrument-track'):
                    compare_solos(folder, dict(seconds=8/DOC_RATE))

    def test_silence_metrics_are_valid_json_and_not_a_gain_request(self):
        result = raw_levels([[0.,0.],[0.,0.]])
        self.assertEqual(result['rms'], 0.)
        self.assertIsNone(result['rms_dbfs'])
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
