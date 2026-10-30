# aura-loading-prototype — 配仓（集装箱装载）多 Agent 原型

用 **C++ 三维装箱内核** 求解，用 **Aura** 写规则 EDSL、多 Agent 协调器（fiber 并行 + COW overlay 隔离）和带安全门禁的规则演化。目标是验证"多 Agent + 规则层"能不能在满足硬约束的前提下，比经验装柜用更少的柜、更低的运费。

> **数据说明**：本仓库是公开仓库，**不包含任何客户数据**。所有示例、测试、可视化和下面的结果都基于 `tools/gen_synthetic.py` 生成的**合成订单**。真实数据放在仓库外，用 `PEICANG_DATA` 指过去在本地跑（见下文），`.gitignore` 已屏蔽 xlsx/zip/csv 和导出目录。
>
> 后来拿到了一批真实装柜单（CSV，只在本地跑，不入库），只把**汇总后的匿名结果**写在下面的"真实装柜单验证"一节。
> 第一版内核（极点启发式）在这批数据上比人工差（3 份带尺寸的柜单要 5 柜，人工 3 柜）。第二版加了**块构造内核**（墙式 / 层式 / 块式 / 人工经验四种构造思路），按刚性名义尺寸**每份都装进 1 个 45HC，装载率 84.7%–90.5%，与人工持平**。但这批柜单本来就是满柜，所以"运费下降 10–18%"仍然不成立（见结论）。

## 结构

```
kernel/pack.cpp          C++20 三维装箱内核入口：algo=ep 极点启发式 + 局部搜索（第一版）；algo=block 调块构造内核
kernel/blocks.hpp        块构造内核：极大空闲空间 + 同规格块（每轴按最大数 / 一维背包取数）+ 前瞻搜索 + 随机重启
tools/import_xlsx.py     真实数据导入：xlsx/csv/zip → 内核格式（只用标准库，自动识别中英文表头和 mm/cm/m）
tools/gen_synthetic.py   合成订单生成器（测试 / 示例 / 基准）
tools/verify.py          独立可行性校验：越界、重叠、超重、支撑率、先卸后装、漏装
tools/bench.py           基准：B0/B1/B2 基线、各构造思路单跑、同等算力单策略 vs AURA 多 Agent；--fill 单柜最大装载率
tools/viz.py             结果 JSON → 自包含 three.js 页面（旋转/缩放/按装载顺序回放）
aura/rules.aura          规则 EDSL：hard（交给内核）/ check（方案校验否决）/ prefer（评分权重）
aura/rules-fill.sexp     单柜评估用的规则文件（PC_RULES），允许剩余货物、按装载率择优
aura/strategies.aura     构造思路 EDSL：constructor（墙式/层式/块式/人工经验）+ heuristic（人工经验规则及权重）+ knob（压缩/倒放开关）
aura/agents.aura         每种构造思路一个 Agent fiber 并行提案，各自写 COW overlay；协调器否决+评分，胜者 commit，其余 rollback
aura/evolve.aura         规则/参数演化：每个候选改动在 overlay 里回放验证，过门禁才 commit，审计落盘
aura/tune.aura           人工经验权重演化：每代所有候选在各自 fiber+overlay 里并行回放，过门禁中最好的 KEEP，其余 ROLLBACK
aura/tune-main.aura      演化入口：训练集 / 留出集，输出 tune-audit.tsv、tuned-strategies.txt（可用 PC_STRATEGIES 载回）
aura/main.aura           入口：批量订单 → explain.md（决策解释报告）+ aura-summary.tsv
tests/run_tests.sh       端到端测试（只用合成数据）
repro/                   本项目中发现的 Aura bug 最小复现
docs/                    格式说明、合成数据基准、决策解释示例、3D 可视化 demo
```

## 内核建模

- 柜型（默认 20GP / 40HQ / 45HC，内尺寸与限重为常见值；**运费是相对值 1.00 / 1.60 / 1.85，仅作占位**，用 `PEICANG_CONTAINERS=xxx.json` 换成真实报价）
- 硬约束：6 向旋转 / 只能直立 / 固定方向；底面支撑 ≥ 75%；顶部承重上限，易碎品上方不压货；按卸货站先卸后装（LIFO）；不同类危险品纵向间距 ≥ 1000 mm；单柜限重
- 多柜型选择：逐柜选"单位运费装得最多"的柜型，或"能装下剩余全部的最便宜柜型"（块构造内核：先对每种柜型贪心试装，能一柜装下全部的取最便宜的去搜索，否则按单位运费容积选柜，时间按预估柜数分配）
- 块构造内核（`algo=block`）：维护极大空闲空间，每步按"空间规则"选一个空间（墙式：最靠柜底；层式：最低；块式：离柜角最近），在里面放一个同规格箱子拼成的 nx·ny·nz 块。每轴的箱数取"最大"和"剩余空隙最能被其他箱规拼满"（一维背包）两种，候选块按加权评分（体积、横截面/底面覆盖、大箱优先、重货在下、同规格成墙、空隙可拼满）排序。搜索是逐步加宽的前瞻（每个候选都贪心补全成完整方案再比较），宽度饱和后用带扰动的随机重启用完剩余时间。支撑率、限重、顶部承重、先卸后装（按卸货站分阶段）、危险品间距都在放块时检查。
- **软纸箱压缩**（`squeeze`）和**允许放倒**（`anyrot`）是显式开关，默认关闭；打开后在结果 metrics 里单独标出，装载率仍按名义尺寸计，不与刚性结果混在一起报告
- 装完后整体平移使重心居中（意味着需要垫木/绑扎），并估算前端/门端两点支撑负荷
- 输出体积/重量下界，便于判断离最优还有多远

格式详见 [docs/FORMAT.md](docs/FORMAT.md)。

## Aura 层做了什么

1. **规则 EDSL**（`aura/rules.aura`）：规则是数据，`(hard min-support 0.75)`、`(check cog-x 0.30 0.70)`、`(prefer cost 1.0)` 等；`rules->kernel-args` 翻译成内核参数，`check-plan` 对内核结果做二次校验并给出中文否决理由。
2. **构造思路 EDSL**（`aura/strategies.aura`）：`(constructor wall "墙式" wall ((vol 1.0) (yz 0.5)) "…")`、`(heuristic big-bottom big 1.0 "大箱打底、大箱先装")`、`(knob squeeze 0 "…")`。人工经验（大箱打底、同规格成墙、重货在下、选能拼满空隙的箱规）是一条条带权重的规则，`constructor->params` 翻译成内核参数。
3. **多 Agent 协调**（`aura/agents.aura`）：墙式 / 层式 / 块式 / 人工经验 4 个 Agent 的构造方式本质不同，各是一个 fiber，后台启动内核子进程（多核真并行），把候选方案写进**自己的 overlay**（`fiber:overlay-define "chosen-plan"`）。提案期间全局 `chosen-plan` 不可见（报告里记录为 unbound 或上一单的值），协调器裁决后只有胜者 `overlay-commit`，其余 `overlay-rollback`。每单的评分、否决理由和 overlay 状态写进 [决策解释报告](docs/explain-synthetic.md)。
4. **带门禁的演化**（`aura/evolve.aura`）：读现场反馈（如破损率、门端超载），生成候选改动（收紧支撑率、降低门端负荷、换参数、甚至"关掉先卸后装"），每个改动在 overlay 里用历史订单回放：安全底线不可放松、违例数不能增加、非反馈驱动的改动必须降运费、反馈驱动的改动最多允许运费 +5%。过门禁 commit，否则 rollback，全部写审计表。
5. **人工经验权重演化**（`aura/tune.aura`）：每代对每条人工经验规则生成"调高 / 调低"候选，另加"换空间规则"和两个有害但合法的候选（压缩容差 0.02、允许倒放）。每个候选在自己的 fiber + overlay 里用训练集回放（确定性单轮搜索，`verify.py` 逐单校验）。门禁：刚性底线（squeeze=0、anyrot=0）不可放松，校验失败数必须为 0，重心违例不能增加，装载率必须上升；本代过门禁的最好候选 KEEP，其余 ROLLBACK。

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
# 人工经验权重演化（训练集 / 留出集）
PC_TRAIN="$(ls examples/synthetic/order_0[1-6].txt | tr '\n' ' ')" PC_HOLDOUT="$(ls examples/synthetic/order_1*.txt | tr '\n' ' ')" PC_GENS=3 \
  PC_OUT=out/tune script -qc "scripts/aura.sh aura/tune-main.aura" /dev/null
PC_STRATEGIES=out/tune/tuned-strategies.txt PC_ORDERS=... script -qc "scripts/aura.sh aura/main.aura" /dev/null   # 用调好的权重
# 基准
python3 tools/bench.py --orders examples/synthetic --out out/bench --time-ms 2000 --strategies --aura
python3 tools/bench.py --orders out/real --out out/fill --time-ms 2000 --strategies --aura --fill   # 单个 45HC 最大装载率
# 块构造内核单跑
build/pack --in examples/synthetic/order_10.txt --out out/b.json algo=block space=0 w_vol=1 w_yz=0.5 time_ms=2000
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

12 个合成订单（144–1291 箱，共 7099 箱），全部方案经 `tools/verify.py` 独立校验为可行。新内核每个构造思路 / 每个 AURA Agent 时间上限 2 s；S_wall4、B2 独占 8 s（= AURA 4 个 Agent 的总算力）。"旧 AURA" 是第一版（极点内核、4 个 Agent 各 8 s）的结果。

| 方案 | 说明 | 总柜数 | 总相对运费 | 加权体积利用率 |
|---|---|---|---|---|
| B0 经验基线 | 只用 40HQ、不旋转、按单据顺序装 | 32 | 51.20 | 45.5% |
| B1 单策略贪心 | 旧内核，混合柜型 + 旋转，一次贪心 | 29 | 42.50 | 59.0% |
| B2 旧内核 + 同等算力搜索 | 单进程 8 s | 28 | 41.35 | 59.6% |
| 旧 AURA | 第一版 4 Agent 各 8 s | 27 | 40.10 | 61.0% |
| 墙式 | 块构造内核 2 s | 28 | 39.20 | 65.3% |
| 层式 | 同上 | 28 | 39.30 | 64.4% |
| 块式 | 同上 | 27 | 39.15 | 63.7% |
| 人工经验 | 同上 | 26 | 38.40 | 64.6% |
| 墙式 ×4 算力 | 单进程 8 s | 27 | 39.30 | 64.2% |
| **AURA 多 Agent** | 4 种构造思路各 2 s，规则校验 + 评分 | **26** | **38.15** | **64.9%** |

- 相对 B0：柜数 −18.8%，相对运费 −25.5%；相对旧 AURA：−4.9%。
- **相对同等算力的单策略（墙式 ×4 算力）：−1 柜，相对运费 −2.9%**；逐单比较 AURA 5 单更好、1 单更差、6 单相同。各单胜出的构造思路分散（块式 4、人工经验 3、墙式 3、层式 2）——不同构造方式在不同订单上占优，这是多 Agent 在这里有收益的原因；第一版的 4 个 Agent 只是同一构造的不同参数，收益为 0。
- 体积/重量下界合计 17 柜（按最大柜型），AURA 用 26 柜（下界偏松，这批合成订单里托盘和长件比例高）。
- B0 是按"常见人工做法"构造的基线，**不是**客户的真实装柜方案。

逐单明细见 [docs/bench-synthetic.md](docs/bench-synthetic.md)，决策解释见 [docs/explain-synthetic.md](docs/explain-synthetic.md)，3D 回放见 [docs/demo.html](docs/demo.html)（order_10 胜出方案，下载后用浏览器打开）。

规则演化（合成订单 order_01–04 + 合成反馈"破损率 3.1%、门端超载"，审计表原样；基线是墙式构造）：

| 候选改动 | 相对运费 | 违例 | 结果 |
|---|---|---|---|
| 反馈：支撑率 0.75→0.85 | 11.50 → 12.85 | 1 → 1 | ROLLBACK（运费增幅超过 5%） |
| 反馈：门端负荷上限 18000→15000 kg | 11.50 → 11.50 | 1 → 1 | KEEP |
| 参数：换层式构造 | 11.50 → 12.25 | 1 → 1 | ROLLBACK |
| 参数：换块式构造 | 11.50 → 12.85 | 1 → 0 | ROLLBACK |
| 参数：墙深只取最大深度 | 11.50 → 12.85 | 1 → 0 | ROLLBACK |
| 规则：关闭先卸后装（有害但合法） | 11.50 → 10.75 | 1 → 0 | ROLLBACK（放松安全底线） |

"关闭先卸后装"能把运费从 11.50 降到 10.75——一个只看运费的优化器会接受它，门禁把它拒绝了。

## 真实装柜单验证（匿名汇总）

数据：23 份货代装柜单，每份是一个**已经装好的柜**的明细，合计 25,320 箱、申报 1,823 m³、约 315 t，品类是普货纸箱（服装、家居、饰品等）。没有易碎、危险品、不可倒置、卸货顺序等字段，也**没有柜型列**；缺"可倒置"字段按只能直立处理。只有 3 份带外箱尺寸（7 种标准箱规，另有少量"超大件"不带尺寸）；其余 20 份只有件数、实重、方数。

柜型推断：23 份里有 22 份的申报方数超过 40HQ 的几何容积（76.35 m³），所以按 45HC（86.0 m³）计；现有方案的申报装载率是 45HC 的 88%–105%，中位 91%。

以下所有方案都是**刚性名义尺寸、只能直立、支撑率 ≥ 75%**，全部经 `verify.py` 校验可行；没有打开压缩/放倒。

**A. 3 份带外箱尺寸的柜单**（名义体积占 45HC 的 84.7% / 86.4% / 90.5%；新内核每个构造思路 / Agent 2 s）

| 方案 | 总柜数 | 总相对运费 | 相对现有方案 |
|---|---|---|---|
| 现有人工方案（假设 45HC） | 3 | 5.55 | — |
| B0 经验基线（只用 40HQ） | 6 | 9.60 | +73% |
| B1 旧内核贪心 | 6 | 7.80 | +41% |
| B2 旧内核 + 同等算力搜索 | 6 | 7.80 | +41% |
| 旧 AURA（第一版，各 8 s） | 5 | 7.05 | +27% |
| 墙式 / 层式 / 块式 / 人工经验（各自单跑） | 3 | 5.55 | **0%** |
| **AURA 多 Agent** | **3** | **5.55** | **0%** |

**3 份都装进 1 个 45HC，装载率 = 名义体积占比（84.7%–90.5%），与人工持平。** 块构造内核纯贪心（几毫秒）就能装下其中 2 份，第 3 份（90.5%）需要前瞻搜索（几十毫秒）。

**A′. 加压测试**：把这 3 份的件数都乘 1.2（一个 45HC 装不下），比较单个 45HC 能装到多少（`--fill`）：

| 方案 | 单柜装载率（3 份加权） | 3 份分别 |
|---|---|---|
| 旧内核（第一版敏感性测试，60 s） | — | 81%–85% |
| 墙式 | 95.0% | 96.7% / 94.7% / 93.7% |
| 层式 | 93.5% | |
| 块式 | 92.9% | |
| 人工经验 | 94.2% | |
| 墙式 ×4 算力 | 95.0% | |
| AURA 多 Agent | 95.0% | 96.7% / 94.7% / 93.6% |

**B. 全部 23 份**（其中 20 份的箱子尺寸由 `方数/件数` 估算，每行一个尺寸，只能看量级；有一份申报方数超过 45HC 容积，不可能装进 1 柜）：

| 方案 | 总柜数 | 总相对运费 | 相对现有运费 | 一柜装下的份数 |
|---|---|---|---|---|
| 现有人工方案 | 23 | 42.55 | — | 23 |
| B0 / B1 / B2 | 47 / 46 / 45 | 75.20 / 60.55 / 59.30 | +77% / +42% / +39% | 0 / 0 / 1 |
| 旧 AURA | 45 | 59.05 | +39% | — |
| 墙式 / 层式 / 块式 / 人工经验 | 31 / 36 / 34 / 35 | 50.30 / 55.05 / 52.80 / 53.80 | +18% / +29% / +24% / +26% | 15 / 10 / 12 / 11 |
| 墙式 ×4 算力 | 30 | 49.30 | +16% | 16 |
| **AURA 多 Agent** | **29** | **47.80** | **+12%** | **17** |

只给 1 个 45HC 时（`--fill`），AURA 的加权装载率 90.8%，23 份里 17 份装完（剩 281 箱）；墙式 ×4 算力同为 90.8%、17 份装完（剩 288 箱）。

**多 Agent 的贡献（同等算力对照）**：B 组 AURA 比"墙式 ×4 算力"少 1 柜、运费 −3.0%（3 份更好、0 份更差）；A 组和 A′ 组持平（3 份带尺寸柜单的箱规少、墙式本身已接近最好）。

**人工经验权重演化**（训练集 = B 组 23 份单柜装载，留出集 = A′ 组 3 份，3 代 × 11 个候选，每代候选在各自 fiber + overlay 里并行回放）：
- 3 代都是"选能把空隙拼满的箱规"这条经验的权重被调高（0 → 0.2 → 0.52 → 1.03），其余候选 ROLLBACK；"压缩容差 0.02"（训练集装载率合计 +2.9%）和"允许倒放"（+1.4%）每代都因放松刚性底线被 ROLLBACK。
- 训练集装载率合计 20.51 → 20.84（平均 89.2% → 90.6%），留出集 2.683 → 2.737（平均 89.4% → 91.2%），都在演化用的快速确定性搜索（单轮、宽度 4）下测得。
- **但在实际使用的 2 s 随机搜索下没有收益**：调好的人工经验构造器在留出集上单跑 94.2% → 93.8%；把它放进 AURA 后，A′ 组持平（95.0%），B 组 29 柜不变、运费 47.80 → 48.05。即演化学到的是"弥补快速搜索的不足"，搜索时间够长时这部分已被搜索本身覆盖。

**结论**
- **对带真实箱规的 3 份柜单，按刚性名义尺寸已与人工持平**（各 1 个 45HC，84.7%–90.5%），比第一版少 2 柜；件数加 20% 时单柜能装到 93.6%–96.7%，说明内核在这类箱规上已有余量。
- 这批柜单本来就是满柜，所以**运费下降 10–18% 仍不成立**：持平就是上限。按申报方数算，23 份全部混装的理论下界是 22 柜（最多省 1 柜，4.3%）；按线路分开装下界是 24 柜。要省钱只能靠前面的"哪些票拼哪个柜"（拼箱选择 / 配载计划），而不是柜内摆放。
- 估算尺寸的 20 份上 AURA 仍比人工多 6 柜：这些份数的"箱子"是按方数平均出来的，每行尺寸都不同，几乎没有同规格可成墙，不代表真实箱规。要得出真实结论，需要这些柜单的外箱尺寸。

## 与 Java / Python / Rust 实现的客观对比

先说明：装箱内核是 C++，速度与 Rust/Java 同档；Aura 的优势在内核外层（规则配置、多方案并行、安全演化）。

| 维度 | Aura + C++ 内核 | Java | Python | Rust |
|---|---|---|---|---|
| 装箱内核速度 | C++，快 | 快 | 慢 10–50 倍，需 C 扩展/OR-Tools | 快 |
| 客户规则配置 | EDSL 规则，运行中热改，不发版 | 接 Drools 等规则引擎或改代码发版 | 可脚本化，但无约束检查 | 改代码重新编译 |
| 多方案并行试 | 每个 Agent 独立 fiber + COW overlay，胜者 commit、其余 rollback | 自行深拷贝+加锁或多进程 | GIL 限制，基本靠多进程 | 安全但需自建隔离与合并 |
| 策略自演化 | overlay 试跑 + 门禁 keep/rollback + 审计日志 | 需自建版本化、沙箱、回放 | 同 Java | 同 Java |
| 方案可解释 | 规则命中与变更有审计记录，可直接生成报告 | 需自行埋点 | 需自行埋点 | 需自行埋点 |
| 生态与人才 | 生态小，需要学习 | 最成熟 | 算法库最多 | 增长中，学习曲线陡 |

**实测证据**（见上文各节）：
- 多 Agent 在同等算力下比最好的单策略少 1 柜、运费约 −3%（合成 12 单 −2.9%，真实 23 份 −3.0%）。
- 门禁自动回滚"压缩容差 / 允许倒放"：它们让训练集装载率 +1.4%–2.9%，但违反刚性底线，每代都被 ROLLBACK；"关闭先卸后装"能降运费，也被门禁拒绝。
- 构造思路和评估规则都是规则文件（`aura/strategies.aura`、`aura/rules.aura`、`PC_STRATEGIES` / `PC_RULES` / `PC_CONS_RULES`），换策略不改 C++。

**不能夸大**：
- 装载率来自 C++ 内核，用 Rust/Java 写同样的算法，结果一样。
- Java + Drools + 自建沙箱也能做到类似效果，大约要多几个人月的基础设施。
- Aura 自身的稳定性仍需加强：并发 `json-parse` 崩溃（[aura#4788](https://github.com/cybrid-systems/aura/issues/4788)）已修复；开发机上出现过一个 aura 进程 9.5 GB 被 OOM 杀掉（发生在 aura 自身的 CI 容器里，不是本原型；本原型 `main.aura` 跑 12 单的峰值 RSS 约 172 MB，拼柜协调器约 124 MB）。

**一句话**：装得满靠算法内核，与语言无关；新规则当天上线、多方案并行对比、越用越准且不乱改，靠 Aura。

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

- 3 份带尺寸柜单的"与人工持平"是按**名义箱规**、刚性尺寸、只能直立、75% 支撑率算的；现场可能有尺寸偏差，箱规表里没有的"超大件"没有参与。
- 其余 20 份柜单的箱子尺寸是按 `方数/件数` 估的（每行一个尺寸），与真实箱规分布差别很大，只能看量级；在这批上 AURA 仍比人工多 6 柜。
- 运费是相对值占位；真实对比需要按航线/柜型的报价。
- 门端/前端负荷是两点支撑的近似；堆码承重只算直接压在上面的货，不做载荷传递。
- 重心居中依赖整体平移，现实中需要垫木或绑扎；没有建模绑扎、托盘、叉车作业空间。
- 块构造内核只用同规格块（不做异规格组合块），柜间不做交换；下界较松，无法给出最优性证明。
- 人工经验权重演化的适应度用的是快速确定性搜索（单轮、宽度 4）；在 2 s 随机搜索下，演化出的权重没有带来提升（见上文），说明适应度和实际使用的搜索模式需要对齐。
- 合成数据的分布（纸箱 / 托盘 / 长件比例）是猜的，真实订单的结果可能完全不同。
