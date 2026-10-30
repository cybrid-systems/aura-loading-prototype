#!/usr/bin/env python3
"""Batch comparison: baselines vs Aura multi-agent decision, on a directory of kernel problem files.

  python3 tools/bench.py --orders examples/synthetic --out out/bench [--time-ms 8000] [--aura]
Baselines (same hard rules, same kernel, so the difference is only the decision strategy):
  B0 经验基线  : 只用 40HQ、不旋转、按单据顺序、无局部搜索
  B1 单策略贪心: 允许混合柜型 + 旋转，单一排序策略，无局部搜索
  B2 单策略+局部搜索: 与"空间优化"Agent 相同参数，但独占 4×time_ms 的搜索时间（= AURA 4 个 Agent 的总算力），
                     用来区分"多 Agent 协调"本身的收益和"多花算力"的收益
  --strategies 追加块构造内核（algo=block）的四种构造思路，参数与 aura/strategies.aura 一致：
  S_wall 墙式 / S_layer 层式 / S_block 块式 / S_human 人工经验，各用 time_ms；
  S_wall4 = 墙式独占 4×time_ms（同等算力的最好单策略，对照 AURA 4 个 Agent 各 time_ms）
  AURA         : 4 个 Agent 并行提案 + 局部搜索 + 规则否决 + 加权选优（aura/main.aura）
  --fill       : 每单只给 1 个 45HC（only=45HC maxbins=1），比较单柜最大装载率（装不下的箱计 unplaced，不算不可行）
Writes <out>/bench.json and <out>/bench.md (aggregate numbers only).
"""
import argparse, glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
from verify import check

KERNEL = os.environ.get("PC_KERNEL", "build/pack")
HARD = "min_support=0.75 lifo=1 hazmat_sep=1000"
BASELINES = {
    "B0": "only=40HQ rotate=0 sort=4 sort_stop=1 iters=0",
    "B1": "sort=0 iters=0",
    "B2": "sort=0 w_x=1.0 w_z=0.15 w_y=0.02 iters=1000000 time_ms={t4}",
}


STRATS = {
    "S_wall": "algo=block space=0 w_vol=1.0 w_yz=0.5 time_ms={t}",
    "S_layer": "algo=block space=1 w_vol=0.5 w_xy=1.0 time_ms={t}",
    "S_block": "algo=block space=2 w_vol=1.0 time_ms={t}",
    "S_human": "algo=block space=0 w_vol=0.3 w_big=1.0 w_same=0.5 w_heavy=0.3 time_ms={t}",
    "S_wall4": "algo=block space=0 w_vol=1.0 w_yz=0.5 time_ms={t4}",
}
FILL = ""


def run_kernel(problem, out, params):
    subprocess.run(f"{KERNEL} --in {problem} --out {out} {HARD} {FILL} {params}", shell=True, check=False, capture_output=True)
    return json.load(open(out))


def agg(rows, key):
    rs = [r[key] for r in rows]
    vol = sum(r["metrics"]["vol_util"] * sum(c["L"] * c["W"] * c["H"] for c in r["containers"]) for r in rs)
    cap = sum(sum(c["L"] * c["W"] * c["H"] for c in r["containers"]) for r in rs)
    return {"containers": sum(r["metrics"]["containers"] for r in rs), "cost": round(sum(r["metrics"]["cost"] for r in rs), 3),
            "vol_util": round(vol / cap, 4) if cap else 0, "lower_bound": sum(r["metrics"]["lower_bound"] for r in rs),
            "infeasible": sum(1 for r in rows if r[key + "_errs"]), "unplaced": sum(r["metrics"].get("unplaced", 0) for r in rs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", default="examples/synthetic")
    ap.add_argument("--out", default="out/bench")
    ap.add_argument("--time-ms", default="8000")
    ap.add_argument("--aura", action="store_true")
    ap.add_argument("--strategies", action="store_true")
    ap.add_argument("--no-baselines", action="store_true")
    ap.add_argument("--fill", action="store_true")
    a = ap.parse_args()
    global FILL
    if a.fill: FILL = "only=45HC maxbins=1"
    runs = {} if a.no_baselines else dict(BASELINES)
    if a.strategies: runs.update(STRATS)
    if a.fill:  # the ep kernel ignores maxbins, and B0 is 40HQ-only: baselines are meaningless in single-45HC fill mode
        for k in BASELINES: runs.pop(k, None)
    if not runs: runs = {"B1": BASELINES["B1"]}
    os.makedirs(a.out, exist_ok=True)
    probs = sorted(glob.glob(os.path.join(a.orders, "*.txt")))
    from concurrent.futures import ThreadPoolExecutor
    t4 = str(4 * int(a.time_ms))
    def one(p):
        base = os.path.basename(p)
        row = {"order": base}
        for k, params in runs.items():
            r = run_kernel(p, os.path.join(a.out, f"{base}.{k}.json"), params.format(t4=t4, t=a.time_ms))
            row[k] = r; row[k + "_errs"] = errs(r)
        return row
    errs = (lambda r: [e for e in check(r) if not e.startswith("unplaced")]) if a.fill else check
    with ThreadPoolExecutor(int(os.environ.get("J", "4"))) as ex:
        rows = list(ex.map(one, probs))
    if a.aura:
        env = dict(os.environ, PC_ORDERS=" ".join(probs), PC_OUT=a.out, PC_TIME_MS=a.time_ms, PC_EXTRA=FILL, **({"PC_RULES": "aura/rules-fill.sexp"} if a.fill else {}))
        subprocess.run("script -qc 'scripts/aura.sh aura/main.aura' /dev/null > " + os.path.join(a.out, "aura.log"), shell=True, env=env)
        tsv = {l.split("\t")[0]: l.split("\t") for l in open(os.path.join(a.out, "aura-summary.tsv"), encoding="utf-8").read().splitlines() if l}
        for row in rows:
            t = tsv[row["order"]]
            r = json.load(open(t[2])); row["AURA"] = r; row["AURA_errs"] = errs(r)
            row["AURA_agent"] = t[1]; row["AURA_ms"] = int(float(t[3]))
    keys = list(runs) + (["AURA"] if a.aura else [])
    k0 = "B1" if "B1" in keys else keys[0]  # B0 is restricted to 40HQ, so its bound is not the all-types bound
    rep = os.path.join(a.orders, "import_report.json")  # real data: containers actually used, if the sheet had them
    exist = {r["file"]: r for r in (json.load(open(rep, encoding="utf-8")) if os.path.exists(rep) else []) if r.get("existing_containers")}
    summary = {k: agg(rows, k) for k in keys}
    per = [{"order": r["order"], "boxes": r[k0]["metrics"]["boxes"],
            **{k: {"containers": r[k]["metrics"]["containers"], "mix": r[k]["metrics"]["mix"], "cost": r[k]["metrics"]["cost"],
                   "vol_util": round(r[k]["metrics"]["vol_util"], 4), "unplaced": r[k]["metrics"].get("unplaced", 0),
                   "feasible": not r[k + "_errs"]} for k in keys},
            "lower_bound": r[k0]["metrics"]["lower_bound"], "agent": r.get("AURA_agent"), "aura_ms": r.get("AURA_ms"),
            "existing": exist.get(r["order"], {}).get("existing_containers"),
            "existing_types": exist.get(r["order"], {}).get("existing_types")} for r in rows]
    json.dump({"summary": summary, "orders": per}, open(os.path.join(a.out, "bench.json"), "w"), ensure_ascii=False, indent=1)
    L = ["| 订单 | 箱数 | 下界(柜) | " + " | ".join(keys) + (" | 胜出Agent | 决策耗时 |" if a.aura else " |"), "|---" * (len(keys) + 3 + (2 if a.aura else 0)) + "|"]
    fmt = lambda d: f"{d['mix']} / {d['cost']:.2f} / {d['vol_util']*100:.1f}%" + (f" 余{d['unplaced']}" if d["unplaced"] else "") + ("" if d["feasible"] else " ✗")
    for o in per:
        L.append(f"| {o['order']} | {o['boxes']} | {o['lower_bound']} | " + " | ".join(fmt(o[k]) for k in keys) +
                 (f" | {o['agent']} | {o['aura_ms']/1000:.1f}s |" if a.aura else " |"))
    L += ["", "| 方案 | 总柜数 | 总相对运费 | 加权体积利用率 | 未装箱数 | 不可行方案数 |", "|---|---|---|---|---|---|"]
    for k in keys:
        s = summary[k]; L.append(f"| {k} | {s['containers']} | {s['cost']:.2f} | {s['vol_util']*100:.1f}% | {s['unplaced']} | {s['infeasible']} |")
    lb = summary[k0]["lower_bound"]  # B0 is restricted to 40HQ, so its bound is not the all-types bound
    ex = [o for o in per if o["existing"]]
    if ex:
        import containers as _ct
        cost_of = {c[0]: c[5] for c in _ct.load()}
        known = all(t in cost_of for o in ex for t in (o["existing_types"] or ["?"]))
        e_tot = sum(o["existing"] for o in ex)
        # one type per order is the common case (a manifest per container); mixed types are costed by their first type
        e_cost = sum(o["existing"] * cost_of.get((o["existing_types"] or ["?"])[0], float("nan")) for o in ex)
        L += ["", f"现有装柜方案对比（{len(ex)} 个有装柜记录的订单/柜单；现有柜型" + ("按导入时 --existing-type 假设" if known else "未知") + "）：", "",
              "| 方案 | 总柜数 | 相对现有柜数 | 总相对运费 | 相对现有运费 | 可行 |", "|---|---|---|---|---|---|",
              f"| EXIST 现有方案 | {e_tot} | — | " + (f"{e_cost:.2f}" if known else "?") + " | — | — |"]
        for k in keys:
            c = sum(o[k]["containers"] for o in ex); co = sum(o[k]["cost"] for o in ex); feas = sum(1 for o in ex if o[k]["feasible"])
            L.append(f"| {k} | {c} | {(c-e_tot)/e_tot*100:+.1f}% | {co:.2f} | " + (f"{(co-e_cost)/e_cost*100:+.1f}%" if known else "?") + f" | {feas}/{len(ex)} |")
        summary["EXIST"] = {"containers": e_tot, "cost": round(e_cost, 3) if known else None, "orders": len(ex)}
        json.dump({"summary": summary, "orders": per}, open(os.path.join(a.out, "bench.json"), "w"), ensure_ascii=False, indent=1)
    if a.aura and all(k in summary for k in ("B0", "B1", "B2")):
        b0, au = summary["B0"], summary["AURA"]
        L += ["", f"- AURA 相对 B0：柜数 {b0['containers']} → {au['containers']}（{(au['containers']-b0['containers'])/b0['containers']*100:+.1f}%），"
              f"相对运费 {b0['cost']:.2f} → {au['cost']:.2f}（{(au['cost']-b0['cost'])/b0['cost']*100:+.1f}%）",
              f"- AURA 相对 B1：相对运费 {summary['B1']['cost']:.2f} → {au['cost']:.2f}（{(au['cost']-summary['B1']['cost'])/summary['B1']['cost']*100:+.1f}%）",
              f"- AURA 相对 B2（同等算力单策略）：相对运费 {summary['B2']['cost']:.2f} → {au['cost']:.2f}（{(au['cost']-summary['B2']['cost'])/summary['B2']['cost']*100:+.1f}%）",
              f"- 体积/重量下界合计 {lb} 柜（最大柜型），AURA 用 {au['containers']} 柜"]
    open(os.path.join(a.out, "bench.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
