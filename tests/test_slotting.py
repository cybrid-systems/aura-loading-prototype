#!/usr/bin/env python3
"""Slotting (part B of #4947) tests: synthetic data only, stdlib only.

  python3 tests/test_slotting.py [-v]

Covers the cost model (incremental deltas == full evaluation), the hard
constraints, the EoH-S leave-one-out rule, the select:offline selector, the
new complementary order families, and the report protocol: the two families
have different specialist members (>= 8% apart), the rolling portfolio beats
the best single member by >= 5% on the WORST family with a bootstrap CI that
excludes 0, hindsight bounds hold, and every deployed assignment is feasible.

The B3 test (Aura std/moead ask/tell) is skipped when no aura with std/moead
is available (AURA_BIN / AURA_PATH).
"""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "slotting"))

import b3             # noqa: E402
import core           # noqa: E402
import eoh_s          # noqa: E402
import gen_slotting   # noqa: E402
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
                  core.assign_affinity(w, self.data), core.assign_pairs(w, self.data),
                  core.assign_weighted(w, self.data, 1.0, 1.0, 0.5),
                  core.assign_biased(w, self.data, 1.2, 0.3, 0.4,
                                     [1.0, -1.0, 0.0, 0.0, 0.5, -0.5])):
            self.assertEqual(core.violations(a, self.data), 0)
            self.assertTrue(all(s >= 0 for s in a))
            self.assertEqual(len(set(a)), len(a))

    def test_local_search_never_worsens(self):
        c = core.Cost(self.data, self.orders)
        start = core.assign_turnover(self.data["windows"][12]["weights"], self.data)
        a, val = core.local_search(start, c, self.data, random.Random(3), 400)
        self.assertLessEqual(val, c.total(start) + 1e-9)
        self.assertEqual(core.violations(a, self.data), 0)


class OrderFamilies(unittest.TestCase):
    """The two synthetic families must really need different layouts."""

    @classmethod
    def setUpClass(cls):
        cls.data = gen_slotting.build(7)
        cls.cost = {}
        for w in range(len(cls.data["windows"])):
            win = cls.data["windows"][w]
            orders = rs.sample_orders(win["weights"], random.Random(7000 + w), 600,
                                      rs.window_spec(cls.data, w))
            cls.cost[w] = core.Cost(cls.data, orders)

    def _family_cost(self, fam, name):
        idx = [w for w in range(len(self.data["windows"]))
               if self.data["windows"][w]["family"] == fam]
        vals = []
        for w in idx:
            win = self.data["windows"][w]
            a = getattr(core, "assign_" + name)(win["weights"], self.data)
            vals.append(self.cost[w].total(a))
        return sum(vals) / len(vals)

    def test_two_families_with_different_order_structure(self):
        wins = self.data["windows"]
        fams = [w["family"] for w in wins]
        self.assertEqual(fams.count("bulk"), fams.count("basket"))
        bulk = [w for w in wins if w["family"] == "bulk"]
        basket = [w for w in wins if w["family"] == "basket"]
        self.assertTrue(all(w["sampler"] == "paired" for w in bulk))
        self.assertTrue(all(w["size"][1] <= 3 for w in bulk))
        self.assertTrue(all(w["sampler"] == "grouped" for w in basket))
        self.assertTrue(all(w["size"][0] >= 8 for w in basket))
        # the kit edges are cross-group, i.e. the structural conflict
        cross = [p for p in self.data["kits"]
                 if self.data["skus"][p[0]]["group"] != self.data["skus"][p[1]]["group"]]
        self.assertGreaterEqual(len(cross), 8)

    def test_specialists_are_complementary(self):
        bulk_prs = self._family_cost("bulk", "pairs")
        bulk_turn = self._family_cost("bulk", "turnover")
        bulk_aff = self._family_cost("bulk", "affinity")
        bask_aff = self._family_cost("basket", "affinity")
        bask_prs = self._family_cost("basket", "pairs")
        bask_turn = self._family_cost("basket", "turnover")
        # family 1: pair packing wins, group contiguity is a disaster
        self.assertLess(bulk_prs, bulk_turn)
        self.assertLess(bulk_prs, 0.92 * bulk_aff)
        # family 2: group contiguity wins, pair packing loses
        self.assertLess(bask_aff, 0.92 * bask_prs)
        self.assertLess(bask_aff, 0.90 * bask_turn)


class EohS(unittest.TestCase):
    def test_keep_requires_positive_margin_and_caps_at_three(self):
        data = gen_slotting.build(7)
        train = []
        for w in range(0, 24, 4):
            weights = data["windows"][w]["weights"]
            train.append((data, weights,
                          core.Cost(data, rs.sample_orders(weights, random.Random(w), 200,
                                                           rs.window_spec(data, w)))))
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

    def test_window_features_carry_order_structure(self):
        win = dict(size=(8, 10), sampler="grouped", cohesion=0.9)
        f = sel.window_features([0.5, 0.5], None, win)
        self.assertAlmostEqual(f["size"], 0.9)
        self.assertAlmostEqual(f["cohesion"], 0.9)
        self.assertEqual(f["structure"], 1.0)


class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rs.run(7, windows=52, budget=1500, plan_n=300, clair_iters=800,
                       moo_evals=48, b3_evals=48)

    def test_shapes_and_members(self):
        r = self.r
        self.assertEqual(len(r["series"]["portfolio"]), 52)
        self.assertEqual(len(r["series"]["oracle"]), 52)
        self.assertIn(r["sbs_roll"]["best"], r["members"])
        self.assertTrue(all(p in r["members"] for p in r["portfolio"]["picks"]))
        self.assertLessEqual(len(r["eoh"]["params"]), 3)
        self.assertTrue(all(w in r["members"] for w in ("prs", "aff", "turn", "abc")))

    def test_assignments_are_feasible(self):
        self.assertEqual(self.r["bad_violations"], 0)

    def test_hindsight_bounds(self):
        r = self.r
        for fam, d in r["families"].items():
            self.assertLessEqual(d["oracle_gain"]["median"] + 1e-9, 100.0)
            self.assertLessEqual(d["oracle_gain"]["median"] + 1e-9, 100.0)
        self.assertLessEqual(r["oracle"]["mean"], r["sbs_roll"]["mean"] + 1e-9)
        self.assertLessEqual(r["clairvoyant"]["worst"], r["oracle"]["worst"] + 1e-9)
        self.assertGreaterEqual(r["gain"]["clairvoyant_headroom"],
                                r["gain"]["selection_headroom"])

    def test_worst_family_gain_at_least_5pct_with_ci(self):
        """Pinned acceptance: paired median per family, bootstrap CI excludes 0."""
        r = self.r
        worst = r["worst_family"]
        self.assertGreaterEqual(worst["median"], 5.0)
        self.assertGreater(worst["ci"][0], 0.0)
        for fam, d in r["families"].items():
            self.assertGreater(d["gains"]["median"], 0.0, fam)
            self.assertGreater(d["gains"]["ci"][0], -2.0, fam)
        self.assertGreater(r["gain"]["mixed_gain"]["median"], 5.0)

    def test_each_family_has_its_own_specialist(self):
        r = self.r
        bulk = r["families"]["bulk"]
        basket = r["families"]["basket"]
        self.assertIn(bulk["best_member"],
                      ("prs", "turn", "ls_turn", "moead", "eoh1", "eoh2", "eoh3"))
        self.assertEqual(basket["best_member"], "aff")
        self.assertGreaterEqual(bulk["specialist_gap_vs_sbs"], 8.0)
        self.assertGreaterEqual(basket["specialist_gap_vs_sbs"], 8.0)

    def test_deterministic(self):
        again = rs.run(7, windows=8, budget=200, plan_n=150, clair_iters=100,
                       moo_evals=8, b3_evals=0)
        third = rs.run(7, windows=8, budget=200, plan_n=150, clair_iters=100,
                       moo_evals=8, b3_evals=0)
        self.assertEqual(again["series"], third["series"])
        self.assertEqual(again["sbs_roll"]["per_member"], third["sbs_roll"]["per_member"])


def _aura_ok():
    try:
        import moead_bridge
        moead_bridge.find_aura()
        return True
    except Exception:
        return False


@unittest.skipUnless(_aura_ok(), "aura with std/moead not available")
class AuraMoead(unittest.TestCase):
    def test_host_ask_tell_roundtrip(self):
        import moead_bridge
        h = moead_bridge.MoeadHost()
        try:
            self.assertEqual(h.make(2, 5, 4, 3, 7, [(0.0, 1.0)] * 3), 6)
            cs = h.ask(4)
            self.assertEqual(len(cs), 4)
            self.assertTrue(all(len(c["genome"]) == 3 for c in cs))
            h.tell([[0.2, 0.8], [0.5, 0.5], [0.1, 0.9], [0.7, 0.3]])
            self.assertEqual(len(h.ask(2)), 2)
        finally:
            h.close()

    def test_front_points_reproduce_their_genome(self):
        data = gen_slotting.build(7)
        win = data["windows"][0]
        plan = core.Cost(data, rs.sample_orders(win["weights"], random.Random(1), 150,
                                                 rs.window_spec(data, 0)))
        res = b3.run_front(data, win["weights"], plan, evals=16, seed=2)
        self.assertGreater(len(res["front"]), 0)
        for p in res["front"]:
            a = b3.config_assign(data, win["weights"], p["genome"])
            self.assertAlmostEqual(plan.total(a), p["objs"][0], places=6)
            self.assertAlmostEqual(plan.aisle_var(a), p["objs"][1], places=9)
        # non-dominated in plan space
        for p in res["front"]:
            for q in res["front"]:
                if q is p:
                    continue
                dominated = (q["objs"][0] <= p["objs"][0] and q["objs"][1] <= p["objs"][1]
                             and (q["objs"][0] < p["objs"][0] or q["objs"][1] < p["objs"][1]))
                self.assertFalse(dominated)


if __name__ == "__main__":
    unittest.main()
