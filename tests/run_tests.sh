#!/usr/bin/env bash
# 端到端测试（只用合成数据）。需在 Aura dev 镜像内运行，AURA_BIN 指向 aura 可执行文件。
set -euo pipefail
cd "$(dirname "$0")/.."
J=${J:-$(nproc)}
mkdir -p build out/test
g++ -O2 -std=c++20 -Wall -Werror -o build/pack kernel/pack.cpp
python3 tools/gen_synthetic.py --orders 4 --seed 101 --out out/test/orders >/dev/null
fail=0
# 1) kernel: every plan must pass the independent checker
ls out/test/orders/*.txt | xargs -P "$J" -I{} sh -c 'build/pack --in {} --out {}.json time_ms=1500 min_support=0.75 lifo=1 hazmat_sep=1000 >/dev/null'
for f in out/test/orders/*.txt; do
  if python3 tools/verify.py "$f.json" >/dev/null; then echo "ok   kernel-feasible $(basename "$f")"; else echo "FAIL kernel-feasible $(basename "$f")"; fail=1; fi
done
# 2) known answer: 8 boxes of 1000^3 into a 20GP-like 2000x2000x2000 bin = exactly 1 bin, 100% volume
cat > out/test/cube.txt <<'P'
C BOX 2000 2000 2000 10000 1 -1
I c c 1000 1000 1000 10 8 1 1e9 0 1 -
P
build/pack --in out/test/cube.txt --out out/test/cube.json iters=0 | grep -q "containers=1 .*vol_util=1.0000" && echo "ok   kernel-cube" || { echo "FAIL kernel-cube"; fail=1; }
# 3) LIFO: stop-1 boxes must end up nearer the door than stop-2 boxes in the same row
cat > out/test/lifo.txt <<'P'
C BOX 4000 1000 1000 10000 1 -1
I a a 1000 1000 1000 10 2 2 1e9 0 1 -
I b b 1000 1000 1000 10 2 2 1e9 0 2 -
P
build/pack --in out/test/lifo.txt --out out/test/lifo.json iters=0 cog_shift=0 >/dev/null
python3 - <<'PY' && echo "ok   kernel-lifo" || { echo "FAIL kernel-lifo"; fail=1; }
import json; b = json.load(open("out/test/lifo.json"))["containers"][0]["boxes"]
s1 = min(x["x"] for x in b if x["stop"] == 1); s2 = max(x["x"] for x in b if x["stop"] == 2)
assert s1 > s2, (s1, s2)
PY
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
exit $fail
