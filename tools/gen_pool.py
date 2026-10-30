#!/usr/bin/env python3
"""生成合成拼柜数据（完全虚构）：若干条线路，每条线路一批按到货顺序排列的票，每票 1–3 种标准纸箱。

  python3 tools/gen_pool.py --routes 4 --seed 11 --out examples/pool
写 <out>/route_K.txt（内核格式，I 行 id = 票号.序号，同票号同一票）和 <out>/pools.json（线路 -> 文件）。
箱规取常见的外贸纸箱尺寸，只能直立、单卸货站、无危险品（与拿到的真实装柜单的字段情况一致）。
"""
import argparse, json, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
import containers, problem

CARTONS = [(600, 400, 400), (550, 450, 350), (500, 400, 300), (610, 510, 410), (450, 350, 300), (650, 500, 450),
           (400, 300, 250), (580, 380, 420), (700, 500, 500), (520, 420, 380), (480, 360, 320), (630, 430, 400)]


def gen_route(rng, r, target_m3):
    items, vol, k = [], 0.0, 0
    while vol < target_m3:
        k += 1
        size = rng.choices(["s", "m", "l"], [0.45, 0.4, 0.15])[0]
        qty_total = {"s": rng.randint(3, 25), "m": rng.randint(25, 90), "l": rng.randint(90, 260)}[size]
        nlines = rng.choice([1, 1, 1, 2, 2, 3])
        for j in range(nlines):
            l, w, h = rng.choice(CARTONS)
            q = max(1, qty_total // nlines)
            kg = round(l * w * h / 1e9 * rng.uniform(90, 260), 1)
            items.append(dict(id=f"s{k:03d}.{j+1}", sku=f"c{l}x{w}x{h}", l=l, w=w, h=h, kg=kg, qty=q, rot=1, max_top=1e9,
                              fragile=False, stop=1, hazmat=""))
            vol += l * w * h * q / 1e9
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="examples/pool")
    ap.add_argument("--scale", type=float, default=1.0, help="线路货量缩放（测试用小规模）")
    a = ap.parse_args()
    rng = random.Random(a.seed); os.makedirs(a.out, exist_ok=True); pools = {}
    for r in range(1, a.routes + 1):
        target = rng.uniform(140, 460) * a.scale
        items = gen_route(rng, r, target)
        p = os.path.join(a.out, f"route_{r}.txt"); problem.write(p, items, containers.load())
        pools[f"R{r}"] = [p]
    json.dump(pools, open(os.path.join(a.out, "pools.json"), "w"), indent=1)
    print(f"wrote {len(pools)} synthetic routes to {a.out}")


if __name__ == "__main__":
    main()
