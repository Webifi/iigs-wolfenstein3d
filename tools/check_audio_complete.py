"""Exercise producer orchestration with tiny recordings and stand-in renderers.

Hardware acceptance is separate; these checks cover rebuild decisions
and the separation between the developer AdLib baseline and DOC inputs.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import audio_complete
from audio_build_cache import digest
from audio_package import write_toml
from audio_provenance import begin, complete, snapshot


def wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x17\x02'*800)


class CompleteTests(unittest.TestCase):
    def test_unavailable_references_do_not_substitute_old_recordings(self):
        from audio_compare import export
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wav(root/'doc.wav')
            versions=[dict(label=name,kind='Developer reference',status='unavailable',
                           reason='Generate with the full synthesis workflow.')
                      for name in ('Original AdLib','Roland reference')]
            versions.append(dict(label='Generated DOC',kind='Compiled-bank playback',source=root/'doc.wav'))
            page=export(root/'preview','Rebuilt audio',[dict(label='SONG',note='DOC from retained Roland samples.',versions=versions)])
            catalog=json.loads(page.with_name('sources.json').read_text())
            actual=catalog['items'][0]['versions']
            self.assertTrue(all(v['status']=='unavailable' and 'file' not in v for v in actual[:2]))
            self.assertEqual(len(list((page.parent/'audio').glob('*.wav'))),1)

    def test_comparison_uses_shared_python_renderer_without_machine_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            compiled, recipes, media = [root/n for n in ('compiled', 'recipes', 'media')]
            work = compiled/'details/SONG'
            work.mkdir(parents=True)
            media.mkdir()
            for name in ('stored.bin', 'unit.bin', 'waves.bin', 'notes.json', 'stereo.txt'):
                (work/name).write_text(name)
            (compiled/'song-00.bin').write_bytes((work/'stored.bin').read_bytes())
            (work/'info.json').write_text(json.dumps(dict(seconds=.1, selected_instruments=[dict(channel=1,name='Piano')])))
            reference = work/'reference/full.wav'
            wav(reference)
            reference.with_suffix('.json').write_text(json.dumps(dict(wav_sha256=digest(reference))))
            solo=work/'reference/channel-01.wav'
            wav(solo)
            solo.with_suffix('.json').write_text(json.dumps(dict(wav_sha256=digest(solo))))
            engine = root/'engine/build/wolf.elf'
            engine.parent.mkdir(parents=True)
            engine.write_text('engine')
            (media/'wolf-hd.po').write_text('image')
            (media/'native-build.json').write_text(json.dumps(dict(work_directory=str(engine.parent.parent))))
            source = root/'original.imf'
            source.write_bytes(b'original AdLib source')
            write_toml(recipes/'songs/SONG.toml', dict(name='SONG', original=dict(file=str(source), sha256=digest(source))))
            (root/'dosbox').write_text('dosbox')
            settings = dict(adlib=dict(executable=str(root/'dosbox')))
            game = SimpleNamespace(key='fixture', required_music={0:'SONG'})
            calls = dict(sb=0, doc=0)
            identity = snapshot('music-pack', 'fixture', [recipes, source])
            complete(compiled, identity)
            def baseline(source, executable, folder, expected):
                calls['sb'] += 1
                wav(folder/'soundblaster.wav')
                (folder/'soundblaster.json').write_text(json.dumps(dict(wav_sha256=digest(folder/'soundblaster.wav'))))
            def renderer(command, **kwargs):
                calls['doc'] += 1
                self.assertEqual(Path(command[1]).name,'doc_render.py')
                self.assertEqual(command[2],str((compiled/'song-00.bin').resolve()))
                self.assertEqual(command[command.index('--parts')+1],str(work.resolve()))
                self.assertNotIn('soundblaster', json.dumps(command))
                output=Path(command[command.index('--out')+1])
                for filename in ('doc','ch01'):
                    target=output.with_name(filename+'.wav');wav(target)
                    report=dict(bank_sha256=digest(compiled/'song-00.bin'),engine_sha256=digest(engine),
                                gain=1,normalization=False,channels=[1],output=dict(sha256=digest(target)))
                    if filename!='doc':report['part']=1
                    target.with_suffix('.json').write_text(json.dumps(report))
            with patch.object(audio_complete, 'profile', return_value=game), \
                 patch('sb_reference.render', side_effect=baseline), \
                 patch('doc_preview.media_binding', return_value=dict(directory=str(media),verified=True)), \
                 patch.object(audio_complete.subprocess, 'run', side_effect=renderer):
                def build():
                    return audio_complete.compare_music(compiled, recipes, media, settings, 'fixture', root/'comparisons')
                page = build()
                build()
                self.assertEqual(calls, dict(sb=1, doc=1))
                catalog = json.loads((page.parent/'sources.json').read_text())
                self.assertEqual([v['label'] for v in catalog['items'][0]['versions']],
                                 ['Original AdLib', 'Roland reference', 'Generated DOC'])
                self.assertEqual([r['part'] for r in catalog['items']],['Full mix','Piano · CH01'])
                self.assertEqual(catalog['gain'], 1)
                self.assertFalse(catalog['normalization'])
                sb = next((root/'comparisons/.audio-cache/soundblaster-SONG').glob('*/soundblaster.wav'))
                sb.unlink()
                build()
                self.assertEqual(calls, dict(sb=2, doc=1))
                doc = next((root/'comparisons/.audio-cache/doc-SONG-parts').glob('*/ch01.wav'))
                doc.unlink()
                build()
                self.assertEqual(calls, dict(sb=2, doc=2))
                # Losing a displayed copy must not resynthesize its source.
                (page.parent/catalog['items'][0]['versions'][0]['file']).unlink()
                build()
                self.assertEqual(calls, dict(sb=2, doc=2))

    def test_settings_do_not_require_machine_emulator_roms_or_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for folder in ('compiler','effects'):(root/folder).mkdir()
            suffix='.exe' if audio_complete.os.name=='nt' else ''
            for name in ('as65816','ln65816'):(root/'compiler'/(name+suffix)).write_text('compiler')
            (root/'renderer.toml').write_text('format = 1\n')
            (root/'dosbox').write_text('renderer')
            settings=dict(format=1,synthesis=dict(settings='renderer.toml'),
                          adlib=dict(executable='dosbox',sha256=digest(root/'dosbox')),
                          build=dict(calypsi='compiler',effect_samples='effects'))
            path=root/'complete.toml';write_toml(path,settings)
            loaded=audio_complete.settings_file(path)
            self.assertNotIn('native',loaded)
            # Old machine paths must not become a hidden optional dependency.
            settings['native']=dict(emulator='missing-mame',cfg='missing-cfg',
                                    nvram='missing-nvram',rompaths=['missing-roms'])
            write_toml(path,settings)
            audio_complete.settings_file(path)

    def test_missing_roland_output_or_changed_mapping_recompiles_song(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recipes = root/'recipes'
            midi, imf, defaults = [root/n for n in ('music.mid','source.imf','defaults.toml')]
            midi.write_bytes(b'midi fixture')
            imf.write_bytes(b'imf fixture')
            defaults.write_text('program = 39\n')
            write_toml(recipes/'songs/SONG.toml', dict(name='SONG', source=dict(file=str(midi)),
                original=dict(file=str(imf)), defaults=dict(file=str(defaults))))
            settings_path = root/'renderer.toml'
            write_toml(settings_path, dict(renderer={}, soundfont={}))
            effects, data = root/'effects', root/'data'
            effects.mkdir(); data.mkdir()
            settings = dict(synthesis=dict(settings=str(settings_path)), build=dict(effect_samples=str(effects)))
            game = SimpleNamespace(key='fixture', document=dict(engine='fixture'), required_music={0:'SONG'})
            calls = []
            def synthesize(command, **kwargs):
                calls.append(command)
                folder = Path(command[command.index('--out')+1])
                identity = snapshot('music', None, [recipes, midi, imf, defaults, settings_path])
                begin(folder, identity)
                wav(folder/'reference/full.wav')
                (folder/'stored.bin').write_bytes(b'bank')
                intermediary = Path(command[command.index('--preserve-samples')+1])
                intermediary.mkdir()
                (intermediary/'selection.toml').write_text('program = 39\n')
                complete(folder, identity)
            with patch.object(audio_complete.subprocess, 'run', side_effect=synthesize), \
                 patch('audio_intermediate.finish_package'), patch('audio_intermediate.export_effects'), \
                 patch('music_pack.MusicPack'):
                def build():
                    return audio_complete.compile_music(root/'out', recipes, settings, game, data, 1)
                music, intermediary = build()
                build()
                self.assertEqual(len(calls), 1)
                self.assertFalse(list(intermediary.rglob('*.wav')))
                self.assertFalse(list(intermediary.rglob('*.bin')))
                raw = next((root/'out/.audio-cache/music-SONG').glob('*/details/reference/full.wav'))
                raw.unlink()
                build()
                self.assertEqual(len(calls), 2)
                defaults.write_text('program = 40\n')
                build()
                self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
