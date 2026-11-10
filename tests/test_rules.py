#!/usr/bin/env python3
"""规则文件解析、热替换和安全底线。不启动 Aura。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ruleset

FAIL = 0


def check(name, ok, detail=""):
    global FAIL
    if ok:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAIL = 1


def main():
    subprocess.check_call([sys.executable, str(ROOT / "build.py")], cwd=ROOT)
    base = ruleset.parse_rules(ROOT / "rules/baseline.sexp")
    route = ruleset.parse_rules(ROOT / "rules/routes/sha-ams.sexp")
    acme = ruleset.parse_rules(ROOT / "rules/customers/acme.sexp")
    check("parse-templates", base and route and acme)
    check("floor-ok", ruleset.floor_issues(route) == [] and ruleset.floor_issues(acme) == [])
    names = {(r.kind, r.name) for r in route}
    check("route-has-no-mix", ("hard", "no-mix") in names)
    diff = " ".join(ruleset.changes(base, route))
    check("route-diff-is-no-mix", "no-mix" in diff and "carton" in diff, diff)

    bad = ruleset.parse_rules(ROOT / "tests/fixtures/relax-lifo.sexp")
    issues = ruleset.floor_issues(bad)
    check("floor-catches-lifo", any("lifo" in s and "低于安全底线" in s for s in issues), issues)

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bad.sexp"
        p.write_text('((hard no-mixx carton pallet "x")\n)\n', encoding="utf-8")
        try:
            ruleset.parse_rules(p)
            check("unknown-key", False, "should have failed")
        except ruleset.RuleError as e:
            check("unknown-key", "no-mixx" in str(e) and str(e).startswith(str(p) + ":1"), e)
        p.write_text('((hard no-mix carton\n)\n', encoding="utf-8")
        try:
            ruleset.parse_rules(p)
            check("syntax-line", False, "should have failed")
        except ruleset.RuleError as e:
            check("syntax-line", ":1:" in str(e) or ":2:" in str(e), e)
        p.write_text(
            '((hard min-support 0.75 "a")\n (hard max-kg 1 "b")\n (hard max-kg 2 "c"))\n',
            encoding="utf-8",
        )
        try:
            ruleset.parse_rules(p)
            check("dup-key", False, "should have failed")
        except ruleset.RuleError as e:
            check("dup-key", "max-kg" in str(e) and "重复" in str(e), e)

    order = ROOT / "examples/rules-demo/order.txt"
    out = ROOT / "out/test-rules"
    out.mkdir(parents=True, exist_ok=True)
    stamp = (ROOT / "build/pack").stat().st_mtime_ns
    old = ruleset.pack(order, base, out / "old.json", ruleset.FAST)
    new = ruleset.pack(order, route, out / "new.json", ruleset.FAST)
    check("kernel-not-rebuilt", (ROOT / "build/pack").stat().st_mtime_ns == stamp)
    check("baseline-packed", old.plan and old.plan["metrics"]["containers"] == 1 and old.plan["metrics"]["unplaced"] == 0, old.stderr)
    hits = ruleset.check_plan(route, old.plan)
    check("old-plan-rejected", any(h.startswith("规则 no-mix") and "carton" in h and "pallet" in h for h in hits), hits)
    check("new-plan-split", new.plan and new.plan["metrics"]["containers"] == 2 and new.plan["metrics"]["unplaced"] == 0, new.plan and new.plan["metrics"])
    check("new-plan-clean", ruleset.check_plan(route, new.plan) == [])
    # same-size different class must not share a container once no_mix is on
    same = out / "same.txt"
    same.write_text(
        "C BOX 2000 1000 1000 10000 1 -1\n"
        "I a carton 400 400 400 5 1 1 1000000000 0 1 -\n"
        "I b pallet 400 400 400 5 1 1 1000000000 0 1 -\n",
        encoding="utf-8",
    )
    mixed = ruleset.pack(same, base, out / "same-old.json", ruleset.FAST)
    split = ruleset.pack(same, route, out / "same-new.json", ruleset.FAST)
    check(
        "same-size-no-mix",
        mixed.plan and mixed.plan["metrics"]["containers"] == 1
        and split.plan and split.plan["metrics"]["containers"] == 2,
        (mixed.plan and mixed.plan["metrics"], split.plan and split.plan["metrics"]),
    )
    heavy = ruleset.pack(order, acme, out / "acme.json", ruleset.FAST)
    check("max-kg-rejects-old", any(h.startswith("规则 max-kg") for h in ruleset.check_plan(acme, old.plan)))
    check("max-kg-new-ok", heavy.plan and heavy.plan["metrics"]["unplaced"] == 0 and ruleset.check_plan(acme, heavy.plan) == [], heavy.stderr)
    only_file = out / "only.sexp"
    text = (ROOT / "rules/baseline.sexp").read_text(encoding="utf-8")
    text = text.replace(
        '(hard  lifo          1     "先卸后装：先到站的货不能被后到站的货挡住")',
        '(hard  lifo          1     "先卸后装：先到站的货不能被后到站的货挡住")\n'
        ' (hard  only-type 40HQ "只用 40HQ")',
    )
    only_file.write_text(text, encoding="utf-8")
    only_rules = ruleset.parse_rules(only_file)
    forced = ruleset.pack(order, only_rules, out / "only.json", ruleset.FAST)
    check("only-type-kernel", forced.plan and forced.plan["metrics"]["mix"] == "1x40HQ", forced.plan and forced.plan["metrics"])
    check("only-type-rejects-old", any("only-type" in h for h in ruleset.check_plan(only_rules, old.plan)))
    bad_arg = subprocess.run(
        [str(ROOT / "build/pack"), "--in", str(order), "--out", str(out / "bad.json"), "no_mix=carton"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    check("no-mix-arg-error", bad_arg.returncode == 2 and "no_mix" in bad_arg.stderr, bad_arg.stderr)
    bad_type = subprocess.run(
        [str(ROOT / "build/pack"), "--in", str(order), "--out", str(out / "bad.json"), "types=NOPE"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    check("types-arg-error", bad_type.returncode == 2 and "NOPE" in bad_type.stderr, bad_type.stderr)
    # default path unchanged: the cube still fills one bin without the new parameters
    cube = out / "cube.txt"
    cube.write_text("C BOX 2000 2000 2000 10000 1 -1\nI c c 1000 1000 1000 10 8 1 1000000000 0 1 -\n", encoding="utf-8")
    proc = subprocess.run(
        [str(ROOT / "build/pack"), "--in", str(cube), "--out", str(out / "cube.json"), "algo=block", "space=0"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    check("default-cube", proc.returncode == 0 and "containers=1" in proc.stdout and "vol_util=1.0000" in proc.stdout, proc.stdout)
    demo = subprocess.run(
        [sys.executable, str(ROOT / "tools/demo_dx.py"), "rules", "--no-aura"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PC_OUT": str(out / "demo")},
    )
    out_text = demo.stdout + demo.stderr
    check(
        "demo-no-aura",
        demo.returncode == 0
        and "旧方案被拒绝" in demo.stdout
        and "规则 no-mix" in demo.stdout
        and "未重编译" in demo.stdout
        and "回放" in demo.stdout
        and "失败（" not in demo.stderr,
        out_text[-2000:],
    )
    refused = subprocess.run(
        [sys.executable, str(ROOT / "tools/demo_dx.py"), "rules", "--no-aura"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PC_RULES": "tests/fixtures/relax-lifo.sexp",
            "PC_OUT": str(out / "refused"),
        },
    )
    check(
        "demo-refuses-floor",
        refused.returncode == 2 and "失败（规则）" in refused.stderr and "安全底线" in refused.stderr and "没有用这份规则重解" in refused.stderr,
        refused.stderr,
    )
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
