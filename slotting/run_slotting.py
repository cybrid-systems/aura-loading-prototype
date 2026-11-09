#!/usr/bin/env python3
"""Synthetic warehouse slotting: rolling portfolio with a learned selector.

Part B of #4947.  No real data: every number comes from slotting/gen_slotting.py.

Protocol (the part the first round got wrong):

  * At the start of window w a policy only knows that window's *forecast*
    demand distribution (windows[w].weights).  It plans on --plan-samples orders
    sampled from that forecast; the assignment is deployed inside w.  The first
    round planned with the window's realised orders and deployed them one
    window late, so it both leaked information and threw a window away.
  * Cost of a window = mean order travel on the window's realised orders.

Policies (see docs/v02-downstream-report.md for the numbers):

  sbs_static    week-0 assignment of the best member, frozen for all windows
                (the comparator the first round used; kept for continuity)
  sbs_roll      the best single member, replanned each window with budget B
  portfolio_eq  members share B total (successive halving) + select:offline
  portfolio     each member gets the full B (no compute parity) + select:offline
  oracle        per-window argmin over the portfolio's assignments (hindsight:
                upper bound on what *selection* could add)
  clairvoyant   per-window optimum on the realised orders (hindsight: upper
                bound on what *any* assignment could add)

  python3 slotting/run_slotting.py --seed 7 --out slotting/out/s7.json
  python3 slotting/run_slotting.py --seeds 7,11,13,17,19 --summary
"""
import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core
import eoh_s
import gen_slotting
import selector as sel_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_SEEDS = (31, 37, 43)
BUDGET = 1500
PLAN_SAMPLES = 800
DRIFT_TV = 0.12
SWITCH_MARGIN = 0.01          # predicted-gap improvement required to switch
MEMBER_ID = {"turn": 0, "abc": 1, "aff": 2, "eoh1": 3, "eoh2": 4, "eoh3": 5,
             "ls_turn": 6, "ls_abc": 7, "ls_eoh1": 8, "ls_eoh2": 9, "ls_eoh3": 10}


# ---------------------------------------------------------------------------
# synthetic instance + demand sampling
# ---------------------------------------------------------------------------
def get_data(seed):
    """Synthetic instance for `seed`: the JSON if present, else the generator
    (deterministic, identical content)."""
    path = os.path.join(ROOT, "slotting", "data", "s%d.json" % seed)
    if os.path.exists(path):
        return core.load(path)
    return gen_slotting.build(seed)


def sample_orders(weights, rng, n):
    cum, acc = [], 0.0
    for x in weights:
        acc += x
        cum.append(acc)
    out = []
    for _ in range(n):
        o = []
        for _ in range(rng.randint(1, 5)):
            r = rng.random() * acc
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] < r:
                    lo = mid + 1
                else:
                    hi = mid
            o.append(lo)
        out.append(o)
    return out


def window_orders(data, w, seed):
    """The window's realised orders (deterministic per seed/window)."""
    ws = data["windows"][w]
    return sample_orders(ws["weights"], random.Random(seed * 1000 + w), ws["orders"])


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
def greedy_members(weights, data, eoh_params):
    out = dict(turn=core.assign_turnover(weights, data),
               abc=core.assign_abc(weights, data),
               aff=core.assign_affinity(weights, data))
    for i, p in enumerate(eoh_params):
        out["eoh%d" % (i + 1)] = eoh_s.assign(p, weights, data)
    return out


def plan_window(data, w, eoh_params, budget, plan_n, seed, alloc="split"):
    """Assignments for window w from the forecast only.

    alloc="split": all LS members share `budget` (successive halving).
    alloc="full":  every LS member gets the full `budget`.
    """
    weights = data["windows"][w]["weights"]
    rng = random.Random(seed * 100003 + w)
    plan = sample_orders(weights, rng, plan_n)
    pc = core.Cost(data, plan)
    base = greedy_members(weights, data, eoh_params)
    ls_from = [n for n in ("turn", "abc") if n in base]
    out = dict(base)
    plan_cost = {n: pc.total(a) for n, a in base.items()}

    def run(n, start, iters, tag):
        r = random.Random(seed * 7919 + w * 31 + MEMBER_ID[n] * 7 + tag)
        a, _ = core.local_search(start, pc, data, r, iters)
        return a

    if alloc == "full":
        for n in ls_from:
            a = run(n, base[n], budget, 1)
            out["ls_" + n] = a
            plan_cost["ls_" + n] = pc.total(a)
    else:
        stage1 = budget // 2
        share = max(1, stage1 // len(ls_from))
        first = {n: run(n, base[n], share, 1) for n in ls_from}
        order = sorted(ls_from, key=lambda n: pc.total(first[n]))
        survivors = order[:max(1, (len(order) + 1) // 2)]
        left = budget - share * len(ls_from)
        share2 = max(1, left // len(survivors))
        for n in survivors:
            a = run(n, first[n], share2, 2)
            out["ls_" + n] = a
            plan_cost["ls_" + n] = pc.total(a)

    plan_cvar = {n: pc.cvar(a) for n, a in out.items()}
    return out, plan_cost, plan_cvar


def build_matrix(data, seed, nw, budget, plan_n, eoh_params, alloc):
    rows = []
    for w in range(nw):
        assigns, pcost, pcvar = plan_window(data, w, eoh_params, budget, plan_n, seed, alloc)
        c = core.Cost(data, window_orders(data, w, seed))
        rows.append(dict(w=w, assigns=assigns, plan_cost=pcost, plan_cvar=pcvar,
                         real={n: c.total(a) for n, a in assigns.items()}, cost=c))
    return rows


# ---------------------------------------------------------------------------
# auxiliary checks
# ---------------------------------------------------------------------------
def paired_stats(a, b):
    """Paired per-window difference (b - a; positive = `a` cheaper) vs zero."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = statistics.fmean(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n > 1 else 0.0
    return dict(mean_diff=round(m, 4), sd=round(sd, 4), se=round(se, 4),
                t=round(m / se, 3) if se else None, wins=sum(1 for v in d if v < 0), n=n)

def ls_variance(assign, cost, data, rng, iters, lam):
    """Swap descent on mean travel + lam * aisle-load variance (B3 probe)."""
    best = list(assign)
    bc = cost.total(best) + lam * cost.aisle_var(best)
    slots, skus = data["slots"], data["skus"]
    for _ in range(iters):
        x, y = rng.randrange(len(best)), rng.randrange(len(best))
        if x == y or best[x] == best[y]:
            continue
        if not core.fits(slots[best[y]], skus[x]) or not core.fits(slots[best[x]], skus[y]):
            continue
        cand = list(best)
        cand[x], cand[y] = cand[y], cand[x]
        v = cost.total(cand) + lam * cost.aisle_var(cand)
        if v < bc:
            best, bc = cand, v
    return best


def b3_check(data, peak_w, base, plan_cost, real_cost, seed, iters=1200):
    """Causal distance / aisle-variance trade-off on the peak window.

    Candidates are optimised on a forecast plan sample (`plan_cost`) and scored
    on the window's realised orders (`real_cost`) -- no hindsight.
    """
    b = dict(distance=round(real_cost.total(base), 3), aisle_var=round(real_cost.aisle_var(base), 6))
    pts = []
    for lam in (0.0, 2.0, 5.0, 10.0, 20.0, 50.0):
        a = ls_variance(base, plan_cost, data, random.Random(seed * 613 + int(lam)), iters, lam)
        pts.append(dict(lam=lam, distance=round(real_cost.total(a), 3),
                        aisle_var=round(real_cost.aisle_var(a), 6)))
    ok = any(p["distance"] <= b["distance"] * 1.0001 and p["aisle_var"] <= 0.9 * b["aisle_var"] for p in pts)
    return dict(base=b, points=pts, ok=ok, week=peak_w + 1)


def noise_probe(data, seed, w, assign, rounds=12, n=260, big=4000):
    """Realised vs expected cost of one assignment at one window.

    The window cost in this scenario is a single draw of `n` orders, so the
    "worst window" carries sampling noise; this probe measures it directly."""
    wt = data["windows"][w]["weights"]
    realised = core.Cost(data, window_orders(data, w, seed)).total(assign)
    expected = core.Cost(data, sample_orders(wt, random.Random(seed * 77 + w), big)).total(assign)
    vals = [core.Cost(data, sample_orders(wt, random.Random(seed * 911 + w * 7 + k), n)).total(assign)
            for k in range(rounds)]
    sd = statistics.stdev(vals)
    return dict(week=w + 1, realised=round(realised, 3), expected=round(expected, 3),
                bias_frac=round(realised / expected - 1, 4),
                sd=round(sd, 3), sd_frac=round(sd / expected, 4), n=n, rounds=rounds)


# ---------------------------------------------------------------------------
# select:offline training
# ---------------------------------------------------------------------------
_SEL_CACHE = {}
_EOH_CACHE = {}


def common_names(rows):
    """Members present in every window (successive halving drops some of them)."""
    names = set(rows[0]["real"])
    for r in rows[1:]:
        names &= set(r["real"])
    return sorted(names)


def train_selector(train_seeds, nw, budget, plan_n, eoh_params, alloc="split"):
    key = (tuple(train_seeds), nw, budget, plan_n, alloc,
           tuple(sorted((p["p"], p["q"], p["r"]) for p in eoh_params)))
    if key in _SEL_CACHE:
        return _SEL_CACHE[key]
    rows, sel = [], None
    names = None
    for ts in train_seeds:
        data = get_data(ts)
        n = min(nw, len(data["windows"]))
        mat = build_matrix(data, ts, n, budget, plan_n, eoh_params, alloc)
        names = common_names(mat)
        if sel is None:
            sel = sel_mod.OfflineSelector(names)
        prev = None
        for w in range(n):
            f = sel_mod.window_features(data["windows"][w]["weights"], prev)
            prev = data["windows"][w]["weights"]
            r = mat[w]
            best_real = min(r["real"].values())
            best_pred = min(r["plan_cost"].values())
            for nm in names:
                x = sel.vector(nm, r["plan_cost"][nm], r["plan_cvar"][nm], best_pred, f)
                y = (r["real"][nm] - best_real) / best_real if best_real else 0.0
                rows.append((x, y))
    sel.fit(rows)
    _SEL_CACHE[key] = sel
    return sel


def select_series(rows, weights_series, sel, names):
    """Per-window member choice with a switch margin (hysteresis)."""
    picks, series, prev_choice, tv = [], [], None, []
    base = weights_series[0]
    for w, r in enumerate(rows):
        f = sel_mod.window_features(weights_series[w], weights_series[w - 1] if w else None)
        tv.append(0.5 * sum(abs(a - b) for a, b in zip(weights_series[w], base)))
        best_pred = min(r["plan_cost"].values())
        feats = [(n, sel.vector(n, r["plan_cost"][n], r["plan_cvar"][n], best_pred, f)) for n in names]
        preds = {n: sel.predict(x) for n, x in feats}
        choice = min(preds, key=preds.get)
        if prev_choice is not None and choice != prev_choice:
            if preds[prev_choice] - preds[choice] <= SWITCH_MARGIN:
                choice = prev_choice
        picks.append(choice)
        series.append(r["real"][choice])
        prev_choice = choice
    return picks, series, tv


# ---------------------------------------------------------------------------
# one seed
# ---------------------------------------------------------------------------
def run(seed, windows=52, budget=BUDGET, plan_n=PLAN_SAMPLES, clair_iters=4000, verbose=False):
    data = get_data(seed)
    nw = min(windows, len(data["windows"]))
    train_seeds = tuple(s for s in TRAIN_SEEDS if s != seed)

    # EoH-S on training windows only (a different synthetic seed); it is
    # expensive and identical for every evaluation seed, so cache it.
    ekey = (train_seeds, nw, plan_n)
    if ekey not in _EOH_CACHE:
        train = []
        for ts in train_seeds:
            d = get_data(ts)
            for w in range(0, min(nw, len(d["windows"])), 4):
                weights = d["windows"][w]["weights"]
                train.append((d, weights,
                              core.Cost(d, sample_orders(weights, random.Random(ts * 31 + w), plan_n))))
        _EOH_CACHE[ekey] = eoh_s.evolve(train, seed=0, gens=4, pop=8)
    kept, audit = _EOH_CACHE[ekey]
    eoh_params = [p for p, _ in kept]

    weights_series = [data["windows"][w]["weights"] for w in range(nw)]

    # full-budget matrix: sbs_roll / oracle / portfolio(no parity) / clairvoyant
    full = build_matrix(data, seed, nw, budget, plan_n, eoh_params, "full")
    names = sorted(full[0]["real"])

    sbs_roll = {n: max(r["real"][n] for r in full) for n in names}
    best = min(sbs_roll, key=sbs_roll.get)
    w0 = full[0]["assigns"]
    static = {n: max(full[w]["cost"].total(w0[n]) for w in range(nw)) for n in names}
    best_static = min(static, key=static.get)

    sel_full = train_selector(train_seeds, nw, budget, plan_n, eoh_params, "full")
    picks_full, port_full, _ = select_series(full, weights_series, sel_full, names)
    oracle = [min(r["real"].values()) for r in full]

    clair = []
    for r in full:
        start = r["assigns"][min(r["real"], key=r["real"].get)]
        a, _ = core.local_search(start, r["cost"], data, random.Random(seed * 17 + r["w"]), clair_iters)
        clair.append(r["cost"].total(a))

    # equal-total-budget matrix: portfolio_eq
    eq = build_matrix(data, seed, nw, budget, plan_n, eoh_params, "split")
    eq_names = common_names(eq)
    sel_eq = train_selector(train_seeds, nw, budget, plan_n, eoh_params, "split")
    picks_eq, port_eq, tv = select_series(eq, weights_series, sel_eq, eq_names)

    # binding window for sbs_roll: used by the noise probe and the B3 probe
    bind_w = max(range(nw), key=lambda w: full[w]["real"][best])
    probe = noise_probe(data, seed, bind_w, full[bind_w]["assigns"][best])
    peak = min(nw - 1, 39)
    peak_plan = core.Cost(data, sample_orders(data["windows"][peak]["weights"],
                                              random.Random(seed * 100003 + peak), plan_n))
    b3 = b3_check(data, peak, full[peak]["assigns"][best], peak_plan, full[peak]["cost"], seed)

    drift_weeks = [w + 1 for w in range(nw) if tv[w] > DRIFT_TV]
    injected = data.get("drift_week", 27) + 1
    switches = [w + 1 for w in range(1, nw) if picks_full[w] != picks_full[w - 1]]

    out = dict(
        seed=seed, windows=nw,
        sbs_roll=dict(best=best, worst=round(sbs_roll[best], 3),
                      per_member={k: round(v, 3) for k, v in sbs_roll.items()}),
        sbs_static=dict(best=best_static, worst=round(static[best_static], 3),
                        per_member={k: round(v, 3) for k, v in static.items()}),
        portfolio=dict(worst=round(max(port_full), 3), mean=round(statistics.fmean(port_full), 3),
                       picks=picks_full, switch_week=switches[0] if switches else None,
                       switches=switches),
        portfolio_eq=dict(worst=round(max(port_eq), 3), mean=round(statistics.fmean(port_eq), 3),
                          picks=picks_eq),
        oracle=dict(worst=round(max(oracle), 3), mean=round(statistics.fmean(oracle), 3)),
        clairvoyant=dict(worst=round(max(clair), 3)),
        drift=dict(threshold=DRIFT_TV, first_drift_week=drift_weeks[0] if drift_weeks else None,
                   injected_week=injected,
                   adapt_lag=(drift_weeks[0] - injected) if drift_weeks else None),
        gain=dict(
            portfolio_vs_roll=round(1 - max(port_full) / sbs_roll[best], 4),
            portfolio_eq_vs_roll=round(1 - max(port_eq) / sbs_roll[best], 4),
            vs_sbs_static=round(1 - max(port_full) / static[best_static], 4),
            selection_headroom=round(1 - max(oracle) / sbs_roll[best], 4),
            clairvoyant_headroom=round(1 - max(clair) / sbs_roll[best], 4),
        ),
        series=dict(portfolio=[round(x, 3) for x in port_full],
                    portfolio_eq=[round(x, 3) for x in port_eq],
                    sbs_roll=[round(full[w]["real"][best], 3) for w in range(nw)],
                    oracle=[round(x, 3) for x in oracle]),
        binding_window=bind_w + 1,
        noise_probe=probe,
        b3=b3,
        paired=paired_stats(port_full, [full[w]["real"][best] for w in range(nw)]),
        eoh=dict(params=eoh_params, audit=audit),
        protocol=dict(budget=budget, plan_samples=plan_n, drift_tv=DRIFT_TV,
                      switch_margin=SWITCH_MARGIN, train_seeds=list(train_seeds),
                      clair_iters=clair_iters),
        members=names,
    )
    return out


def summary(results):
    print("seed  SBS_static  SBS_roll  port_eq   port    oracle  clair   port/roll  port_eq/roll  sel_head  clair_head  switch  adapt  bind_wk  noise(sd%)")
    for r in results:
        print("%4d  %10.2f  %8.2f  %7.2f  %7.2f  %7.2f  %6.2f  %+9.2f%%  %+12.2f%%  %+8.2f%%  %+10.2f%%  %6s  %5s  %7d  %+9.2f"
              % (r["seed"], r["sbs_static"]["worst"], r["sbs_roll"]["worst"], r["portfolio_eq"]["worst"],
                 r["portfolio"]["worst"], r["oracle"]["worst"], r["clairvoyant"]["worst"],
                 100 * r["gain"]["portfolio_vs_roll"], 100 * r["gain"]["portfolio_eq_vs_roll"],
                 100 * r["gain"]["selection_headroom"], 100 * r["gain"]["clairvoyant_headroom"],
                 str(r["portfolio"]["switch_week"]), str(r["drift"]["adapt_lag"]),
                 r["binding_window"], 100 * r["noise_probe"]["sd_frac"]))
    if len(results) > 1:
        avg = lambda k: 100 * statistics.fmean(r["gain"][k] for r in results)
        print("mean: portfolio/roll %+.2f%%  portfolio_eq/roll %+.2f%%  selection_headroom %+.2f%%  clairvoyant %+.2f%%"
              % (avg("portfolio_vs_roll"), avg("portfolio_eq_vs_roll"),
                 avg("selection_headroom"), avg("clairvoyant_headroom")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--seeds", default="")
    ap.add_argument("--windows", type=int, default=52)
    ap.add_argument("--budget", type=int, default=BUDGET)
    ap.add_argument("--plan-samples", type=int, default=PLAN_SAMPLES)
    ap.add_argument("--clair-iters", type=int, default=4000)
    ap.add_argument("--out", default="slotting/out/run.json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()] or [a.seed]
    results = [run(s, a.windows, a.budget, a.plan_samples, a.clair_iters) for s in seeds]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(results[0] if len(results) == 1 else results, open(a.out, "w"), indent=1)
    if not a.quiet:
        summary(results)
        for r in results:
            print("seed %d: members %s | eoh kept %d | drift wk %s (injected %s) | switch wk %s"
                  % (r["seed"], ",".join(r["members"]), len(r["eoh"]["params"]),
                     r["drift"]["first_drift_week"], r["drift"]["injected_week"],
                     r["portfolio"]["switch_week"]))


if __name__ == "__main__":
    main()
