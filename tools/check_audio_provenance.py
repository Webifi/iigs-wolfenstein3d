"""Reject stale inputs, tools, outputs and interrupted builds before adoption."""
from pathlib import Path
import json
import tempfile
import unittest
from audio_provenance import snapshot,begin,complete,validate,failed,native_binding,recipe_paths
from audio_build_cache import inputs,stage,digest

class Provenance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.code=self.root/'project';(self.code/'tools/doccompiler').mkdir(parents=True)
        (self.code/'tools/doccompiler/compiler.py').write_text('compiler version one')
        self.recipe=self.root/'recipe.toml';self.recipe.write_text('level=1\n')
        self.sample=self.root/'sample.bin';self.sample.write_bytes(b'source sample')
        self.out=self.root/'output'
    def tearDown(self):self.temp.cleanup()
    def build(self):
        identity=snapshot('music-pack','fixture',[self.recipe,self.sample],self.code)
        begin(self.out,identity);(self.out/'pack.toml').write_text('new pack\n');(self.out/'song.bin').write_bytes(b'new bank')
        return complete(self.out,identity,self.code)
    def test_unchanged_outputs_validate_and_every_dependency_change_rejects(self):
        for target in (self.recipe,self.sample,self.code/'tools/doccompiler/compiler.py',self.out/'song.bin'):
            self.build();self.assertEqual(validate(self.out,self.code)['status'],'complete')
            target.write_bytes(target.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):validate(self.out,self.code)
    def test_failed_rebuild_does_not_leave_a_current_manifest(self):
        self.build();begin(self.out,dict(kind='music-pack'));failed(self.out,ValueError('missing source'))
        self.assertFalse((self.out/'pack.toml').exists())
        with self.assertRaisesRegex(ValueError,'incomplete or failed'):validate(self.out,self.code)
        self.assertTrue(list(self.out.parent.glob(self.out.name+'.previous-*/pack.toml')))
    def test_rebuild_cannot_adopt_leftover_reference_audio(self):
        self.build();old=self.out/'reference/full.wav';old.parent.mkdir();old.write_bytes(b'old reference')
        self.build()
        self.assertFalse(old.exists())
        self.assertNotIn('reference/full.wav',validate(self.out,self.code)['outputs'])
        self.assertTrue(list(self.out.parent.glob(self.out.name+'.previous-*/reference/full.wav')))
    def test_changed_input_during_compile_cannot_be_sealed(self):
        identity=snapshot('music','fixture',[self.recipe],self.code);begin(self.out,identity)
        (self.out/'song.bin').write_bytes(b'bank');self.recipe.write_text('level=2\n')
        with self.assertRaisesRegex(ValueError,'changed during'):complete(self.out,identity,self.code)
    def test_changed_input_during_cached_stage_cannot_be_cached(self):
        identity=inputs([self.sample])
        def mutate(folder):
            (folder/'bank').write_bytes(b'bank');self.sample.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'input changed'):stage(self.root/'cached','song',identity,mutate)
        self.assertFalse(list((self.root/'cached').rglob('.stage.json')))
    def test_native_preview_rejects_a_different_loaded_bank(self):
        identity=snapshot('music','fixture',[self.recipe],self.code)
        begin(self.out,identity)
        bank=self.out/'stored.bin';bank.write_bytes(b'compiled bank')
        complete(self.out,identity,self.code)
        native=self.root/'native';(native/'mix').mkdir(parents=True)
        files={'bank':str(bank)}
        for key in ('elf','disk','emulator'):
            path=self.root/key;path.write_bytes(key.encode());files[key]=str(path)
        pins={key:digest(path) for key,path in files.items()}
        (native/'identity.json').write_text(json.dumps(dict(profile=dict(files=files,sha256=pins))))
        wav=native/'mix/music.wav';wav.write_bytes(b'rendered audio')
        (native/'PASS.json').write_text(json.dumps(dict(repeatable=True,runs=dict(mix=dict(wav_sha256=digest(wav))))))
        loaded=native/'mix/loaded-cold.bin';loaded.write_bytes(bank.read_bytes())
        self.assertEqual(native_binding(native,self.out,self.code)['bank_sha256'],digest(bank))
        loaded.write_bytes(b'different packed bank')
        with self.assertRaisesRegex(ValueError,'loaded a different'):native_binding(native,self.out,self.code)
    def test_offline_original_is_resolved_from_licensed_data(self):
        self.recipe.write_text('[original]\nfile="licensed/SONG.imf"\n[source]\nfile="sample.bin"\n')
        self.assertEqual(set(recipe_paths(self.recipe,offline=True)),{self.recipe.resolve(),self.sample.resolve()})
        with self.assertRaisesRegex(ValueError,'Missing audio dependency'):recipe_paths(self.recipe)

if __name__=='__main__':unittest.main()
