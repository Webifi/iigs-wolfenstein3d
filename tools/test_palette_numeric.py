"""Bounded palette search agrees with full distance evaluation, including ties."""
import ctypes
import random
import struct
import unittest

import native_host as nh
from viewcolor import Metric, lab12


class PaletteArithmetic(unittest.TestCase):
    def test_bounded_costs_and_reused_columns(self):
        rng = random.Random(4816)
        for case in range(40):
            metric = Metric(dict(err_kc=1.5, err_kh=2.0, err_d0=(0.0, 15.0)[case%2], noise_kc=1.0, hue_k=1.0))
            colors = [lab12(tuple(rng.randrange(16) for _ in range(3))) for _ in range(60)]
            targets = [(c, rng.random(), (0.0, .2, .35)[i%3]) for i,c in enumerate(colors[:19])]
            flags = [i%7==0 for i in range(len(targets))]
            prepared = nh.targets(targets, flags)
            rows = [(c,rng.random()*80) for c in colors[19:]]
            solids = [(c,0.0) for c in colors[19:25]]
            cache = {}
            for ceiling in (.01, 1000.0, None):
                full = nh.best(prepared, rows, solids, metric)
                base = None if ceiling is None else (nh.D*len(targets))(*[ceiling]*len(targets))
                got = nh.best_reusing(prepared, rows, solids, metric, cache, base)
                expected = full if base is None else [min(v,ceiling) for v in full]
                self.assertEqual(bytes(got), struct.pack('='+str(len(expected))+'d', *expected))

    def test_pick_preserves_ties_and_full_score(self):
        rng = random.Random(65536)
        metric = Metric(dict(err_kc=1.2, err_kh=1.7, err_d0=0, noise_kc=1, hue_k=1))
        rows = [(lab12(tuple(rng.randrange(16) for _ in range(3))), rng.random()*30) for _ in range(300)]
        rows += rows[:5]
        mixes = nh.mixes(rows)
        for i in range(100):
            lab = rows[i][0] if i<20 else lab12(tuple(rng.randrange(16) for _ in range(3)))
            lam = (0.0,.2,.35)[i%3]
            expected = min(range(len(rows)), key=lambda j:metric.err(lab,rows[j][0])+lam*rows[j][1])
            self.assertEqual(nh.pick(mixes,len(rows),lab,lam,metric), expected)


if __name__ == '__main__':
    unittest.main()
