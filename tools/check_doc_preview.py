"""Exercise easy-build preview identity and regeneration without a synthesizer."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import doc_preview
from audio_build_cache import digest
from audio_provenance import snapshot,begin,complete


class PreviewTests(unittest.TestCase):
    def test_public_build_failure_withdraws_the_previous_player(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'out';page=out/'comparisons/preview/index.html'
            page.parent.mkdir(parents=True);page.write_text('old playback page')
            run=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'build.py'),
                '--game','wolf3d','--audio-only','--audio-song','GETTHEM','--no-audio-preview',
                '--data',str(Path(temp)/'missing-data'),'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(run.returncode,2,run.stdout+run.stderr)
            catalog=json.loads(page.with_name('sources.json').read_text())
            self.assertEqual(catalog['items'][0]['status'],'failed')
            self.assertEqual(catalog['items'][0]['versions'],[])

    def test_packed_selection_must_match_the_rebuilt_bank(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);compiled=root/'compiled';recipe=root/'song.toml';recipe.write_text('song="TEST"\n')
            identity=snapshot('music-pack','fixture',[recipe]);begin(compiled,identity)
            (compiled/'song-00.bin').write_bytes(b'rebuilt bank');complete(compiled,identity)
            work=root/'work';(work/'build/gen').mkdir(parents=True)
            engine=work/'build/wolf.elf';engine.write_bytes(b'engine')
            (work/'build/gen/audio-input.json').write_text(json.dumps(dict(songs=[dict(id=0,name='TEST',sha256='different bank')])) )
            media=root/'media';media.mkdir()
            (media/'native-build.json').write_text(json.dumps(dict(work_directory=str(work),audio_receipt_sha256=digest(compiled/'audio-build.json'))))
            with self.assertRaisesRegex(ValueError,'selection differs from rebuilt bank'):
                doc_preview.media_binding(media,compiled,engine)

    def test_rebuilds_changed_or_missing_outputs_and_never_fills_reference_slots(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);compiled=root/'compiled';recipe=root/'song.toml';recipe.write_text('song="TEST"\n')
            identity=snapshot('music','fixture',[recipe]);begin(compiled,identity)
            bank=compiled/'stored.bin';bank.write_bytes(b'compiled bank');complete(compiled,identity)
            engine=root/'engine.elf';engine.write_bytes(b'engine')
            tools=root/'tools';tools.mkdir()
            for name in ('doc_render.py','doc_output.py','doc_preview.py','emu816.py','elf.py','music_pack.py'):
                (tools/name).write_text('fixture')
            game=SimpleNamespace(key='fixture',required_music={0:'TEST'})
            calls=[]
            def renderer(command,**kwargs):
                calls.append(command)
                self.assertEqual(command[2],str(bank.resolve()))
                output=Path(command[-1])
                with wave.open(str(output),'wb') as stream:
                    stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\x02\x01'*800)
                output.with_suffix('.json').write_text(json.dumps(dict(bank_sha256=digest(bank),
                    engine_sha256=digest(engine),gain=1,normalization=False,output=dict(sha256=digest(output)))))
            with patch.object(doc_preview,'TOOLS',tools),patch.object(doc_preview.subprocess,'run',side_effect=renderer):
                def build():return doc_preview.generate(compiled,engine,root/'preview',game,song='TEST')
                page=build();build();self.assertEqual(len(calls),1)
                catalog=json.loads(page.with_name('sources.json').read_text())
                versions=catalog['items'][0]['versions']
                self.assertEqual([v.get('status') for v in versions],['unavailable','unavailable',None])
                self.assertEqual(versions[2]['provenance']['wav_sha256'],digest(next((root/'preview/.audio-cache').rglob('doc.wav'))))
                next((root/'preview/.audio-cache').rglob('doc.wav')).unlink();build();self.assertEqual(len(calls),2)
                engine.write_bytes(b'updated engine');build();self.assertEqual(len(calls),3)
                bank.write_bytes(b'changed bank')
                with self.assertRaisesRegex(ValueError,'output missing or changed'):build()
                catalog=json.loads(page.with_name('sources.json').read_text())
                self.assertEqual(catalog['items'][0]['status'],'failed')
                self.assertEqual(catalog['items'][0]['versions'],[])


if __name__=='__main__':unittest.main()
