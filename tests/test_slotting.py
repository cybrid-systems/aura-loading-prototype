#!/usr/bin/env python3
"""Slotting (part B of #4947) tests: synthetic data only, stdlib only.

  python3 tests/test_slotting.py [-v]

Covers the cost model (incremental deltas == full evaluation), the hard
constraints, the EoH-S leave-one-out rule, the select:offline selector, and the
report's protocol invariants: a hindsight per-window oracle is an upper bound on
selection, a clairvoyant assignment is an upper bound on any assignment, and the
"portfolio beats the best single algorithm by 5% on the worst window" claim is
not a selection effect (< 5% headroom on the pinned window prefix).
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "slotting"))

import core            # noqa: E402
import eoh_s           # noqa: E402
import gen_slotting    # noqa: E402
import run_slotting as rs   # noqa: E402
import selector as sel      # noqa: E402


class CostModel(unittest.TestCase):
    def setUp(self):
        self.data = gen_slotting.build(7)
        self.orders = rs.window_orders(self.data, 12, 7)
        self.cost = core.Cost(self.data, self.orders)
        self.assign = core.assign_turnover(self.data["windows"][12]["weights"], self.data)

    def test_full_cost_matches_direct_formula(self):
        direct = 0.0
        for o in self.orders:
            xs = sorted({self.data["slots"][self.assign[i]]["x"] for i in set(o)})
            direct += 2.0 * xs[-1] + (xs[-1] - xs[0])
        self.assertAlmostEqual(self.cost.total(self.assign), direct / len(self.orders), places=9)

    def test_swap_delta_matches_full_recompute(self):
        rng = random.Random(5)
        c = core.Cost(self.data, self.orders)
        c.sync(self.assign)
        a = list(self.assign)
        for _ in range(20):
            x, y = rng.randrange(len(a)), rng.randrange(len(a))
            if a[x] == a[y] or not (core.fits(self.data["slots"][a[y]], self.data["skus"][x])
                                    and core.fits(self.data["slots"][a[x]], self.data["skus"][y])):
                continue
            d = c.delta_swap(a, x, y)
            b = list(a)
            b[x], b[y] = b[y], b[x]
            before = c.total(a)
            c.apply_swap(a, x, y)
            self.assertAlmostEqual(d, c.total(a) - before, places=9)
            self.assertAlmostEqual(c.total(a), core.Cost(self.data, self.orders).total(a), places=9)

    def test_shift_delta_matches_full_recompute(self):
        c = core.Cost(self.data, self.orders)
        c.sync(self.assign)
        a = list(self.assign)
        free = [s for s in range(len(self.data["slots"])) if s not in set(a)]
        for x in range(10):
            slot = free[x]
            if not core.fits(self.data["slots"][slot], self.data["skus"][x]):
                continue
            d = c.delta_shift(a, x, slot)
            b = list(a)
            b[x] = slot
            self.assertAlmostEqual(d, c.total(b) - c.total(a), places=9)
            c.apply_shift(a, x, slot)

    def test_constructors_are_feasible(self):
        w = self.data["windows"][12]["weights"]
        for a in (core.assign_turnover(w, self.data), core.assign_abc(w, self.data),
                  core.assign_affinity(w, self.data), core.assign_weighted(w, self.data, 1.0, 1.0, 0.5)):
            self.assertEqual(core.violations(a, self.data), 0)
            self.assertTrue(all(s >= 0 for s in a))
            self.assertEqual(len(set(a)), len(a))

    def test_local_search_never_worsens(self):
        c = core.Cost(self.data, self.orders)
        start = core.assign_turnover(self.data["windows"][12]["weights"], self.data)
        a, val = core.local_search(start, c, self.data, random.Random(3), 400)
        self.assertLessEqual(val, c.total(start) + 1e-9)
        self.assertEqual(core.violations(a, self.data), 0)


class EohS(unittest.TestCase):
    def test_keep_requires_positive_margin_and_caps_at_three(self):
        data = gen_slotting.build(7)
        train = []
        for w in range(0, 24, 4):
            weights = data["windows"][w]["weights"]
            train.append((data, weights, core.Cost(data, rs.sample_orders(weights, random.Random(w), 200))))
        kept, audit = eoh_s.evolve(train, seed=7, gens=2, pop=5)
        self.assertLessEqual(len(kept), 3)
        self.assertTrue(all(m > 0 for _, m in kept))
        self.assertTrue(any(r["status"] in ("KEEP", "DROP") for r in audit))
        for params, _ in kept:
            self.assertGreaterEqual(params["p"], eoh_s.BOUNDS["p"][0])


class Selector(unittest.TestCase):
    def test_fit_and_pick(self):
        s = sel.OfflineSelector(["a", "b"])
        f = sel.window_features([0.5, 0.5], [0.5, 0.5])
        rows = []
        for i in range(20):
            x = s.vector("a", 10.0 + i, 12.0, 10.0, f)
            rows.append((x, 0.1))
            x = s.vector("b", 10.0, 12.0, 10.0, f)
            rows.append((x, 0.0))
        s.fit(rows)
        pick, _ = s.pick([("a", s.vector("a", 10.0, 12.0, 10.0, f)),
                          ("b", s.vector("b", 10.0, 12.0, 10.0, f))])
        self.assertIn(pick, ("a", "b"))
        self.assertEqual(len(s.w), s.nfeat)

    def test_drift_distance(self):
        self.assertAlmostEqual(sel.tv([1.0, 0.0], [0.0, 1.0]), 1.0)
        self.assertAlmostEqual(sel.tv([0.5, 0.5], [0.5, 0.5]), 0.0)


class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rs.run(7, windows=26, budget=300, plan_n=200, clair_iters=600)

    def test_shapes_and_members(self):
        r = self.r
        self.assertEqual(len(r["series"]["portfolio"]), 26)
        self.assertEqual(len(r["series"]["oracle"]), 26)
        self.assertIn(r["sbs_roll"]["best"], r["members"])
        self.assertTrue(all(p in r["members"] for p in r["portfolio"]["picks"]))
        self.assertLessEqual(len(r["eoh"]["params"]), 3)

    def test_hindsight_bounds(self):
        r = self.r
        # oracle = per-window min over the portfolio's own assignments
        self.assertLessEqual(r["oracle"]["worst"], r["sbs_roll"]["worst"] + 1e-9)
        # clairvoyant optimises on the realised orders: never worse than the oracle
        self.assertLessEqual(r["clairvoyant"]["worst"], r["oracle"]["worst"] + 1e-9)
        self.assertGreaterEqual(r["gain"]["clairvoyant_headroom"], r["gain"]["selection_headroom"])

    def test_selection_is_not_the_5pct_effect(self):
        # pinned evidence for the report: at this budget the hindsight per-window
        # oracle over a 7-10 member portfolio adds well under 5% on the worst
        # window, so a *causal* selector cannot reach the 5% target.
        self.assertLess(self.r["gain"]["selection_headroom"], 0.05)

    def test_deterministic(self):
        again = rs.run(7, windows=12, budget=200, plan_n=150, clair_iters=200)
        third = rs.run(7, windows=12, budget=200, plan_n=150, clair_iters=200)
        self.assertEqual(again["gain"], third["gain"])
        self.assertEqual(again["series"], third["series"])


if __name__ == "__main__":
    unittest.main()
