#!/usr/bin/env python3
"""PK（盲测对比）评测：对同一批问题，用同一个独立校验器给各家方案打分，出排行榜。规范见 docs/PK.md。

  python3 tools/pk.py --problems dir_or_files... --plans NAME=DIR [NAME=DIR ...] [--ours-ms 2000] [--md out.md] [--json out.json]

每个参赛方 DIR 下放 <问题文件名去掉 .txt>.json（内核输出格式）或 .csv（简表格式），可选 <名>.time 写求解耗时（秒）。
--ours-ms T：同时现场跑本仓库内核（algo=block，四种构造组合中取最好，每种 T 毫秒）作为参赛方 "ours"。
"""
import argparse, csv, glob, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from verify import check

E = 1e-3


def parse_problem(path):
    cts, items, rules = {}, {}, {}
    for ln in open(path, encoding="utf-8"):
        t = ln.split()
        if not t or t[0].startswith("#"):
            continue
        if t[0] == "C":
            cts[t[1]] = dict(L=float(t[2]), W=float(t[3]), H=float(t[4]), max_kg=float(t[5]), cost=float(t[6]))
        elif t[0] == "I":
            items[t[1]] = dict(l=float(t[3]), w=float(t[4]), h=float(t[5]), kg=float(t[6]), qty=int(t[7]), rot=int(t[8]),
                               max_top=float(t[9]), fragile=t[10] == "1", stop=int(t[11]), hazmat=t[12])
        elif t[0] == "R" and len(t) >= 3:
            rules[t[1]] = t[2]
    return cts, items, rules


def load_plan(path, cts, items):
    """kernel JSON, or CSV with columns container,type,id,x,y,z,dx,dy,dz (one row per box)"""
    if path.endswith(".json"):
        r = json.load(open(path))
        for c in r["containers"]:  # never trust the contender's own per-box attributes: take them from the problem
            for b in c["boxes"]:
                it = items.get(item_of(b["id"]))
                if it:
                    b.update(kg=it["kg"], stop=it["stop"], fragile=it["fragile"], hazmat=it["hazmat"])
            if c.get("type") in cts:
                c.update(cts[c["type"]])
        r.setdefault("unplaced", [])
        return r
    conts = {}
    for row in csv.DictReader(open(path, encoding="utf-8")):
        k = row["container"]; ct = row["type"]
        if k not in conts:
            conts[k] = dict(type=ct, **cts.get(ct, dict(L=0, W=0, H=0, max_kg=0, cost=0)), boxes=[])
        it = items.get(item_of(row["id"]), dict(kg=0, stop=1, fragile=False, hazmat="-"))
        conts[k]["boxes"].append(dict(id=row["id"], x=float(row["x"]), y=float(row["y"]), z=float(row["z"]), dx=float(row["dx"]),
                                      dy=float(row["dy"]), dz=float(row["dz"]), kg=it["kg"], stop=it["stop"], fragile=it["fragile"], hazmat=it["hazmat"]))
    return {"containers": list(conts.values()), "unplaced": []}


def item_of(bid):
    """box ids are `<item id>` or `<item id>#<copy>`"""
    return bid.rsplit("#", 1)[0] if "#" in bid else bid


def extra_checks(r, cts, items, hazmat_sep=0.0):
    """everything verify.check does not cover: box identity/count, dims vs allowed orientation, container type, fragile, hazmat gap"""
    errs, cnt = [], {}
    for ci, c in enumerate(r["containers"]):
        if c.get("type") not in cts:
            errs.append(f"c{ci} unknown container type {c.get('type')}")
        for b in c["boxes"]:
            it = items.get(item_of(b["id"]))
            if not it:
                errs.append(f"c{ci} unknown box id {b['id']}"); continue
            cnt[item_of(b["id"])] = cnt.get(item_of(b["id"]), 0) + 1
            d = (b["dx"], b["dy"], b["dz"]); s = (it["l"], it["w"], it["h"])
            if sorted(d) != sorted(s) and max(abs(p - q) for p, q in zip(sorted(d), sorted(s))) > 1:
                errs.append(f"c{ci} {b['id']} dims {d} != item {s}")
            elif it["rot"] == 1 and abs(b["dz"] - it["h"]) > 1:
                errs.append(f"c{ci} {b['id']} must stay upright")
            elif it["rot"] == 2 and max(abs(p - q) for p, q in zip(d, s)) > 1:
                errs.append(f"c{ci} {b['id']} fixed orientation")
        bs = c["boxes"]

        def area(a, b):
            return max(0.0, min(a["x"] + a["dx"], b["x"] + b["dx"]) - max(a["x"], b["x"])) * max(0.0, min(a["y"] + a["dy"], b["y"] + b["dy"]) - max(a["y"], b["y"]))
        on = [[] for _ in bs]
        for q in bs:
            if q["z"] < E:
                continue
            sup = [(k, area(q, b)) for k, b in enumerate(bs) if abs(b["z"] + b["dz"] - q["z"]) < E]
            sup = [(k, a_) for k, a_ in sup if a_ > E]; tot = sum(a_ for _, a_ in sup)
            for k, a_ in sup:
                on[k].append((q, a_, tot))
        for i, b in enumerate(bs):
            it = items.get(item_of(b["id"]))
            if not it:
                continue
            top = 0.0  # direct load, each box above shares its weight in proportion to contact area (same model as the kernel)
            for q in on[i]:
                top += q[0]["kg"] * q[1] / q[2]
            if it["fragile"] and top > 0:
                errs.append(f"c{ci} {b['id']} fragile but loaded")
            elif top > it["max_top"] + E:
                errs.append(f"c{ci} {b['id']} top load {top:.0f} > {it['max_top']:.0f}")
            for q in bs:
                if it["hazmat"] != "-" and q["hazmat"] not in ("-", it["hazmat"]) and q is not b:
                    gap = max(q["x"] - b["x"] - b["dx"], b["x"] - q["x"] - q["dx"])
                    if gap < hazmat_sep - E:
                        errs.append(f"c{ci} hazmat {it['hazmat']}/{q['hazmat']} gap {gap:.0f}")
    for k, it in items.items():
        if cnt.get(k, 0) != it["qty"]:
            errs.append(f"{k}: placed {cnt.get(k, 0)} of {it['qty']}")
    return errs


def score(r, cts, items, rules):
    errs = check(r, float(rules.get("min_support", 0.75)), rules.get("lifo", "1") != "0") + \
        extra_checks(r, cts, items, float(rules.get("hazmat_sep", 1000)))
    vol = sum(b["dx"] * b["dy"] * b["dz"] for c in r["containers"] for b in c["boxes"])
    cap = sum(cts[c["type"]]["L"] * cts[c["type"]]["W"] * cts[c["type"]]["H"] for c in r["containers"] if c.get("type") in cts)
    return dict(ok=not errs, errors=errs[:10], n_errors=len(errs), containers=len(r["containers"]),
                cost=round(sum(cts.get(c.get("type"), {}).get("cost", 0) for c in r["containers"]), 4),
                vol_util=round(vol / cap, 4) if cap else 0.0)


def run_ours(prob, outdir, ms):
    os.makedirs(outdir, exist_ok=True); base = os.path.splitext(os.path.basename(prob))[0]
    strats = {"wall": "space=0 w_vol=1.0 w_yz=0.5", "human": "space=0 w_vol=0.3 w_big=1.0 w_same=0.5 w_heavy=0.3",
              "block": "space=2 w_vol=1.0", "layer": "space=1 w_vol=1.0 w_xy=0.5"}
    t0 = time.time(); best = None
    procs = {k: (subprocess.Popen(f"build/pack --in {prob} --out {outdir}/{base}.{k}.json algo=block time_ms={ms} min_support=0.75 lifo=1 hazmat_sep=1000 {v}", shell=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)) for k, v in strats.items()}
    for k, p in procs.items():
        p.wait()
        try:
            r = json.load(open(f"{outdir}/{base}.{k}.json"))
        except Exception:
            continue
        m = r["metrics"]; key = (len(r["unplaced"]), m["cost"], -m["vol_util"])
        if best is None or key < best[0]:
            best = (key, r)
        os.remove(f"{outdir}/{base}.{k}.json")
    json.dump(best[1], open(f"{outdir}/{base}.json", "w"))
    open(f"{outdir}/{base}.time", "w").write(f"{time.time() - t0:.2f}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", nargs="+", required=True)
    ap.add_argument("--plans", nargs="*", default=[])
    ap.add_argument("--ours-ms", type=int, default=0)
    ap.add_argument("--ours-dir", default="out/pk/ours")
    ap.add_argument("--md"); ap.add_argument("--json")
    a = ap.parse_args()
    probs = []
    for p in a.problems:
        probs += sorted(glob.glob(os.path.join(p, "*.txt"))) if os.path.isdir(p) else [p]
    entrants = dict(x.split("=", 1) for x in a.plans)
    if a.ours_ms:
        for p in probs:
            run_ours(p, a.ours_dir, a.ours_ms)
        entrants["ours"] = a.ours_dir
    res = {n: [] for n in entrants}
    for p in probs:
        cts, items, rules = parse_problem(p); base = os.path.splitext(os.path.basename(p))[0]
        for n, d in entrants.items():
            f = next((x for x in (os.path.join(d, base + ".json"), os.path.join(d, base + ".csv")) if os.path.exists(x)), None)
            if not f:
                res[n].append(dict(problem=base, ok=False, errors=["missing plan"], n_errors=1, containers=0, cost=0, vol_util=0, time_s=None)); continue
            s = score(load_plan(f, cts, items), cts, items, rules); tf = os.path.join(d, base + ".time")
            s["time_s"] = float(open(tf).read()) if os.path.exists(tf) else None; s["problem"] = base
            res[n].append(s)
    rows = []
    for n, rs in res.items():
        ok = [r for r in rs if r["ok"]]; ts = [r["time_s"] for r in rs if r["time_s"] is not None]
        rows.append(dict(entrant=n, problems=len(rs), executable=len(ok), containers=sum(r["containers"] for r in ok),
                         cost=round(sum(r["cost"] for r in ok), 3), vol_util=round(sum(r["vol_util"] for r in ok) / len(ok), 4) if ok else 0,
                         time_s=round(sum(ts), 1) if ts else None))
    # ranking: more executable plans first, then lower total freight on the problems where all leading entrants
    # (the ones with the most executable plans) are executable - so one broken entrant cannot empty the comparison set
    top = max(r["executable"] for r in rows)
    lead = [r["entrant"] for r in rows if r["executable"] == top]
    common = [i for i in range(len(probs)) if all(res[n][i]["ok"] for n in lead)]
    for row in rows:
        row["cost_common"] = round(sum(res[row["entrant"]][i]["cost"] for i in common), 3) if row["entrant"] in lead else None
    rows.sort(key=lambda r: (-r["executable"], r["cost_common"] if r["cost_common"] is not None else 1e18, r["cost"]))
    md = [f"PK：{len(probs)} 个问题；“共同可执行”= 可执行数最多的参赛方都可执行的 {len(common)} 个问题", "",
          "| 名次 | 参赛方 | 可执行 | 柜数(可执行的) | 运费(可执行的) | 运费(共同可执行) | 平均装载率 | 耗时 s |", "|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(rows, 1):
        md.append(f"| {k} | {r['entrant']} | {r['executable']}/{r['problems']} | {r['containers']} | {r['cost']} | {r['cost_common'] if r['cost_common'] is not None else '-'} | "
                  f"{r['vol_util']:.1%} | {r['time_s'] if r['time_s'] is not None else '-'} |")
    print("\n".join(md))
    for n, rs in res.items():
        for r in rs:
            if not r["ok"]:
                print(f"  {n}/{r['problem']}: {r['n_errors']} 处违规，如 {r['errors'][:3]}")
    if a.md:
        open(a.md, "w").write("\n".join(md) + "\n")
    if a.json:
        json.dump(dict(rows=rows, detail=res), open(a.json, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
