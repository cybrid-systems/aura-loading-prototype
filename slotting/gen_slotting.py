#!/usr/bin/env python3
"""Synthetic warehouse-slotting generator (no real data).   v0.2 P9 / part B

  python3 slotting/gen_slotting.py --seed 7 --out slotting/data/s7.json

Two structurally different order families, built so that no single slotting
heuristic is best on both (see docs/v02-downstream-report.md 4.4):

  bulk    long/heavy pallet picks: 1-3 items per order, drawn i.i.d. from a
          strongly skewed demand over a small hot set of heavy SKUs.  An order
          rarely contains two picks that belong together, so co-locating SKUs
          by affinity only wastes the prime (low-x) slots: demand ranking
          (turnover) is what matters.
  basket  many small picks: 6-8 light items per order.  A cohesion fraction of
          the baskets is picked inside one product group (the way a store
          replenishment basket looks), so keeping a group contiguous is worth
          2-4x; the remaining baskets are cross-group and then the same
          co-location is a liability.

A window forecast is its demand weights plus the order-structure spec (size
range, sampler, cohesion), i.e. what a planner knows before the week starts.
Realised orders are drawn from the same spec with a different RNG, so planning
on the forecast is honest and same-week deployment is possible.

The rest is made up as before: aisle/bay/level layout, SKU sizes, weights and
hazard flags, a co-purchase affinity matrix, a 52-week stream with a demand
rotation at week 27 and a peak at weeks 40-44.
"""
import argparse, json, os, random

FAMILIES = ("bulk", "basket")
BULK_SIZE = (1, 3)
BASKET_SIZE = (8, 10)
BULK_COHESION = (0.60, 0.45, 0.30, 0.15)     # paired-pick share, bulk windows
BASKET_COHESION = (0.92, 0.88, 0.82, 0.76)   # same-group share, basket windows
HOT_BULK = 8                                  # hot SKUs per bulk block
HOT_BASKET = 40                               # hot SKUs per basket block
BLOCK = 4                                     # weeks between demand rotations


def _slots(rng, aisles, bays, levels):
    out = []
    for a in range(aisles):
        for b in range(bays):
            for l in range(levels):
                out.append(dict(id=len(out), aisle=a, bay=b, level=l,
                                x=round(a * 10.0 + b * 0.55, 3),
                                cap_m3=round(rng.uniform(0.9, 1.4), 3),
                                cap_kg=round(rng.uniform(180, 320), 1)))
    return out


def _skus(rng):
    """140 SKUs: bulky/long, dense, light, and a hazmat tail."""
    out = []

    def add(fam, m3lo, m3hi, kglo, kghi, haz=False):
        vol = round(rng.uniform(m3lo, m3hi), 4)
        out.append(dict(id=len(out), family=fam, m3=vol,
                        kg=round(rng.uniform(kglo, kghi), 2), hazmat=haz,
                        group=0))

    for _ in range(40):
        add("home", 0.055, 0.100, 30, 90)       # bulky + heavy (no top level)
    for _ in range(50):
        add("food", 0.005, 0.022, 5, 40)        # dense small
    for _ in range(45):
        add("apparel", 0.006, 0.030, 1, 9)      # light small
    for _ in range(5):
        add("hazmat", 0.010, 0.030, 3, 15, True)
    return out


GROUP_SIZES = (24, 20, 16, 14, 12, 10, 9, 8, 7, 6, 5, 4)   # 135 groupable SKUs


def _groups(rng, skus):
    """12 product groups of very different sizes.

    Real catalogues are lopsided: a handful of big categories carry most of the
    lines, a long tail of small ones carries the rest.  Size matters for the
    scenario: an ordering heuristic that ranks SKUs by their group's total
    demand puts the big (mostly cold) categories in the prime slots, which is
    exactly wrong for single-pick pallet orders and exactly right for
    same-group baskets.
    """
    groups = [[] for _ in GROUP_SIZES]
    small = [k["id"] for k in skus if not k["hazmat"] and k["m3"] <= 0.05]
    bulky = [k["id"] for k in skus if k["m3"] > 0.05]
    rng.shuffle(small)
    rng.shuffle(bulky)
    # one bulky line per group first, then fill the rest with small lines
    for g, i in enumerate(bulky):
        groups[g % len(GROUP_SIZES)].append(i)
    j = 0
    for g, size in enumerate(GROUP_SIZES):
        while len(groups[g]) < size:
            groups[g].append(small[j])
            j += 1
    for g, mem in enumerate(groups):
        for i in mem:
            skus[i]["group"] = g
    for k in skus:
        if k["hazmat"]:
            k["group"] = 100 + k["id"]
    return groups


def zipf(rng, ids, alpha, floor, n_sku):
    """Skewed demand over the given ids, a flat floor elsewhere."""
    w = [floor] * n_sku
    for r, i in enumerate(sorted(ids, key=lambda _: rng.random())):
        w[i] += 1.0 / ((r + 1) ** alpha)
    return w


def sample_orders(weights, rng, n, spec=None):
    """Draw n orders from a demand distribution + order-structure spec.

    spec = dict(size=(lo, hi), sampler="iid"|"grouped", cohesion=c,
                groups=[[sku...]...]).  The same spec drives the forecast plan
    and the realised window, so a policy never sees the realised orders.
    """
    lo, hi = (spec or {}).get("size", (1, 5))
    sampler = (spec or {}).get("sampler", "iid")
    cohesion = (spec or {}).get("cohesion", 0.0)
    groups = (spec or {}).get("groups")
    kits = (spec or {}).get("kits")
    cum, acc = [], 0.0
    for x in weights:
        acc += x
        cum.append(acc)
    gmass, gtot = [], 0.0
    if sampler == "grouped" and groups:
        for g in groups:
            m = sum(weights[i] for i in g)
            gmass.append(m)
            gtot += m

    def draw():
        r = rng.random() * acc
        lo_i, hi_i = 0, len(cum) - 1
        while lo_i < hi_i:
            mid = (lo_i + hi_i) // 2
            if cum[mid] < r:
                lo_i = mid + 1
            else:
                hi_i = mid
        return lo_i

    out = []
    for _ in range(n):
        k = rng.randint(lo, hi)
        if sampler == "paired" and rng.random() < cohesion and kits:
            km = [weights[a] + weights[b] for a, b in kits]
            r = rng.random() * sum(km)
            acc_k, pick_k = 0.0, kits[0]
            for kk, m in zip(kits, km):
                acc_k += m
                if acc_k >= r:
                    pick_k = kk
                    break
            out.append(list(pick_k))
        elif sampler == "grouped" and rng.random() < cohesion and gtot > 0:
            r = rng.random() * gtot
            gi, run = 0, 0.0
            for gi, m in enumerate(gmass):
                run += m
                if run >= r:
                    break
            mem = groups[gi]
            out.append(rng.sample(mem, min(len(mem), k)))
        else:
            out.append([draw() for _ in range(k)])
    return out


def build(seed):
    rng = random.Random(seed)
    aisles, bays, levels = 6, 10, 3
    slots = _slots(rng, aisles, bays, levels)
    skus = _skus(rng)
    groups = _groups(rng, skus)
    # Kits: an assembly pallet pairs one bulky line from group g with an
    # accessory line from group g+6.  The pair is picked as one order, so its
    # two SKUs want adjacent slots -- but they belong to different product
    # groups, so grouping by category actively separates them.  That is the
    # structural conflict with the basket family (4.4).
    kits = []
    for g in range(6):
        big = sorted([i for i in groups[g] if skus[i]["m3"] > 0.05],
                     key=lambda i: -skus[i]["m3"])
        part = sorted([i for i in groups[g + 6] if skus[i]["m3"] <= 0.03],
                      key=lambda i: -skus[i]["m3"])
        for t in range(min(2, len(big), len(part))):
            kits.append([big[t], part[t]])
    kit_edges = {"%d-%d" % (min(p), max(p)) for p in kits}

    # co-purchase affinity: weak within a group, strong for a kit pair
    aff = {}
    for i in range(len(skus)):
        for j in range(i + 1, len(skus)):
            key = "%d-%d" % (i, j)
            if key in kit_edges:
                aff[key] = round(rng.uniform(0.85, 1.0), 3)
            elif skus[i]["group"] == skus[j]["group"] and skus[i]["group"] < 100:
                aff[key] = round(rng.uniform(0.2, 0.55), 3)

    heavy = [k["id"] for k in skus if not k["hazmat"] and k["kg"] > 25]
    dense = [k["id"] for k in skus if not k["hazmat"] and k["m3"] <= 0.022]
    small = [k["id"] for k in skus if not k["hazmat"] and k["m3"] <= 0.03]
    # the bulk hot sets live in the four smallest groups: high pick frequency
    # does not mean high category volume, and that is what breaks a single
    # "demand x group mass" heuristic.
    tail = set(sorted(range(len(GROUP_SIZES)),
                      key=lambda g: GROUP_SIZES[g])[:4])
    tail_dense = [i for i in dense if skus[i]["group"] in tail]
    tail_heavy = [i for i in heavy if skus[i]["group"] in tail]
    kit_items = [i for p in kits for i in p]

    windows = []
    basket_i = bulk_i = 0
    for w in range(52):
        peak = 1.9 if 40 <= w <= 44 else 1.0
        drift = w >= 27
        block = w // BLOCK
        # families alternate in two-week blocks, 26 windows each over the year
        fam = FAMILIES[(w // 2) % 2]
        # The hot set rotates every BLOCK weeks (a store rotates its picks all
        # year, not once), and the rotation after week 27 draws from the other
        # half of the pool: that is the injected season drift.
        brng = random.Random(seed * 131 + block * 17 + (1 if drift else 0))
        if fam == "bulk":
            hot = brng.sample(kit_items, min(HOT_BULK, len(kit_items)))
            weights = zipf(brng, hot, 0.55, 0.002, len(skus))
            c = BULK_COHESION[bulk_i % len(BULK_COHESION)]
            bulk_i += 1
            spec = dict(size=BULK_SIZE, sampler="paired", cohesion=c, kits=kits)
        else:
            hot = brng.sample(small, min(HOT_BASKET, len(small)))
            weights = zipf(brng, hot, 0.45, 0.004, len(skus))
            c = BASKET_COHESION[basket_i % len(BASKET_COHESION)]
            basket_i += 1
            spec = dict(size=BASKET_SIZE, sampler="grouped", cohesion=c)
        tot = sum(weights)
        windows.append(dict(week=w + 1, family=fam,
                            weights=[round(x / tot, 6) for x in weights],
                            size=list(spec["size"]), sampler=spec["sampler"],
                            cohesion=spec["cohesion"],
                            orders=int(round(260 * peak))))
    return dict(seed=seed, layout=dict(aisles=aisles, bays=bays, levels=levels),
                slots=slots, skus=skus, affinity=aff, groups=groups, kits=kits,
                windows=windows, drift_week=27, peak_weeks=[40, 44],
                families=list(FAMILIES))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="slotting/data/slotting.json")
    a = ap.parse_args()
    d = build(a.seed)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(d, open(a.out, "w"))
    print("wrote %s: %d slots, %d SKUs, %d windows (%d bulk / %d basket)"
          % (a.out, len(d["slots"]), len(d["skus"]), len(d["windows"]),
             sum(1 for w in d["windows"] if w["family"] == "bulk"),
             sum(1 for w in d["windows"] if w["family"] == "basket")))


if __name__ == "__main__":
    main()
