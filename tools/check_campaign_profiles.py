"""Campaign, content-identity and resource checks using public synthetic data."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from campaign_manifest import compile_manifest, native_support, require_supported
from campaign_profile import Campaign
from check_dos_profiles import fixture
from dos_data import DosData
from game_profile import PROFILES, load_profile
from map_semantics import MapSemantics


def campaign(game, document):
    with patch('campaign_profile.read_toml', return_value=copy.deepcopy(document)):
        return Campaign(Path('synthetic.toml'), game)


class Defaults(unittest.TestCase):
    def test_every_official_campaign_and_repeatable_manifest(self):
        for key, count in [('shareware', 10), ('wolf3d', 60), ('spear', 21),
                           ('spear-mission2', 21), ('spear-mission3', 21)]:
            with self.subTest(profile=key):
                c = PROFILES[key].campaign
                self.assertEqual(len(c.floors), count)
                self.assertEqual(c.manifest(), c.manifest())
                self.assertFalse(c.manifest()['full_game_runtime_verified'])

    def test_wolf_secrets_and_distinct_final_triggers(self):
        c = PROFILES['wolf3d'].campaign
        for ep, (entry, target) in enumerate(zip([0, 0, 6, 2, 4, 2], [1, 1, 7, 3, 5, 3])):
            base = ep * 10
            self.assertEqual(c.routes[(base + entry, 'secret_exit')]['target_source_floor_index'], base + 9)
            self.assertEqual(c.routes[(base + 9, 'normal_exit')]['target_source_floor_index'], base + target)
            trigger = 'bj_exit' if ep in (0, 4) else 'boss_death'
            self.assertEqual(c.routes[(base + 8, trigger)]['destination_kind'], 'ending')
        self.assertIn(17, c.episodes['episode-2']['boss_source_floor_indices'])
        self.assertIn(59, c.episodes['episode-6']['boss_source_floor_indices'])
        self.assertEqual(c.floors[0]['par_seconds'], 90)
        self.assertEqual(c.floors[9]['bonus_points'], 15000)

    def test_spear_routes_do_not_become_wolf_episodes(self):
        for key in ('spear', 'spear-mission2', 'spear-mission3'):
            c = PROFILES[key].campaign
            self.assertEqual(len(c.episodes), 1)
            for entry, secret, target in ((3, 18, 4), (11, 19, 12)):
                self.assertEqual(c.routes[(entry, 'secret_exit')]['target_source_floor_index'], secret)
                self.assertEqual(c.routes[(secret, 'normal_exit')]['target_source_floor_index'], target)
            transition = c.routes[(17, 'spear_pickup')]
            self.assertEqual(transition['target_source_floor_index'], 20)
            self.assertEqual(transition['arrival'], 'preserve_player_pose')
            self.assertFalse(transition['show_tally'])
            self.assertEqual(c.floors[4]['tally_kind'], 'fixed_bonus')

    def test_strict_fields_ids_routes_and_reachability(self):
        g = PROFILES['shareware']
        cases = [
            ('unknown', lambda d: d.update(surprise=True)),
            ('format', lambda d: d.update(format=2)),
            ('duplicate floor_id', lambda d: d['floors'][1].update(floor_id=d['floors'][0]['floor_id'])),
            ('ambiguous', lambda d: d['routes'].append(copy.deepcopy(d['routes'][0]))),
            ('unreachable', lambda d: d.update(routes=[r for r in d['routes'] if r['trigger'] != 'secret_exit'])),
            ('no explicit route', lambda d: d.update(routes=[r for r in d['routes'] if r['destination_kind'] != 'ending'])),
            ('par_seconds', lambda d: d['floors'][0].update(par_seconds=0)),
            ('unknown episode', lambda d: d['floors'][0].update(episode_id='absent')),
            ('picture_role', lambda d: d['floors'][0].update(picture_role='absent')),
            ('outside', lambda d: d['floors'][0].update(picture_role='ending_first', picture_offset=4095)),
            ('source floor reference', lambda d: d['episodes'][0].update(start_source_floor_index=True)),
        ]
        for error, edit in cases:
            with self.subTest(error=error):
                doc = copy.deepcopy(g.campaign.document); edit(doc)
                with self.assertRaisesRegex(ValueError, error):
                    campaign(g, doc)

    def test_source_display_compiled_indices_are_separate(self):
        g = PROFILES['shareware']; doc = copy.deepcopy(g.campaign.document)
        doc['floors'][0]['display_floor_number'], doc['floors'][9]['display_floor_number'] = 10, 1
        c = campaign(g, doc); manifest = c.manifest()['campaign']
        self.assertEqual(manifest['floors'][0]['source_floor_index'], 9)
        self.assertEqual(manifest['episodes'][0]['start_compiled_floor_index'], 9)
        secret = next(r for r in manifest['routes'] if r['trigger'] == 'secret_exit')
        self.assertEqual((secret['compiled_floor_index'], secret['target_compiled_floor_index']), (9, 0))
        self.assertEqual(c.save_rules(), g.campaign.save_rules())

    def test_titles_and_table_order_do_not_change_save_rules(self):
        g = PROFILES['wolf3d']; doc = copy.deepcopy(g.campaign.document)
        doc['title'] = 'Another displayed name'; doc['episode_menu_order'].reverse()
        for key in ('episodes', 'floors', 'routes', 'endings'):
            doc[key].reverse()
        c = campaign(g, doc)
        self.assertEqual(c.save_rules(), g.campaign.save_rules())
        self.assertNotEqual(c.manifest()['metadata_sha256'], g.campaign.manifest()['metadata_sha256'])

    def test_unknown_behavior_is_a_native_requirement(self):
        g = PROFILES['shareware']; doc = copy.deepcopy(g.campaign.document)
        doc['routes'][0]['trigger'] = 'custom-switch'
        c = campaign(g, doc)
        self.assertIn('route.custom-switch', c.requirements())

    def test_explicit_cross_episode_route_needs_its_own_capability(self):
        g = PROFILES['wolf3d']; doc = copy.deepcopy(g.campaign.document)
        doc['routes'].append(dict(source_floor_index=0, trigger='custom-crossing', destination_kind='floor',
                                 target_source_floor_index=10, show_tally=False))
        self.assertIn('campaign.cross-episode-routes', campaign(g, doc).requirements())

    def test_missing_resource_sprite_name_is_an_error(self):
        m = MapSemantics(PROFILES['wolf3d'].resource('map_semantics'))
        with self.assertRaisesRegex(ValueError, 'unknown resource sprites'):
            m.source_sprites(dict(sprite_names=['NOT_A_REAL_SPRITE'], sprite_prefixes=[]))

    def test_resource_closure_includes_drops_morphs_projectiles(self):
        for key, placements, needed in [
            ('wolf3d', [178, 196, 215, 126], {'actor.hitler', 'projectile.hypo', 'projectile.rocket', 'drop.clip', 'drop.machinegun'}),
            ('spear', [161, 107, 143], {'projectile.heavy-rocket', 'projectile.spark', 'projectile.rocket', 'drop.key1'})]:
            m = MapSemantics(PROFILES[key].resource('map_semantics'))
            report = m.inspect_floor([[107] * 4096, placements + [0] * (4096-len(placements)), [0] * 4096])
            ids = {r['resource_id'] for r in report['resources']}
            self.assertLessEqual(needed | {'player.weapons', 'presentation.overlays'}, ids)
            self.assertFalse(report['native_allocation_verified'])

    def test_source_codes_above_255_are_mutant_placements(self):
        m = MapSemantics(PROFILES['wolf3d'].resource('map_semantics'))
        report = m.inspect_floor([[107] * 4096, [256, 257, 258, 259, 4095] + [0] * 4091, [0] * 4096])
        self.assertEqual([r['code'] for r in report['objects'] if r['behavior'] == 'mutant'], [256,257,258,259])
        self.assertEqual(report['unmapped_codes'], [dict(plane=1, code=4095, count=1, positions=[dict(x=4,y=0)])])
        self.assertTrue(report['all_words_preserved'])

    def test_preflagged_wall_keeps_flag_without_becoming_elevator_trigger(self):
        m = MapSemantics(PROFILES['spear'].resource('map_semantics'))
        r = m.inspect_floor([[85] + [107]*4095, [0]*4096, [0]*4096])
        wall = next(o for o in r['objects'] if o['code'] == 85)
        self.assertEqual(wall['parameters'], dict(wall_material=21, door_side=True))
        self.assertIn('map.door-side-wall', r['required_capabilities'])
        self.assertNotIn('route.normal_exit', r['required_capabilities'])

    def test_resource_cycles_terminate_and_unknown_dependencies_fail(self):
        doc = copy.deepcopy(MapSemantics(PROFILES['spear'].resource('map_semantics')).document)
        doc.pop('sprite_catalog')
        row = next(r for r in doc['resources'] if r['resource_id'] == 'actor.spectre')
        row['requires'] = ['actor.spectre']
        with patch('map_semantics.read_toml', return_value=doc):
            self.assertEqual(len(MapSemantics('test').closure(['actor.spectre'])), 1)
            row['requires'] = ['absent']
            with self.assertRaisesRegex(ValueError, 'unknown resource'):
                MapSemantics('test')

    def test_overlapping_code_ranges_are_rejected(self):
        doc = copy.deepcopy(MapSemantics(PROFILES['wolf3d'].resource('map_semantics')).document)
        doc['objects'].append(dict(name='overlap', plane=1, kind='actor', behavior='test', capabilities=[], codes=[256]))
        with patch('map_semantics.read_toml', return_value=doc), self.assertRaisesRegex(ValueError, 'ambiguous map'):
            MapSemantics('test')


class SyntheticManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.folder = self.root / 'data with spaces'; self.config = fixture(self.folder)
        path = self.folder / 'campaign.toml'
        path.write_text('''format = 1
profile_id = "custom-test"
campaign_id = "example"
title = "Example"
episode_menu_order = ["one"]
default_episode = "one"
source_references = []
[[episodes]]
episode_id = "one"
title = "One"
start_source_floor_index = 0
boss_source_floor_indices = []
ending_id = "done"
[[floors]]
floor_id = "start"
source_floor_index = 0
episode_id = "one"
display_floor_number = 42
title = "Start"
role = "normal"
tally_kind = "none"
music_name = "TEST"
[[routes]]
source_floor_index = 0
trigger = "normal_exit"
destination_kind = "ending"
ending_id = "done"
show_tally = false
[[endings]]
ending_id = "done"
kind = "custom"
''')
        semantics = self.folder/'semantics.toml'
        semantics.write_text('''format = 1
catalog_id = "synthetic"
source_references = []
[[objects]]
name = "areas"
plane = 0
kind = "geometry"
behavior = "area"
capabilities = ["map.areas"]
codes = [107, 108]
[[objects]]
name = "empty-objects"
plane = 1
kind = "empty"
behavior = "empty"
capabilities = []
codes = [0]
[[objects]]
name = "empty-extra-plane"
plane = 2
kind = "empty"
behavior = "empty"
capabilities = []
codes = [0]
''')
        self.config.write_text('campaign = "campaign.toml"\nmap_semantics = '+json.dumps(str(semantics))+'\n'+self.config.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self):
        return compile_manifest(DosData(self.folder, self.config))

    def test_full_decoder_manifest_and_cli_report_before_support_failure(self):
        r = self.manifest()
        self.assertFalse(r['native_support']['checked'])
        self.assertEqual(len(r['source_files']), 8)
        self.assertEqual(load_profile(self.config).floor_label(0), 'Floor 42')
        out = self.root/'result.json'
        command = [sys.executable, '-B', str(Path(__file__).with_name('wolf_image.py')), 'inspect-campaign',
                   '--data', str(self.folder), '--profile', str(self.config), '--out', str(out), '--require-supported']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Supply an engine-owned', result.stderr)
        self.assertEqual(json.loads(out.read_text()), r)

    def test_source_map_change_changes_save_identity_but_title_does_not(self):
        before = self.manifest()
        p = self.folder/'campaign.toml'; p.write_text(p.read_text().replace('title = "Start"', 'title = "Renamed"'))
        after = self.manifest()
        self.assertEqual(before['save_content_sha256'], after['save_content_sha256'])
        self.assertNotEqual(before['metadata_sha256'], after['metadata_sha256'])
        p = self.folder/'GAMEMAPS.TEST'; raw = bytearray(p.read_bytes()); struct.pack_into('<H', raw, 46, 108); p.write_bytes(raw)
        self.assertNotEqual(before['save_content_sha256'], self.manifest()['save_content_sha256'])

    def test_capability_pass_never_claims_native_runtime_or_allocation(self):
        r = self.manifest()
        doc = dict(format=1, engine_id='test-fixture', save_abi='v1', capabilities=r['required_capabilities'], limits=r['required_limits'])
        with patch('campaign_manifest.read_toml', return_value=doc):
            r['native_support'] = native_support(r, 'fixture')
        require_supported(r)
        self.assertFalse(r['native_support']['runtime_verified'])
        self.assertFalse(r['native_support']['allocation_verified'])
        doc['limits'] = dict(doc['limits'], floors=0, source_info_max=255)
        doc['capabilities'] = []
        with patch('campaign_manifest.read_toml', return_value=doc):
            r['native_support'] = native_support(r, 'fixture')
        with self.assertRaisesRegex(ValueError, 'floors needs 1, supports 0'):
            require_supported(r)

    def test_host_counts_are_not_ep03_limits(self):
        doc = self.config.read_text().replace('count = 1', 'count = 61', 1).replace('floor_songs = ["TEST"]', 'floor_songs = '+json.dumps(['TEST']*61))
        self.config.write_text(doc.replace('engine = "wolf3d"', 'engine = "custom-rules"'))
        g = load_profile(self.config)
        self.assertEqual((g.floors, g.document['engine']), (61, 'custom-rules'))
        r = dict(required_capabilities=['rules.custom-rules'], required_limits=dict(floors=61, episodes=1, map_width=64,map_height=64,source_info_max=259), floor_resources=[])
        doc = dict(format=1, engine_id='fixture', save_abi='v1', capabilities=[], limits=dict(r['required_limits'], floors=60,source_info_max=255))
        with patch('campaign_manifest.read_toml', return_value=doc):
            report = native_support(r, 'fixture')
        self.assertEqual([x['name'] for x in report['unmet_limits']], ['floors','source_info_max'])
        self.assertEqual(report['missing_capabilities'], ['rules.custom-rules'])


if __name__ == '__main__':
    unittest.main()
