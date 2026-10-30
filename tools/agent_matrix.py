#!/usr/bin/env python3
"""Agent 贡献矩阵：每个问题 × 每个构造 Agent 跑一次内核（同样的 time_ms），记录结果和问题特征，
用来回答 "每个 Agent 带来多少"（leave-one-out）、"按特征派发能不能在同等算力下赢过固定 4 Agent"。

  python3 tools/agent_matrix.py --problems a.txt b.txt ... --out out/matrix.json [--time-ms 2000] [--fill] [-j 4]
  python3 tools/agent_matrix.py --report out/matrix.json [--md out.md]
Agent 参数与 aura/strategies.aura 保持一致（tests 检查）。
"""
import argparse, itertools, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from verify import check

AGENTS = {  # 前 4 个 = 默认 4 Agent；后 4 个 = 专家 Agent（只在派发规则命中时启用）
    "wall": "space=0 w_vol=1.0 w_yz=0.5",
    "layer": "space=1 w_vol=0.5 w_xy=1.0",
    "block": "space=2 w_vol=1.0",
    "human": "space=0 w_vol=0.3 w_big=1.0 w_same=0.5 w_heavy=0.3",
    "oversize": "space=2 w_vol=0.5 w_big=2.0 w_heavy=0.5",
    "cog": "space=1 w_vol=0.5 w_xy=0.5 w_heavy=1.5",
    "mixed": "space=0 w_vol=1.0 w_yz=0.5 mixed=1",
    "fitgap": "space=0 w_vol=1.0 w_waste=1.0",
}
BASE4 = ["wall", "layer", "block", "human"]
# 与 aura/strategies.aura 的 dispatch 规则相同：(特征, 比较, 阈值, 被替换, 替换成)
DISPATCH = [("types", ">=", 40, "block", "fitgap"), ("fill", ">", 1.0, "layer", "mixed")]


def dispatch(feat):
    ags = list(BASE4)
    for f, op, th, old, new in DISPATCH:
        v = feat[f]
        if (v >= th if op == ">=" else v > th):
            ags[ags.index(old)] = new
    return ags
HARD = "min_support=0.75 lifo=1 hazmat_sep=1000"


def features(path):
    cts, its = {}, []
    for ln in open(path, encoding="utf-8"):
        t = ln.split()
        if t and t[0] == "C":
            cts[t[1]] = [float(x) for x in t[2:6]]
        elif t and t[0] == "I":
            its.append(dict(l=float(t[3]), w=float(t[4]), h=float(t[5]), kg=float(t[6]), q=int(t[7]), rot=int(t[8]),
                            fragile=t[10] == "1", stop=int(t[11]), haz=t[12] != "-"))
    V = sum(i["l"] * i["w"] * i["h"] * i["q"] for i in its) / 1e9; n = sum(i["q"] for i in its)
    big = sum(i["l"] * i["w"] * i["h"] * i["q"] for i in its if max(i["l"], i["w"], i["h"]) > 1200) / 1e9
    hc = cts.get("45HC", next(iter(cts.values())))
    kg = sum(i["kg"] * i["q"] for i in its)
    return dict(types=len(its), boxes=n, vol=round(V, 2), fill=round(V / (hc[0] * hc[1] * hc[2] / 1e9), 3),
                oversize=round(big / V, 3) if V else 0, density=round(kg / V, 1) if V else 0,
                weight_fill=round(kg / hc[3], 3), stops=len({i["stop"] for i in its}), hazmat=any(i["haz"] for i in its),
                fragile=round(sum(i["q"] for i in its if i["fragile"]) / max(n, 1), 3))


def run(prob, agent, a):
    base = os.path.splitext(os.path.basename(prob))[0]; d = os.path.join(a.work, base); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, agent + ".json")
    fill = "only=45HC maxbins=1" if a.fill else ""
    subprocess.run(f"build/pack --in {prob} --out {out} algo=block {AGENTS[agent]} {HARD} {fill} time_ms={a.time_ms} seed={a.seed}",
                   shell=True, capture_output=True)
    try:
        r = json.load(open(out))
    except Exception:
        return dict(ok=False)
    errs = [e for e in check(r) if not (a.fill and e.startswith("unplaced"))]
    m = r["metrics"]; placed = sum(b["dx"] * b["dy"] * b["dz"] for c in r["containers"] for b in c["boxes"]) / 1e9
    cog = max([max(abs(c["cog"][0] - 0.5 * c["L"]) / c["L"] if c["cog"][0] > 1 else abs(c["cog"][0] - 0.5),
                   abs(c["cog"][1] - 0.5 * c["W"]) / c["W"] if c["cog"][1] > 1 else abs(c["cog"][1] - 0.5)) for c in r["containers"]] or [0])
    os.remove(out)
    return dict(ok=not errs, unplaced=len(r["unplaced"]), cost=m["cost"], containers=m["containers"], vol_util=m["vol_util"],
                placed_m3=round(placed, 4), cog_dev=round(cog, 4))


def key(res, fill):
    if not res.get("ok"):
        return (1, 0, 0)
    return (0, -res["placed_m3"], 0) if fill else (res["unplaced"], res["cost"], -res["vol_util"])


def best(row, agents, fill):
    return min((row["runs"][g] for g in agents), key=lambda r: key(r, fill))


def report(M, md=None):
    fill = M["fill"]; rows = M["rows"]; names = [g for g in AGENTS if all(g in r["runs"] for r in rows)]
    def score(agents):  # fill: total placed m3 (higher better); multi-bin: total cost (lower better)
        if callable(agents):
            return round(sum(best(r, agents(r["features"]), fill).get("placed_m3" if fill else "cost", 0) for r in rows), 3)
        if fill:
            return round(sum(best(r, agents, fill).get("placed_m3", 0) for r in rows), 3)
        return round(sum(best(r, agents, fill).get("cost", 0) for r in rows), 3)
    have = lambda gs: all(g in names for g in gs)
    out = [f"{len(rows)} 个问题，每个 Agent {M['time_ms']} ms，{'单柜装载（总装入 m³，越大越好）' if fill else '多柜（总运费，越小越好）'}", ""]
    out.append("| Agent 组合 | 结果 | 赢的问题数 |"); out.append("|---|---|---|")
    for g in names:
        wins = sum(1 for r in rows if key(r["runs"][g], fill) == key(best(r, names, fill), fill))
        out.append(f"| 单独 {g} | {score([g])} | {wins} |")
    if have(BASE4):
        out.append(f"| 固定 4 Agent ({'+'.join(BASE4)}) | {score(BASE4)} | |")
        if have(["fitgap", "mixed"]):
            nd = sum(1 for r in rows if dispatch(r["features"]) != BASE4)
            out.append(f"| 按特征派发 4 Agent（同等算力，{nd} 题换了专家） | {score(dispatch)} | |")
    out.append(f"| 全部 {len(names)} Agent（{len(names) / 4:g} 倍算力） | {score(names)} | |")
    for g in BASE4:
        if have(BASE4):
            out.append(f"| 4 Agent 去掉 {g} | {score([x for x in BASE4 if x != g])} | |")
    for g in names:
        if g not in BASE4 and have(BASE4):
            out.append(f"| 4 Agent + {g}（5 倍单算力） | {score(BASE4 + [g])} | |")
    if len(names) >= 4:
        bestk = min(itertools.combinations(names, 4), key=lambda c: score(list(c)) * (-1 if fill else 1))
        out.append(f"| 事后最优的 4 个（同等算力上限，有过拟合） | {score(list(bestk))} ({'+'.join(bestk)}) | |")
    txt = "\n".join(out); print(txt)
    if md:
        open(md, "w").write(txt + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", nargs="*", default=[])
    ap.add_argument("--out"); ap.add_argument("--report"); ap.add_argument("--md")
    ap.add_argument("--time-ms", type=int, default=2000); ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--fill", action="store_true"); ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--work", default="out/matrix-work"); ap.add_argument("--agents", default=",".join(AGENTS))
    a = ap.parse_args()
    if a.report:
        return report(json.load(open(a.report)), a.md)
    ags = a.agents.split(","); jobs = [(p, g) for p in a.problems for g in ags]
    with ThreadPoolExecutor(a.j) as ex:
        res = list(ex.map(lambda pg: run(pg[0], pg[1], a), jobs))
    rows = []
    for p in a.problems:
        rows.append(dict(problem=os.path.basename(p), features=features(p), runs={g: res[jobs.index((p, g))] for g in ags}))
    M = dict(time_ms=a.time_ms, fill=a.fill, rows=rows)
    json.dump(M, open(a.out, "w"), indent=1)
    report(M, a.md)


if __name__ == "__main__":
    main()
