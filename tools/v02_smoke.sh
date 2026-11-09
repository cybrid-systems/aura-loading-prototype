#!/usr/bin/env bash
# CI smoke for the v0.2 downstream work: synthetic only, small budgets.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 build.py >/dev/null
mkdir -p out/smoke
python3 tools/gen_synthetic.py --orders 2 --seed 5 --out out/smoke/orders >/dev/null
for m in wall layer block human; do
  python3 tools/pc_eval.py --problem out/smoke/orders/order_01.txt --member $m \
    --budget-ms 300 --seed 1 --out out/smoke/$m.json | tail -1 > out/smoke/$m.score
  test -s out/smoke/$m.json
  echo "ok   pc_eval $m"
done
# 拼柜成员的构造阶段本身就要几秒，冒烟给它一个现实的预算
python3 tools/pc_eval.py --problem out/smoke/orders/order_01.txt --member nf \
  --budget-ms 4000 --seed 1 --out out/smoke/nf.json | tail -1 > out/smoke/nf.score
test -s out/smoke/nf.json && echo "ok   pc_eval nf"
python3 tools/verify.py out/smoke/wall.json >/dev/null && echo "ok   pc_eval wall feasible"
python3 tools/portfolio_merge.py --help >/dev/null
python3 slotting/gen_slotting.py --seed 3 --out slotting/data/s3.json >/dev/null
python3 tests/test_slotting.py >/dev/null && echo "ok   slotting tests"
timeout 180 python3 slotting/run_slotting.py --seed 3 --windows 8 --budget 200 --plan-samples 150 \
  --clair-iters 200 --out out/smoke/slot-run.json --quiet
python3 - <<'PY'
import json
r = json.load(open("out/smoke/slot-run.json"))
assert r["oracle"]["worst"] <= r["sbs_roll"]["worst"] + 1e-9
assert r["clairvoyant"]["worst"] <= r["oracle"]["worst"] + 1e-9
PY
echo "ok   slotting skeleton"
echo "@@smoke done"
