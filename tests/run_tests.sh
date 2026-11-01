#!/usr/bin/env bash
# 端到端测试（只用合成数据）。需在 Aura dev 镜像内运行，AURA_BIN 指向 aura 可执行文件。
set -euo pipefail
cd "$(dirname "$0")/.."
J=${J:-$(nproc)}
mkdir -p out/test
python3 build.py
python3 tools/gen_synthetic.py --orders 4 --seed 101 --out out/test/orders >/dev/null
fail=0
# 1) kernel: every plan must pass the independent checker
ls out/test/orders/*.txt | xargs -P "$J" -I{} sh -c 'build/pack --in {} --out {}.json time_ms=1500 min_support=0.75 lifo=1 hazmat_sep=1000 >/dev/null'
ls out/test/orders/*.txt | xargs -P "$J" -I{} sh -c 'build/pack --in {} --out {}.block.json algo=block space=0 w_vol=1 w_yz=0.5 time_ms=1500 min_support=0.75 lifo=1 hazmat_sep=1000 >/dev/null'
for f in out/test/orders/*.txt; do
  if python3 tools/verify.py "$f.json" >/dev/null; then echo "ok   kernel-feasible $(basename "$f")"; else echo "FAIL kernel-feasible $(basename "$f")"; fail=1; fi
  if python3 tools/verify.py "$f.block.json" >/dev/null; then echo "ok   block-feasible $(basename "$f")"; else echo "FAIL block-feasible $(basename "$f")"; fail=1; fi
done
# 2) known answer: 8 boxes of 1000^3 into a 20GP-like 2000x2000x2000 bin = exactly 1 bin, 100% volume
cat > out/test/cube.txt <<'P'
C BOX 2000 2000 2000 10000 1 -1
I c c 1000 1000 1000 10 8 1 1e9 0 1 -
P
build/pack --in out/test/cube.txt --out out/test/cube.json iters=0 | grep -q "containers=1 .*vol_util=1.0000" && echo "ok   kernel-cube" || { echo "FAIL kernel-cube"; fail=1; }
for sp in 0 1 2; do
  build/pack --in out/test/cube.txt --out out/test/cube-b$sp.json algo=block space=$sp | grep -q "containers=1 .*vol_util=1.0000" && echo "ok   block-cube space=$sp" || { echo "FAIL block-cube space=$sp"; fail=1; }
done
# 2b) lookahead: 1670 high = 3x350 + 2x310 exactly, but either pure stack leaves a gap.
#     greedy (width=1) stacks one size and stops short; the lookahead search (width=4) must find the mixed column
cat > out/test/col.txt <<'P'
C SLOT 600 600 1670 10000 1 -1
I a a 600 600 350 10 10 2 1e9 0 1 -
I b b 600 600 310 10 10 2 1e9 0 1 -
P
g1=$(build/pack --in out/test/col.txt --out out/test/col1.json algo=block only=SLOT maxbins=1 width=1 noise=0 time_ms=1 || true)
g4=$(build/pack --in out/test/col.txt --out out/test/col4.json algo=block only=SLOT maxbins=1 width=4 noise=0 time_ms=1 || true)
if echo "$g4" | grep -q "vol_util=1.0000" && ! echo "$g1" | grep -q "vol_util=1.0000"; then echo "ok   block-lookahead-column"; else echo "FAIL block-lookahead-column"; fail=1; fi
# 2c) squeeze / anyrot are flagged in the metrics (never mixed up with rigid results)
build/pack --in out/test/cube.txt --out out/test/sq.json algo=block squeeze=0.02 >/dev/null
python3 -c "import json; m=json.load(open('out/test/sq.json'))['metrics']; assert m['squeeze']==0.02 and m['algo']=='block'" && echo "ok   block-squeeze-flag" || { echo "FAIL block-squeeze-flag"; fail=1; }
# 3) LIFO: stop-1 boxes must end up nearer the door than stop-2 boxes in the same row
cat > out/test/lifo.txt <<'P'
C BOX 4000 1000 1000 10000 1 -1
I a a 1000 1000 1000 10 2 2 1e9 0 1 -
I b b 1000 1000 1000 10 2 2 1e9 0 2 -
P
for a in ep block; do
build/pack --in out/test/lifo.txt --out out/test/lifo-$a.json iters=0 cog_shift=0 algo=$a >/dev/null
python3 - $a <<'PY' && echo "ok   kernel-lifo $a" || { echo "FAIL kernel-lifo $a"; fail=1; }
import json, sys; b = json.load(open(f"out/test/lifo-{sys.argv[1]}.json"))["containers"][0]["boxes"]
s1 = min(x["x"] for x in b if x["stop"] == 1); s2 = max(x["x"] for x in b if x["stop"] == 2)
assert s1 > s2, (s1, s2)
PY
done
# 3b) importer: forwarder loading-manifest layout (container label above the header, 件数/实重/方数 are line totals,
#     carton size in one "a×b×c cm" column, continuation lines without 件数). Fake values only.
mkdir -p out/test/manifest
cat > out/test/manifest/m.csv <<'P'
柜号,TEST-1,,,,
装柜开始时间,,,装柜结束时间,,
服务商单号,件数,实重,方数,货品尺寸,中文品名
T001,10,100,0.6,50×40×30cm,甲
,,,,,乙
T002,4,80,1.2,超大件,丙
P
PEICANG_DATA=out/test/manifest python3 tools/import_xlsx.py convert --out out/test/manifest-out --existing-type 45HC --est-dims >/dev/null
python3 - <<'PY' && echo "ok   import-manifest" || { echo "FAIL import-manifest"; fail=1; }
import json; r = [x for x in json.load(open("out/test/manifest-out/import_report.json")) if "file" in x]
assert len(r) == 1 and r[0]["group"] == "sheet" and r[0]["boxes"] == 14, r
assert r[0]["existing_containers"] == 1 and r[0]["existing_types"] == ["45HC"] and r[0]["boxes_dims_estimated"] == 4, r
I = [l.split() for l in open("out/test/manifest-out/" + r[0]["file"]) if l.startswith("I ")]
assert I[0][3:8] == ["500", "400", "300", "10.0", "10"], I[0]   # cm -> mm, line weight / 件数
PY
# 4) Aura coordinator: one winner commits, the rest roll back, report written
PC_TIME_MS=1500 PC_ORDERS="$(ls out/test/orders/*.txt | head -2 | tr '\n' ' ')" PC_OUT=out/test/aura \
  script -qc "scripts/aura.sh aura/main.aura" /dev/null > out/test/aura.log 2>&1 || true
if grep -q "@@done=ok" out/test/aura.log && [ "$(grep -o 'committed' out/test/aura/explain.md | wc -l)" = 2 ]; then echo "ok   aura-coordinator"; else echo "FAIL aura-coordinator"; fail=1; fi
# 5) Aura evolution: harmful-but-legal change (LIFO off) must be rolled back
printf 'damage_rate 0.05\n' > out/test/fb.txt
PC_TIME_MS=1000 PC_ORDERS="$(ls out/test/orders/*.txt | head -2 | tr '\n' ' ')" PC_FEEDBACK=out/test/fb.txt PC_OUT=out/test/evo \
  script -qc "scripts/aura.sh aura/evolve-main.aura" /dev/null > out/test/evo.log 2>&1 || true
if grep -q "关闭先卸后装.*ROLLBACK.*安全底线" out/test/evo/evolve-audit.tsv && grep -q "lifo=1" out/test/evo/evolved.txt; then echo "ok   aura-evolve-gate"; else echo "FAIL aura-evolve-gate"; fail=1; fi
# 6) Aura tuning loop: rigid floor (squeeze / anyrot) must be rolled back even though it raises utilization
PC_TUNE_EXTRA="only=45HC maxbins=1 width=1 noise=0 time_ms=600000" PC_GENS=1 PC_TRAIN="$(ls out/test/orders/*.txt | head -2 | tr '\n' ' ')" PC_OUT=out/test/tune \
  script -qc "scripts/aura.sh aura/tune-main.aura" /dev/null > out/test/tune.log 2>&1 || true
if grep -q "压缩容差.*ROLLBACK.*刚性底线" out/test/tune/tune-audit.tsv && grep -q "允许倒放.*ROLLBACK.*刚性底线" out/test/tune/tune-audit.tsv \
   && grep -q "squeeze=0 anyrot=0" out/test/tune/tune-summary.txt; then echo "ok   aura-tune-gate"; else echo "FAIL aura-tune-gate"; fail=1; fi
# 7) tuned strategies and a custom rule file load back into the coordinator (PC_STRATEGIES / PC_RULES)
PC_STRATEGIES=out/test/tune/tuned-strategies.txt PC_RULES=aura/rules-fill.sexp PC_EXTRA="only=45HC maxbins=1" PC_TIME_MS=300 \
  PC_ORDERS="$(ls out/test/orders/*.txt | head -1)" PC_OUT=out/test/tuned script -qc "scripts/aura.sh aura/main.aura" /dev/null > out/test/tuned.log 2>&1 || true
if grep -q "单柜评估" out/test/tuned/explain.md 2>/dev/null || grep -q "采用：\*\*[^#]" out/test/tuned/explain.md 2>/dev/null; then echo "ok   aura-load-tuned"; else echo "FAIL aura-load-tuned"; fail=1; fi
# 8) consolidation known answer: shipments of 2,3,2,1 unit cubes into a 4-cube container.
#    next-fit in arrival order needs 3 containers; the optimum (and the volume bound) is 2 = {2,2},{3,1}
cat > out/test/cons.txt <<'P'
C SLOT4 4000 1000 1000 10000 1 -1
I a.1 a 1000 1000 1000 10 2 2 1e9 0 1 -
I b.1 b 1000 1000 1000 10 3 2 1e9 0 1 -
I c.1 c 1000 1000 1000 10 2 2 1e9 0 1 -
I d.1 d 1000 1000 1000 10 1 2 1e9 0 1 -
P
rm -rf out/test/cons out/test/cons-work
python3 tools/consolidate.py --pool out/test/cons.txt --name K --algo nf --base-type SLOT4 --max-fill 1 --out out/test/cons --work out/test/cons-work -j 2 >/dev/null
python3 tools/consolidate.py --pool out/test/cons.txt --name K --algo lns --base-type SLOT4 --max-fill 1 --time-s 5 --search-ms 200 --out out/test/cons --work out/test/cons-work -j 2 >/dev/null
python3 - <<'PY' && echo "ok   consolidate-known-answer" || { echo "FAIL consolidate-known-answer"; fail=1; }
import json, sys; sys.path.insert(0, "tools"); from verify import check
nf = json.load(open("out/test/cons/K.nf.json")); ln = json.load(open("out/test/cons/K.lns.json"))
assert nf["metrics"]["containers"] == 3 and ln["metrics"]["containers"] == 2 and ln["metrics"]["gap"] == 0.0, (nf["metrics"], ln["metrics"])
for c in ln["containers"]:
    assert not check({"containers": [c], "unplaced": []}), c["shipments"]
assert sorted(s for c in ln["containers"] for s in c["shipments"]) == ["0:a", "0:b", "0:c", "0:d"]
PY
# 8b) consolidation on a small synthetic route: LNS never worse than next-fit, every shipment exactly once
python3 tools/gen_pool.py --routes 1 --seed 5 --scale 0.3 --out out/test/pool >/dev/null
for al in nf lns; do python3 tools/consolidate.py --groups out/test/pool/pools.json --algo $al --time-s 8 --search-ms 300 --out out/test/pool-out --work out/test/pool-work -j "$J" >/dev/null; done
python3 - <<'PY' && echo "ok   consolidate-synthetic" || { echo "FAIL consolidate-synthetic"; fail=1; }
import json; nf = json.load(open("out/test/pool-out/R1.nf.json"))["metrics"]; ln = json.load(open("out/test/pool-out/R1.lns.json"))["metrics"]
assert ln["cost"] <= nf["cost"] + 1e-9 and ln["cost"] >= ln["lb_cost"] - 1e-9, (nf, ln)
PY
# 9) PK harness: our own plan is executable; a plan with a missing box and a box laid on its side is not
f=$(ls out/test/orders/*.txt | head -1); b=$(basename "$f" .txt); rm -rf out/test/pk; mkdir -p out/test/pk/bad
python3 tools/pk.py --problems "$f" --ours-ms 300 --ours-dir out/test/pk/ours --json out/test/pk/a.json >/dev/null
python3 - "$b" <<'PY'
import json, sys; r = json.load(open(f"out/test/pk/ours/{sys.argv[1]}.json")); bs = r["containers"][0]["boxes"]; bs.pop()
up = next(x for x in bs if x["dx"] != x["dz"]); up["dx"], up["dz"] = up["dz"], up["dx"]
json.dump(r, open(f"out/test/pk/bad/{sys.argv[1]}.json", "w"))
PY
python3 tools/pk.py --problems "$f" --plans ours=out/test/pk/ours bad=out/test/pk/bad --json out/test/pk/b.json >/dev/null
python3 - <<'PY' && echo "ok   pk-harness" || { echo "FAIL pk-harness"; fail=1; }
import json; d = json.load(open("out/test/pk/b.json"))["detail"]
assert d["ours"][0]["ok"], d["ours"][0]["errors"]
e = " ".join(d["bad"][0]["errors"]) + " " + str(d["bad"][0]["n_errors"])
assert not d["bad"][0]["ok"] and "placed" in json.dumps(d["bad"]) and ("upright" in json.dumps(d["bad"]) or "overlap" in e or "bounds" in e), d["bad"]
PY
# 10) feature-based agent dispatch: 40+ carton types -> the fit-gap specialist replaces the block agent (same agent count)
python3 - <<'PY'
import sys; sys.path.insert(0, "tools"); import containers, problem
problem.write("out/test/many.txt", [dict(id=f"t{k}", l=300 + 7 * k, w=250 + 3 * k, h=200 + 5 * k, kg=5, qty=2, rot=1) for k in range(42)], containers.load())
PY
PC_TIME_MS=200 PC_ORDERS="out/test/many.txt" PC_OUT=out/test/disp script -qc "scripts/aura.sh aura/main.aura" /dev/null > out/test/disp.log 2>&1 || true
if grep -q "派发：箱规" out/test/disp/explain.md && [ "$(grep -o 'committed\|rolled-back' out/test/disp/explain.md | wc -l)" = 4 ] && grep -q "拼缝" out/test/disp/explain.md; then echo "ok   aura-dispatch"; else echo "FAIL aura-dispatch"; fail=1; fi
python3 - <<'PY' && echo "ok   dispatch-rules-in-sync" || { echo "FAIL dispatch-rules-in-sync"; fail=1; }
import re, sys; sys.path.insert(0, "tools"); import agent_matrix as am
src = open("aura/strategies.aura", encoding="utf-8").read()
got = [(f, op, float(th), o, n) for f, op, th, o, n in re.findall(r"\(dispatch (\w+)\s+(>=|>|<=|<)\s+([\d.]+)\s+(\w+) (\w+)", src)]
assert got == [(f, op, float(th), o, n) for f, op, th, o, n in am.DISPATCH], got
for g in am.AGENTS: assert g in ("wall", "layer", "block", "human") or f"(specialist {g} " in src, g
PY
# 11) Aura consolidation agents: each agent in its own overlay, the cheapest plan that passes the site rules commits
printf '{"K": ["out/test/cons.txt"]}' > out/test/cons-groups.json
PC_CONS_GROUPS=out/test/cons-groups.json PC_OUT=out/test/cons-aura PC_CONS_TIME_S=3 PC_CONS_EXTRA="--base-type SLOT4 --max-fill 1 --search-ms 200" \
  script -qc "scripts/aura.sh aura/consolidate-main.aura" /dev/null > out/test/cons-aura.log 2>&1 || true
if grep -q "@@done=ok" out/test/cons-aura.log && grep -q "committed" out/test/cons-aura/explain.md && grep -q "rolled-back" out/test/cons-aura/explain.md \
   && awk -F'\t' '$3==2' out/test/cons-aura/cons-summary.tsv | grep -q K; then echo "ok   aura-consolidate"; else echo "FAIL aura-consolidate"; fail=1; fi
exit $fail
