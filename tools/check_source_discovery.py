"""Folder-discovery regression checks without commercial data."""
import copy
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from check_dos_profiles import fixture
from game_profile import GameProfile, REQUIRED, load_profile
from source_discovery import catalogs, discover, MAP_FILES


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        source = self.root/'fixture'; config = fixture(source); base = load_profile(config)
        self.input = self.root/'owned files'; self.input.mkdir()
        self.payloads = {stem:(source/(stem+'.TEST')).read_bytes() for stem in REQUIRED}
        self.games = {}
        for key,ext in [('spear','SOD'),('spear-mission2','SD2'),('spear-mission3','SD3')]:
            doc=copy.deepcopy(base.document);doc['id']=key
            doc['files']={stem:stem+'.'+(ext if stem in MAP_FILES else 'SOD') for stem in REQUIRED}
            self.games[key]=GameProfile(config,doc,base.conversion)
        self.layouts=[dict(extension=ext,shared_extension='SOD',profile=key) for key,ext in
                      [('spear','SOD'),('spear','SD1'),('spear-mission2','SD2'),('spear-mission3','SD3')]]

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, folder, ext, value=107, shared=True):
        folder.mkdir(parents=True,exist_ok=True)
        for stem,content in self.payloads.items():
            if stem not in MAP_FILES and not shared:
                continue
            suffix=ext if stem in MAP_FILES else 'SOD'
            if stem=='GAMEMAPS':
                content=bytearray(content);content[46:48]=value.to_bytes(2,'little')
            (folder/(stem+'.'+suffix)).write_bytes(content)

    def edition(self, folder, ext, key):
        return dict(edition_id=key+'-fixture', profile=key, description='Synthetic fixture',
                    map_files={s:hashlib.sha256((folder/(s+'.'+ext)).read_bytes()).hexdigest() for s in MAP_FILES})

    def scan(self, editions):
        with patch('source_discovery.catalogs',return_value=(self.layouts,editions)), patch('game_profile.PROFILES',self.games):
            return discover(self.input)

    def test_real_catalog_is_readable(self):
        layouts,editions=catalogs()
        self.assertEqual(len(layouts),6)
        self.assertGreaterEqual(len(editions),5)

    def test_combined_package_finds_three_campaigns_no_renaming(self):
        editions=[]
        for ext,key,n in [('SOD','spear',107),('SD2','spear-mission2',108),('SD3','spear-mission3',109)]:
            self.install(self.input,ext,n)
            editions.append(self.edition(self.input,ext,key))
        shutil.copyfile(self.input/'MAPHEAD.SOD',self.input/'MAPHEAD.SD1')
        r=self.scan(editions)
        self.assertEqual({c['profile'] for c in r['candidates']},set(self.games))
        self.assertTrue(all(c['status']=='ready' and not c['native_build_verified'] for c in r['candidates']))

    def test_mission_installed_as_sod_is_identified_by_content(self):
        self.install(self.input,'SOD',108)
        r=self.scan([self.edition(self.input,'SOD','spear-mission2')])
        self.assertEqual(r['candidates'][0]['profile'],'spear-mission2')
        self.assertEqual(r['candidates'][0]['status'],'ready')
        self.assertEqual(r['candidates'][0]['files']['GAMEMAPS']['path'],'GAMEMAPS.SOD')

    def test_shared_files_prefer_identified_base_over_renamed_mission(self):
        base=self.input/'spear';self.install(base,'SOD',107)
        renamed=self.input/'mission2';self.install(renamed,'SOD',108)
        path=renamed/'VGAGRAPH.SOD';raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        mission=self.input/'mission3';self.install(mission,'SD3',109,False)
        editions=[self.edition(base,'SOD','spear'),self.edition(renamed,'SOD','spear-mission2'),
                  self.edition(mission,'SD3','spear-mission3')]
        rows=self.scan(editions)['candidates']
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row['status']=='ready' for row in rows))
        resolved=next(row for row in rows if row['profile']=='spear-mission3')
        self.assertEqual(resolved['files']['VGAGRAPH']['path'],'spear/VGAGRAPH.SOD')
        own=next(row for row in rows if row['profile']=='spear-mission2')
        self.assertEqual(own['files']['VGAGRAPH']['path'],'mission2/VGAGRAPH.SOD')

    def test_missing_base_file_is_not_taken_from_another_mission(self):
        base=self.input/'spear';self.install(base,'SOD',107)
        renamed=self.input/'mission2';self.install(renamed,'SOD',108)
        editions=[self.edition(base,'SOD','spear'),self.edition(renamed,'SOD','spear-mission2')]
        (base/'VGAGRAPH.SOD').unlink()
        rows=self.scan(editions)['candidates']
        row=next(r for r in rows if r['profile']=='spear')
        self.assertEqual(row['status'],'incomplete')
        self.assertEqual({d['file'] for d in row['diagnostics']},{'VGAGRAPH.SOD'})
        self.assertEqual(next(r for r in rows if r['profile']=='spear-mission2')['status'],'ready')

    def test_standalone_editions_do_not_fill_each_others_missing_files(self):
        one=self.input/'edition-one';two=self.input/'edition-two'
        self.install(one,'SOD',107);self.install(two,'SOD',108)
        self.layouts=[dict(extension='SOD',shared_extension='SOD',profile='spear')]
        editions=[self.edition(one,'SOD','spear'),self.edition(two,'SOD','spear')]
        (one/'VGAGRAPH.SOD').unlink()
        rows=self.scan(editions)['candidates']
        self.assertEqual(next(r for r in rows if r['folder']=='edition-one')['status'],'incomplete')
        self.assertEqual(next(r for r in rows if r['folder']=='edition-two')['status'],'ready')

    def test_shared_sibling_folders_and_identical_duplicates(self):
        mission=self.input/'mission';self.install(mission,'SD2',108,False)
        shared=self.input/'shared';shared.mkdir()
        for stem,raw in self.payloads.items():
            if stem not in MAP_FILES:
                (shared/(stem+'.SOD')).write_bytes(raw)
        duplicate=self.input/'copy';shutil.copytree(shared,duplicate)
        r=self.scan([self.edition(mission,'SD2','spear-mission2')])
        self.assertEqual(r['candidates'][0]['status'],'ready')
        (duplicate/'AUDIOT.SOD').write_bytes(b'different')
        r=self.scan([self.edition(mission,'SD2','spear-mission2')])
        error=next(d for d in r['candidates'][0]['diagnostics'] if d['file']=='AUDIOT.SOD')
        self.assertEqual(error['kind'],'ambiguous')
        self.assertEqual(len(error['paths']),2)

    def test_missing_files_are_named(self):
        self.install(self.input,'SD3',109)
        editions=[self.edition(self.input,'SD3','spear-mission3')]
        (self.input/'VSWAP.SD3').unlink();(self.input/'VGADICT.SOD').unlink()
        row=self.scan(editions)['candidates'][0]
        self.assertEqual(row['status'],'incomplete')
        self.assertEqual({d['file'] for d in row['diagnostics']},{'VSWAP.SD3','VGADICT.SOD'})

    def test_only_audio_and_graphics_report_missing_map_files(self):
        self.install(self.input,'SOD')
        for stem in MAP_FILES:
            (self.input/(stem+'.SOD')).unlink()
        rows=self.scan([])['candidates']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'incomplete')
        self.assertEqual({d['file'] for d in rows[0]['diagnostics']},{s+'.SOD' for s in MAP_FILES})

    def test_empty_template_folders_are_not_incomplete_games(self):
        for key in self.games:
            folder=self.input/key;folder.mkdir();(folder/'README.md').write_text('Put extracted game files here.')
        self.assertEqual(self.scan([])['candidates'],[])

    def test_archive_input_names_package_and_requests_user_extraction(self):
        package=self.input/'game.zip';package.write_bytes(b'not executed or extracted')
        result=self.scan([])
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['packages'],['game.zip'])
        self.assertIn('Extract or install',result['diagnostics'][0]['message'])
        self.assertIn('game.zip',result['diagnostics'][0]['message'])
        self.assertEqual(list(self.input.iterdir()),[package])

    def test_unknown_modified_map_is_not_mislabelled_official(self):
        self.install(self.input,'SOD',107)
        editions=[self.edition(self.input,'SOD','spear')]
        self.install(self.input,'SOD',108)
        row=self.scan(editions)['candidates'][0]
        self.assertEqual(row['status'],'unrecognized-variant')
        self.assertFalse(row['recognized_campaign'])

    def test_bad_shared_container_is_incompatible(self):
        self.install(self.input,'SOD',107)
        editions=[self.edition(self.input,'SOD','spear')]
        (self.input/'AUDIOHED.SOD').write_bytes(b'bad')
        row=self.scan(editions)['candidates'][0]
        self.assertEqual(row['status'],'incompatible')
        self.assertIn('audio directory',row['diagnostics'][0]['message'])

    def test_installer_only_folder_has_actionable_diagnostic(self):
        (self.input/'owned-game.7z').write_bytes(b'fixture')
        r=self.scan([])
        self.assertEqual(r['candidates'],[])
        self.assertEqual(r['packages'],['owned-game.7z'])
        self.assertIn('Extract or install',r['diagnostics'][0]['message'])


if __name__=='__main__':
    unittest.main()
