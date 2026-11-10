#!/bin/sh
# 一行跑起来：
#   curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-loading-prototype/main/run.sh | sh
#
# 也可以：
#   ./run.sh            内核 demo + Aura 货位演化（和上面那条一样）
#   ./run.sh rules      客户规则热替换，不重编内核
#   ./run.sh evolve     安全门禁 KEEP / ROLLBACK
#   ./run.sh agents     多 Agent，胜者提交、败者回滚
#
# 需要：python3、g++、git、curl。rules/evolve/agents 还要 script（bsdutils）。
# 环境变量：AURA_VERSION（默认 v0.2.0）、AURA_SKIP_EVO=1（只跑内核 demo）、
#           AURA_BIN（用已有的 aura）、AURA_LOADING_DIR（clone 目录）、
#           PC_RULES（rules 演示换成你的规则文件）。
set -eu

VERSION=${AURA_VERSION:-v0.2.0}
SRC=https://github.com/cybrid-systems/aura-loading-prototype
CMD=

say() { printf '%s\n' "$*"; }

usage() {
  cat <<'EOF'
用法：
  ./run.sh            编译内核、跑装柜 demo，再跑 Aura 货位演化
  ./run.sh rules      客户规则热替换（改 .sexp，不重编内核）
  ./run.sh evolve     安全门禁：KEEP / ROLLBACK
  ./run.sh agents     多 Agent 并行，胜者提交、败者回滚
  AURA_SKIP_EVO=1 ./run.sh

改规则看 docs/rules.md。换一份规则：PC_RULES=rules/customers/acme.sexp ./run.sh rules
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    say "缺少 $1：请先安装（$2）。"
    exit 1
  }
}

if [ "${1:-}" != "" ]; then
  case "$1" in
    rules|evolve|agents) CMD=$1 ;;
    -h|--help|help) usage; exit 0 ;;
    *) say "未知命令：$1"; usage; exit 2 ;;
  esac
fi

need python3 "Debian/Ubuntu: apt install python3；macOS: brew install python"
need g++ "Debian/Ubuntu: apt install g++；macOS: xcode-select --install"
need curl "Debian/Ubuntu: apt install curl；macOS 自带"

# 1. 找到仓库：当前目录就是它，否则 clone 到 ./aura-loading-prototype
if [ -f ./build.py ] && [ -d ./kernel ]; then
  REPO=$(pwd)
elif [ -f ./aura-loading-prototype/build.py ]; then
  REPO=$(pwd)/aura-loading-prototype
else
  need git "https://git-scm.com/downloads"
  REPO=${AURA_LOADING_DIR:-$(pwd)/aura-loading-prototype}
  if [ -d "$REPO/.git" ]; then
    say "==> 更新 $REPO"
    git -C "$REPO" pull -q --ff-only || true
  else
    say "==> clone 到 $REPO"
    git clone -q --depth 1 "$SRC" "$REPO"
  fi
fi
cd "$REPO"

# 装官方 Aura v0.2.0。失败时：默认路径的内核 demo 已经跑完就返回 0；三条演示必须有 Aura。
ensure_aura() {
  strict=$1
  AURA_BIN=${AURA_BIN:-}
  if [ -z "$AURA_BIN" ] && [ -x "$REPO/.aura/current/bin/aura" ]; then
    AURA_BIN=$REPO/.aura/current/bin/aura
  fi
  if [ -z "$AURA_BIN" ]; then
    say ""
    say "==> 安装 Aura $VERSION 到 $REPO/.aura"
    if ! curl -fsSL "https://raw.githubusercontent.com/cybrid-systems/aura/$VERSION/install.sh" \
      | AURA_VERSION="$VERSION" AURA_PREFIX="$REPO/.aura" AURA_BIN_DIR="$REPO/.aura/bin" sh
    then
      say ""
      if [ "$strict" = "1" ]; then
        say "失败（Aura）：官方 v0.2.0 安装失败。检查网络，或设置 AURA_BIN 指向已有的 aura。"
        exit 1
      fi
      say "Aura 安装失败：内核 demo 已完成；重试或手动设置 AURA_BIN。"
      exit 0
    fi
    AURA_BIN=$REPO/.aura/current/bin/aura
  fi
  if [ ! -x "$AURA_BIN" ]; then
    say "失败（Aura）：AURA_BIN 不可执行：$AURA_BIN"
    exit 1
  fi
  AURA_PATH=${AURA_PATH:-$(dirname "$(dirname "$AURA_BIN")")/lib}
  export AURA_BIN AURA_PATH
}

if [ -n "$CMD" ]; then
  need script "Debian/Ubuntu: apt install bsdutils（提供 script）；macOS 自带"
  ensure_aura 1
  exec python3 tools/demo_dx.py "$CMD"
fi

say ""
say "==> [1/2] C++ 装箱内核（块构造 + 独立校验 + 3D 回放）"
python3 build.py demo --block

if [ "${AURA_SKIP_EVO:-0}" = "1" ]; then
  say ""
  say "==> 跳过 Aura 演化 demo（AURA_SKIP_EVO=1）"
  exit 0
fi

ensure_aura 0

say ""
say "==> [2/2] Aura v0.2 演化栈：std/portfolio + std/algo-select + std/moead"
say "    52 周滚动货位分配；选择器按特征选 4 个成员，MOEA/D 前沿进入组合"
say "    约 40 秒 …"
python3 slotting/run_slotting.py --seed 7 --windows 52 --budget 1500 --b3-evals 24 \
  --out out/demo/slotting.json

say ""
say "完成。3D 回放：$REPO/out/b.html"
say "规则热替换：./run.sh rules    安全门禁：./run.sh evolve    多 Agent：./run.sh agents"
