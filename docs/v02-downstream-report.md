# v0.2 下游验证报告：aura-loading-prototype（P9，仅合成数据）

> 仓库：cybrid-systems/aura-loading-prototype，基线提交 `240551e`（main）。
> Aura 固定到 **99ddc81c9**（v0.2.0-rc 线，`std/portfolio`、`std/algo-select`、`std/hyper-heuristic`、`std/moead`、`std/pareto`、`std/evo-core` 均已在该提交）。
> 本报告所有数字都来自 `tools/gen_synthetic.py` / `tools/gen_pool.py` / `slotting/gen_slotting.py` 生成的**合成**数据；没有读取、推导或提交任何真实柜单。

## 0. 结论摘要

| 验收项 | 结果 | 一句话 |
|---|---|---|
| A1 实际算力偏离预算 ≤10% | **部分通过** | 装载矩阵 8 个 Agent 共 960 次运行，中位偏离 −2.4%～−3.1%，100% 在 ±10% 内；逐级淘汰的 1142 ms 时间片只有 64%–82% 在 ±10% 内（中位 −5%～−8%）；拼柜层超出预算 2–7 倍（见 5.2，PARTIAL） |
| A2 按特征选择 + 淘汰 优于固定 4 Agent（p<0.05） | **未通过（在噪声内）** | 留出集总运费 164.5 vs 164.7（+0.12%），配对 t=0.19，p=0.43 |
| A3 SBS→VBS 间隙闭合 ≥40% | **通过（但间隙本身很小）** | 81.8%（按 seed 平均 95%）；SBS 33.35，VBS 32.80，方法 32.90，间隙仅占运费的 1.6% |
| A4 训练升/留出降的 KEEP = 0（5 seed） | **通过** | 5 seed × 7 候选：1 个 KEEP（same-up，seed 1），其留出集也改善（+0.35）；0 个坏 KEEP |
| A5 放松安全底线 100% ROLLBACK | **通过** | 3 个放松候选（squeeze/anyrot/lifo=0）× 5 seed = 15/15 ROLLBACK-safety，审计完整 |
| A6 多目标 Pareto + verify.py 可行 | **通过** | 成员级前沿 4 个；MOEA/D+NSGA-II 232 个点；抽检 40 个成员方案 + 232 个 MOO 方案全部通过 `tools/verify.py`，0 不可行 |
| B1 组合+在线 最差窗口比 SBS 低 ≥5% | **未通过** | 5 seed 平均 −0.86%（最好 +4.14%，最差 −6.47%） |
| B2 漂移后 ≤2 窗口切换 | **通过** | 5/5 seed 在漂移周 27 之后的第 28 周完成切换（1 个窗口） |
| B3 MOEA/D 前沿中存在距离不劣于 SBS 且通道方差 −10% | **部分通过** | 5 seed 中 2 个（s11、s17）找到这样的点，3 个没有 |
| B4 EoH 启发式 KEEP 的 leave-one-out 正边际 | **未完成（PARTIAL）** | 本轮只落了骨架：4 个成员 + 在线漂移；MOEA/D 为 Python 版，未接 std/moead；EoH 未做 |

## 1. 固定条件

- 数据：训练 12 单（`examples/synthetic`，seed 7，7099 箱），留出 12 单（`examples/holdout-synthetic`，seed 71），拼柜 12 条线路（`examples/pool-v02`，seed 23）。
- seed：1–5；所有对比都按 seed 配对。
- 装载预算：每 Agent 2000 ms（矩阵 / 固定 4 Agent）；逐级淘汰总预算 4×2000=8000 ms，4 个候选 → 7 个时间片，每片 1142 ms。
- 硬件：14 核 Linux（arm64 容器），每个 shard 独立进程并行；Aura 侧顺序执行成员，成员内部再并行。
- 只用合成数据；`out/` 不进仓库。

## 2. 实现

| 文件 | 作用 |
|---|---|
| `aura/portfolio.aura` | 把 8 个构造 Agent、拼柜 nf/ff/ffd/LNS、MOEA/D、NSGA-II 共 14 个成员登记进 `std/portfolio`（`portfolio:build`）；成员工厂调用 `tools/pc_eval.py`，MOO 成员的基因组解码成内核权重 |
| `aura/portfolio-main.aura` | 驱动：`matrix`（单 seed 矩阵分片）、`select-halving`（`select:offline` + `alloc "successive-halving"`）、`eoh`（`tune:gate` 配对门禁 + 安全底线）、`moo-front`（`std/moead` + `std/pareto` NSGA-II 的真实前沿） |
| `tools/pc_eval.py` | 成员求值器：每个成员在一个墙钟预算内求解一个合成订单，写 `verify.py` 可复检的方案 JSON，最后一行打印标量分数。预算内提前收敛就用下一个 seed 重启，直到预算用完（与内核自身的随机重启同一约定） |
| `tools/portfolio_v02.sh` | 分阶段驱动（matrix/halving/cons/eoh/moo），每个 seed 一个并行 shard |
| `tools/portfolio_merge.py` / `tools/portfolio_report.py` | 多 seed 矩阵合并；从原始 TSV 聚合报告数字 |
| `slotting/` | 合成货位分配：生成器、目标函数、4 个成员、滚动窗口在线选择、MOEA/D-lite |

**选择器**：`select:make (hash "model" "knn" "k" 2 "sense" "min")`，特征为箱规种数、装载压力、超长件占比、卸货站数、密度、重量填充率、易碎占比（7 维）。k=2 是在训练矩阵上做模型选择得到的（k=1/3/5 的 LOO 间隙闭合分别为 −1.7%/−81.7%/−69.6%，k=2 为 +9.6%）。

**淘汰**：对每个留出订单，选择器给出 4 个候选，`portfolio:run` 用 `alloc "successive-halving"` 把这 4 个候选淘汰到 1 个，总预算与固定 4 Agent 相同（8000 ms）。

**已知上游问题**：在 99ddc81c9 上，`std/algo-select` 的 `select-tree-total`（algo-select.aura:225）用特征下标去索引成员分数行；当特征数 > 成员数时，即使 `model="knn"` 也会在 `select:offline` 里越界。本工作把特征压到 7 维（< 8 个成员）规避，并在报告里记录，没有改 aura 源码。

## 3. A. 装载 / 拼柜验收

### A1 算力对齐（审计可查）

装载矩阵 8 个 Agent × 12 单 × 5 seed = 480 次/数据集，预算 2000 ms：

| Agent | 运行数 | 预算中位 (ms) | 实际中位 (ms) | 中位偏离 | ±10% 内 |
|---|---|---|---|---|---|
| wall | 120 | 2000 | 1943.7 | −2.8% | 100% |
| layer | 120 | 2000 | 1948.3 | −2.6% | 100% |
| block | 120 | 2000 | 1949.7 | −2.5% | 100% |
| human | 120 | 2000 | 1945.3 | −2.7% | 100% |
| oversize | 120 | 2000 | 1946.9 | −2.7% | 100% |
| cog | 120 | 2000 | 1943.4 | −2.8% | 100% |
| mixed | 120 | 2000 | 1941.0 | −2.9% | 100% |
| fitgap | 120 | 2000 | 1946.3 | −2.7% | 100% |

逐级淘汰时间片 1142 ms（2100 次成员运行，含早期未加余量的重复运行）：

| 成员 | 运行数 | 实际中位 (ms) | 中位偏离 | ±10% 内 |
|---|---|---|---|---|
| wall | 595 | 1053.5 | −7.7% | 66% |
| layer | 300 | 1052.8 | −7.8% | 64% |
| block | 372 | 1063.0 | −6.9% | 74% |
| human | 324 | 1054.7 | −7.6% | 71% |
| mixed | 206 | 1078.8 | −5.5% | 79% |
| oversize | 197 | 1081.1 | −5.3% | 82% |
| fitgap | 106 | 1063.0 | −6.9% | 81% |

结论：装载主线的 2000 ms 预算对齐通过（无超支，全部在 ±10% 内）；1142 ms 的小时间片受内核“一次搜索迭代”粒度影响，约 1/4–1/3 的运行落在 −10%～−15%，**如实记为部分通过**。另外，早期版本余量不足时曾把所有成员判成 cancelled，导致该轮没有胜者；最终版用“固定开销 + 3%”的余量修正（`tools/pc_eval.py:margin`）。

### A2 按特征选择 + 淘汰 vs 固定 4 Agent（同等实际算力）

留出集 12 单 × 5 seed，总运费（越低越好）：

| seed | 固定 4 Agent (wall+layer+block+human) | 选择+淘汰 | 差值（正=选择更好） |
|---|---|---|---|
| 1 | 33.30 | 32.95 | +0.35 |
| 2 | 32.20 | 32.95 | −0.75 |
| 3 | 32.95 | 32.95 | 0.00 |
| 4 | 32.95 | 32.70 | +0.25 |
| 5 | 33.30 | 32.95 | +0.35 |
| **合计** | **164.70** | **164.50** | **+0.20 (+0.12%)** |

配对单侧 t 检验（n=5）：均值差 0.04，sd 0.46，t=0.19，p=0.43。**达不到 p<0.05；结论是“在噪声内”，方向略正但不能宣称收益。** 原因可查：合成订单的运费是柜型组合的离散值，12 单里 5 单所有 Agent 同价；同一 seed 内选择器和固定 4 Agent 的短名单高度重叠。

### A3 SBS→VBS 间隙闭合（留出集）

- SBS（最好的单一 Agent，按 12 单均值）：**33.35**（wall）
- VBS（逐单取最好成员再平均）：**32.80**
- 方法（选择+淘汰）：**32.90**
- 间隙闭合：**81.8%**（(33.35−32.90)/(33.35−32.80)）；按 seed 分别计算的平均为 95%，单 seed 范围 −25%～+200%。

**通过 ≥40%，但必须同时说明：SBS–VBS 间隙只有 0.55（运费的 1.6%），分母很小，这个百分比很不稳定。** 它不是“方法接近最优”的强证据。

### A4 演化门禁（新门禁下无“训练升、留出降”的 KEEP）

5 个 seed × 7 个候选（4 个权重提案 + 3 个安全放松），每个候选在 12 个训练单上以 `tune:gate`（单侧配对 t，α=0.05，n=12）判定，KEEP 后再在 12 个留出单上复核：

- KEEP：**1**（same-up，seed 1；t=1.796，p≈0.0499；训练集总运费下降 2.60，留出集下降 0.35，两项都改善）
- ROLLBACK-gate：19
- ROLLBACK-safety：**15/15**（squeeze=0.02、anyrot=1、lifo=0 各 5 次，全部拒绝，审计行完整）
- **训练升/留出降的 KEEP：0**（5 个 seed 全部满足）

### A5 多目标 Pareto（运费、重心偏差、门端负荷）

- 成员级（12 留出单 × 5 seed，取均值）：前沿 4 个点

| 成员 | 运费 | 重心偏差 | 门端负荷 |
|---|---|---|---|
| block | 2.7833 | 0.1793 | 0.5051 |
| wall | 2.7858 | 0.1317 | 0.4960 |
| mixed | 2.7983 | 0.1319 | 0.4943 |
| fitgap | 2.8025 | 0.1668 | 0.4906 |

- MOEA/D 与 NSGA-II（`std/moead` / `std/pareto`，3 目标，8 s/实例，4 个留出单 × 5 seed）：**232 个前沿点**。
- 可行性：抽检成员方案 40 个（每个成员 5 个）+ MOO 全部 232 个方案，`tools/verify.py` **0 失败**。

## 4. B. 合成货位分配（`slotting/`）

骨架已落地：180 个货位（6 通道 × 10 列 × 3 层）、140 个 SKU（含 5% 危险品）、共购关联矩阵、52 周订单流（第 27 周季节结构漂移，第 40–44 周峰值）。成员：ABC（体积）、周转率就近、关联贪心、局部搜索（交换）；在线：滚动窗口 + 总变差漂移检测 + 每窗口重排。MOEA/D 为 Python 版 Tchebycheff 局部搜索（不是 `std/moead`）。

| seed | SBS 最差窗口距离 | 在线最差窗口距离 | 改进 | 切换周（漂移 27） | MOEA/D 前沿点数 | 存在“距离不劣、方差 −10%”的点 |
|---|---|---|---|---|---|---|
| 7 | 79.93 | 78.51 | +1.78% | 28 | 11 | 否 |
| 11 | 81.84 | 78.45 | +4.14% | 28 | 10 | 是 |
| 13 | 72.61 | 75.07 | −3.38% | 28 | 13 | 否 |
| 17 | 80.27 | 80.55 | −0.35% | 28 | 9 | 是 |
| 19 | 73.41 | 78.16 | −6.47% | 28 | 9 | 否 |

- B1：5 seed 平均 **−0.86%**，最好 +4.14%，**未达到 ≥5%**。最差窗口通常出现在漂移后的第一个窗口（在线策略还来不及换布局），这是滚动重排的固有滞后。
- B2：**通过**，漂移周 27 → 第 28 周切换，1 个窗口。
- B3：**部分通过**（2/5 seed 找到满足条件的点）。
- B4：**未完成（PARTIAL）**——没有把 EoH 生成的启发式接进组合，也没有 leave-one-out 边际贡献。

## 5. 零回归、CI 与 pin

### 5.1 零回归
- `kernel/`、`tools/bench.py`、`tools/verify.py`、`tools/consolidate.py` 均未修改（`git diff --stat` 见提交）。
- 用 `tools/bench.py --strategies` 在 order_01 上复跑：B0 2×40HQ/3.20/47.2%，B1、B2、S_wall 均为 1×20GP+1×40HQ/2.60/65.8%，与 `docs/bench-synthetic.md` 的 order_01 行逐格一致；`verify.py` 对全部方案报 feasible。`tests/run_tests.sh` 的 Aura 部分需要 dev 镜像里的旧 aura 二进制，本机未跑，故只对内核/工具链做上述复核。
- 新代码只在 `aura/portfolio*.aura`、`tools/pc_eval.py`、`tools/portfolio_*.py|sh`、`slotting/`、`examples/holdout-synthetic`、`examples/pool-v02`。

### 5.2 拼柜层（nf/ff/ffd/LNS）——PARTIAL
拼柜成员已登记并跑过矩阵，但 `tools/consolidate.py` 在这个规模上单条线路的构造阶段就要 6–16 s（nf 6.3 s、ff 8.6 s、ffd 11.1 s、LNS 14.2 s），2 s 预算完全包不住（实测中位偏离 +216%～+611%）。把预算改成 12 s 重跑时，也只完成了部分线路。**因此拼柜层的“实际算力对齐”和 SBS/VBS 对比记为 PARTIAL，不作为本次通过项。**

### 5.3 CI 与 pin
- `ci/test.yml` 增加 `tools/v02_smoke.sh`（合成数据、小预算：6 个成员各 300 ms + 8 窗口 slotting）。
- Aura pin：`99ddc81c9`；运行时要求 `AURA_PATH=<aura>/lib`（`tools/portfolio_v02.sh` 会检查）。
- CI 只跑合成数据；`out/` 不入库。

## 6. 限制

1. 运费是**相对值**且离散（1.00/1.60/1.85 组合），所以很多订单所有 Agent 同价；SBS–VBS 间隙只有运费的 1.6%，A3 的百分比虽然过线，统计意义弱。
2. 8 个构造 Agent 在 2 s 预算内大量同解，选择器的特征信号弱；A2 的“噪声内”是数据性质，不是实现 bug。
3. 逐级淘汰的 1142 ms 时间片小于内核搜索迭代粒度，导致一部分运行偏离预算 10%–15%。
4. MOEA/D/NSGA-II 作为成员时每次评估都要起一个内核进程，3 目标搜索在 2 s 内只能做十几次评估；真正的前沿用 8 s 单独跑。
5. B 的在线策略每窗口重排有 1 个窗口的滞后；MOEA/D 是 Python 版，未接 `std/moead`；EoH 边际贡献未做。

## 7. 复现

```bash
export AURA_PATH=/path/to/aura-99ddc81c9/lib   # aura checkout at 99ddc81c9
python3 build.py
tools/portfolio_v02.sh all                     # 约 20–30 分钟，14 核
python3 slotting/gen_slotting.py --seed 7 --out slotting/data/s7.json
python3 slotting/run_slotting.py --seed 7 --out slotting/out/s7.json
python3 tools/portfolio_report.py --root out/v02
tools/v02_smoke.sh                             # CI 用的 1 分钟冒烟
```

审计文件：`out/v02/{train,holdout}/audit_s*.tsv`（成员、问题、预算、实际耗时、可行、seed）、`out/v02/halving/halving-audit_s*.tsv`（每轮成员预算/实际/状态/分数）、`out/v02/eoh/eoh_s*.tsv`（提案、KEEP/ROLLBACK、t、训练/留出差）。
