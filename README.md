# aura-loading-prototype

用 **C++ 三维装箱内核** 求解，用 **Aura** 写规则、跑多 Agent 并行提案和带安全门禁的策略演化。给一批订单，输出可独立校验的装柜方案、费用和决策解释。

**一行跑起来**（Linux/macOS，只要 `python3` + `g++` + `git` + `curl`）：

```sh
curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-loading-prototype/main/run.sh | sh
```

它会自动装 Aura v0.2.0、编译内核、跑一个 1.5 秒的装柜 demo，再用 Aura 的进化栈跑一遍 52 周货位组合搜索。约 1–2 分钟（含下载 Aura），输出：

```
containers=3 mix=1x20GP+1x40HQ+1x45HC cost=4.45 vol_util=0.8613 unplaced=0
verify: OK
3D replay: out/b.html

seed  family   SBS    port   gain       CI
   7  bulk    8.74    6.75  +15.0%  [+10.5,+32.4]
   7  basket 78.40   49.93  +36.6%  [+31.4,+41.1]
      worst family bulk +15.0%  | mixed +31.7%
```

已经 clone 了？`./run.sh`。只想看内核 demo：`AURA_SKIP_EVO=1 ./run.sh`。

## 实测结果（全部合成数据，`tools/verify.py` 独立校验）

| 场景 | 对比 | 结果 |
|---|---|---|
| 12 单装载 | AURA 4 Agent vs 同算力单策略 | 26 vs 27 柜，运费 **−2.9%** |
| 6 条线路拼柜 | Aura 4 Agent vs 单进程 LNS | 27 vs 28 柜；比按到货顺序 **−16.1%** |
| 52 周货位组合 | `std/portfolio` vs 全年 SBS | 最差族中位 **+26.8%**，5/5 seed 的 CI 下界 > 0 |
| 同上，混合流 | 组合 vs SBS | 中位 **+33.7%**；拿到 oracle 上界的 **90–96%** |
| MOEA/D 前沿 | `std/moead`，峰值周膝点 | **5/5 命中**；距离比 0.930–0.993，通道方差比 0.823–0.898 |
| 多目标 | `std/moead` + `std/pareto` | **234 个 Pareto 点**，全部经 `verify.py`，0 不可行 |
| 安全门禁 | 15 个放松底线候选 × 5 seed | **15/15 ROLLBACK**，0 个坏 KEEP |

协议、逐 seed 数字和失败项：[docs/v02-downstream-report.md](docs/v02-downstream-report.md)。上表的 v0.2 项目在 tag `v0.2.0`（`cf7353373`）上复测：B1/B3 逐 seed 数字一致，Pareto 234 点全部经 `verify.py` 校验。

## 最新 Aura v0.2 用在哪

- `std/portfolio`：14 个成员（8 个构造 Agent、nf/ff/ffd/LNS、MOEA/D、NSGA-II）注册、预算分配与 successive-halving。
- `std/algo-select`：7 维特征、kNN 选 4 个候选；收益来自**每个窗口换对成员**，不是给每个成员堆算力。
- `std/moead` ask/tell：Aura 进程持有 MOEA/D 状态，Python 只负责给货位方案打分；`std/pareto` 出 NSGA-II 前沿。
- `tools/verify.py`：不采信求解器自报，独立校验越界、重叠、超重、支撑率、先卸后装。

## 为什么是 Aura（差异化）

1. **多方案并行，不互相污染。** 每个 Agent 一个 fiber + COW overlay，提案期间互不可见；协调器裁决后胜者 commit，其余 rollback。同等算力下比最好的单策略少 1 柜、运费约 −3%（合成 12 单 −2.9%，真实 23 份 −3.0%）。
2. **策略是数据，不是代码。** 硬约束、校验、权重、构造思路、派发规则、拼柜现场规则都是 `.aura` / sexp 文件，用 `PC_RULES` / `PC_STRATEGIES` / `PC_CONS_RULES` 换掉即可，热改不发版。
3. **演化有门禁，不乱改。** 每个候选在 overlay 里回放，过门禁才 commit。放松安全底线的改动——关掉先卸后装、压缩、倒放——即使能降运费或提装载率，也每次 ROLLBACK，审计留痕。
4. **决策可解释、离线可复算。** 每单/每条线路输出 `explain.md`：各 Agent 结果、否决理由、overlay 状态。派发规则在 Aura 里执行，同时被 `tools/agent_matrix.py` 离线复算，测试检查两边一致。

装得满靠 C++ 内核（换 Rust/Java 写同样的算法，结果一样）；Aura 的差异在**内核之外**：规则热改、多方案隔离对拍、安全演化。更细的对比见 [docs/DETAILS.md](docs/DETAILS.md)。

## 真实柜单（匿名汇总，数据不入库）

23 份货代装柜单、25,320 箱，只在本地跑，只把汇总结果写在这里。

- **柜内摆放**：3 份带外箱尺寸的柜单与人工持平——各 1 个 45HC，名义装载率 84.7%–90.5%。其余 20 份的箱子尺寸按 `方数/件数` 估算，只能看量级。
- **拼柜**：15 份按线路重新拼，与人工持平（15 柜）。
- 所以“运费降 10–18%”**不成立**：这批柜单本来就是人工拼好的满柜，持平是上限。详见 [报告](docs/v02-downstream-report.md)。

## 深入

- [实现细节与完整实测](docs/DETAILS.md)：内核建模、全部基线、专家派发、限制、开发中碰到的 Aura 问题。
- [v0.2 下游验证报告](docs/v02-downstream-report.md) · [装载基准](docs/bench-synthetic.md) · [决策解释](docs/explain-synthetic.md) · [PK 盲测](docs/PK.md) · [数据格式](docs/FORMAT.md)

常用命令：

```sh
python3 build.py demo --block                      # 块构造 + 校验 + 3D 回放
python3 slotting/run_slotting.py --seeds 7,11,13,17,19
AURA_PATH=/path/to/aura/lib tools/portfolio_v02.sh all
python3 tests/test_slotting.py                     # 成本模型 / 约束 / B1 判据 / B3
AURA_BIN=/path/to/aura-0.2.0/bin/aura python3 bench/v020/run_v020.py
```

运费是相对值（20GP/40HQ/45HC = 1.00/1.60/1.85），真实报价用 `PEICANG_CONTAINERS` 替换。仓库不包含任何客户数据；示例和测试全部由 `tools/gen_synthetic.py` 生成。
