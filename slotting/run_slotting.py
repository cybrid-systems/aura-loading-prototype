#!/usr/bin/env python3
"""Synthetic warehouse slotting: rolling portfolio with a learned selector.

Part B of #4947.  No real data: every number comes from slotting/gen_slotting.py.

Protocol (the part the first round got wrong, kept fixed here):

  * At the start of window w a policy only knows that window forecast: its
    demand weights AND its order structure (size range, sampler, cohesion).
    It plans on --plan-samples orders sampled from that forecast; the
    assignment is deployed inside w.  It never sees the realised orders.
  * Cost of a window = mean order travel on the window realised orders.
  * The scenario has two order families (bulk kit pallets / many-small
    baskets, see gen_slotting.py).  A policy is scored per family with a
    paired median over windows plus a bootstrap CI; the headline number is the
    WORST family, because a mixed stream is what a warehouse actually faces.

Policies:

  sbs_roll      the best single member for the whole year (same per-window
                budget, same protocol) -- the comparator
  portfolio_eq  members share the budget (successive halving) + select:offline
  portfolio     each member gets the full budget (no compute parity) + select
  oracle        per-window argmin over the portfolio own assignments
                (hindsight: upper bound on what *selection* could add)
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

import b3
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
BOOTSTRAP = 2000
MEMBER_ID = {"turn": 0, "abc": 1, "aff": 2, "prs": 3, "eoh1": 4, "eoh2": 5,
             "eoh3": 6, "ls_turn": 7, "ls_abc": 8, "ls_eoh1": 9, "ls_eoh2": 10,
             "ls_eoh3": 11}


# ---------------------------------------------------------------------------
# synthetic instance + demand sampling
# ---------------------------------------------------------------------------
def get_data(seed):
    """Synthetic instance for seed: the JSON if present, else the generator
    (deterministic, identical content)."""
    path = os.path.join(ROOT, "slotting", "data", "s%d.json" % seed)
    if os.path.exists(path):
        return core.load(path)
    return gen_slotting.build(seed)


def window_spec(data, w):
    """Order-structure spec of window w (part of the forecast)."""
    win = data["windows"][w]
    return dict(size=tuple(win.get("size", (1, 5))),
                sampler=win.get("sampler", "iid"),
                cohesion=win.get("cohesion", 0.0),
                groups=data.get("groups"), kits=data.get("kits"))


def sample_orders(weights, rng, n, spec=None):
    """Orders from a demand distribution + order-structure spec.

    Same code path for the forecast plan and for the realised window, so a
    policy can only differ from reality through its own choices.
    """
    return gen_slotting.sample_orders(weights, rng, n, spec)


def window_orders(data, w, seed):
    """The window realised orders (deterministic per seed/window)."""
    ws = data["windows"][w]
    return sample_orders(ws["weights"], random.Random(seed * 1000 + w),
                         ws["orders"], window_spec(data, w))


def family_of(data, w):
    return data["windows"][w].get("family", "all")


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
def greedy_members(weights, data, eoh_params):
    out = dict(turn=core.assign_turnover(weights, data),
               abc=core.assign_abc(weights, data),
               aff=core.assign_affinity(weights, data),
               prs=core.assign_pairs(weights, data))
    for i, p in enumerate(eoh_params):
        out["eoh%d" % (i + 1)] = eoh_s.assign(p, weights, data)
    return out


def plan_window(data, w, eoh_params, budget, plan_n, seed, alloc="split", moo=None):
    """Assignments for window w from the forecast only.

    alloc="split": all LS members share the budget (successive halving).
    alloc="full":  every LS member gets the full budget.
    """
    weights = data["windows"][w]["weights"]
    spec = window_spec(data, w)
    rng = random.Random(seed * 100003 + w)
    plan = sample_orders(weights, rng, plan_n, spec)
    pc = core.Cost(data, plan)
    base = greedy_members(weights, data, eoh_params)
    cfg = (moo or {}).get(family_of(data, w))
    if cfg and cfg.get("genome"):
        base["moead"] = b3.config_assign(data, weights, cfg["genome"])
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


def build_matrix(data, seed, nw, budget, plan_n, eoh_params, alloc, moo=None):
    rows = []
    for w in range(nw):
        assigns, pcost, pcvar = plan_window(data, w, eoh_params, budget, plan_n,
                                            seed, alloc, moo)
        c = core.Cost(data, window_orders(data, w, seed))
        bad = {n: core.violations(a, data) for n, a in assigns.items()}
        rows.append(dict(w=w, family=family_of(data, w), assigns=assigns,
                         plan_cost=pcost, plan_cvar=pcvar,
                         real={n: c.total(a) for n, a in assigns.items()},
                         violations=bad, cost=c))
    return rows


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
def paired_stats(a, b):
    """Paired per-window difference (b - a; positive = a cheaper) vs zero."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = statistics.fmean(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n > 1 else 0.0
    return dict(mean_diff=round(m, 4), sd=round(sd, 4), se=round(se, 4),
                t=round(m / se, 3) if se else None,
                wins=sum(1 for v in d if v < 0), n=n)


def median_gain_ci(port, sbs, rounds=BOOTSTRAP, seed=0):
    """Paired median relative gain of portfolio over sbs + percentile CI.

    gain_w = 1 - port_w / sbs_w.  The estimator is the median over windows
    (robust to the max-of-noise problem of the first round); the CI resamples
    windows with replacement.  Reported in percent.
    """
    g = [1.0 - p / s for p, s in zip(port, sbs) if s > 0]
    if not g:
        return dict(median=0.0, ci=[0.0, 0.0], n=0)
    med = statistics.median(g)
    rng = random.Random(seed)
    n = len(g)
    boots = []
    for _ in range(rounds):
        boots.append(statistics.median([g[rng.randrange(n)] for _ in range(n)]))
    boots.sort()
    lo = boots[int(0.025 * rounds)]
    hi = boots[int(0.975 * rounds) - 1]
    return dict(median=round(100 * med, 2), ci=[round(100 * lo, 2), round(100 * hi, 2)],
                mean=round(100 * statistics.fmean(g), 2), n=n,
                excl_zero=(lo > 0.0))


def noise_probe(data, seed, w, assign, rounds=12, n=260, big=4000):
    """Realised vs expected cost of one assignment at one window."""
    ws = data["windows"][w]
    spec = window_spec(data, w)
    realised = core.Cost(data, window_orders(data, w, seed)).total(assign)
    expected = core.Cost(data, sample_orders(ws["weights"],
                                             random.Random(seed * 77 + w), big, spec)).total(assign)
    vals = [core.Cost(data, sample_orders(ws["weights"],
                                          random.Random(seed * 911 + w * 7 + k), n, spec)).total(assign)
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
_MOO_CACHE = {}


def moo_configs(train_seeds, nw, plan_n, evals=96):
    """One MOEA/D knee configuration per order family, learned on TRAINING seeds.

    This is the B3 wiring: the front-end is Aura std/moead ask/tell (see
    slotting/b3.py), and the chosen configuration becomes a portfolio member
    ("moead") for every held-out seed.
    """
    key = (tuple(train_seeds), nw, plan_n, evals)
    if key in _MOO_CACHE:
        return _MOO_CACHE[key]
    by_seed, merged = {}, {}
    for ts in train_seeds:
        d = get_data(ts)
        fams = {}
        seen = set()
        for w in range(min(nw, len(d["windows"]))):
            fam = family_of(d, w)
            if fam in seen:
                continue
            seen.add(fam)
            win = d["windows"][w]
            plan = sample_orders(win["weights"], random.Random(ts * 7 + w),
                                 plan_n, window_spec(d, w))
            fams[fam] = b3.learn_config(d, win, plan, evals=evals, seed=ts + w)
        by_seed[ts] = fams
    for ts in train_seeds:
        for fam, v in by_seed[ts].items():
            if fam not in merged and v.get("status") == "ok":
                merged[fam] = v
    _MOO_CACHE[key] = dict(by_seed=by_seed, merged=merged)
    return _MOO_CACHE[key]


def common_names(rows):
    """Members present in every window (successive halving drops some)."""
    names = set(rows[0]["real"])
    for r in rows[1:]:
        names &= set(r["real"])
    return sorted(names)


def train_selector(train_seeds, nw, budget, plan_n, eoh_params, alloc="split",
                   moo=None):
    key = (tuple(train_seeds), nw, budget, plan_n, alloc,
           tuple(sorted((p["p"], p["q"], p["r"]) for p in eoh_params)),
           tuple(sorted(k for k, v in (moo or {}).items() if v.get("genome"))))
    if key in _SEL_CACHE:
        return _SEL_CACHE[key]
    rows, sel = [], None
    names = None
    for ts in train_seeds:
        data = get_data(ts)
        n = min(nw, len(data["windows"]))
        mat = build_matrix(data, ts, n, budget, plan_n, eoh_params, alloc, moo)
        names = common_names(mat)
        if sel is None:
            sel = sel_mod.OfflineSelector(names)
        prev = None
        for w in range(n):
            win = data["windows"][w]
            f = sel_mod.window_features(win["weights"], prev, win)
            prev = win["weights"]
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
        win = r.get("window")
        f = sel_mod.window_features(weights_series[w],
                                    weights_series[w - 1] if w else None, win)
        tv.append(0.5 * sum(abs(a - b) for a, b in zip(weights_series[w], base)))
        best_pred = min(r["plan_cost"].values())
        feats = [(n, sel.vector(n, r["plan_cost"][n], r["plan_cvar"][n], best_pred, f))
                 for n in names]
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
def family_breakdown(rows, port, picks, sbs_name, seed):
    """Per-family SBS vs portfolio with paired median gain + bootstrap CI.

    If the shared comparator is not in this matrix (successive halving drops
    members), the best available member is used and reported as `sbs`.
    """
    names = common_names(rows)
    if sbs_name not in names:
        sbs_name = min(names,
                       key=lambda n: statistics.fmean(r["real"][n] for r in rows))
    out = {}
    for fam in sorted({r["family"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["family"] == fam]
        sbs_series = [rows[i]["real"][sbs_name] for i in idx]
        port_series = [port[i] for i in idx]
        agg = {n: statistics.fmean(rows[i]["real"][n] for i in idx) for n in names}
        best_m = min(agg, key=agg.get)
        gains = median_gain_ci(port_series, sbs_series, seed=seed * 7 + len(fam))
        oracle_gains = median_gain_ci([min(rows[i]["real"].values()) for i in idx],
                                      sbs_series, seed=seed * 13 + len(fam))
        out[fam] = dict(
            n=len(idx), sbs_member=sbs_name,
            sbs=round(agg[sbs_name], 3),
            portfolio=round(statistics.fmean(port_series), 3),
            gains=gains,
            oracle_gain=oracle_gains,
            best_member=best_m, best_cost=round(agg[best_m], 3),
            second_cost=round(sorted(agg.values())[1], 3),
            specialist_gap_vs_sbs=round(100 * (1 - agg[best_m] / agg[sbs_name]), 2),
            picks={n: sum(1 for i in idx if picks[i] == n) for n in sorted(set(picks[i] for i in idx))},
        )
    return out


def run(seed, windows=52, budget=BUDGET, plan_n=PLAN_SAMPLES, clair_iters=4000,
        verbose=False, moo_evals=96, b3_evals=160):
    data = get_data(seed)
    nw = min(windows, len(data["windows"]))
    train_seeds = tuple(s for s in TRAIN_SEEDS if s != seed)

    # EoH-S on training windows only (different synthetic seeds); expensive and
    # identical for every evaluation seed, so cache it.
    ekey = (train_seeds, nw, plan_n)
    if ekey not in _EOH_CACHE:
        train = []
        for ts in train_seeds:
            d = get_data(ts)
            for w in range(0, min(nw, len(d["windows"])), 4):
                win = d["windows"][w]
                train.append((d, win["weights"],
                              core.Cost(d, sample_orders(win["weights"],
                                                       random.Random(ts * 31 + w),
                                                       plan_n, window_spec(d, w)))))
        _EOH_CACHE[ekey] = eoh_s.evolve(train, seed=0, gens=4, pop=8)
    kept, audit = _EOH_CACHE[ekey]
    eoh_params = [p for p, _ in kept]
    moo = moo_configs(train_seeds, nw, plan_n, evals=moo_evals)["merged"]

    weights_series = [data["windows"][w]["weights"] for w in range(nw)]

    full = build_matrix(data, seed, nw, budget, plan_n, eoh_params, "full", moo)
    for r in full:
        r["window"] = data["windows"][r["w"]]
    names = sorted(full[0]["real"])
    if verbose:
        print("  members:", ", ".join(names))

    mean_cost = {n: statistics.fmean(r["real"][n] for r in full) for n in names}
    worst_cost = {n: max(r["real"][n] for r in full) for n in names}
    best = min(mean_cost, key=mean_cost.get)
    w0 = full[0]["assigns"]
    static = {n: max(full[w]["cost"].total(w0[n]) for w in range(nw)) for n in names}
    best_static = min(static, key=static.get)

    sel_full = train_selector(train_seeds, nw, budget, plan_n, eoh_params, "full", moo)
    picks_full, port_full, tv = select_series(full, weights_series, sel_full, names)
    oracle = [min(r["real"].values()) for r in full]

    clair = []
    for r in full:
        start = r["assigns"][min(r["real"], key=r["real"].get)]
        a, _ = core.local_search(start, r["cost"], data,
                                 random.Random(seed * 17 + r["w"]), clair_iters)
        clair.append(r["cost"].total(a))

    eq = build_matrix(data, seed, nw, budget, plan_n, eoh_params, "split", moo)
    for r in eq:
        r["window"] = data["windows"][r["w"]]
    eq_names = common_names(eq)
    sel_eq = train_selector(train_seeds, nw, budget, plan_n, eoh_params, "split", moo)
    picks_eq, port_eq, tv_eq = select_series(eq, weights_series, sel_eq, eq_names)
    best_eq = best if best in eq_names else min(
        eq_names, key=lambda n: statistics.fmean(r["real"][n] for r in eq))

    fam_full = family_breakdown(full, port_full, picks_full, best, seed)
    fam_eq = family_breakdown(eq, port_eq, picks_eq, best, seed)
    worst_fam = min(fam_full, key=lambda f: fam_full[f]["gains"]["median"])

    bind_w = max(range(nw), key=lambda w: full[w]["real"][best])
    probe = noise_probe(data, seed, bind_w, full[bind_w]["assigns"][best])

    # B3: travel / aisle-variance front on the peak week forecast (causal),
    # reported on the peak week realised orders.
    peak = 39 if nw > 39 else nw - 1
    peak_plan = core.Cost(data, sample_orders(data["windows"][peak]["weights"],
                                              random.Random(seed * 100003 + peak),
                                              plan_n, window_spec(data, peak)))
    b3_res = b3.check_window(data, data["windows"][peak], peak_plan,
                             full[peak]["assigns"][best], full[peak]["cost"],
                             evals=b3_evals, seed=seed)

    # Drift is measured within a family: consecutive windows of different
    # families trivially differ (different order structure), so comparing them
    # would report a "drift" every other week.
    tv_fam, last_of = [0.0] * nw, {}
    for w in range(nw):
        fam = full[w]["family"]
        if fam in last_of:
            p = last_of[fam]
            tv_fam[w] = 0.5 * sum(abs(a - b) for a, b in
                                  zip(weights_series[w], weights_series[p]))
        last_of[fam] = w
    drift_weeks = [w + 1 for w in range(nw) if tv_fam[w] > DRIFT_TV]
    injected = data.get("drift_week", 27) + 1
    # How many windows after the injected season drift does each family's pick
    # change?  (The forecast exposes the change at the window start, so a
    # causal policy can react with zero lag; this measures whether it did.)
    drift_lag = {}
    for fam in sorted({r["family"] for r in full}):
        pre = [w for w in range(nw) if full[w]["family"] == fam and w + 1 < injected]
        post = [w for w in range(nw) if full[w]["family"] == fam and w + 1 >= injected]
        if not pre or not post:
            continue
        before = picks_full[pre[-1]]
        hit = next((w for w in post if picks_full[w] != before), None)
        drift_lag[fam] = (hit + 1 - injected) if hit is not None else None
    switches = [w + 1 for w in range(1, nw) if picks_full[w] != picks_full[w - 1]]
    fam_changes = [w + 1 for w in range(1, nw)
                   if full[w]["family"] != full[w - 1]["family"]]

    bad = sum(sum(r["violations"].values()) for r in full)

    out = dict(
        seed=seed, windows=nw, bad_violations=bad,
        sbs_roll=dict(best=best, mean=round(mean_cost[best], 3),
                      worst=round(worst_cost[best], 3),
                      per_member={k: round(v, 3) for k, v in mean_cost.items()}),
        sbs_static=dict(best=best_static, worst=round(static[best_static], 3),
                        per_member={k: round(v, 3) for k, v in static.items()}),
        portfolio=dict(mean=round(statistics.fmean(port_full), 3),
                       worst=round(max(port_full), 3), picks=picks_full,
                       switches=switches, switch_count=len(switches)),
        portfolio_eq=dict(best=best_eq, mean=round(statistics.fmean(port_eq), 3),
                          worst=round(max(port_eq), 3), picks=picks_eq,
                          switch_count=sum(1 for w in range(1, nw)
                                           if picks_eq[w] != picks_eq[w - 1])),
        oracle=dict(mean=round(statistics.fmean(oracle), 3),
                    worst=round(max(oracle), 3)),
        clairvoyant=dict(worst=round(max(clair), 3)),
        families=fam_full, families_eq=fam_eq,
        worst_family=dict(name=worst_fam,
                          median=fam_full[worst_fam]["gains"]["median"],
                          ci=fam_full[worst_fam]["gains"]["ci"]),
        drift=dict(threshold=DRIFT_TV,
                   tv_spikes=drift_weeks,
                   injected_week=injected,
                   within_family_tv=[round(x, 3) for x in tv_fam],
                   pick_change_lag=drift_lag,
                   family_changes=fam_changes),
        gain=dict(
            mixed_gain=median_gain_ci(port_full, [full[w]["real"][best] for w in range(nw)],
                                      seed=seed),
            mixed_gain_eq=median_gain_ci(port_eq, [eq[w]["real"][best_eq] for w in range(nw)],
                                         seed=seed + 1),
            vs_sbs_static=round(1 - statistics.fmean(port_full)
                                / statistics.fmean([full[w]["cost"].total(w0[best_static])
                                                    for w in range(nw)]), 4),
            selection_headroom=round(1 - statistics.fmean(oracle) / mean_cost[best], 4),
            clairvoyant_headroom=round(1 - statistics.fmean(clair) / mean_cost[best], 4),
        ),
        series=dict(portfolio=[round(x, 3) for x in port_full],
                    portfolio_eq=[round(x, 3) for x in port_eq],
                    sbs_roll=[round(full[w]["real"][best], 3) for w in range(nw)],
                    oracle=[round(x, 3) for x in oracle],
                    family=[full[w]["family"] for w in range(nw)]),
        binding_window=bind_w + 1,
        noise_probe=probe,
        b3=dict(week=peak + 1, **b3_res),
        moead=dict(merged={k: {kk: vv for kk, vv in v.items() if kk != "genome"}
                           for k, v in moo.items()},
                   genomes={k: [round(x, 3) for x in v["genome"]]
                            for k, v in moo.items() if v.get("genome")},
                   member="moead" if moo else None),
        paired=paired_stats(port_full, [full[w]["real"][best] for w in range(nw)]),
        eoh=dict(params=eoh_params, audit=audit),
        protocol=dict(budget=budget, plan_samples=plan_n, drift_tv=DRIFT_TV,
                      switch_margin=SWITCH_MARGIN, train_seeds=list(train_seeds),
                      clair_iters=clair_iters, bootstrap=BOOTSTRAP),
        members=names,
    )
    return out


def summary(results):
    print("%4s  %-8s  %8s  %8s  %8s  %7s  %7s  %s"
          % ("seed", "family", "SBS", "port", "port_eq", "gain", "CI", "oracle"))
    for r in results:
        for fam, d in sorted(r["families"].items()):
            g = d["gains"]
            print("%4d  %-8s  %8.2f  %8.2f  %8.2f  %+6.1f%%  [%+5.1f,%+5.1f]  %+6.1f%%  n=%d best=%s"
                  % (r["seed"], fam, d["sbs"], d["portfolio"],
                     r["families_eq"][fam]["portfolio"], g["median"], g["ci"][0],
                     g["ci"][1], d["oracle_gain"]["median"], d["n"], d["best_member"]))
        print("      worst family %s %+.1f%% CI [%+.1f,%+.1f]  | mixed %+.1f%% CI [%+.1f,%+.1f]  | sbs=%s"
              % (r["worst_family"]["name"], r["worst_family"]["median"],
                 r["worst_family"]["ci"][0], r["worst_family"]["ci"][1],
                 r["gain"]["mixed_gain"]["median"], r["gain"]["mixed_gain"]["ci"][0],
                 r["gain"]["mixed_gain"]["ci"][1], r["sbs_roll"]["best"]))
    if len(results) > 1:
        wf = [r["worst_family"]["median"] for r in results]
        print("mean worst-family %+.2f%%  (per seed %s)"
              % (statistics.fmean(wf), " ".join("%+.1f" % x for x in wf)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--seeds", default="")
    ap.add_argument("--windows", type=int, default=52)
    ap.add_argument("--budget", type=int, default=BUDGET)
    ap.add_argument("--plan-samples", type=int, default=PLAN_SAMPLES)
    ap.add_argument("--clair-iters", type=int, default=4000)
    ap.add_argument("--moo-evals", type=int, default=96,
                    help="MOEA/D evaluations per family config (B3)")
    ap.add_argument("--b3-evals", type=int, default=160,
                    help="MOEA/D evaluations for the B3 peak-week front (0 = skip)")
    ap.add_argument("--out", default="slotting/out/run.json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()] or [a.seed]
    results = [run(s, a.windows, a.budget, a.plan_samples, a.clair_iters,
                   moo_evals=a.moo_evals, b3_evals=a.b3_evals)
               for s in seeds]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(results[0] if len(results) == 1 else results, open(a.out, "w"), indent=1)
    if not a.quiet:
        summary(results)


if __name__ == "__main__":
    main()
