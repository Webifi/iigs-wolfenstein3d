"""Consumer preflight must not pass a frozen ELF off as a conversion engine."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock, patch

from audio_package import write_toml
from campaign_manifest import compile_manifest
import check_campaign_profiles as fixtures
from consumer_build import check_bundle, main, package_path, preflight, select_candidates, REQUIRED_BUNDLE_ROLES
from dos_data import DosData


class Consumer(unittest.TestCase):
    setUp = fixtures.SyntheticManifest.setUp
    tearDown = fixtures.SyntheticManifest.tearDown

    def manifest(self):
        return compile_manifest(DosData(self.folder, self.config))

    def bundle(self):
        root=self.root/'bundle';root.mkdir()
        manifest=self.manifest()
        cap=dict(format=1,engine_id='fixture',save_abi='test',
                 capabilities=manifest['required_capabilities'],limits=manifest['required_limits'])
        write_toml(root/'capabilities.toml',cap)
        for name in REQUIRED_BUNDLE_ROLES-{'capabilities'}:
            (root/(name+'.bin')).write_bytes(b'synthetic unimplemented binding')
        files={}
        for path in root.iterdir():
            files[path.stem]=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        doc=dict(format=1,engine_id='fixture',save_abi='test',asset_abi='fixture-v1',adapter='not-implemented',
                 verified_profiles=['custom-test'],files=files)
        write_toml(root/'engine-bundle.toml',doc)
        return root,doc,manifest

    def test_default_build_reports_missing_bundle_and_samples_no_images(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir()}
        r=preflight(self.folder,self.root/'out',selected_profile=self.config,release_root=self.root)
        self.assertEqual(r['status'],'preflight-failed')
        self.assertEqual(r['images'],[])
        self.assertEqual({d['kind'] for d in r['campaigns'][0]['diagnostics']},
                         {'missing-engine-bundle','missing-audio-source'})
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir()})

    def test_inspect_only_is_explicitly_source_validation(self):
        r=preflight(self.folder,self.root/'out',selected_profile=self.config,inspect_only=True)
        self.assertEqual(r['status'],'source-inspection-complete')
        self.assertFalse(r['native_build_verified'])
        self.assertEqual(r['images'],[])

    def test_complete_file_inventory_still_requires_implemented_adapter(self):
        root,_,manifest=self.bundle()
        with self.assertRaisesRegex(ValueError,'native asset bindings/converter are not implemented'):
            check_bundle(root/'engine-bundle.toml',manifest)

    def test_elf_alone_does_not_satisfy_bundle_contract(self):
        root,doc,manifest=self.bundle()
        doc['files']={'engine':doc['files']['engine']}
        write_toml(root/'engine-bundle.toml',doc)
        with self.assertRaisesRegex(ValueError,'an ELF alone cannot convert'):
            check_bundle(root/'engine-bundle.toml',manifest)

    def test_changed_bundle_bytes_and_unverified_profile_are_rejected(self):
        root,doc,manifest=self.bundle()
        (root/'engine.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'bundle file changed'):
            check_bundle(root/'engine-bundle.toml',manifest)
        doc['verified_profiles']=[];write_toml(root/'engine-bundle.toml',doc)
        with self.assertRaisesRegex(ValueError,'not verified for custom-test'):
            check_bundle(root/'engine-bundle.toml',manifest)

    def test_bundle_cannot_escape_package(self):
        for name in ('../secret','/absolute','C:/outside','a\\b'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'inside its folder'):
                package_path(self.root,name)

    def test_default_paths_separate_sources_from_dist(self):
        empty=dict(campaigns=[],discovery=dict(diagnostics=[]),status='source-inspection-complete')
        with patch('consumer_build.preflight',return_value=empty) as call, \
                patch('sys.argv',['build.py','--inspect-only']), contextlib.redirect_stdout(io.StringIO()):
            main()
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(call.call_args.args[:2],(root/'game-data',root/'dist/output'))

    def candidate(self, folder=None):
        source=DosData(folder or self.folder,self.config)
        files={s:dict(path=str(source.files[source.filename(s).upper()]),sha256=hashlib.sha256(source.read(s)).hexdigest())
               for s in source.profile.files}
        identity=hashlib.sha256(json.dumps({s:v['sha256'] for s,v in files.items()},sort_keys=True).encode()).hexdigest()[:16]
        return dict(candidate_id=identity,profile=source.profile.key,folder=(folder or self.folder).name,
                    status='ready',diagnostics=[],files=files)

    def test_selection_excludes_unrelated_incomplete_game_and_reports_missing_selection(self):
        game=DosData(self.folder,self.config).profile
        incomplete=dict(candidate_id='incomplete',profile='wolf3d',folder='wolf3d',status='incomplete',
                        diagnostics=[dict(kind='missing',message='Missing VSWAP.WL6')],files={})
        inventory=dict(candidates=[self.candidate(),incomplete],diagnostics=[],packages=[])
        with patch.dict('game_profile.PROFILES',{game.key:game}), patch('consumer_build.discover',return_value=inventory):
            all_games=preflight(self.folder,self.root/'all',inspect_only=True)
            self.assertEqual(all_games['status'],'preflight-failed')
            self.assertEqual(len(all_games['campaigns']),2)
            selected=preflight(self.folder,self.root/'selected',inspect_only=True,selected_games=[game.key])
            self.assertEqual(selected['status'],'source-inspection-complete')
            self.assertEqual([r['profile'] for r in selected['campaigns']],[game.key])
            self.assertEqual(selected['campaigns'][0]['campaign_manifest'],game.key+'/campaign.json')
            missing=preflight(self.folder,self.root/'missing',inspect_only=True,selected_games=['shareware'])
            self.assertEqual(missing['status'],'preflight-failed')
            self.assertEqual(missing['campaigns'],[])
            error=missing['discovery']['diagnostics'][0]
            self.assertEqual(error['kind'],'missing-selected-game')
            self.assertIn('VSWAP.WL1',error['message'])

    def test_selected_duplicates_dispatch_once_to_the_game_output(self):
        game=DosData(self.folder,self.config).profile
        candidate=self.candidate()
        inventory=dict(candidates=[candidate,dict(candidate,folder='identical-copy')],diagnostics=[],packages=[])
        bundle=self.root/'engine-bundle.toml';bundle.write_text('# synthetic dispatch fixture\n')
        audio=self.root/'audio';audio.mkdir();(audio/'intermediate.toml').write_text('# synthetic audio fixture\n')
        adapter=Mock()
        def build(*args):
            path=args[-1]/'synthetic.po';path.write_bytes(b'test dispatch only')
            return [str(path)]
        adapter.build.side_effect=build
        with patch.dict('game_profile.PROFILES',{game.key:game}), patch('consumer_build.discover',return_value=inventory), \
                patch('consumer_build.check_bundle',return_value=({}, {}, adapter)), \
                patch('audio_package.validate_effects',return_value=audio):
            result=preflight(self.folder,self.root/'out',bundle=bundle,audio_source=audio,selected_games=[game.key])
        self.assertEqual(result['status'],'build-complete')
        self.assertEqual(adapter.build.call_count,1)
        self.assertEqual(adapter.build.call_args.args[-1],(self.root/'out'/game.key).resolve())
        self.assertEqual(result['campaigns'][0]['duplicate_folders'],['identical-copy'])

    def test_distinct_editions_have_separate_output_folders(self):
        game=DosData(self.folder,self.config).profile
        second=self.root/'second';shutil.copytree(self.folder,second)
        path=second/'GAMEMAPS.TEST';raw=bytearray(path.read_bytes());raw[46:48]=(108).to_bytes(2,'little');path.write_bytes(raw)
        first,other=self.candidate(),self.candidate(second)
        inventory=dict(candidates=[first,other],diagnostics=[],packages=[])
        with patch.dict('game_profile.PROFILES',{game.key:game}), patch('consumer_build.discover',return_value=inventory):
            result=preflight(self.folder,self.root/'editions',inspect_only=True)
        self.assertEqual(result['status'],'source-inspection-complete')
        self.assertEqual({r['output_folder'] for r in result['campaigns']},
                         {game.key+'/'+c['candidate_id'] for c in (first,other)})
        self.assertNotEqual(result['campaigns'][0]['save_content_sha256'],result['campaigns'][1]['save_content_sha256'])

    def test_selected_game_is_detected_identity_not_folder_label(self):
        rows=[dict(candidate_id=k,profile=k,folder='spear',status='ready',diagnostics=[])
              for k in ('spear','spear-mission2','spear-mission3')]
        selected,errors=select_candidates(dict(candidates=rows),['spear-mission3'])
        self.assertEqual([r['profile'] for r in selected],['spear-mission3'])
        self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main()
