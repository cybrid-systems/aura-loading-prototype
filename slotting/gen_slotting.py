#!/usr/bin/env python3
"""Synthetic warehouse-slotting generator (no real data).   v0.2 P9 / part B

  python3 slotting/gen_slotting.py --seed 7 --out slotting/data/s7.json

Everything is made up: an aisle/bay/level layout, a SKU catalogue with sizes,
weights and hazard flags, a co-purchase affinity matrix, and a 52-week order
stream with (a) a seasonal profile switch at week 27, (b) a peak at weeks
40-44, and (c) an SKU-structure drift (demand moves to the new families).
"""
import argparse, json, math, os, random


def build(seed):
    rng = random.Random(seed)
    A, B, L = 6, 10, 3
    slots = []
    for a in range(A):
        for b in range(B):
            for l in range(L):
                slots.append(dict(id=len(slots), aisle=a, bay=b, level=l,
                                  x=a * 10.0 + b * 0.55,
                                  cap_m3=round(rng.uniform(0.9, 1.4), 3),
                                  cap_kg=round(rng.uniform(180, 320), 1)))
    fams = ["food", "home", "apparel", "electronic", "hazmat"]
    skus = []
    for i in range(140):
        fam = rng.choices(fams, [0.40, 0.24, 0.18, 0.13, 0.05])[0]
        vol = round(rng.uniform(0.004, 0.09), 4)
        kg = round(vol * rng.uniform(70, 420), 2)
        skus.append(dict(id=i, family=fam, m3=vol, kg=kg, hazmat=(fam == "hazmat"),
                         group=i % 18))
    # co-purchase: same group and same family
    aff = {}
    for i in range(140):
        for j in range(i + 1, 140):
            if skus[i]["group"] == skus[j]["group"]:
                aff["%d-%d" % (i, j)] = round(rng.uniform(0.4, 1.0), 3)
            elif skus[i]["family"] == skus[j]["family"] and rng.random() < 0.05:
                aff["%d-%d" % (i, j)] = round(rng.uniform(0.1, 0.4), 3)
    base = [rng.uniform(0.1, 1.0) for _ in range(140)]
    windows = []
    for w in range(52):
        season = 1.0 if w < 27 else 1.0
        peak = 1.9 if 40 <= w <= 44 else 1.0
        weights = []
        for i in range(140):
            v = base[i]
            if w >= 27:  # structure drift: new families take over
                v *= 3.2 if i % 7 == 0 else (0.35 if i % 5 == 0 else 1.0)
            if 40 <= w <= 44:
                v *= 1.4 if i % 3 == 0 else 0.8
            weights.append(v * season * peak)
        tot = sum(weights)
        weights = [x / tot for x in weights]
        windows.append(dict(week=w + 1, weights=[round(x, 6) for x in weights],
                            orders=int(round(260 * peak))))
    return dict(seed=seed, layout=dict(aisles=A, bays=B, levels=L), slots=slots,
                skus=skus, affinity=aff, windows=windows,
                drift_week=27, peak_weeks=[40, 44])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="slotting/data/slotting.json")
    a = ap.parse_args()
    d = build(a.seed)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(d, open(a.out, "w"))
    print("wrote %s: %d slots, %d SKUs, %d windows" % (a.out, len(d["slots"]), len(d["skus"]), len(d["windows"])))


if __name__ == "__main__":
    main()
