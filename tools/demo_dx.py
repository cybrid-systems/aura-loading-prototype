#!/usr/bin/env python3
"""三条给调度员的演示。数字只来自这一次运行。

  python3 tools/demo_dx.py rules [--no-aura]
  python3 tools/demo_dx.py evolve
  python3 tools/demo_dx.py agents

失败时第一行是「失败（规则）」「失败（校验）」「失败（内核）」或「失败（Aura）」。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ruleset

ROOT = ruleset.ROOT


def die(kind: str, message: str, code: int):
    print(f"失败（{kind}）：{message}", file=sys.stderr)
    raise SystemExit(code)


def compile_kernel():
    proc = subprocess.run([sys.executable, str(ROOT / "build.py")], cwd=ROOT)
    if proc.returncode != 0:
        die("内核", "编译 build/pack 失败。需要 g++（C++20）。Debian/Ubuntu: apt install g++；macOS: xcode-select --install", 4)


def binary_mtime() -> int:
    return (ROOT / "build" / "pack").stat().st_mtime_ns


def load_rules(path: str):
    try:
        return ruleset.parse_rules(path)
    except ruleset.RuleError as e:
        die("规则", str(e), 2)


def aura_env(extra: dict) -> dict:
    env = os.environ.copy()
    bin_path = env.get("AURA_BIN") or ""
    if not bin_path:
        bundled = ROOT / ".aura" / "current" / "bin" / "aura"
        if bundled.is_file():
            bin_path = str(bundled)
            env["AURA_BIN"] = bin_path
    if not bin_path or not os.access(bin_path, os.X_OK):
        die(
            "Aura",
            "没有可执行的 AURA_BIN。运行 ./run.sh rules 会安装官方 Aura v0.2.0，或自行设置 AURA_BIN。",
            5,
        )
    if not env.get("AURA_PATH"):
        env["AURA_PATH"] = str(Path(bin_path).resolve().parent.parent / "lib")
    if not shutil.which("script"):
        die("Aura", "需要 script（否则 Aura 的输出会被缓冲）。Debian/Ubuntu: apt install bsdutils", 5)
    env.update(extra)
    env.setdefault("PC_TIMEOUT", "180")
    return env


def run_aura(entry: str, env: dict, log_path: Path) -> str:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["script", "-qc", f"scripts/aura.sh {entry}", "/dev/null"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    log_path.write_text(log, encoding="utf-8")
    if "@@done=ok" not in log and "@@done=refused" not in log:
        tail = "\n".join(log.strip().splitlines()[-30:])
        die("Aura", f"{entry} 没有跑完（退出码 {proc.returncode}）。日志 {log_path}\n{tail}", 5)
    return log


def verify(path: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify.py"), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    text = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, text


def _kv(rest: str) -> dict:
    out = {}
    for tok in rest.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def parse_record(text: str) -> dict:
    rec = {
        "floor": "ok",
        "floor_msg": "",
        "args": "",
        "order": "",
        "base_rules": "",
        "new_rules": "",
        "old": {},
        "new": {},
        "hit_old": [],
        "hit_new": [],
        "replay": [],
    }
    pending: dict[str, list] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("FLOOR bad "):
            rec["floor"] = "bad"
            rec["floor_msg"] = line[len("FLOOR bad ") :]
        elif line.startswith("FLOOR "):
            rec["floor"] = line.split(None, 1)[1]
        elif line.startswith("ARGS "):
            rec["args"] = line[5:]
        elif line.startswith("ORDER "):
            rec["order"] = line[6:]
        elif line.startswith("BASE_RULES "):
            rec["base_rules"] = line[len("BASE_RULES ") :]
        elif line.startswith("NEW_RULES "):
            rec["new_rules"] = line[len("NEW_RULES ") :]
        elif line.startswith("OLD "):
            rec["old"] = {} if line.endswith(" missing") else _kv(line[4:])
        elif line.startswith("NEW "):
            rec["new"] = {} if line.endswith(" missing") else _kv(line[4:])
        elif line.startswith("HIT_OLD "):
            rec["hit_old"].append(line[8:])
        elif line.startswith("HIT_NEW "):
            rec["hit_new"].append(line[8:])
        elif line.startswith("REPLAY_HIT "):
            _tag, name, msg = line.split(" ", 2)
            pending.setdefault(name, []).append(msg)
        elif line.startswith("REPLAY "):
            _tag, name, base, new, viol = line.split()
            rec["replay"].append({"name": name, "base": base, "new": new, "viol": int(viol), "hits": []})
    for row in rec["replay"]:
        row["hits"] = pending.get(row["name"], [])
    return rec


def fmt_plan(m: dict) -> str:
    if not m or m.get("missing"):
        return "内核无输出"
    return f"柜 {m.get('containers', '?')}（{m.get('mix', '?')}） 运费 {m.get('cost', '?')} 未装 {m.get('unplaced', '?')}"


def rules_lines(rec: dict) -> list[str]:
    lines = [
        "规则热替换",
        f"订单 {rec['order']}",
        f"基线 {rec['base_rules']}",
        f"  {fmt_plan(rec['old'])}",
        f"换成 {rec['new_rules']}",
    ]
    if rec["hit_old"]:
        lines.append("  旧方案被拒绝")
        lines.extend(f"  {hit}" for hit in rec["hit_old"])
    else:
        lines.append("  旧方案仍满足新规则")
    if rec["hit_new"] or not rec["new"]:
        lines.append("  新方案被拒绝" if rec["hit_new"] else "  新方案 内核无输出")
        lines.extend(f"  {hit}" for hit in rec["hit_new"])
    else:
        lines.append(f"  新方案 {fmt_plan(rec['new'])}")
    lines.append("回放历史")
    worse = False
    for row in rec["replay"]:
        lines.append(f"  {row['name']}  运费 {row['base']}→{row['new']}  新规则违例 {row['viol']}")
        for hit in row["hits"]:
            lines.append(f"    {hit}")
            worse = True
        if row["viol"]:
            worse = True
    if worse or rec["hit_new"]:
        lines.append("新违规见上面列出的行。")
    else:
        lines.append("回放：新规则下重解后没有新的规则违例。安全底线没有放松。")
    return lines


def present_rules(rec: dict, out: str):
    lines = rules_lines(rec)
    print("\n".join(lines))
    body = ["# 规则热替换", ""]
    if rec["args"]:
        body.append(f"传给内核（没有重编译）：`{rec['args']}`")
        body.append("")
    body.extend(lines[1:])
    body.append("")
    body.append(f"解释文件：{out}/explain.md")
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "explain.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"解释 {out}/explain.md")


def local_record(base_rules, new_rules, base_path, new_path, order, hist, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    lines = ["FLOOR ok", f"ARGS {ruleset.kernel_args(new_rules)}", f"ORDER {order}", f"BASE_RULES {base_path}", f"NEW_RULES {new_path}"]
    old = _pack(order, base_rules, out / "old.json")
    new = _pack(order, new_rules, out / "new.json")
    lines.append(_metric("OLD", old))
    lines.append(_metric("NEW", new))
    for hit in ruleset.check_plan(new_rules, old) if old else ["内核无输出"]:
        lines.append(f"HIT_OLD {hit}")
    for hit in ruleset.check_plan(new_rules, new) if new else ["内核无输出"]:
        lines.append(f"HIT_NEW {hit}")
    for hpath in hist.split():
        name = Path(hpath).name
        b = _pack(hpath, base_rules, out / f"hist-base-{name}.json")
        n = _pack(hpath, new_rules, out / f"hist-new-{name}.json")
        hits = ruleset.check_plan(new_rules, n) if n else ["内核无输出"]
        lines.append(f"REPLAY {name} {_cost(b)} {_cost(n)} {len(hits)}")
        for hit in hits:
            lines.append(f"REPLAY_HIT {name} {hit}")
    (out / "record.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "explain.md").write_text(
        "# 规则热替换\n\n" + "\n".join(lines) + "\n\n旧方案按新规则复核；新方案和历史回放都用同一份规则文件。\n",
        encoding="utf-8",
    )
    return parse_record("\n".join(lines))


def _pack(problem, rules, dest: Path):
    result = ruleset.pack(problem, rules, dest, ruleset.FAST)
    if result.plan is None or result.code not in (0, 3):
        err = (result.stderr or result.stdout).strip()
        kind = "规则" if err.startswith("参数 ") else "内核"
        die(kind, err or f"build/pack 退出码 {result.code}（{problem}）", 2 if kind == "规则" else 4)
    return result.plan


def _cost(plan) -> str:
    if not plan:
        return "-"
    return str(ruleset._r3(float((plan.get("metrics") or {}).get("cost", 0))))


def _metric(tag: str, plan) -> str:
    if not plan:
        return f"{tag} missing"
    m = plan.get("metrics") or {}
    return f"{tag} containers={m.get('containers', '?')} mix={m.get('mix', '?')} cost={_cost(plan)} unplaced={m.get('unplaced', '?')}"


def check_verify(rec: dict, out: Path):
    old_ok, old_msg = verify(out / "old.json")
    print("独立校验 verify.py（越界、重叠、超重、支撑、先卸后装）")
    print(f"  旧方案 {'通过' if old_ok else old_msg}")
    if not old_ok:
        die("校验", f"基线方案没有通过 verify.py：{old_msg}", 3)
    new_path = out / "new.json"
    if new_path.is_file():
        new_ok, new_msg = verify(new_path)
        print(f"  新方案 {'通过' if new_ok else new_msg}")
        if not rec["hit_new"] and not new_ok:
            die("校验", f"新方案没有通过 verify.py：{new_msg}", 3)
    for row in rec["replay"]:
        path = out / f"hist-new-{row['name']}.json"
        if not path.is_file():
            continue
        ok, msg = verify(path)
        print(f"  回放 {row['name']} {'通过' if ok else msg}")
        if row["viol"] == 0 and not ok:
            die("校验", f"回放 {row['name']} 没有通过 verify.py：{msg}", 3)


def agree(label: str, aura_hits: list[str], py_hits: list[str]):
    if set(aura_hits) != set(py_hits):
        die(
            "校验",
            f"{label} 的规则命中不一致。\n  Aura：{aura_hits or '（无）'}\n  本地：{py_hits or '（无）'}",
            3,
        )


def cmd_rules(no_aura: bool):
    base_path = os.environ.get("PC_RULES_BASE") or "rules/baseline.sexp"
    new_path = os.environ.get("PC_RULES") or "rules/routes/sha-ams.sexp"
    order = os.environ.get("PC_ORDER") or "examples/rules-demo/order.txt"
    hist = os.environ.get("PC_HISTORY") or "examples/rules-demo/hist/only-carton.txt examples/rules-demo/hist/mixed.txt"
    out = Path(os.environ.get("PC_OUT") or "out/rules-demo")
    t0 = time.perf_counter()
    base_rules = load_rules(base_path)
    new_rules = load_rules(new_path)
    issues = ruleset.floor_issues(new_rules)
    if issues:
        die("规则", "热替换已拒绝，内核没有用这份规则重解。\n" + "\n".join(issues), 2)
    diff = ruleset.changes(base_rules, new_rules)
    print(f"规则文件 {new_path}")
    if diff:
        for line in diff:
            print(f"  {line}")
    else:
        print("  和基线相同")
    print("安全底线 通过（lifo ≥ 1，支撑率 ≥ 0.75，危险品间距 ≥ 1000）")
    compile_kernel()
    stamp = binary_mtime()
    if no_aura:
        rec = local_record(base_rules, new_rules, base_path, new_path, order, hist, out)
    else:
        env = aura_env(
            {
                "PC_RULES_BASE": base_path,
                "PC_RULES": new_path,
                "PC_ORDER": order,
                "PC_HISTORY": hist,
                "PC_OUT": str(out),
                "PC_TIME_MS": os.environ.get("PC_TIME_MS") or "200",
            }
        )
        log = run_aura("aura/rules-main.aura", env, out / "aura.log")
        record_path = out / "record.txt"
        if not record_path.is_file():
            die("Aura", f"没有写出 {record_path}", 5)
        rec = parse_record(record_path.read_text(encoding="utf-8"))
        if "@@done=refused" in log or rec["floor"] == "bad":
            die("规则", rec["floor_msg"] or "Aura 拒绝了这份规则", 2)
        if not ruleset.same_args(rec["args"], ruleset.kernel_args(new_rules)):
            die(
                "规则",
                f"Aura 传给内核的参数和文件解析不一致。\n  文件：{ruleset.kernel_args(new_rules)}\n  Aura：{rec['args']}",
                2,
            )
        old_plan = json.loads((out / "old.json").read_text(encoding="utf-8"))
        new_plan = json.loads((out / "new.json").read_text(encoding="utf-8"))
        agree("旧方案", rec["hit_old"], ruleset.check_plan(new_rules, old_plan))
        agree("新方案", rec["hit_new"], ruleset.check_plan(new_rules, new_plan))
    if binary_mtime() != stamp:
        die("内核", "换规则时 build/pack 被重新编译了", 4)
    print()
    present_rules(rec, str(out))
    print("内核 build/pack 未重编译")
    check_verify(rec, out)
    print(f"用时 {time.perf_counter() - t0:.1f}s")


def present_gate(rows: list[dict], out: str):
    print("安全演化")
    print("每个候选在自己的 overlay 里回放。门禁不过就 ROLLBACK，通过才 KEEP。")
    print()
    md = [
        "# 安全演化",
        "",
        "每个候选在自己的 overlay 里回放。门禁不过就 ROLLBACK，通过才 KEEP。",
        "放松先卸后装、压缩、倒放即使运费不变，也必须 ROLLBACK。",
        "",
    ]
    for row in rows:
        print(f"{row['decision']}  {row['change']}")
        print(f"          运费 {row['cost_before']}→{row['cost_after']}  违例 {row['viol_before']}→{row['viol_after']}")
        print(f"          门禁：{row['reason']}")
        print(f"          overlay：{row['overlay']}")
        print()
        md.append(f"- **{row['decision']}** {row['change']}")
        md.append(f"  - 运费 {row['cost_before']}→{row['cost_after']}，违例 {row['viol_before']}→{row['viol_after']}")
        md.append(f"  - 门禁：{row['reason']}")
        md.append(f"  - overlay：{row['overlay']}")
    md.append("")
    md.append(f"审计：{out}/evolve-audit.tsv")
    (Path(out) / "explain.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"审计 {out}/evolve-audit.tsv")
    print(f"解释 {out}/explain.md")


def read_audit(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        rows.append(dict(zip(header, cols)))
    return rows


def cmd_evolve():
    t0 = time.perf_counter()
    compile_kernel()
    out = Path(os.environ.get("PC_OUT") or "out/evolve-demo")
    order = os.environ.get("PC_ORDERS") or "examples/rules-demo/order.txt"
    env = aura_env(
        {
            "PC_ORDERS": order,
            "PC_OUT": str(out),
            "PC_TIME_MS": os.environ.get("PC_TIME_MS") or "200",
            "PC_EXTRA": os.environ.get("PC_EXTRA") or "",
        }
    )
    run_aura("aura/gate-main.aura", env, out / "aura.log")
    audit = out / "evolve-audit.tsv"
    if not audit.is_file():
        die("Aura", f"没有写出 {audit}", 5)
    rows = read_audit(audit)
    present_gate(rows, str(out))
    text = audit.read_text(encoding="utf-8")
    missing = []
    for needle in ("关闭先卸后装", "压缩容差", "允许倒放", "门端载荷"):
        if needle not in text:
            missing.append(needle)
    if missing:
        die("Aura", "审计里缺了候选：" + "、".join(missing), 5)
    if "KEEP" not in text or "ROLLBACK" not in text:
        die("Aura", "审计里应该同时有 KEEP 和 ROLLBACK", 5)
    print(f"用时 {time.perf_counter() - t0:.1f}s")


def cmd_agents():
    t0 = time.perf_counter()
    compile_kernel()
    out = Path(os.environ.get("PC_OUT") or "out/agents-demo")
    orders = os.environ.get("PC_ORDERS") or "examples/synthetic/order_01.txt"
    env = aura_env(
        {
            "PC_ORDERS": orders,
            "PC_OUT": str(out),
            "PC_TIME_MS": os.environ.get("PC_TIME_MS") or "500",
            "PC_EXTRA": os.environ.get("PC_EXTRA") or "width=1 noise=0",
            "PC_DISPATCH": os.environ.get("PC_DISPATCH") or "0",
        }
    )
    log = run_aura("aura/main.aura", env, out / "aura.log")
    shown = []
    for line in log.splitlines():
        s = line.rstrip()
        t = s.strip()
        if t.startswith("@@done"):
            continue
        if t.startswith("订单 ") or t.startswith("胜者 ") or t.startswith("解释 ") or t.startswith("败者已"):
            shown.append(t)
        elif line.startswith("  ") and ("柜" in t or t.startswith("否决") or "  " in line):
            shown.append(s)
    if not any(x.startswith("胜者 ") for x in shown):
        tail = "\n".join(log.strip().splitlines()[-30:])
        die("Aura", f"协调器没有打出胜者。日志 {out / 'aura.log'}\n{tail}", 5)
    print("多 Agent")
    print("每个构造思路一个 fiber。胜者 commit，其余 rollback。")
    print()
    print("\n".join(shown))
    explain = out / "explain.md"
    if not explain.is_file():
        die("Aura", f"没有写出 {explain}", 5)
    print(f"用时 {time.perf_counter() - t0:.1f}s")


def main(argv: list[str]):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        raise SystemExit(0 if argv else 2)
    cmd, args = argv[0], argv[1:]
    if cmd == "rules":
        if any(a not in ("--no-aura",) for a in args):
            die("规则", "rules 只接受 --no-aura", 2)
        cmd_rules("--no-aura" in args)
    elif cmd == "evolve":
        if args:
            die("规则", "evolve 不接受参数", 2)
        cmd_evolve()
    elif cmd == "agents":
        if args:
            die("规则", "agents 不接受参数", 2)
        cmd_agents()
    else:
        die("规则", f"未知命令 {cmd}。可用：rules、evolve、agents", 2)


if __name__ == "__main__":
    main(sys.argv[1:])
