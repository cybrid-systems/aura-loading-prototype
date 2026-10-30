#!/usr/bin/env bash
# 把 aura/*.aura 拼成一个文件后用 Aura 运行（与 aura-scm-agents 相同的做法）。
#   AURA_BIN=/path/to/aura scripts/aura.sh aura/main.aura
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
SRC="${1:-aura/main.aura}"; mkdir -p build
FILE="build/$(basename "$SRC" .aura).all.aura"
{ echo '(require "std/process" all:)'; cat aura/rules.aura aura/strategies.aura aura/agents.aura; case "$SRC" in aura/evolve-main.aura) cat aura/evolve.aura;; aura/tune-main.aura) cat aura/tune.aura;; aura/consolidate-main.aura) cat aura/consolidate.aura;; esac; cat "$SRC"; } > "$FILE"
: "${AURA_BIN:?set AURA_BIN to an Aura binary}"
# 标准库路径：dev 镜像里 AURA_RUNTIME_DIR 指向 aura 源码树，std/ 在它的 lib/ 下
if [ -z "${AURA_PATH:-}" ] && [ -n "${AURA_RUNTIME_DIR:-}" ]; then export AURA_PATH="$AURA_RUNTIME_DIR/lib"; fi
exec env AURA_SANDBOX=off AURA_PIPELINE_STRICT=0 timeout "${PC_TIMEOUT:-1800}" "$AURA_BIN" --load "$FILE"
