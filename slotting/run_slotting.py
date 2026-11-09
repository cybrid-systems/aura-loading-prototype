#!/usr/bin/env python3
"""Synthetic warehouse slotting: objectives, members, rolling-window online selection.

  python3 slotting/run_slotting.py --seed 7 --out slotting/out/s7.json [--windows 52]

Part B of #4947.  No real data: everything comes from slotting/gen_slotting.py.
Members (Python, stdlib only):
  abc        volume-priority placement
  turnover   pick-frequency-priority placement
  affinity   co-purchase cluster placement
  ls         local search (swap) from the turnover assignment
The online policy is a rolling window that scores each member on the last
window, detects a demand-structure drift (total-variation distance), and
switches within the next window.  MOEA/D-lite (Tchebycheff, 12 directions)
is run once on the peak window to expose the distance/aisle-variance front.
"""
import argparse, json, math, random, statistics


def fits(slot, sku):
    if sku["hazmat"] != (slot["aisle"] == 5):
        return False
    if sku["kg"] > 25 and slot["level"] == 2:
        return False
    if sku["m3"] > slot["cap_m3"] or sku["kg"] > slot["cap_kg"]:
        return False
    return True


def assign_priority(order, data):
    slots, skus = data["slots"], data["skus"]
    free = sorted(range(len(slots)), key=lambda s: (slots[s]["x"], slots[s]["level"]))
    used, out = set(), [-1] * len(skus)
    for i in order:
        for s in free:
            if s in used:
                continue
            if fits(slots[s], skus[i]):
                out[i] = s
                used.add(s)
                break
    return out


def assign_affinity(weights, data):
    slots, skus = data["slots"], data["skus"]
    groups = {}
    for i, k in enumerate(skus):
        groups.setdefault(k["group"], []).append(i)
    order = []
    for g, members in sorted(groups.items(), key=lambda kv: -sum(weights[i] for i in kv[1])):
        order.extend(sorted(members, key=lambda i: -weights[i]))
    return assign_priority(order, data)


def window_orders(data, w, seed):
    rng = random.Random(seed * 1000 + w)
    ws = data["windows"][w]
    n = ws["orders"]
    cum, acc = [], 0.0
    for x in ws["weights"]:
        acc += x
        cum.append(acc)
    orders = []
    for _ in range(n):
        k = rng.randint(1, 5)
        o = []
        for _ in range(k):
            r = rng.random() * acc
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] < r:
                    lo = mid + 1
                else:
                    hi = mid
            o.append(lo)
        orders.append(o)
    return orders


def travel(assign, orders, data):
    slots = data["slots"]
    tot = 0.0
    for o in orders:
        xs = sorted({slots[assign[i]]["x"] for i in o if assign[i] >= 0})
        if not xs:
            continue
        tot += 2.0 * xs[-1] + sum(xs[k] - xs[k - 1] for k in range(1, len(xs)))
    return tot / max(1, len(orders))


def aisle_load(assign, orders, data):
    slots = data["slots"]
    cnt = [0.0] * data["layout"]["aisles"]
    for o in orders:
        for i in o:
            if assign[i] >= 0:
                cnt[slots[assign[i]]["aisle"]] += 1
    return cnt


def objectives(assign, orders, data):
    dist = travel(assign, orders, data)
    load = aisle_load(assign, orders, data)
    tot = sum(load) or 1.0
    vari = statistics.pvariance([x / tot for x in load])
    aff = 0.0
    slots = data["slots"]
    n = 0
    for key, v in data["affinity"].items():
        i, j = (int(x) for x in key.split("-"))
        if assign[i] >= 0 and assign[j] >= 0:
            aff += v * abs(slots[assign[i]]["x"] - slots[assign[j]]["x"])
            n += 1
    return dict(distance=round(dist, 3), aisle_var=round(vari, 6),
                affinity=round(aff / max(1, n), 3), violations=violations(assign, data))


def violations(assign, data):
    slots, skus = data["slots"], data["skus"]
    used, bad = {}, 0
    for i, s in enumerate(assign):
        if s < 0:
            bad += 1
            continue
        used.setdefault(s, []).append(i)
        if not fits(slots[s], skus[i]):
            bad += 1
    for s, items in used.items():
        if sum(skus[i]["m3"] for i in items) > slots[s]["cap_m3"] + 1e-9:
            bad += 1
        if sum(skus[i]["kg"] for i in items) > slots[s]["cap_kg"] + 1e-9:
            bad += 1
    return bad


def ls_improve(assign, weights, data, orders, iters=90, rng=None):
    rng = rng or random.Random(1)
    slots = data["slots"]
    best = list(assign)
    best_cost = travel(best, orders, data) + 0.05 * objectives(best, orders, data)["affinity"]
    for _ in range(iters):
        a, b = rng.randrange(len(best)), rng.randrange(len(best))
        if a == b or best[a] == best[b]:
            continue
        cand = list(best)
        cand[a], cand[b] = cand[b], cand[a]
        if violations(cand, data) > 0:
            continue
        c = travel(cand, orders, data) + 0.05 * objectives(cand, orders, data)["affinity"]
        if c < best_cost:
            best, best_cost = cand, c
    return best


def member_assignments(weights, data, rng, orders=None):
    abc = assign_priority(sorted(range(len(data["skus"])), key=lambda i: -weights[i] * data["skus"][i]["m3"]), data)
    turn = assign_priority(sorted(range(len(data["skus"])), key=lambda i: -weights[i]), data)
    aff = assign_affinity(weights, data)
    ls = ls_improve(turn, weights, data, orders or window_orders(data, 0, 7), 140, rng)
    return {"abc": abc, "turnover": turn, "affinity": aff, "ls": ls}


def mock_orders_for(weights, data, rng, n=120):
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


def moead_lite(assign, data, orders, rng, dirs=12, iters=180):
    """Tchebycheff-weighted 3-objective local search over swaps (no std/moead here;
    the Aura-side MOEA/D is used for the packing problem)."""
    vecs = []
    for k in range(dirs):
        t = k / (dirs - 1)
        vecs.append((t + 0.01, 1.0 - t + 0.01, 0.3))
    start = objectives(assign, orders, data)
    ref = (start["distance"] * 1.1, start["aisle_var"] * 1.1 + 1e-9, start["affinity"] * 1.1 + 1e-9)
    pts = [dict(distance=start["distance"], aisle_var=start["aisle_var"], affinity=start["affinity"])]
    for wv in vecs:
        best, bc = list(assign), None
        for _ in range(iters):
            a, b = rng.randrange(len(best)), rng.randrange(len(best))
            if a == b or best[a] == best[b]:
                continue
            cand = list(best)
            cand[a], cand[b] = cand[b], cand[a]
            if violations(cand, data) > 0:
                continue
            o = objectives(cand, orders, data)
            f = max(wv[0] * (o["distance"] / ref[0]), wv[1] * (o["aisle_var"] / ref[1]),
                    wv[2] * (o["affinity"] / ref[2]))
            if bc is None or f < bc:
                best, bc = cand, f
        o = objectives(best, orders, data)
        pts.append(dict(distance=o["distance"], aisle_var=o["aisle_var"], affinity=o["affinity"]))
    front = []
    for p in pts:
        dom = False
        for q in pts:
            if q is p:
                continue
            if (q["distance"] <= p["distance"] and q["aisle_var"] <= p["aisle_var"]
                    and q["affinity"] <= p["affinity"]
                    and (q["distance"] < p["distance"] or q["aisle_var"] < p["aisle_var"]
                         or q["affinity"] < p["affinity"])):
                dom = True
                break
        if not dom:
            front.append(p)
    return front


def run(seed, windows=52):
    data = json.load(open("slotting/data/s%d.json" % seed))
    rng = random.Random(seed)
    nw = min(windows, len(data["windows"]))
    obs = [window_orders(data, w, seed) for w in range(nw)]
    base = data["windows"][0]["weights"]

    # SBS: a fixed assignment chosen at week 0, best worst-window distance
    fixed = member_assignments(base, data, rng)
    sbs = {}
    for name, a in fixed.items():
        vals = [travel(a, obs[w], data) for w in range(nw)]
        sbs[name] = dict(worst=round(max(vals), 3), mean=round(statistics.fmean(vals), 3))

    # online rolling window
    hist = {k: [] for k in fixed}
    deploy = fixed["ls"]
    deployed = []
    switch_week = None
    switches = []
    baseline = base
    for w in range(nw):
        weights = data["windows"][w]["weights"]
        tv = 0.5 * sum(abs(weights[i] - baseline[i]) for i in range(len(weights)))
        drift = tv > 0.12
        cur = member_assignments(weights, data, rng, obs[w])
        cur_scores = {k: travel(a, obs[w], data) for k, a in cur.items()}
        if w == 0:
            chosen = min(cur_scores, key=cur_scores.get)
            deployed.append(travel(deploy, obs[w], data))
        else:
            if drift:
                chosen = min(cur_scores, key=cur_scores.get)
                if switch_week is None:
                    switch_week = w + 1
                switches.append(w + 1)
            else:
                means = {k: statistics.fmean(hist[k][-3:]) if hist[k] else 1e18 for k in hist}
                chosen = min(means, key=means.get)
            deployed.append(travel(prev_deploy, obs[w], data))
        for k in hist:
            hist[k].append(cur_scores[k])
        prev_deploy = cur[chosen]
        deploy = prev_deploy
    worst_online = max(deployed)
    best_sbs = min(v["worst"] for v in sbs.values())
    best_name = min(sbs, key=lambda k: sbs[k]["worst"])

    # MOEA/D-lite on the peak window
    peak = 40 if nw > 40 else nw - 1
    front = moead_lite(fixed["ls"], data, obs[peak], random.Random(seed + 99))
    base_peak = objectives(fixed["ls"], obs[peak], data)
    ok_var = False
    for p in front:
        if p["distance"] <= base_peak["distance"] and p["aisle_var"] <= 0.9 * base_peak["aisle_var"]:
            ok_var = True
    out = dict(seed=seed, windows=nw, sbs=sbs, best_sbs=best_name, sbs_worst=round(best_sbs, 3),
               online_worst=round(worst_online, 3),
               worst_improvement=round(1 - worst_online / best_sbs, 4),
               switch_week=switch_week, switches=switches, drift_week=data["drift_week"],
               deployed=[round(x, 3) for x in deployed],
               peak_week=peak + 1, base_peak=base_peak,
               moead_front=front, moead_points=len(front), moead_aisle_var_ok=ok_var)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--windows", type=int, default=52)
    ap.add_argument("--out", default="slotting/out/run.json")
    a = ap.parse_args()
    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    r = run(a.seed, a.windows)
    json.dump(r, open(a.out, "w"), indent=1)
    print(json.dumps({k: r[k] for k in ("seed", "sbs_worst", "online_worst", "worst_improvement", "switch_week")}))


if __name__ == "__main__":
    main()
