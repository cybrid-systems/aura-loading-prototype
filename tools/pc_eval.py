#!/usr/bin/env python3
"""Portfolio member evaluator (synthetic data only) for the v0.2 downstream study.

Every member solves ONE kernel problem file (one synthetic order) under a wall-clock
budget and writes a plan JSON that tools/verify.py can re-check.  The last stdout line
is a single number (the score) so it can be called from Aura portfolio factories.

  python3 tools/pc_eval.py --problem P --member wall --budget-ms 700 --seed 1 --out O.json
  python3 tools/pc_eval.py --features P                 # JSON problem features, one line
  python3 tools/pc_eval.py --problem P --member param --params "space=0 w_vol=1.0" ...

Members
  constructors : wall layer block human oversize cog mixed fitgap  (algo=block, all types)
  consolidation: nf ff ffd lns  (tools/consolidate.py on the order as one route)
  param        : a single kernel configuration (used by the MOEA/D / NSGA-II members)

Budget alignment: a member that converges early is restarted with the next seed until
its budget is spent (same convention as the kernel's own random restarts), so reported
actual time tracks the budget instead of the fastest lucky run.  The internal deadline
keeps a safety margin so the caller's watchdog never sees an overrun.
"""
import argparse, json, os, random, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KERNEL = os.environ.get("PC_KERNEL", os.path.join(REPO, "build/pack"))
HARD = "min_support=0.75 lifo=1 hazmat_sep=1000"

CONSTRUCTORS = {
    "wall": "space=0 w_vol=1.0 w_yz=0.5",
    "layer": "space=1 w_vol=0.5 w_xy=1.0",
    "block": "space=2 w_vol=1.0",
    "human": "space=0 w_vol=0.3 w_big=1.0 w_same=0.5 w_heavy=0.3",
    "oversize": "space=2 w_vol=0.5 w_big=2.0 w_heavy=0.5",
    "cog": "space=1 w_vol=0.5 w_xy=0.5 w_heavy=1.5",
    "mixed": "space=0 w_vol=1.0 w_yz=0.5 mixed=1",
    "fitgap": "space=0 w_vol=1.0 w_waste=1.0",
}
CONSOLIDATION = ["nf", "ff", "ffd", "lns"]
MEMBERS = list(CONSTRUCTORS) + CONSOLIDATION
def margin(budget):
    """Headroom for process spawn, JSON write and the kernel's coarse time check.

    The kernel stops between search iterations, so it can overshoot time_ms by one
    iteration (~50 ms); the caller's watchdog fires at the budget, and an overrun
    would mark every member 'cancelled' and leave the round without a winner.
    """
    return 150 + int(budget * 0.03)


def features(path):
    cts, its = {}, []
    for ln in open(path, encoding="utf-8"):
        t = ln.split()
        if t and t[0] == "C":
            cts[t[1]] = [float(x) for x in t[2:6]]
        elif t and t[0] == "I":
            its.append(dict(l=float(t[3]), w=float(t[4]), h=float(t[5]), kg=float(t[6]), q=int(t[7]),
                            rot=int(t[8]), fragile=t[10] == "1", stop=int(t[11]), haz=t[12] != "-"))
    V = sum(i["l"] * i["w"] * i["h"] * i["q"] for i in its) / 1e9
    n = sum(i["q"] for i in its)
    big = sum(i["l"] * i["w"] * i["h"] * i["q"] for i in its if max(i["l"], i["w"], i["h"]) > 1200) / 1e9
    hc = cts.get("45HC", next(iter(cts.values()), [12032, 2352, 2698, 26500]))
    kg = sum(i["kg"] * i["q"] for i in its)
    return dict(types=len(its), boxes=n, vol=round(V, 2),
                fill=round(V / (hc[0] * hc[1] * hc[2] / 1e9), 3),
                oversize=round(big / V, 3) if V else 0,
                density=round(kg / V, 1) if V else 0,
                weight_fill=round(kg / hc[3], 3),
                stops=len({i["stop"] for i in its}),
                hazmat=1 if any(i["haz"] for i in its) else 0,
                fragile=round(sum(i["q"] for i in its if i["fragile"]) / max(n, 1), 3))


def plan_metrics(r):
    conts = r.get("containers", [])
    cog = 0.0
    door = 0.0
    for c in conts:
        g = c.get("cog", [0.5, 0.5, 0.0])
        cog = max(cog, abs(g[0] - 0.5) * 2.0, abs(g[1] - 0.5) * 2.0)
        el = c.get("end_load_kg", {})
        f, d = float(el.get("front", 1.0)), float(el.get("door", 1.0))
        if f + d > 1e-9:
            door = max(door, d / (f + d))
    m = r.get("metrics", {})
    return dict(cost=float(m.get("cost", 1e9)), containers=int(m.get("containers", len(conts))),
                vol_util=float(m.get("vol_util", 0.0)), unplaced=len(r.get("unplaced", [])),
                cog_dev=round(cog, 4), door_load=round(door, 4))


def verify_ok(r):
    sys.path.insert(0, HERE)
    from verify import check
    try:
        return not check(r)
    except Exception:
        return False


def score_of(m):
    if m["unplaced"]:
        return 1e7 + 1000.0 * m["unplaced"] + m["cost"]
    return m["cost"]


def finish(out, member, problem, budget, seed, started, best, attempts, extra=None):
    m = plan_metrics(best) if best else dict(cost=1e9, containers=0, vol_util=0.0, unplaced=999,
                                             cog_dev=1.0, door_load=1.0)
    rec = dict(member=member, problem=os.path.abspath(problem), budget_ms=budget, seed=seed,
               attempts=attempts, wall_ms=round((time.monotonic() - started) * 1000, 1),
               feasible=bool(best) and m["unplaced"] == 0, **m)
    rec["score"] = round(score_of(m), 4)
    if extra:
        rec.update(extra)
    rec["plan_file"] = os.path.abspath(out)
    if best:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        json.dump(best, open(out, "w"))
    ap = os.environ.get("PC_AUDIT", "")
    if ap:
        with open(ap, "a") as fh:
            fh.write("%s\t%s\t%s\t%s\t%s\t%s\n" % (member, os.path.basename(problem), budget,
                                                   rec["wall_ms"], rec["feasible"], seed))
    print(json.dumps(rec))
    print(rec["score"])
    return rec


def eval_kernel(problem, params, budget, seed, out, member, started, extra=None):
    deadline = started + (budget - margin(budget)) / 1000.0
    best, best_key, attempts = None, (1, 1e9, 1.0), 0
    tmp = tempfile.mkdtemp(prefix="pce-%s-" % member)
    try:
        while True:
            left = int((deadline - time.monotonic()) * 1000)
            if left < 50:
                break
            attempts += 1
            pf = os.path.join(tmp, "a%d.json" % attempts)
            subprocess.run([KERNEL, "--in", problem, "--out", pf, "algo=block"] + params.split() +
                           [HARD, "seed=%d" % (seed + attempts - 1), "time_ms=%d" % max(30, left - 35)],
                           capture_output=True)
            try:
                r = json.load(open(pf))
            except Exception:
                continue
            m = plan_metrics(r)
            key = (m["unplaced"], m["cost"], m["cog_dev"])
            if best is None or key < best_key:
                best, best_key = r, key
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish(out, member, problem, budget, seed, started, best, attempts, extra)


def shuffled_problem(path, seed, dest):
    rng = random.Random(seed)
    cts, its = [], []
    for ln in open(path, encoding="utf-8"):
        t = ln.split()
        if not t:
            continue
        (cts if t[0] == "C" else its).append(ln.rstrip("\n"))
    rng.shuffle(its)
    open(dest, "w").write("\n".join(cts + its) + "\n")


def eval_consolidation(problem, algo, budget, seed, out, started):
    deadline = started + (budget - margin(budget)) / 1000.0
    best, best_key, attempts, last = None, (1, 1e9, 1.0), 0, 0.15
    tmp = tempfile.mkdtemp(prefix="pce-%s-" % algo)
    try:
        while True:
            left = (deadline - time.monotonic())
            if left < max(0.10, last * 1.15 + 0.02):
                break
            attempts += 1
            t_att = time.monotonic()
            pf = os.path.join(tmp, "p%d.txt" % attempts)
            shuffled_problem(problem, seed * 1000 + attempts, pf)
            od = os.path.join(tmp, "o%d" % attempts)
            cmd = [sys.executable, os.path.join(HERE, "consolidate.py"), "--pool", pf,
                   "--name", "x", "--algo", algo, "--out", od, "--work", od + "w", "-j", "2"]
            if algo == "lns":
                cmd += ["--time-s", "%.3f" % max(0.08, left - 0.35), "--search-ms", "25"]
            subprocess.run(cmd, capture_output=True)
            last = time.monotonic() - t_att
            try:
                m = json.load(open(os.path.join(od, "summary.%s.json" % algo)))[0]
                r = json.load(open(os.path.join(od, "x.%s.json" % algo)))
            except Exception:
                continue
            mm = plan_metrics(r)
            mm["cost"] = float(m.get("cost", mm["cost"]))
            key = (mm["unplaced"], mm["cost"], mm["cog_dev"])
            if best is None or key < best_key:
                best, best_key = r, key
                best["metrics"] = dict(best.get("metrics", {}), **{"cost": mm["cost"]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish(out, algo, problem, budget, seed, started, best, attempts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem")
    ap.add_argument("--features", action="store_true")
    ap.add_argument("--member", default="wall")
    ap.add_argument("--params", nargs="+", default=[])
    ap.add_argument("--budget-ms", type=int, default=700)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="/tmp/pc_plan.json")
    a = ap.parse_args()
    if a.features:
        print(json.dumps(features(a.problem)))
        return
    started = time.monotonic()
    if a.member == "param":
        eval_kernel(a.problem, " ".join(a.params), a.budget_ms, a.seed, a.out, "param", started)
    elif a.member in CONSTRUCTORS:
        eval_kernel(a.problem, CONSTRUCTORS[a.member], a.budget_ms, a.seed, a.out, a.member, started)
    elif a.member in CONSOLIDATION:
        eval_consolidation(a.problem, a.member, a.budget_ms, a.seed, a.out, started)
    else:
        print(json.dumps({"error": "unknown member " + a.member}))
        print(1e9)
        sys.exit(2)


if __name__ == "__main__":
    main()
