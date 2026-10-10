"""Regress missing/stale-output rebuilds, failed stages and unchanged previews."""
import json
import base64
from pathlib import Path
import tempfile
import unittest
import wave
from audio_build_cache import inputs,stage
from audio_compare import export,digest


class BuildTests(unittest.TestCase):
    def test_missing_changed_and_new_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'mapping.toml';source.write_text('program=39')
            calls=[]
            def build(out):
                calls.append(1);(out/'reference.wav').write_bytes(source.read_bytes())
            folder,changed=stage(root,'song',inputs([source]),build)
            self.assertTrue(changed)
            self.assertFalse(stage(root,'song',inputs([source]),build)[1])
            (folder/'reference.wav').unlink()
            self.assertTrue(stage(root,'song',inputs([source]),build)[1])
            (folder/'reference.wav').write_bytes(b'wrong existing WAV')
            self.assertTrue(stage(root,'song',inputs([source]),build)[1])
            source.write_text('program=40')
            self.assertTrue(stage(root,'song',inputs([source]),build)[1])
            self.assertEqual(len(calls),4)

    def test_failed_stage_never_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def fail(out):
                (out/'partial.wav').write_bytes(b'partial')
                raise ValueError('render failed')
            for _ in range(2):
                with self.assertRaises(ValueError):stage(root,'failed',{},fail)
            self.assertFalse(list(root.rglob('.stage.json')))

    def test_standalone_player_preserves_wav_and_repairs_missing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav'
            with wave.open(str(source),'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'));wav.writeframes(b'\x17\x02'*800)
            rows=[dict(label='</script> musical part',note='Reference',versions=[dict(label='Source',kind='test fixture',source=source,sha256=digest(source))])]
            page=export(root/'preview','Comparison',rows)
            self.assertNotIn('fetch(',page.read_text())
            self.assertNotIn('</script> musical part',page.read_text())
            catalog=json.loads((page.parent/'sources.json').read_text())
            version=catalog['items'][0]['versions'][0]
            payload=page.parent/version['payload']
            arguments=json.loads('['+payload.read_text().removeprefix('window.audioFileLoaded(').removesuffix(');\n')+']')
            self.assertEqual(arguments[0],digest(source))
            self.assertEqual(base64.b64decode(arguments[1]),source.read_bytes())
            payload.write_text('broken payload');export(page.parent,'Comparison',rows)
            self.assertIn('window.audioFileLoaded(',payload.read_text())
            page_text=page.read_text()
            for feature in ('id="songs"','id="wave"','id="head"','WAV RMS','ArrowLeft','ArrowRight','s.start(t0,','ctx.createBufferSource()'):
                self.assertIn(feature,page_text)
            wav=page.parent/catalog['items'][0]['versions'][0]['file']
            self.assertEqual(wav.read_bytes(),source.read_bytes())
            wav.unlink();export(page.parent,'Comparison',rows)
            self.assertEqual(wav.read_bytes(),source.read_bytes())
            wav.write_bytes(b'corrupt');export(page.parent,'Comparison',rows)
            self.assertEqual(wav.read_bytes(),source.read_bytes())


if __name__=='__main__':unittest.main()
