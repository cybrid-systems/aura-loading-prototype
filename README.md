# aura-loading-prototype

配仓是硬约束求解，加上一大堆会变的客户规则。C++ 内核负责把柜子装得满；Aura 把规则写成可以热改、可以并行试、可以安全演化的数据。给一批订单，得到装柜方案、费用，以及一份给调度员的解释。

## 为什么用 Aura

1. **客户规则当天生效，不用发版。** 禁混装、限柜型、限重、站序（先卸后装）、重心、支撑率、危险品间距写在 `.aura` / S-expression 里。调度员改文件、设 `PC_RULES`，内核二进制不动。对比改 C++/Java 再发版，或对接 Drools 仍要走一趟上线。
2. **多策略并行试，胜者提交、败者回滚。** 每个思路一个 fiber + COW overlay，互不污染；协调器评分和校验之后，胜者 commit，其余 rollback。同等算力下比最好的单策略少柜、运费约 −3%（合成 12 单 −2.9%，真实 23 份 −3.0%）。
3. **规则可以安全地自己进化。** 候选在 overlay 里回放历史订单。安全底线不能放松、违例不能增加、运费不能乱涨，过了才 KEEP，否则 ROLLBACK，全程留审计。放松底线的候选 **15/15 ROLLBACK**。
4. **可解释、可审计。** 每单写明哪个 Agent 提案、为什么被否决、最后选了谁。规则命中、变更和回滚都有记录。

| | Aura 规则 | 硬编码 C++/Java | Drools | 纯求解器 |
|---|---|---|---|---|
| 客户规则当天生效 | 改文件，`PC_RULES` 热替换，内核不发版 | 改代码再发版 | 规则能改，仍有上线流程 | 约束在模型里，改完要重走求解 |
| 多方案并行、败者回滚 | fiber + COW overlay | 自己做隔离 | 自己做隔离 | 一次一个模型 |
| 规则自己进化 | overlay 回放 + 门禁 + 审计 | 自己做沙箱和回放 | 自己做 | 没有这层 |
| 给调度员的解释 | 规则命中和选案写进 explain | 自己埋点 | 有规则命中日志 | 通常只给方案 |

装得满靠内核。用 Rust 或 Java 写同样的算法，装载结果一样。Aura 的差别在内核外面。

真实柜单上「运费降 10–18%」不成立：那是已经拼好的满柜，持平是上限。派发和演化的收益目前在噪声里。协议和全部数字见 [报告](docs/v02-downstream-report.md)，实现和限制见 [docs/DETAILS.md](docs/DETAILS.md)。

## 一行跑起来

Linux / macOS，要有 `python3`、`g++`、`git`、`curl`：

```sh
curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-loading-prototype/main/run.sh | sh
```

这一行会安装官方 Aura v0.2.0、编译内核、跑一个短装柜，再用货位演化跑 52 周合成数据。已经 clone 了就 `./run.sh`。只看内核：`AURA_SKIP_EVO=1 ./run.sh`。缺哪个命令，脚本会写明该装什么。

## 三条演示

```sh
./run.sh rules      # 先出合法方案，再换线路规则。旧方案被哪条规则拒绝、新方案、历史回放
./run.sh evolve     # 关闭先卸后装 / 压缩 / 倒放 → ROLLBACK；收紧门端载荷 → KEEP
./run.sh agents     # 各 Agent 的柜数和运费、谁提交、谁回滚、explain 路径
```

改哪几个键：[docs/rules.md](docs/rules.md)。演示用合成订单，屏幕上的柜数和运费是这一次跑出来的。换自己的文件：

```sh
PC_RULES=rules/customers/acme.sexp ./run.sh rules
```

规则文件写错会指出行号和键名。失败会标明是规则、校验、内核还是 Aura。换一条规则不会重编 C++。

运费是相对值（20GP / 40HQ / 45HC = 1.00 / 1.60 / 1.85）。仓库里没有客户数据。
