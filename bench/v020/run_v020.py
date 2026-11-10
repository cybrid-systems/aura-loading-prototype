#!/usr/bin/env python3
"""Repeatable Aura v0.2.0 probes for aura-loading-prototype.

Writes a JSON report under out/v020/ and a short text summary on stdout.
Exit 0 when every probe that must succeed did. A probe that is documenting
a known failure mode is marked expect=defect and does not fail the run
when the defect is still present.

Requires AURA_BIN (the v0.2.0 launcher). Does not download a toolchain.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent / "probes"
REPRO = ROOT / "repro" / "v020"
OUT = ROOT / "out" / "v020"


def aura_bin() -> str:
    env = os.environ.get("AURA_BIN")
    if env and Path(env).is_file():
        return env
    sys.exit("AURA_BIN is not set to an Aura launcher. Refusing to guess a toolchain.")


def base_env() -> dict:
    env = os.environ.copy()
    env["AURA_SANDBOX"] = "off"
    env["AURA_PIPELINE_STRICT"] = "0"
    lib = os.environ.get("AURA_LIB") or os.environ.get("AURA_PATH")
    if lib:
        env["AURA_LIB"] = lib.split(":")[0]
        env["AURA_PATH"] = lib
    return env


def parse_at(text: str) -> dict:
    got = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("@@") and "=" in line:
            k, v = line[2:].split("=", 1)
            got[k] = v
    return got


def rss_kb(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def run_aura(src: Path, timeout: float, extra_args: list[str] | None = None,
             env_extra: dict | None = None, sample_rss: bool = False) -> dict:
    env = base_env()
    if env_extra:
        env.update(env_extra)
    # --worker-threads before --load is rejected ("unknown option --load").
    cmd = [aura_bin(), "--load", str(src), *(extra_args or [])]
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    samples = []
    try:
        if sample_rss:
            while True:
                try:
                    out, err = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    cur = rss_kb(proc.pid)
                    if cur:
                        samples.append(cur)
                    if time.perf_counter() - t0 > timeout:
                        proc.kill()
                        out, err = proc.communicate()
                        wall = (time.perf_counter() - t0) * 1000
                        return {"rc": -9, "wall_ms": round(wall, 1), "stdout": out or "",
                                "stderr": err or "", "at": parse_at((out or "") + "\n" + (err or "")),
                                "rss_kb": samples, "timeout": True}
        else:
            out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        wall = (time.perf_counter() - t0) * 1000
        return {"rc": -9, "wall_ms": round(wall, 1), "stdout": out or "", "stderr": err or "",
                "at": parse_at((out or "") + "\n" + (err or "")), "rss_kb": samples, "timeout": True}
    wall = (time.perf_counter() - t0) * 1000
    text = (out or "") + "\n" + (err or "")
    return {"rc": proc.returncode, "wall_ms": round(wall, 1), "stdout": out or "",
            "stderr": err or "", "at": parse_at(text), "rss_kb": samples, "timeout": False}


def concat(parts: list[Path], dest: Path) -> Path:
    dest.write_text("\n".join(p.read_text() for p in parts))
    return dest


def verdict(row: dict) -> str:
    expect = row["expect"]
    if row.get("timeout"):
        return "timeout" if expect != "timeout" else "present"
    if expect == "ok":
        return "pass" if row["rc"] == 0 and row["at"].get("status") in ("ok", "ran", None) and row["rc"] == 0 else "fail"
    if expect == "defect":
        return "present"
    if expect == "timeout":
        return "absent"
    return "pass" if row["rc"] == 0 else "fail"


def main() -> int:
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "io.txt").write_text("")
    (REPRO / "small.json").write_text('{"a":[1,2,3],"b":{"c":4},"name":"box"}')
    ver = subprocess.run([aura_bin(), "--version"], cwd=ROOT, env=base_env(),
                         capture_output=True, text=True)
    version = (ver.stdout or ver.stderr).strip()
    rows = []

    def add(name, src, timeout, expect="ok", args=None, env=None, rss=False, note=""):
        if only and name not in only:
            return
        res = run_aura(Path(src), timeout, args, env, rss)
        res.update(name=name, expect=expect, note=note, src=str(src))
        res["result"] = verdict(res)
        # Keep stdout small in the JSON when it is huge.
        if len(res["stdout"]) > 8000:
            res["stdout"] = res["stdout"][:4000] + "\n…\n" + res["stdout"][-2000:]
        if len(res["stderr"]) > 4000:
            res["stderr"] = res["stderr"][-4000:]
        rows.append(res)
        print(f"{res['result']:8} {name:28} rc={res['rc']} {res['wall_ms']:8.1f} ms  {res['at'].get('status','')}", flush=True)

    rules = concat([ROOT / "aura" / "rules.aura", PROBE / "rule_hot_tail.aura"], OUT / "rule_hot.aura")

    cases = [
        ("stdlib-core", PROBE / "stdlib_core.aura", 30, "ok"),
        ("set-cons-shadow", REPRO / "set_cons_shadow.aura", 20, "ok"),
        ("catch-capture", REPRO / "catch_capture.aura", 20, "ok"),
        ("json-parse-fibers", REPRO / "json_parse_small.aura", 30, "ok"),
        ("fiber-correct", PROBE / "fiber_correct.aura", 20, "ok"),
        ("fiber-race", PROBE / "fiber_race.aura", 20, "ok"),
        ("hash-fiber-keys", REPRO / "hash_fiber_keys.aura", 60, "ok"),
        ("orch-flow", PROBE / "orch_flow.aura", 20, "ok"),
        ("orch-timeout", REPRO / "orch_parallel_timeout.aura", 8, "timeout"),
        ("obs-metrics", PROBE / "obs_metrics.aura", 30, "ok"),
        ("stats-export", REPRO / "stats_export.aura", 20, "ok"),
        ("incr-rebind", PROBE / "incr_rebind.aura", 60, "ok"),
        ("evo-select", PROBE / "evo_select.aura", 30, "ok"),
        ("rule-hot", rules, 60, "ok"),
        ("coord-hot", PROBE / "coord_hot.aura", 60, "ok"),
    ]
    for name, src, timeout, expect in cases:
        env = {"IO_PATH": str(OUT / "io.txt"), "JSON_PATH": str(REPRO / "small.json")}
        args = ["--preset", "dev"] if name == "incr-rebind" else None
        add(name, src, timeout, expect, args, env)

    # Fiber scaling. CLI backend ignores a worker cap if the curve does not move.
    for n in (1, 2, 4, 8, 16, 32):
        add(f"scale-n{n}", PROBE / "fiber_scale.aura", 60, "ok",
            env={"FIBER_N": str(n), "FIBER_WORK": "150000"})
    for workers in (1, 4):
        add(f"scale-workers{workers}", PROBE / "fiber_scale.aura", 60, "ok",
            ["--worker-threads", str(workers)],
            {"FIBER_N": "16", "FIBER_WORK": "150000"})

    add("soak", PROBE / "fiber_soak.aura", 70, "ok",
        env={"SOAK_S": "20", "FIBER_N": "16"}, rss=True)

    # C++ baseline, same shapes.
    cxx = shutil.which(os.environ.get("CXX", "g++")) or shutil.which("g++")
    cpp = {"built": False}
    if only and "cpp" not in only:
        cxx = None
    if not cxx:
        cpp["error"] = "g++ not found"
    else:
        bin_path = OUT / "cpp_baseline"
        cmd = [cxx, "-O2", "-std=c++20", "-o", str(bin_path), str(Path(__file__).parent / "cpp_baseline.cpp")]
        b = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        cpp["built"] = b.returncode == 0
        cpp["compiler"] = cxx
        cpp["stderr"] = b.stderr[-500:]
        if b.returncode == 0:
            for mode, args in (
                ("spin", ["spin", "150000"]),
                ("threads", ["threads", "150000", "8"]),
                ("check", ["check", "0", "0", "4000000"]),
                ("coord", ["coord", "0", "8"]),
            ):
                t0 = time.perf_counter()
                r = subprocess.run([str(bin_path), *args], cwd=ROOT, capture_output=True, text=True)
                cpp[mode] = {"rc": r.returncode, "wall_ms": round((time.perf_counter() - t0) * 1000, 3),
                             "at": parse_at(r.stdout), "stdout": r.stdout}
                print(f"{'cpp':8} {mode:28} rc={r.returncode} {cpp[mode]['wall_ms']:8.1f} ms", flush=True)

    cli_order = None
    if not only or "cli-worker-order" in only:
        bad = subprocess.run(
            [aura_bin(), "--worker-threads", "1", "--load", str(PROBE / "fiber_scale.aura")],
            cwd=ROOT, env={**base_env(), "FIBER_N": "1", "FIBER_WORK": "1"},
            capture_output=True, text=True, timeout=20)
        cli_order = {"rc": bad.returncode, "stderr": (bad.stderr or "")[-600:],
                     "stdout": (bad.stdout or "")[-300:]}
        print(f"{'cli':8} {'worker-then-load':28} rc={bad.returncode}", flush=True)

    # Cold process vs in-process rebind: one full 40-define load.
    cold_src = OUT / "cold40.aura"
    bodies = " ".join(f"(define (f{i} x) (+ x {i}))" for i in range(40))
    cold_src.write_text(bodies + "\n(display (f0 1))\n(newline)\n")
    cold = []
    for _ in range(5):
        cold.append(run_aura(cold_src, 30, ["--preset", "dev"]))
    cpp_note = {"cold_load_ms": [c["wall_ms"] for c in cold]}

    report = {
        "aura_version": version,
        "aura_bin": aura_bin(),
        "rows": rows,
        "cpp": cpp,
        "cold_load": cpp_note,
        "cli_worker_order": cli_order,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str))
    failed = [r for r in rows if r["expect"] == "ok" and r["result"] != "pass"]
    print(f"@@report {OUT / 'report.json'}")
    print(f"@@failed {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
