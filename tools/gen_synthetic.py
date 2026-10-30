#!/usr/bin/env python3
"""Generate synthetic (fully made-up) loading orders for tests, examples and benchmarks.

  python3 tools/gen_synthetic.py --orders 12 --seed 7 --out examples/synthetic
Each order gets <out>/order_NN.txt (kernel format) and the batch an index.json.
No real customer data is used anywhere in this generator.
"""
import argparse, json, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
import containers, problem

PROFILES = [  # (l, w, h) ranges in mm, kg/m3 density range, share
    ("carton-s", (250, 450), (200, 400), (150, 350), (120, 260)),
    ("carton-m", (400, 700), (300, 500), (250, 500), (100, 220)),
    ("carton-l", (600, 1000), (400, 700), (400, 800), (80, 180)),
    ("pallet", (1100, 1250), (900, 1050), (900, 1500), (150, 380)),
    ("long", (1500, 2400), (200, 400), (150, 300), (150, 350)),
]


def gen_order(rng, idx, target_m3):
    items, vol, k = [], 0.0, 0
    while vol < target_m3:
        name, L, W, H, dens = rng.choice(PROFILES)
        l, w, h = rng.randint(*L) // 10 * 10, rng.randint(*W) // 10 * 10, rng.randint(*H) // 10 * 10
        m3 = l * w * h / 1e9
        kg = round(m3 * rng.uniform(*dens), 1)
        qty = rng.randint(1, 6) if name == "pallet" else rng.randint(4, 60)
        fragile = rng.random() < 0.08
        rot = 1 if (name == "pallet" or rng.random() < 0.6) else 0
        stop = rng.choice([1, 1, 2, 2, 3])
        hazmat = rng.choice(["3", "8"]) if rng.random() < 0.04 else ""
        max_top = 0 if fragile else round(kg * rng.choice([3, 5, 8, 20]), 1)
        k += 1
        items.append(dict(id=f"S{idx:02d}-{k:03d}", sku=f"{name}-{k:03d}", l=l, w=w, h=h, kg=kg, qty=qty,
                          rot=rot, max_top=max_top, fragile=fragile, stop=stop, hazmat=hazmat))
        vol += m3 * qty
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="examples/synthetic")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    os.makedirs(a.out, exist_ok=True)
    idx = []
    for i in range(1, a.orders + 1):
        target = rng.choice([25, 45, 70, 110, 160])  # m3 of cargo
        items = gen_order(rng, i, target)
        p = os.path.join(a.out, f"order_{i:02d}.txt")
        problem.write(p, items, containers.load())
        idx.append({"order": f"order_{i:02d}", "file": os.path.basename(p), "lines": len(items),
                    "boxes": sum(x["qty"] for x in items)})
    json.dump(idx, open(os.path.join(a.out, "index.json"), "w"), indent=1)
    print(f"wrote {len(idx)} synthetic orders to {a.out}")


if __name__ == "__main__":
    main()
