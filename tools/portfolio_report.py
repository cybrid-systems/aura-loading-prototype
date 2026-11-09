#!/usr/bin/env python3
"""Aggregate the v0.2 P9 synthetic runs into the report tables (no real data).

  python3 tools/portfolio_report.py --root out/v02 --md docs/v02-downstream-report.md

Reads the Aura shard outputs (matrix_s*.json, halving_s*.tsv, eoh_s*.tsv,
moo_s*.tsv, audit_s*.tsv) and prints / writes the measured numbers only.
"""
import argparse, glob, json, math, os, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pc_eval import plan_metrics, verify_ok

BASE4 = ["wall", "layer", "block", "human"]


def betacf(a, b, x):
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lb) * betacf(a, b, x) / a
    return 1.0 - math.exp(lb) * betacf(b, a, 1.0 - x) / b


def t_p(t, df):
    if df <= 0 or not math.isfinite(t):
        return 1.0
    x = df / (df + t * t)
    tail = 0.5 * betai(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    m = statistics.fmean(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else 0.0
    t = m / se if se > 1e-12 else (1e9 if m > 0 else 0.0)
    return dict(n=n, mean=round(m, 4), sd=round(sd, 4), t=round(t, 3), p=round(t_p(t, n - 1), 4))


def load_matrix(path):
    d = json.load(open(path))
    return d


def member_total(m, insts, name):
    j = m["members"].index(name)
    vals = [m["means"][m["instances"].index(p)][j] for p in insts]
    return sum(vals), vals


def audit_stats(paths):
    rows = []
    for p in paths:
        for ln in open(p):
            t = ln.rstrip("\n").split("\t")
            if len(t) >= 5:
                rows.append(dict(member=t[0], problem=t[1], budget=float(t[2]),
                                 actual=float(t[3]), feasible=t[4] == "True", seed=t[5] if len(t) > 5 else ""))
    by = {}
    for r in rows:
        by.setdefault(r["member"], []).append(max(1e-9, r["budget"]), )
    out = {}
    for mem, rs in by.items():
        rs = [r for r in rows if r["member"] == mem]
        budgets = [r["budget"] for r in rs]
        actuals = [r["actual"] for r in rs]
        dev = [a / b - 1.0 for a, b in zip(actuals, budgets) if b > 0]
        out[mem] = dict(n=len(rs), budget=round(statistics.median(budgets), 1),
                        actual_med=round(statistics.median(actuals), 1),
                        dev_med=round(statistics.median(dev), 4),
                        within10=round(sum(1 for x in dev if abs(x) <= 0.10) / len(dev), 3),
                        over=round(max(dev), 4), under=round(min(dev), 4))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="out/v02")
    ap.add_argument("--md", default="docs/v02-downstream-report.md")
    a = ap.parse_args()
    R = a.root
    res = {}
    tr = load_matrix(os.path.join(R, "train/matrix_merged.json"))
    ho = load_matrix(os.path.join(R, "holdout/matrix_merged.json"))
    res["members"] = tr["members"]
    res["instances"] = dict(train=len(tr["instances"]), holdout=len(ho["instances"]))

    # SBS / VBS on the holdout (means over seeds)
    per_member = {}
    for name in ho["members"]:
        per_member[name] = sum(ho["means"][i][ho["members"].index(name)] for i in range(len(ho["instances"])))
    sbs_name = min(per_member, key=per_member.get)
    sbs = per_member[sbs_name]
    vbs = sum(min(row) for row in ho["means"])
    res["holdout"] = dict(sbs=round(sbs, 3), sbs_member=sbs_name, vbs=round(vbs, 3),
                          per_member={k: round(v, 3) for k, v in sorted(per_member.items(), key=lambda kv: kv[1])})

    # halving vs fixed4, per seed
    sel, fix, rows = [], [], []
    for p in sorted(glob.glob(os.path.join(R, "halving/halving_s*.tsv"))):
        s = int(os.path.basename(p).split("_s")[1].split(".")[0])
        ra = [l.rstrip("\n").split("\t") for l in open(p) if l.strip()]
        tot = sum(float(r[4]) for r in ra)
        m = load_matrix(os.path.join(R, "holdout/matrix_s%d.json" % s))
        f = sum(min(row[m["members"].index(x)] for x in BASE4) for row in m["means"])
        sel.append(tot)
        fix.append(f)
        rows.append(dict(seed=s, instances=len(ra), selection=round(tot, 3), fixed4=round(f, 3),
                         diff=round(f - tot, 3)))
    res["comparison"] = dict(rows=rows, selection_total=round(sum(sel), 3), fixed4_total=round(sum(fix), 3),
                             improvement=round(1 - sum(sel) / sum(fix), 4),
                             paired=paired([-x for x in sel], [-x for x in fix]))
    # gap closure on the holdout, using the halving cost per instance (seed-mean)
    halv = {}
    for p in sorted(glob.glob(os.path.join(R, "halving/halving_s*.tsv"))):
        for l in open(p):
            t = l.rstrip("\n").split("\t")
            if len(t) >= 5:
                halv.setdefault(t[1], []).append(float(t[4]))
    method = sum(statistics.fmean(v) for v in halv.values())
    res["gap"] = dict(sbs=round(sbs, 3), vbs=round(vbs, 3), method=round(method, 3),
                      closure=round((sbs - method) / (sbs - vbs), 4) if sbs != vbs else None)

    # compute alignment
    res["compute"] = audit_stats(sorted(glob.glob(os.path.join(R, "train/audit_s*.tsv"))) +
                                 sorted(glob.glob(os.path.join(R, "holdout/audit_s*.tsv"))) +
                                 sorted(glob.glob(os.path.join(R, "halving/audit_s*.tsv"))))

    # EoH audit
    eoh = dict(keep=0, rb_gate=0, rb_safety=0, keeps=[], bad_keep=0)
    for p in sorted(glob.glob(os.path.join(R, "eoh/eoh_s*.tsv"))):
        for l in open(p):
            t = l.rstrip("\n").split("\t")
            if len(t) < 5 or t[0] != "eoh":
                continue
            status = t[3]
            if status == "KEEP":
                eoh["keep"] += 1
                hd = float(t[7]) if len(t) > 7 and t[7] not in ("-", "") else 0.0
                eoh["keeps"].append(dict(seed=t[1], name=t[2], p=float(t[4]), train=float(t[6]), hold=hd))
                if hd <= 0:
                    eoh["bad_keep"] += 1
            elif status == "ROLLBACK-safety":
                eoh["rb_safety"] += 1
            else:
                eoh["rb_gate"] += 1
    res["eoh"] = eoh

    # Pareto: member aggregates from the plans of the holdout matrix runs
    plans = []
    for p in sorted(glob.glob(os.path.join(R, "holdout/matrix_s*.json"))):
        s = int(os.path.basename(p).split("_s")[1].split(".")[0])
        m = load_matrix(p)
        for i, inst in enumerate(m["instances"]):
            for j, name in enumerate(m["members"]):
                q = os.path.join("out/portfolio/work", "%s_%s_s%d.json" % (name, os.path.basename(inst), s))
                if os.path.exists(q):
                    try:
                        r = json.load(open(q))
                        mm = plan_metrics(r)
                        mm.update(member=name, instance=os.path.basename(inst), seed=s,
                                  verified=None)
                        plans.append(mm)
                    except Exception:
                        pass
    agg = {}
    for pl in plans:
        d = agg.setdefault(pl["member"], dict(n=0, cost=0.0, cog=0.0, door=0.0, bad=0))
        d["n"] += 1
        d["cost"] += pl["cost"]
        d["cog"] += pl["cog_dev"]
        d["door"] += pl["door_load"]
        d["bad"] += 0
    members = []
    for k, d in agg.items():
        if d["n"]:
            members.append(dict(member=k, cost=round(d["cost"] / d["n"], 4), cog=round(d["cog"] / d["n"], 4),
                                door=round(d["door"] / d["n"], 4), n=d["n"], unverified=d["bad"]))
    # verify a sample of the plans behind every member (verify.py is O(n^2) in boxes;
    # the full 480-plan sweep is not needed to prove the front is feasible)
    import random
    rng = random.Random(7)
    for k, d in agg.items():
        cand = [pl for pl in plans if pl["member"] == k]
        for pl in (rng.sample(cand, min(5, len(cand))) if cand else []):
            q = os.path.join("out/portfolio/work", "%s_%s_s%d.json" % (pl["member"], pl["instance"], pl["seed"]))
            if os.path.exists(q) and not verify_ok(json.load(open(q))):
                d["bad"] += 1
    front = []
    for x in members:
        if not any((y["cost"] <= x["cost"] and y["cog"] <= x["cog"] and y["door"] <= x["door"]) and
                   (y["cost"] < x["cost"] or y["cog"] < x["cog"] or y["door"] < x["door"]) for y in members):
            front.append(x)
    res["pareto"] = dict(members=sorted(members, key=lambda x: x["cost"]), front=front,
                         plans=len(plans), verified_sample=sum(min(5, d["n"]) for d in agg.values()),
                         unverified=sum(d["bad"] for d in agg.values()))
    moo = []
    for p in sorted(glob.glob(os.path.join(R, "moo/moo_s*.tsv"))):
        for l in open(p):
            t = l.rstrip("\n").split("\t")
            if len(t) >= 6 and t[1] in ("moead", "nsga2"):
                ok = False
                if t[5] and os.path.exists(t[5]):
                    try:
                        ok = verify_ok(json.load(open(t[5])))
                    except Exception:
                        ok = False
                moo.append(dict(seed=os.path.basename(p).split("_s")[1].split(".")[0], instance=t[0],
                                algo=t[1], cost=float(t[2]), cog=float(t[3]), door=float(t[4]), verified=ok))
    res["moo"] = dict(points=len(moo), algorithms=sorted({x["algo"] for x in moo}),
                      unverified=sum(1 for x in moo if not x["verified"]), sample=moo[:12])

    # consolidation portfolio
    cpath = os.path.join(R, "cons/matrix_merged.json")
    if os.path.exists(cpath):
        c = load_matrix(cpath)
        sbs_c = min(sum(c["means"][i][j] for i in range(len(c["instances"]))) for j in range(len(c["members"])))
        vbs_c = sum(min(row) for row in c["means"])
        res["cons"] = dict(members=c["members"], sbs=round(sbs_c, 3), vbs=round(vbs_c, 3),
                           per_member={n: round(sum(c["means"][i][c["members"].index(n)]
                                                    for i in range(len(c["instances"]))), 3)
                                       for n in c["members"]})

    json.dump(res, open(os.path.join(R, "summary.json"), "w"), indent=1)
    print(json.dumps(res, indent=1)[:4000])


if __name__ == "__main__":
    main()
