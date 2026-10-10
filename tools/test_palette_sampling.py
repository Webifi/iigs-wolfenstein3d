"""Small source-map cases for complete, floor-local palette sampling."""
import unittest
from collections import Counter

from palette_sampling import wall_faces, wall_histogram, world_distribution, solid_index, no_regression, conversion_scores


class PaletteSampling(unittest.TestCase):
    def test_both_sides_of_a_hidden_material_contribute(self):
        faces = wall_faces([1, 1, 1, 1, 12, 1, 1, 1, 1], 106, width=3)
        self.assertGreater(faces[22], 0)
        self.assertGreater(faces[23], 0)
        self.assertNotIn(24, faces)  # an absent floor material gets no vote

    def test_exposure_uses_correct_orientation_without_row_wrap(self):
        faces = wall_faces([2, 1, 107, 1, 1, 1, 1, 1, 1], 106, width=3)
        self.assertEqual((faces[2], faces[3]), (1, 1))
        faces = wall_faces([107, 2, 107, 1, 2, 1, 1, 1, 1], 106, width=3)
        self.assertEqual(faces[3], 2)

    def test_door_types_and_switched_elevator_are_present(self):
        for tile, page in ((90, 99), (91, 98), (92, 105), (93, 104), (100, 103), (101, 102)):
            faces = wall_faces([tile], 106, width=1)
            self.assertEqual(faces[page], 2)
            self.assertEqual((faces[100], faces[101]), (1, 1))
        faces = wall_faces([21], 106, width=1)
        self.assertEqual(set(faces), {40, 41, 42, 43})

    def test_full_texels_supply_colors_missing_from_views(self):
        pages = [bytes([3]) * 4096, bytes([7]) * 4096]
        counts, _ = wall_histogram([1], pages, 10)
        self.assertEqual(counts, Counter({3: 4096, 7: 4096}))
        weights = world_distribution(Counter({3: 100}), counts, .2)
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertAlmostEqual(weights[7], .1)
        self.assertAlmostEqual(weights[3], .9)

    def test_solid_surface_does_not_take_bright_dither_component(self):
        cfg = dict(error_chroma_weight=2, error_hue_weight=2, large_error_scale=20,
                   noise_chroma_weight=2, noise_hue_weight=6)
        # Source ceiling 221: the old low-nibble selection chose (102,68,34).
        colors = [(0,0,0), (102,68,34), (51,34,17)]
        self.assertEqual(solid_index((64,48,24), colors, cfg), 2)

    def test_wall_gain_cannot_hide_weapon_or_other_light_regression(self):
        before = {'walls/0': 4, 'walls/3': 3, 'weapons/3': 2}
        self.assertFalse(no_regression(before, {'walls/0': 3, 'walls/3': 3.1, 'weapons/3': 2}))
        self.assertFalse(no_regression(before, {'walls/0': 3, 'walls/3': 3, 'weapons/3': 2.1}))
        self.assertFalse(no_regression(before, {'walls/0': 3}))
        self.assertTrue(no_regression(before, {'walls/0': 3, 'walls/3': 3, 'weapons/3': 2}))

    def test_background_target_is_unlit_and_solid(self):
        import viewcolor as vc
        from build_colors import fitting_targets
        source = [(0,0,0)] * 256
        source[3:7] = [(170,0,0),(0,170,0),(0,0,170),(170,170,170)]
        targets, weights, solid = fitting_targets({3:.5,4:.5}, Counter({5:1}),
                                                  Counter({6:1}), source, {3:.5})
        self.assertEqual(sum(solid), 1)
        self.assertAlmostEqual(sum(weights), 1)
        target = next(t for t,s in zip(targets,solid) if s)
        self.assertEqual(target[0], vc.oklab8(source[3]))
        self.assertEqual(target[2], 0)
        self.assertEqual(len(targets), 8)  # two lit colors, weapon, solid background

    def test_solid_search_cannot_claim_a_dither_average(self):
        import viewcolor as vc
        from build_colors import CFG
        palette = [(0,0,0),(15,15,15)]
        target = vc.mean_lin(palette,[1,1])
        metric = vc.Metric(CFG)
        solid = vc.Search([(target,1,0)],metric,[True])
        mixed = vc.Search([(target,1,0)],metric,[False])
        choices = solid.all_mixes(palette,range(2))
        singles = [(vc.lab12(c),0) for c in palette]
        self.assertGreater(solid.best(choices,singles)[0], 0)
        self.assertEqual(mixed.best(choices,singles)[0], 0)

    def test_lower_noise_cannot_hide_worse_color_matching(self):
        import viewcolor as vc
        from build_colors import CFG
        colors = [(0,0,0),(10,10,10),(15,15,15)]
        source = [(188,188,188)]
        dither = [[(0x02,0x20)]]  # black/white mean is close to source gray
        solid = [[(0x11,0x11)]]   # quieter, but visibly too dark
        domains = [('walls',Counter({0:1}),'wall',1)]
        a = conversion_scores(source,colors,dither,dither,[1],domains,vc.Metric(CFG))
        b = conversion_scores(source,colors,solid,solid,[1],domains,vc.Metric(CFG))
        self.assertLess(b['walls/0'],a['walls/0'])
        self.assertGreater(b['walls/0/color'],a['walls/0/color'])
        self.assertFalse(no_regression(a,b))


if __name__ == '__main__':
    unittest.main()
