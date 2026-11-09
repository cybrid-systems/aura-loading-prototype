#!/usr/bin/env bash
# v0.2 P9 downstream experiment driver (synthetic data only).
#   tools/portfolio_v02.sh [phase]     phase = all | matrix | halving | cons | eoh | moo
# Aura 99ddc81c9 stdlib is required: AURA_PATH must point at that checkout's lib/.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${PC_V02_OUT:-out/v02}
BUD=${PC_BUDGET_MS:-2000}
EOR=${PC_EOH_BUDGET_MS:-1000}
MOOB=${PC_MOO_BUDGET_MS:-8000}
SEEDS=${PC_SEEDS:-"1 2 3 4 5"}
TRAIN=$(ls examples/synthetic/order_*.txt | tr '\n' ' ')
HOLD=$(ls examples/holdout-synthetic/order_*.txt | tr '\n' ' ')
ROUTES=$(ls examples/pool-v02/route_*.txt | tr '\n' ' ')
AURA_BIN=${AURA_BIN:-aura}
mkdir -p "$OUT/train" "$OUT/holdout" "$OUT/halving" "$OUT/cons" "$OUT/eoh" "$OUT/moo"
cat aura/portfolio.aura aura/portfolio-main.aura > build/portfolio.all.aura

run_one () {  # $1 mode $2 seed $3 outdir $4 instances ; rest = extra KEY=VALUE
  local mode=$1 seed=$2 od=$3 insts=$4
  shift 4
  env AURA_SANDBOX=off AURA_PATH="$AURA_PATH" \
      PC_MODE=$mode PC_SEED=$seed PC_BUDGET_MS=$BUD PC_INSTANCES="$insts" PC_OUT="$od" \
      PC_AUDIT="$od/audit_s$seed.tsv" "$@" \
      timeout 3600 "$AURA_BIN" --load build/portfolio.all.aura >> "$od/log_s$seed.txt" 2>&1
}

phase_matrix () {
  for s in $SEEDS; do run_one matrix $s "$OUT/train" "$TRAIN" & done; wait
  for s in $SEEDS; do run_one matrix $s "$OUT/holdout" "$HOLD" & done; wait
  python3 tools/portfolio_merge.py --dir "$OUT/train" --out "$OUT/train/matrix_merged.json"
  python3 tools/portfolio_merge.py --dir "$OUT/holdout" --out "$OUT/holdout/matrix_merged.json"
}

phase_halving () {
  for s in $SEEDS; do
    run_one select-halving $s "$OUT/halving" "$HOLD" PC_TRAIN_MATRIX="$OUT/train/matrix_merged.json" &
  done; wait
}

phase_cons () {
  for s in $SEEDS; do run_one matrix $s "$OUT/cons" "$ROUTES" PC_FAMILY=consolidation & done; wait
  python3 tools/portfolio_merge.py --dir "$OUT/cons" --out "$OUT/cons/matrix_merged.json"
}

phase_eoh () {
  for s in $SEEDS; do
    run_one eoh $s "$OUT/eoh" "" PC_TRAIN="$TRAIN" PC_HOLDOUT="$HOLD" PC_BUDGET_MS=$EOR &
  done; wait
}

phase_moo () {
  FOUR=$(ls examples/holdout-synthetic/order_*.txt | head -4 | tr '\n' ' ')
  for s in $SEEDS; do run_one moo-front $s "$OUT/moo" "$FOUR" PC_MOO_BUDGET_MS=$MOOB & done; wait
}

PHASE=${1:-all}
case "$PHASE" in
  matrix) phase_matrix ;;
  halving) phase_halving ;;
  cons) phase_cons ;;
  eoh) phase_eoh ;;
  moo) phase_moo ;;
  all) phase_matrix; phase_halving; phase_cons; phase_eoh; phase_moo ;;
  *) echo "phase: all|matrix|halving|cons|eoh|moo" >&2; exit 2 ;;
esac
echo "@@phase=$PHASE done"
