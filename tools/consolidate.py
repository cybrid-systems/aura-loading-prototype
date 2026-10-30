#!/usr/bin/env python3
"""拼柜（consolidation）外层优化：把一条线路上的多票货分配到若干个柜里，并为每个柜选柜型。

  python3 tools/consolidate.py --pool a.txt b.txt ... --out out/cons/R1 [--algo lns] [--time-s 60]
  python3 tools/consolidate.py --groups pools.json --out out/cons            # {"线路A": ["a.txt", ...], ...}

输入是内核格式的问题文件（docs/FORMAT.md）。一"票"（shipment）= 一条 I 行；I 行的 id 写成 `票号.序号`（如 s012.1、s012.2）
时同一票号的几行算同一票。同一票必须进同一个柜（不拆票），这是拼柜和柜内摆放的区别。
同一个问题文件里的票按出现顺序视为到货顺序（next-fit 基线用）。

算法（--algo）：
  nf   next-fit：按到货顺序装，装不下就封柜开新柜，只用一种柜型（--base-type，默认 45HC）——近似"人工按到货顺序拼"
  ff   first-fit：按到货顺序，放进第一个装得下的已开柜（后到的小票可以回填前面的柜），只用一种柜型
  ffd  first-fit decreasing：按体积从大到小，放进第一个装得下的已开柜，只用一种柜型
  lns  从 ffd 出发做大邻域搜索：拆掉装得最空的柜把货重新插进别的柜（插不下时做一次"挤出-换柜"的柜间交换）、
       两柜合并重装成更便宜的柜型组合、（前两种都不行时）单个柜降柜型、随机移票；只接受总运费下降（或运费相同、装得更集中）的改动
构造阶段（nf/ff/ffd 和 lns 的起点）只用快速确定性判定；lns 改进阶段对接近装满的判定再加 --search-ms 的随机重启搜索。
每次"这些票能不能装进这个柜型"都由 C++ 内核真算（algo=block only=<柜型> maxbins=1），多种构造思路组成组合预言机
（--oracle wall,human,block,layer：依次试，任何一种全部装下即可行），每个最终柜的方案都经 verify.py 独立校验。
下界：每条线路 min Σ运费，使 Σ容积 ≥ 货物体积、Σ限重 ≥ 货物重量（容积按 100% 计，严格成立），并报告最优性间隙。
"""
import argparse, json, os, random, shutil, subprocess, sys, time, hashlib, itertools
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from verify import check

KERNEL = os.environ.get("PC_KERNEL", "build/pack")
KEEP_WORK = os.environ.get("PC_KEEP_WORK", "0") == "1"  # 默认算完一条线路就删掉中间文件
HARD = "min_support=0.75 lifo=1 hazmat_sep=1000"
ORACLE = {  # same constructor parameters as aura/strategies.aura
    "wall": "space=0 w_vol=1.0 w_yz=0.5",
    "human": "space=0 w_vol=0.3 w_big=1.0 w_same=0.5 w_heavy=0.3",
    "block": "space=2 w_vol=1.0",
    "layer": "space=1 w_vol=0.5 w_xy=1.0",
}


def parse(path):
    cts, lines = [], []
    for l in open(path, encoding="utf-8"):
        t = l.split()
        if not t or t[0].startswith("#"):
            continue
        if t[0] == "C":
            cts.append((t[1], float(t[2]), float(t[3]), float(t[4]), float(t[5]), float(t[6])))
        elif t[0] == "I":
            lines.append(l.rstrip("\n"))
    return cts, lines


def load_pool(files):
    cts, ships, order = None, {}, []
    for fi, f in enumerate(files):
        c, lines = parse(f)
        cts = cts or c
        for l in lines:
            t = l.split()
            key = f"{fi}:{t[1].split('.')[0]}"
            # keep ids unique across files
            t[1] = f"f{fi}_{t[1]}"
            if key not in ships:
                ships[key] = {"key": key, "lines": [], "vol": 0.0, "kg": 0.0, "boxes": 0}; order.append(key)
            s = ships[key]; q = int(t[7]); s["lines"].append(" ".join(t)); s["boxes"] += q
            s["vol"] += float(t[3]) * float(t[4]) * float(t[5]) * q / 1e9; s["kg"] += float(t[6]) * q
    return cts, [ships[k] for k in order]


class Oracle:
    def __init__(self, cts, work, strategies, budget_ms, j):
        self.cts = {c[0]: c for c in cts}; self.work = work; self.strats = strategies; self.budget = budget_ms
        self.search_fill = 0.95; self.max_fill = 0.985; self.cache = {}; self.calls = 0; self.kernel_ms = 0.0; self.pool = ThreadPoolExecutor(j); os.makedirs(work, exist_ok=True)

    def cap(self, ct):
        c = self.cts[ct]; return c[1] * c[2] * c[3] / 1e9

    def _run(self, ct, ships, params, tag):
        c = self.cts[ct]
        h = hashlib.sha1((ct + "|" + "|".join(sorted(s["key"] for s in ships)) + "|" + params).encode()).hexdigest()[:16]
        pf, rf = os.path.join(self.work, f"p_{h}.txt"), os.path.join(self.work, f"r_{h}_{tag}.json")
        with open(pf, "w") as f:
            f.write(f"C {c[0]} {c[1]:.0f} {c[2]:.0f} {c[3]:.0f} {c[4]:.0f} {c[5]} -1\n")
            for s in ships:
                f.write("\n".join(s["lines"]) + "\n")
        t0 = time.time()
        subprocess.run(f"{KERNEL} --in {pf} --out {rf} algo=block only={ct} maxbins=1 {HARD} {params}", shell=True, capture_output=True)
        self.kernel_ms += (time.time() - t0) * 1000; self.calls += 1
        try:
            os.remove(pf)
            r = json.load(open(rf))
        except Exception:
            return False, None
        ok = not r["unplaced"] and not check(r)
        if not ok:  # only feasible plans are ever reused; keep the work dir small (thousands of kernel calls per route)
            os.remove(rf); rf = None
        return ok, rf

    def fits(self, ct, ships):
        key = (ct, frozenset(s["key"] for s in ships))
        hit = self.cache.get(key)
        if hit and (hit[0][0] or hit[1] or self.budget <= 0):
            return hit[0]
        c = self.cts[ct]; vol = sum(s["vol"] for s in ships); kg = sum(s["kg"] for s in ships)
        if kg > c[4] or vol > self.max_fill * self.cap(ct):  # weight is exact; volume above --max-fill (default 98.5%, never reached by the kernel on cartons) is skipped
            self.cache[key] = ((False, None), True); return (False, None)
        res = (False, None)
        if not hit:
            # quick deterministic pass with every constructor in parallel, then a timed search if it is close
            futs = [self.pool.submit(self._run, ct, ships, ORACLE[s] + " width=1 noise=0 time_ms=1000000", "q" + s) for s in self.strats]
            for f in futs:
                ok, rf = f.result()
                if ok and not res[0]:
                    res = (True, rf)
        searched = False
        if not res[0] and self.budget > 0 and vol <= self.search_fill * self.cap(ct):
            searched = True
            futs = [self.pool.submit(self._run, ct, ships, ORACLE[s] + f" time_ms={self.budget}", "s" + s) for s in self.strats]
            for f in futs:
                ok, rf = f.result()
                if ok and not res[0]:
                    res = (True, rf)
        self.cache[key] = (res, searched or self.budget <= 0 or vol > self.search_fill * self.cap(ct))
        return res


def cost_of(oracle, ct):
    return oracle.cts[ct][5]


def lower_bound(cts, ships):
    V = sum(s["vol"] for s in ships); K = sum(s["kg"] for s in ships)
    best = (1e18, None); lim = int(V / min(c[1] * c[2] * c[3] / 1e9 for c in cts)) + 2
    for n in itertools.product(range(lim + 1), repeat=len(cts)):
        v = sum(k * c[1] * c[2] * c[3] / 1e9 for k, c in zip(n, cts)); w = sum(k * c[4] for k, c in zip(n, cts))
        cost = sum(k * c[5] for k, c in zip(n, cts))
        if v >= V - 1e-9 and w >= K - 1e-9 and cost < best[0]:
            best = (cost, n)
    capmax = max(c[1] * c[2] * c[3] / 1e9 for c in cts)
    big = sum(1 for s in ships if s["vol"] > capmax / 2)
    import math
    return {"cost": round(best[0], 4), "mix": {c[0]: k for k, c in zip(best[1], cts) if k}, "containers": max(math.ceil(V / capmax - 1e-9), big)}


class Plan:
    def __init__(self, bins):
        self.bins = bins  # list of [ct, [ships], result_path]

    def cost(self, o):
        return sum(cost_of(o, b[0]) for b in self.bins)

    def conc(self, o):  # higher = fuller containers (tie-break between equal-cost plans)
        return sum((sum(s["vol"] for s in b[1]) / o.cap(b[0])) ** 2 for b in self.bins)

    def copy(self):
        return Plan([[b[0], list(b[1]), b[2]] for b in self.bins])


def next_fit(o, ships, ct):
    bins, cur = [], []
    for s in ships:
        ok, rf = o.fits(ct, cur + [s])
        if ok:
            cur.append(s); last = rf
        else:
            if cur:
                bins.append([ct, cur, last])
            cur = [s]; ok, last = o.fits(ct, cur)
            if not ok:
                raise SystemExit(f"shipment {s['key']} does not fit a single {ct}")
    if cur:
        bins.append([ct, cur, last])
    return Plan(bins)


def first_fit_dec(o, ships, ct, key=lambda s: -s["vol"]):
    bins = []
    for s in sorted(ships, key=key):
        for b in bins:
            if o.cap(ct) * o.max_fill - sum(x["vol"] for x in b[1]) < s["vol"]:
                continue
            ok, rf = o.fits(ct, b[1] + [s])
            if ok:
                b[1].append(s); b[2] = rf; break
        else:
            ok, rf = o.fits(ct, [s])
            if not ok:
                raise SystemExit(f"shipment {s['key']} does not fit a single {ct}")
            bins.append([ct, [s], rf])
    return Plan(bins)


def cheapest_fit(o, ships):
    for ct in sorted(o.cts, key=lambda t: o.cts[t][5]):
        ok, rf = o.fits(ct, ships)
        if ok:
            return ct, rf
    return None, None


def downsize(o, p, stats):
    for b in p.bins:
        for ct in sorted(o.cts, key=lambda t: o.cts[t][5]):
            if o.cts[ct][5] >= o.cts[b[0]][5]:
                break
            ok, rf = o.fits(ct, b[1])
            if ok:
                b[0], b[2] = ct, rf; stats["downsize"] += 1; break


def try_insert(o, p, s, skip, allow_eject, stats):
    """insert shipment s into some bin != skip (best fit = least free volume left); optional one-step ejection chain"""
    cands = sorted((i for i in range(len(p.bins)) if i != skip),
                   key=lambda i: o.cap(p.bins[i][0]) - sum(x["vol"] for x in p.bins[i][1]) - s["vol"])
    for i in cands:
        b = p.bins[i]
        if o.cap(b[0]) - sum(x["vol"] for x in b[1]) < s["vol"] * 0.99:
            continue
        ok, rf = o.fits(b[0], b[1] + [s])
        if ok:
            b[1].append(s); b[2] = rf; return True
    if not allow_eject:
        return False
    # inter-container swap: eject a smaller shipment e from bin i so that s fits there, and move e into another bin
    for i in cands:
        b = p.bins[i]
        for e in sorted(b[1], key=lambda x: x["vol"]):
            if e["vol"] >= s["vol"]:
                break
            rest = [x for x in b[1] if x is not e]
            ok, rf = o.fits(b[0], rest + [s])
            if not ok:
                continue
            saved = (list(b[1]), b[2]); b[1] = rest + [s]; b[2] = rf
            if try_insert(o, p, e, skip, False, stats):
                stats["swap"] += 1; return True
            b[1], b[2] = saved
    return False


def lns(o, p, deadline, rng, stats, lb_cost=0.0):
    # downsizing early makes containers fuller and blocks "eliminate a container" (measured: real pools got 1 container
    # worse), so it is only a fallback move when nothing else improves, plus once at the end
    best = p.copy()
    while time.time() < deadline and best.cost(o) > lb_cost + 1e-9:  # stop early at the (exact) cost lower bound
        improved = False
        # 1) eliminate a container: emptiest first
        order = sorted(range(len(best.bins)), key=lambda i: sum(s["vol"] for s in best.bins[i][1]) / o.cap(best.bins[i][0]))
        for i in order[:3]:
            if time.time() > deadline:
                break
            q = best.copy(); ships = sorted(q.bins[i][1], key=lambda s: -s["vol"]); ok = True
            for s in ships:
                if not try_insert(o, q, s, i, True, stats):
                    ok = False; break
            if ok:
                del q.bins[i]; stats["eliminate"] += 1; best = q; improved = True; break
        if improved:
            continue
        # 2) repack two containers into a cheaper type combination (e.g. 45HC+45HC -> 45HC+20GP)
        n = len(best.bins)
        pairs = sorted(itertools.combinations(range(n), 2),
                       key=lambda ij: sum(sum(s["vol"] for s in best.bins[k][1]) / o.cap(best.bins[k][0]) for k in ij))
        for i, j in pairs[:6]:
            if time.time() > deadline:
                break
            U = best.bins[i][1] + best.bins[j][1]; cur = cost_of(o, best.bins[i][0]) + cost_of(o, best.bins[j][0])
            V = sum(s["vol"] for s in U)
            combos = sorted({tuple(sorted(c)) for c in itertools.product(o.cts, repeat=2)}, key=lambda c: sum(cost_of(o, t) for t in c))
            for combo in combos:
                if sum(cost_of(o, t) for t in combo) >= cur - 1e-9:
                    break
                if sum(o.cap(t) for t in combo) * o.max_fill < V:
                    continue
                # big container first, FFD with a random tie-break
                bins = [[t, [], None] for t in sorted(combo, key=lambda t: -o.cap(t))]
                ok = True
                for s in sorted(U, key=lambda s: -s["vol"] * (1 + 0.05 * rng.random())):
                    for b in bins:
                        if o.cap(b[0]) * o.max_fill - sum(x["vol"] for x in b[1]) < s["vol"]:
                            continue
                        f, rf = o.fits(b[0], b[1] + [s])
                        if f:
                            b[1].append(s); b[2] = rf; break
                    else:
                        ok = False; break
                if ok:
                    q = best.copy(); q.bins = [b for k, b in enumerate(q.bins) if k not in (i, j)] + [b for b in bins if b[1]]
                    stats["repack2"] += 1; best = q; improved = True; break
            if improved:
                break
        if improved:
            continue
        # 3) downsize single containers (only when no container can be eliminated / no pair repacked)
        q = best.copy(); downsize(o, q, stats)
        if q.cost(o) < best.cost(o) - 1e-9:
            best = q; continue
        # 4) random perturbation: move one random shipment between two bins (kept only if cost stays and concentration rises)
        if len(best.bins) < 2:
            break
        q = best.copy(); i, j = rng.sample(range(len(q.bins)), 2)
        if q.bins[i][1]:
            s = rng.choice(q.bins[i][1]); rest = [x for x in q.bins[i][1] if x is not s]
            f, rf = o.fits(q.bins[j][0], q.bins[j][1] + [s])
            if f and rest:
                okr, rr = o.fits(q.bins[i][0], rest)
                if okr:
                    q.bins[j][1].append(s); q.bins[j][2] = rf; q.bins[i][1] = rest; q.bins[i][2] = rr
                    if (q.cost(o), -q.conc(o)) < (best.cost(o), -best.conc(o)):
                        stats["move"] += 1; best = q
        stats["rounds"] += 1
    downsize(o, best, stats)
    return best


def finish(o, p, ships, out, name, algo, lb, t0):
    keys = sorted(s["key"] for b in p.bins for s in b[1])
    assert keys == sorted(s["key"] for s in ships), "every shipment exactly once"
    merged = {"containers": [], "unplaced": [], "metrics": {}}
    for b in p.bins:
        r = json.load(open(b[2])); assert not r["unplaced"] and not check(r)
        c = r["containers"][0]; c["shipments"] = [s["key"] for s in b[1]]; merged["containers"].append(c)
    cap = sum(c["L"] * c["W"] * c["H"] for c in merged["containers"]); vol = sum(b["dx"] * b["dy"] * b["dz"] for c in merged["containers"] for b in c["boxes"])
    mix = {}
    for b in p.bins:
        mix[b[0]] = mix.get(b[0], 0) + 1
    m = {"pool": name, "algo": algo, "shipments": len(ships), "boxes": sum(s["boxes"] for s in ships),
         "containers": len(p.bins), "mix": "+".join(f"{v}x{k}" for k, v in sorted(mix.items())), "cost": round(p.cost(o), 4),
         "vol_util": round(vol / cap, 4), "lb_cost": lb["cost"], "lb_containers": lb["containers"],
         "gap": round(p.cost(o) / lb["cost"] - 1, 4) if lb["cost"] else None,
         "kernel_calls": o.calls, "kernel_ms": round(o.kernel_ms), "ms": round((time.time() - t0) * 1000)}
    merged["metrics"] = m
    os.makedirs(out, exist_ok=True)
    json.dump(merged, open(os.path.join(out, f"{name}.{algo}.json"), "w"))
    if not KEEP_WORK:
        shutil.rmtree(o.work, ignore_errors=True)
    return m


def solve_pool(name, files, a):
    t0 = time.time()
    cts, ships = load_pool(files)
    if a.types:
        cts = [c for c in cts if c[0] in a.types.split(",")]
    o = Oracle(cts, os.path.join(a.work, name), a.oracle.split(","), 0, a.j)  # constructive phase: quick oracle only
    o.max_fill = a.max_fill + 1e-9
    lb = lower_bound(cts, ships)
    rng = random.Random(a.seed); stats = dict(downsize=0, eliminate=0, swap=0, repack2=0, move=0, rounds=0)
    if a.algo == "nf":      # 按到货顺序装满一柜再开下一柜（最朴素的人工做法）
        p = next_fit(o, ships, a.base_type)
    elif a.algo == "ff":    # 按到货顺序，后到的小票可以回填前面没封的柜
        p = first_fit_dec(o, ships, a.base_type, key=lambda s: 0)
    elif a.algo == "ffd":   # 按体积从大到小首次适应
        p = first_fit_dec(o, ships, a.base_type)
    else:
        keyf = {"kg": lambda s: -s["kg"], "arrival": lambda s: 0}.get(a.seed_order, lambda s: -s["vol"])
        start = first_fit_dec(o, ships, a.base_type, key=keyf)
        o.budget = a.search_ms  # improvement phase: timed kernel search on close calls
        p = lns(o, start, time.time() + a.time_s, rng, stats, lb["cost"])
    m = finish(o, p, ships, a.out, name, a.algo, lb, t0); m["moves"] = stats
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", nargs="*")
    ap.add_argument("--groups")
    ap.add_argument("--name", default="pool")
    ap.add_argument("--out", default="out/cons")
    ap.add_argument("--work", default="out/cons-work")
    ap.add_argument("--algo", default="lns", choices=["nf", "ff", "ffd", "lns"])
    ap.add_argument("--base-type", default="45HC")
    ap.add_argument("--types", default="", help="comma list of allowed container types (default: all in the files)")
    ap.add_argument("--oracle", default="wall,human")
    ap.add_argument("--search-ms", type=int, default=1500, help="timed kernel search when the quick pass fails (0 = off)")
    ap.add_argument("--max-fill", type=float, default=0.985, help="skip kernel calls above this volume fill (1.0 for exact-fit test data)")
    ap.add_argument("--time-s", type=float, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seed-order", default="vol", choices=["vol", "kg", "arrival"])
    ap.add_argument("-j", type=int, default=int(os.environ.get("J", "2")))
    a = ap.parse_args()
    pools = json.load(open(a.groups, encoding="utf-8")) if a.groups else {a.name: a.pool}
    res = [solve_pool(n, fs, a) for n, fs in pools.items()]
    for m in res:
        print("@@c " + " ".join(f"{k}={v}" for k, v in m.items() if k != "moves") + " moves=" + ",".join(f"{k}:{v}" for k, v in m["moves"].items()))
    json.dump(res, open(os.path.join(a.out, f"summary.{a.algo}.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
