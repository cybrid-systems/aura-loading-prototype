"""B3: travel / aisle-variance front, searched by Aura std/moead ask/tell.

The first round swept a hand-written lambda (distance + lambda * aisle
variance) in Python.  That is replaced here by the real MOEA/D in
slotting/moead_host.aura: the genome is a slotting configuration

    genome = (p, q, r, b_0 .. b_5)

where priority(i) = -(w_i^p * m3_i^q * group_mass_i^r) (core.assign_biased) and
b_a shifts the slot order of aisle a by b_a metres.  The two objectives are the
mean order travel and the aisle-load variance on the window FORECAST sample --
no realised orders.  The front therefore contains real configs; the knee point
is added to the portfolio as a member, and the front is what the B3 acceptance
test reads.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core
from core import fits

DIM = 9
BOUNDS = [(0.3, 3.0), (-1.0, 2.0), (-1.0, 2.0)] + [(-8.0, 8.0)] * 6


def decode(genome):
    g = list(genome) + [0.0] * DIM
    return g[0], g[1], g[2], [g[3 + a] for a in range(6)]


def config_assign(data, weights, genome):
    p, q, r, beta = decode(genome)
    return core.assign_biased(weights, data, p, q, r, beta)


def subproblem_weight(h, sub):
    """Das-Dennis weight of MOEA/D subproblem `sub` (2 objectives)."""
    return (sub / float(h), 1.0 - sub / float(h))


def aisle_counts(cost, assign):
    cnt = [0.0] * cost.data["layout"]["aisles"]
    for ids in cost.orders:
        for i in ids:
            if assign[i] >= 0:
                cnt[cost.slots[assign[i]]["aisle"]] += 1
    return cnt


def pvariance(cnt):
    tot = sum(cnt) or 1.0
    m = tot / len(cnt)
    return sum((x - m) ** 2 for x in cnt) / len(cnt)


def ls_tradeoff(assign, cost, data, rng, iters, lam):
    """Swap descent on travel/d0 + lam * aisle-variance/v0.

    Both objectives are normalised by the starting point, so lam is the relative
    weight MOEA/D assigned to the aisle-balance objective.  The variance delta of
    a swap is O(1): a SKU moves its occurrences (one per order that contains it)
    from one aisle count to another.
    """
    a = list(assign)
    cost.sync(a)
    slots, skus = data["slots"], data["skus"]
    cnt = aisle_counts(cost, a)
    d0 = max(cost.total(a), 1e-9)
    v0 = max(pvariance(cnt), 1e-9)
    occ = [len(v) for v in cost.by_sku]
    best = d0 / d0 + lam * pvariance(cnt) / v0
    for _ in range(iters):
        x, y = rng.randrange(cost.n), rng.randrange(cost.n)
        if x == y or a[x] == a[y]:
            continue
        if not fits(slots[a[y]], skus[x]) or not fits(slots[a[x]], skus[y]):
            continue
        d = cost.delta_swap(a, x, y)
        ax, ay = slots[a[x]]["aisle"], slots[a[y]]["aisle"]
        if ax == ay:
            cand = best + d / d0
            dvar = 0.0
        else:
            before = pvariance(cnt)
            cnt[ax] -= occ[x]
            cnt[ay] += occ[x]
            cnt[ay] -= occ[y]
            cnt[ax] += occ[y]
            dvar = pvariance(cnt) - before
            cand = best + d / d0 + lam * dvar / v0
            cnt[ax] += occ[x]
            cnt[ay] -= occ[x]
            cnt[ay] += occ[y]
            cnt[ax] -= occ[y]
        if cand < best - 1e-12:
            best = cand
            cost.apply_swap(a, x, y)
            if ax != ay:
                cnt[ax] -= occ[x]
                cnt[ay] += occ[x]
                cnt[ay] -= occ[y]
                cnt[ax] += occ[y]
    return a


def polish_var(assign, cost, data, rng, iters, travel_cap):
    """Var-reducing swaps that never push travel above the incumbent's.

    The B3 claim is "no worse distance, 10% less aisle variance"; a weighted
    descent only grazes that corner, so the knee is refined with a hard travel
    cap (all on the forecast plan, never on realised orders).
    """
    a = list(assign)
    cost.sync(a)
    slots, skus = data["slots"], data["skus"]
    cnt = aisle_counts(cost, a)
    travel = cost.total(a)
    occ = [len(v) for v in cost.by_sku]
    for _ in range(iters):
        x, y = rng.randrange(cost.n), rng.randrange(cost.n)
        if x == y or a[x] == a[y]:
            continue
        ax, ay = slots[a[x]]["aisle"], slots[a[y]]["aisle"]
        if ax == ay:
            continue
        if not fits(slots[a[y]], skus[x]) or not fits(slots[a[x]], skus[y]):
            continue
        d = cost.delta_swap(a, x, y)
        if travel + d > travel_cap:
            continue
        before = pvariance(cnt)
        cnt[ax] -= occ[x]
        cnt[ay] += occ[x]
        cnt[ay] -= occ[y]
        cnt[ax] += occ[y]
        if pvariance(cnt) < before - 1e-15:
            cost.apply_swap(a, x, y)
            travel += d
        else:
            cnt[ax] += occ[x]
            cnt[ay] -= occ[x]
            cnt[ay] += occ[y]
            cnt[ax] -= occ[y]
    return a


def pareto(points):
    """Non-dominated points (min, min), duplicates collapsed."""
    keep = []
    seen = set()
    for p in points:
        key = (round(p["objs"][0], 9), round(p["objs"][1], 9))
        if key in seen:
            continue
        seen.add(key)
        dom = False
        for q in points:
            if q is p:
                continue
            if (q["objs"][0] <= p["objs"][0] and q["objs"][1] <= p["objs"][1]
                    and (q["objs"][0] < p["objs"][0] or q["objs"][1] < p["objs"][1])):
                dom = True
                break
        if not dom:
            keep.append(p)
    keep.sort(key=lambda p: p["objs"][0])
    return keep


def knee(front, base_objs, var_slack=0.9):
    """Cheapest point whose variance is at most var_slack * base variance."""
    cap = var_slack * base_objs[1]
    ok = [p for p in front if p["objs"][1] <= cap]
    if ok:
        return min(ok, key=lambda p: p["objs"][0]), True
    return min(front, key=lambda p: p["objs"][0]), False


def eval_genome(data, weights, plan_cost, genome, lam=0.0, ls_iters=0, seed=0):
    """Construct from the genome, then refine with the subproblem weight.

    lam is the relative weight of aisle balance (w1 / w0 of the MOEA/D
    subproblem); lam=0 is a pure travel descent.
    """
    a = config_assign(data, weights, genome)
    if ls_iters and lam > 0:
        a = ls_tradeoff(a, plan_cost, data, random.Random(seed), ls_iters, lam)
    return a


def run_front(data, weights, plan_cost, evals=160, batch=8, h=8, t=4, seed=0,
              binary=None, ls_iters=0, travel_cap=None, polish_iters=0):
    """Ask/tell MOEA/D over slotting genomes; returns the evaluated front."""
    import moead_bridge
    host = moead_bridge.MoeadHost(binary)
    try:
        host.make(2, h, t, DIM, seed, BOUNDS)
        pts = []
        rounds = max(1, evals // batch)
        for _ in range(rounds):
            cands = host.ask(batch)
            objs = []
            for c in cands:
                w0, w1 = subproblem_weight(h, c["sub"])
                lam = min(w1 / max(w0, 1e-3), 2000.0)
                a = eval_genome(data, weights, plan_cost, c["genome"], lam,
                                ls_iters, seed * 1000 + c["slot"] * 17 + c["gen"])
                if travel_cap is not None and polish_iters:
                    a = polish_var(a, plan_cost, data,
                                   random.Random(seed * 31 + c["slot"] * 7 + c["gen"]),
                                   polish_iters, travel_cap)
                objs.append([plan_cost.total(a), plan_cost.aisle_var(a)])
                pts.append(dict(genome=c["genome"], objs=objs[-1], slot=c["slot"],
                                sub=c["sub"], lam=lam))
            host.tell(objs)
    finally:
        host.close()
    return dict(points=pts, front=pareto(pts), nfe=len(pts))


def learn_config(data, window, plan_orders, evals=96, seed=0, binary=None,
                 ls_iters=300):
    """One MOEA/D front on a window forecast; returns the knee configuration.

    Called on TRAINING synthetic seeds only, so the configuration is a causal
    portfolio member for every held-out seed.
    """
    weights = window["weights"]
    pc = core.Cost(data, plan_orders)
    base = core.assign_turnover(weights, data)
    base_objs = [pc.total(base), pc.aisle_var(base)]
    try:
        res = run_front(data, weights, pc, evals=evals, seed=seed,
                        binary=binary, ls_iters=ls_iters)
    except Exception as e:                      # aura missing / crashed
        return dict(status="unavailable", error=str(e), genome=None)
    pick, met = knee(res["front"], base_objs)
    return dict(status="ok", genome=pick["genome"], objs=[round(x, 6) for x in pick["objs"]],
                meets_var_target=met, base_objs=[round(x, 6) for x in base_objs],
                front_size=len(res["front"]), nfe=res["nfe"])


def check_window(data, window, plan_cost, base_assign, real_cost, evals=160,
                 seed=0, binary=None, h=10, t=4, ls_iters=400, polish_iters=800):
    """B3 acceptance on one window: front point with no worse distance and
    at most 90% of the base aisle variance (evaluated on realised orders).

    The front is built on the forecast plan (causal); the realised cost is only
    used to *report* the two objectives of each point.
    """
    weights = window["weights"]
    try:
        res = run_front(data, weights, plan_cost, evals=evals, seed=seed,
                        binary=binary, h=h, t=t, ls_iters=ls_iters,
                        travel_cap=0.95 * plan_cost.total(base_assign),
                        polish_iters=polish_iters)
    except Exception as e:
        return dict(status="unavailable", error=str(e), ok=False)
    base = [real_cost.total(base_assign), real_cost.aisle_var(base_assign)]
    pts = []
    for p in res["front"]:
        a = eval_genome(data, weights, plan_cost, p["genome"], p.get("lam", 0.0),
                        ls_iters, seed * 1000 + p.get("slot", 0) * 17)
        if polish_iters:
            a = polish_var(a, plan_cost, data,
                           random.Random(seed * 31 + p.get("slot", 0) * 7),
                           polish_iters, 0.95 * plan_cost.total(base_assign))
        pts.append(dict(genome=[round(x, 4) for x in p["genome"]],
                        plan=[round(x, 6) for x in p["objs"]],
                        distance=round(real_cost.total(a), 3),
                        aisle_var=round(real_cost.aisle_var(a), 6)))
    hit = [p for p in pts
           if p["distance"] <= base[0] * 1.0001 and p["aisle_var"] <= 0.9 * base[1]]
    best = None
    if hit:
        best = min(hit, key=lambda p: p["distance"])
    return dict(status="ok", base=dict(distance=round(base[0], 3),
                                       aisle_var=round(base[1], 6)),
                front_size=len(res["front"]), nfe=res["nfe"],
                hit=best, ok=bool(hit),
                best_distance=min(p["distance"] for p in pts) if pts else None,
                min_var=min(p["aisle_var"] for p in pts) if pts else None,
                points=pts)
