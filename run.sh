#!/bin/sh
# 一行跑起来：
#   curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-loading-prototype/main/run.sh | sh
#
# 需要：python3、g++、git、curl（或 wget）。
# 环境变量：AURA_VERSION（默认 v0.2.0）、AURA_SKIP_EVO=1（只跑内核 demo）、
#           AURA_BIN（用已有的 aura）、AURA_LOADING_DIR（clone 目录）。
set -eu

VERSION=${AURA_VERSION:-v0.2.0}
SRC=https://github.com/cybrid-systems/aura-loading-prototype

say() { printf '%s\n' "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    say "缺少 $1：请先安装（$2）。"
    exit 1
  }
}
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

say ""
say "==> [1/2] C++ 装箱内核（块构造 + 独立校验 + 3D 回放）"
python3 build.py demo --block

if [ "${AURA_SKIP_EVO:-0}" = "1" ]; then
  say ""
  say "==> 跳过 Aura 演化 demo（AURA_SKIP_EVO=1）"
  exit 0
fi

# 2. Aura v0.2：装到 .aura/，用 std/portfolio + std/algo-select + std/moead
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
    say "Aura 安装失败：内核 demo 已完成；重试或手动设置 AURA_BIN。"
    exit 0
  fi
  AURA_BIN=$REPO/.aura/current/bin/aura
fi
AURA_PATH=${AURA_PATH:-$(dirname "$(dirname "$AURA_BIN")")/lib}
export AURA_BIN AURA_PATH

say ""
say "==> [2/2] Aura v0.2 演化栈：std/portfolio + std/algo-select + std/moead"
say "    52 周滚动货位分配；选择器按特征选 4 个成员，MOEA/D 前沿进入组合"
say "    约 40 秒 …"
python3 slotting/run_slotting.py --seed 7 --windows 52 --budget 1500 --b3-evals 24 \
  --out out/demo/slotting.json

say ""
say "完成。3D 回放：$REPO/out/b.html"
