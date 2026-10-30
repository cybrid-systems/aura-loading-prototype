#!/usr/bin/env bash
# 把 aura/*.aura 拼成一个文件后用 Aura 运行（与 aura-scm-agents 相同的做法）。
#   AURA_BIN=/path/to/aura scripts/aura.sh aura/main.aura
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
SRC="${1:-aura/main.aura}"; mkdir -p build
FILE="build/$(basename "$SRC" .aura).all.aura"
{ echo '(require "std/process" all:)'; cat aura/rules.aura aura/agents.aura; if [ "$SRC" = aura/evolve-main.aura ]; then cat aura/evolve.aura; fi; cat "$SRC"; } > "$FILE"
: "${AURA_BIN:?set AURA_BIN to an Aura binary}"
exec env AURA_SANDBOX=off AURA_PIPELINE_STRICT=0 timeout "${PC_TIMEOUT:-1800}" "$AURA_BIN" --load "$FILE"
