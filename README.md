# aura-loading-prototype — 配仓（集装箱装载）多 Agent 原型

用 **C++ 三维装箱内核** 求解，用 **Aura** 写规则 EDSL、多 Agent 协调器（fiber 并行 + COW overlay 隔离）和带安全门禁的规则演化。目标是验证"多 Agent + 规则层"能不能在满足硬约束的前提下，比经验装柜用更少的柜、更低的运费。

> **数据说明**：本仓库是公开仓库，**不包含任何客户数据**。所有示例、测试、可视化和下面的结果都基于 `tools/gen_synthetic.py` 生成的**合成订单**。真实数据放在仓库外，用 `PEICANG_DATA` 指过去在本地跑（见下文），`.gitignore` 已屏蔽 xlsx/zip/csv 和导出目录。
>
> 后来拿到了一批真实装柜单（CSV，只在本地跑，不入库），只把**汇总后的匿名结果**写在下面的"真实装柜单验证"一节。结论：**在这批数据上，"运费下降 10–18%" 不成立**——现有人工方案的装载率已经高于本内核能达到的水平。

## 结构

```
kernel/pack.cpp          C++20 三维装箱内核：极点启发式 + 局部搜索（随机扰动装载顺序）
tools/import_xlsx.py     真实数据导入：xlsx/csv/zip → 内核格式（只用标准库，自动识别中英文表头和 mm/cm/m）
tools/gen_synthetic.py   合成订单生成器（测试 / 示例 / 基准）
tools/verify.py          独立可行性校验：越界、重叠、超重、支撑率、先卸后装、漏装
tools/bench.py           基准：B0/B1/B2 基线 vs AURA 多 Agent，输出 bench.md / bench.json
tools/viz.py             结果 JSON → 自包含 three.js 页面（旋转/缩放/按装载顺序回放）
aura/rules.aura          规则 EDSL：hard（交给内核）/ check（方案校验否决）/ prefer（评分权重）
aura/agents.aura         4 个 Agent fiber 并行提案，各自写 COW overlay；协调器否决+评分，胜者 commit，其余 rollback
aura/evolve.aura         规则/参数演化：每个候选改动在 overlay 里回放验证，过门禁才 commit，审计落盘
aura/main.aura           入口：批量订单 → explain.md（决策解释报告）+ aura-summary.tsv
tests/run_tests.sh       端到端测试（只用合成数据）
repro/                   本项目中发现的 Aura bug 最小复现
docs/                    格式说明、合成数据基准、决策解释示例、3D 可视化 demo
```

## 内核建模

- 柜型（默认 20GP / 40HQ / 45HC，内尺寸与限重为常见值；**运费是相对值 1.00 / 1.60 / 1.85，仅作占位**，用 `PEICANG_CONTAINERS=xxx.json` 换成真实报价）
- 硬约束：6 向旋转 / 只能直立 / 固定方向；底面支撑 ≥ 75%；顶部承重上限，易碎品上方不压货；按卸货站先卸后装（LIFO）；不同类危险品纵向间距 ≥ 1000 mm；单柜限重
- 多柜型选择：逐柜选"单位运费装得最多"的柜型，或"能装下剩余全部的最便宜柜型"
- 装完后整体平移使重心居中（意味着需要垫木/绑扎），并估算前端/门端两点支撑负荷
- 输出体积/重量下界，便于判断离最优还有多远

格式详见 [docs/FORMAT.md](docs/FORMAT.md)。

## Aura 层做了什么

1. **规则 EDSL**（`aura/rules.aura`）：规则是数据，`(hard min-support 0.75)`、`(check cog-x 0.30 0.70)`、`(prefer cost 1.0)` 等；`rules->kernel-args` 翻译成内核参数，`check-plan` 对内核结果做二次校验并给出中文否决理由。
2. **多 Agent 协调**（`aura/agents.aura`）：空间优化 / 稳定重量 / 卸货顺序 / 成本 4 个 Agent，各是一个 fiber，后台启动内核子进程（多核真并行），把候选方案写进**自己的 overlay**（`fiber:overlay-define "chosen-plan"`）。提案期间全局 `chosen-plan` 不可见（报告里记录为 unbound 或上一单的值），协调器裁决后只有胜者 `overlay-commit`，其余 `overlay-rollback`。每单的评分、否决理由和 overlay 状态写进 [决策解释报告](docs/explain-synthetic.md)。
3. **带门禁的演化**（`aura/evolve.aura`）：读现场反馈（如破损率、门端超载），生成候选改动（收紧支撑率、降低门端负荷、换参数、甚至"关掉先卸后装"），每个改动在 overlay 里用历史订单回放：安全底线不可放松、违例数不能增加、非反馈驱动的改动必须降运费、反馈驱动的改动最多允许运费 +5%。过门禁 commit，否则 rollback，全部写审计表。

## 运行

需要 g++ (C++20)、python3；Aura 部分需要 `aura` 可执行文件（开发时用的是 `ghcr.io/cybrid-systems/dev:v1.0.9` 镜像和 aura `69d360068`），并设置 `AURA_SANDBOX=off AURA_PIPELINE_STRICT=0`。

```bash
g++ -O2 -std=c++20 -o build/pack kernel/pack.cpp
python3 tools/gen_synthetic.py --orders 12 --seed 7 --out examples/synthetic   # 已提交，可直接用
build/pack --in examples/synthetic/order_10.txt --out out/r.json time_ms=3000
python3 tools/verify.py out/r.json
python3 tools/viz.py out/r.json out/r.html

# 多 Agent（Aura）
PC_ORDERS="examples/synthetic/order_01.txt examples/synthetic/order_07.txt" PC_OUT=out/aura \
  script -qc "scripts/aura.sh aura/main.aura" /dev/null
# 规则演化
PC_ORDERS="$(ls examples/synthetic/order_0[1-4].txt | tr '\n' ' ')" PC_FEEDBACK=examples/feedback.synthetic.txt PC_OUT=out/evo \
  script -qc "scripts/aura.sh aura/evolve-main.aura" /dev/null
# 基准
python3 tools/bench.py --orders examples/synthetic --out out/bench --time-ms 8000 --aura
# 测试
tests/run_tests.sh
```

（Aura 的 stdout 在管道下是块缓冲，所以用 `script -qc` 给它一个 pty。）

### 真实数据（只在本地）

```bash
export PEICANG_DATA=/path/outside/repo          # 放 xlsx / csv / zip
python3 tools/import_xlsx.py inspect             # 只打印表结构和字段映射，不打印内容
python3 tools/import_xlsx.py convert --out out/real [--map mapping.json] \
    [--group auto|order|sheet] [--existing-type 45HC] [--est-dims]
python3 tools/bench.py --orders out/real --out out/bench-real --aura
```

导入器把 SKU / 客户 / 单号匿名化为 `real_XX_YYY`；如果表里带有现有装柜记录（柜号/柜型），`bench.py` 会多出"现有方案"对比一行——这才是验证 10–18% 的正确方式。导入假设：毛重按单箱计、卸货站顺序按目的地首次出现顺序、缺"可倒置"列时按只能直立处理；与实际表头不符时用 `--map` 指定。

货代**装柜单**格式（表头上方一行写柜号/柜名，`件数 / 实重 / 方数` 是整行合计，外箱尺寸写在一列里如 `55×45×35cm`，同一票的其他品名另起一行且不填件数）也能直接导入：
- 柜号写在表头上方时自动按**整张表 = 一个已装好的柜**出一个问题（`--group sheet` 可强制），现有方案记为 1 柜；表里没有柜型时用 `--existing-type` 指定。
- `实重/方数/总重/总体积` 这类列按整行合计处理，自动除以件数；不填件数的续行跳过。
- 尺寸列解析不了（如"超大件"）或根本没有尺寸列时，默认跳过并在 `import_report.json` 里计数；加 `--est-dims` 则按 `方数/件数` 和固定长宽高比 1.25:1:0.9 估一个箱子，并计入 `boxes_dims_estimated`。估出来的尺寸只用于粗算，不能当真实装载方案。

`out/` 已在 `.gitignore` 中，不要把结果里的明细提交到公开仓库。

## 合成数据实测结果

12 个合成订单（144–1291 箱，共 7099 箱），全部方案经 `tools/verify.py` 独立校验为可行。每个 AURA Agent 时间上限 8 s，4 个并行。

| 方案 | 说明 | 总柜数 | 总相对运费 | 加权体积利用率 |
|---|---|---|---|---|
| B0 经验基线 | 只用 40HQ、不旋转、按单据顺序装 | 32 | 51.20 | 45.5% |
| B1 单策略贪心 | 混合柜型 + 旋转，一次贪心 | 29 | 42.50 | 59.0% |
| B2 单策略 + 同等算力搜索 | 与"空间优化"Agent 同参数，单进程 32 s | 27 | 40.10 | 61.0% |
| **AURA 多 Agent** | 4 Agent 并行各 8 s，规则校验 + 评分 | **27** | **40.10** | **61.0%** |

- 相对 B0：柜数 −15.6%，相对运费 −21.7%
- 相对 B1：相对运费 −5.6%
- **相对 B2：0%**。在这批合成数据上，多 Agent 的方案与"一个策略给 4 倍搜索时间"完全相同；收益来自混合柜型、旋转和局部搜索，而不是多 Agent 本身。多 Agent 的实际价值是墙钟时间（8 s vs 32 s）、每个硬/软规则的可解释否决（例如 order_03 中"稳定/重量"方案因 45HC 重心 x=0.715 超出 [0.3, 0.7] 被否决），以及演化门禁。
- 体积/重量下界合计 18 柜（按最大柜型），AURA 用 27 柜，说明还有空间（下界本身偏松）。（早先版本写的 20 柜是误用了只允许 40HQ 的 B0 的下界，已在 `bench.py` 修正。）
- B0 是按"常见人工做法"构造的基线，**不是**客户的真实装柜方案，所以"−21.7%"只说明算法相对这个基线的差距，不等于真实运费节省。

逐单明细见 [docs/bench-synthetic.md](docs/bench-synthetic.md)，3D 回放见 [docs/demo.html](docs/demo.html)（order_10 胜出方案，下载后用浏览器打开）。

规则演化（合成订单 order_01–04 + 合成反馈"破损率 3.1%、门端超载"，每次回放内核 3 s / 150 次迭代，审计表原样）：

| 候选改动 | 相对运费 | 违例 | 结果 |
|---|---|---|---|
| 反馈：支撑率 0.75→0.85 | 12.85 → 12.85 | 0 → 0 | KEEP（满足反馈，增幅 ≤5%） |
| 反馈：门端负荷上限 18000→15000 kg | 12.85 → 12.85 | 0 → 0 | KEEP |
| 参数：按底面积排序 | 12.85 → 12.60 | 0 → 0 | KEEP（运费下降） |
| 参数：按高度排序 + 更重视低层 | 12.60 → 13.70 | 0 → 0 | ROLLBACK |
| 参数：不分站排序 | 12.60 → 14.00 | 0 → 0 | ROLLBACK |
| 规则：关闭先卸后装（有害但合法） | 12.60 → 12.60 | 0 → 0 | ROLLBACK（放松安全底线） |

另一组测试（`tests/run_tests.sh`，另一批合成订单，反馈"破损率 5%"）中，"关闭先卸后装"能把运费从 8.40 降到 7.65——一个只看运费的优化器会接受它，门禁把它拒绝了；同组里"支撑率 0.85"导致违例数上升，也被回滚。

## 真实装柜单验证（匿名汇总）

数据：23 份货代装柜单，每份是一个**已经装好的柜**的明细，合计 25,320 箱、申报 1,823 m³、约 315 t，品类是普货纸箱（服装、家居、饰品等）。没有易碎、危险品、不可倒置、卸货顺序等字段，也**没有柜型列**。只有 3 份带外箱尺寸（8 档标准箱规，另有少量"超大件"不带尺寸）；其余 20 份只有件数、实重、方数。

柜型推断：23 份里有 22 份的申报方数超过 40HQ 的几何容积（76.35 m³），所以按 45HC（86.0 m³）计；现有方案的申报装载率是 45HC 的 88%–105%，中位 91%。（超过 100% 的那份说明申报方数比几何体积偏大，或者用的柜子更大。）

**A. 3 份带外箱尺寸的柜单**（按标准箱规的名义尺寸；名义体积占 45HC 的 85%–91%；每个 AURA Agent 8 s，B2 32 s）

| 方案 | 总柜数 | 总相对运费 | 相对现有方案 |
|---|---|---|---|
| 现有人工方案（假设 45HC） | 3 | 5.55 | — |
| B0 经验基线（只用 40HQ） | 6 | 9.60 | +73% |
| B1 单策略贪心 | 6 | 7.80 | +41% |
| B2 单策略 + 同等算力搜索 | 6 | 7.80 | +41% |
| AURA 多 Agent | 5 | 7.05 | +27% |

只有 1 份被 AURA 装进 1 个 45HC（装载率 84.8%），另外 2 份都要再加一个小柜。敏感性测试：只用 45HC、允许 6 向旋转、支撑率放宽到 0.6、单进程搜索 60 s，3 份仍然全部装不进 1 柜，第一柜最高只到 81%–85%，各剩 17–158 箱。

**B. 全部 23 份**（其中 20 份的箱子尺寸由 `方数/件数` 估算，只能看量级）：现有 23 柜（相对运费 42.55）；B0 47 柜 / 75.20；B1 46 / 60.55；B2 45 / 59.30；AURA 45 / 59.05，比现有方案多 39% 运费。

**结论**
- 这批柜单都是货代拼箱的满柜，现有人工装载率（名义尺寸 85%–91%，申报方数中位 91%）**高于**本内核目前的上限（单个 45HC 约 84%–85%）。所以本原型在这批数据上**比现有方案差**，"运费下降 10–18%" 不成立。
- 即使装载做到 100%，按申报方数算的理论下界也是 22 柜（23 份全部混装时），也就是最多省 1 柜（4.3%）；按线路分开装的话，下界是 24 柜（有一份的申报方数超过 45HC 容积），比现有的 23 柜还多。这说明对已经装满的柜，装载几何已经没有空间可省；要省钱只能靠前面的"哪些票拼哪个柜"（拼箱选择 / 配载计划），而不是柜内摆放。
- 内核还差什么：软包装纸箱可以压缩，现场能"塞"进去；内核用的是刚性名义尺寸、75% 支撑率、极点启发式，每次构造约 0.3 s，60 s 只够搜 50–230 轮。要追上人工的 90%+ 装载率，需要更强的算法，比如按层或按墙构造、同尺寸箱子先成块再摆放、更快的增量评估。

## 开发中碰到的 Aura 问题（aura `69d360068`）

| 问题 | 绕过 | issue |
|---|---|---|
| 多个 fiber 并发 `json-parse` → glibc double free（SIGABRT），与 overlay/GC 无关 | 所有 `json-parse` 放到主 fiber 串行 | [aura#4788](https://github.com/cybrid-systems/aura/issues/4788) |
| 局部变量与原语同名（`log`、`sqrt`）时 `(set! x (cons v x))` 右值解析成全局原语，得到 `(1 . <unknown>)` | 避免与原语同名的局部名 | [aura#4789](https://github.com/cybrid-systems/aura/issues/4789) |
| fiber lambda 捕获的外层变量需在 lambda 内重新 `let` 绑定（已知问题 #4781） | `spawn-reporting` 模式 | [aura#4781](https://github.com/cybrid-systems/aura/issues/4781) |
| `shell` 原语只能通过 `(require "std/process" all:)` 的 `sh` 使用，只返回退出码 | 结果走文件 | — |
| 管道下 stdout 块缓冲，超时被杀时输出全丢 | `script -qc` | — |

复现用例在 [repro/](repro/)。

## 局限

- **没有用真实数据跑过**；10–18% 未验证。
- 运费是相对值占位；真实对比需要按航线/柜型的报价。
- 门端/前端负荷是两点支撑的近似；堆码承重只算直接压在上面的货，不做载荷传递。
- 重心居中依赖整体平移，现实中需要垫木或绑扎；没有建模绑扎、托盘、叉车作业空间。
- 局部搜索只扰动装载顺序，不做柜间交换；下界较松，无法给出最优性证明。
- 合成数据的分布（纸箱 / 托盘 / 长件比例）是猜的，真实订单的结果可能完全不同。
