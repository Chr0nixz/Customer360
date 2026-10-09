# Benchmark 扩展计划

文档状态：2026-10-06 N0–N2 闭环落地版（N0 封堵数据泄露、N1 隐藏语义与真实网关验收、N2 版本链锁定全部通过，见[扩展验收与下一阶段计划](acceptance-and-next-plan.md)）。

本文回答一个具体问题：当前 benchmark 是否还需要扩大，以及扩大应优先落在哪些边界。本文补充 [路线图](../ROADMAP.md) 和 [后续开发计划](development-plan.md)，不改变 v1.0 的评分权重、Gold 生成流程、公开/隐藏切分、SQL Guard 或权限语义。

## 1. 结论

当前不需要继续扩大数据库的行数，也不应先把公开题包从 300 题直接扩到 1,000 题。已实现但尚未整体验收的扩展重点落在：

1. 扩大可执行的 Join 语义覆盖（从 1 条扩充至 5 条完整闭环）；
2. 修正题目在模板、聚合、分组和失败类型上的结构性偏斜（当前 seed-42 生成结果：客户过滤 84，Group By 37，Join 38，指标 30/30 覆盖）；
3. 增加隐藏集规模和分层抽样（从 30 题扩至 60 题；当前生成结果为 34 answer / 15 clarification / 11 refuse / 8 null_handling）；
4. 保持 Standard/Large 作为独立的性能与资源诊断轨道。

## 2. 当前基线与扩展达成对比

### 2.1 数据规模

| 规模 | 客户数 | 交易数 | 定位 | 当前策略 |
|---|---:|---:|---|---|
| Tiny | 100 | 2,000 | 日常回归、Gold 核验、四类变体 | 默认评测和 CI |
| Standard | 10,000 | 300,000 | 集成和性能诊断 | nightly/perf，不混入 Tiny 语义分数 |
| Large | 100,000 | 3,000,000 | 压力和性能诊断 | 仅显式运行 |

三档数据使用同一业务语义和比较规则。数据规模的变化应只用于检验资源、延迟和执行计划，不应改变 Gold 口径。Tiny 的每表 10,000 行物化上限继续保留。

### 2.2 任务规模

当前任务包结构：

- 20 道人工开发题，固定为 `C360_0001–0020`，用于链路和回归，不计入正式加权分数；
- 300 道公开生成题，维持 180 道 train、120 道 generated-dev；
- 60 道独立隐藏题（已由 30 题扩容完成，起始编号 `C360_4001`）；
- 正式评分分开计算 `public_dev=120` 和 `private_hidden=60`，不合并、不排名。

### 2.3 覆盖达成对照

| 项目 | 原先基线 | 扩展实施后达成 | 评估与交付状态 |
|---|---:|---:|---|
| 核心表 | 9 | 9 | 覆盖客户、交易、持仓、资产、资金流和服务关系主链路 |
| 字段 | 72 | 72 | 支撑当前业务口径 |
| 指标 | 30 | **30/30 (100%)** | 全部 30 个指标在公开包 100% 出现（已修复指标遗漏） |
| Join 元数据 | 20 | 20 | 元数据数量足够 |
| 可编译 Join | 1 | **5** | 覆盖交易、资金流、持仓、资产快照、服务关系（已闭环通过真实网关检验） |
| 公开 Join 题 | 8 | **38** | 覆盖全部 5 条可编译路径 |
| 非空分组题 | 0 | **42** | 覆盖地区、等级、渠道、交易类型等多维 Group By（N0 防泄露加固通过） |
| 公开题 `customer_filter` | 190/300 | **84/300** | 由 63.3% 降至 28.0% |
| 隐藏题 | 30 | **60** | 35 answer / 15 clarify / 10 refuse / 9 null；独立语义验收与错误类区分已全部通过 |

旧 RC 的 Baseline 诊断分数约 0.75，不能代表本轮扩展后的正式结果。当前先处理分组数据泄露和隐藏语义验收；新分数须在版本锁定后重跑。

## 3. 扩展目标

扩展分为三个独立轴，不能用一个总数掩盖其中的缺口。

### 3.1 数据轴：保持规模，补性能证据

在 v1.0.x 阶段冻结 Tiny/Standard/Large 的行数和现有 seed 摘要。新增工作只包括：

- 为 Standard/Large 固定生成和 Gold 执行的性能基线；
- 记录 P50/P95、超时、失败码、物化行数和内存上限；
- 对同一 semantic spec 在 Tiny、Standard、Large 上做结果语义回归；
- 明确扫描量和 Token 在尚未实现测量前继续标记为 `unavailable`。

只有出现以下证据时才重新评估是否扩大行数：Standard 在受控环境下无法区分执行计划差异，或 Large 仍不能触发已声明的资源边界。届时先增加单一事实表的规模变体，不直接改变所有表的比例。

### 3.2 语义轴：先扩大可执行能力

目标不是把 20 条 Join 全部实现，而是先实现 4–6 条高价值、语义边界清楚的路径：

| 优先级 | Join 路径 | 必须覆盖的风险 |
|---:|---|---|
| 1 | `customer_transactions` | 客户去重、成功状态、时间窗口、客户范围 |
| 2 | `customer_holdings` | 一对多 fanout、持仓状态、重复计数 |
| 3 | `customer_asset_snapshots` | 最新快照、指定估值日、缺失快照 |
| 4 | `customer_cash_flows` | 流入/流出方向、成功状态、净额与币种 |
| 5 | `customer_service_relations` | 当前有效关系、历史关系、空服务经理 |
| 6 | 视业务价值选择一条复合路径 | 多 Join 前置聚合、权限和资源限制 |

每条新增路径必须同时具备：连接键、方向、基数、时间有效性、允许指标、必选过滤、客户行级范围、预聚合要求、错误 SQL fixture 和独立 Python oracle。只把路径写入元数据但不能安全编译，不算覆盖完成。

### 3.3 任务轴：重平衡，不先增总量

保持公开总量 300，先把现有题包调整为可审计的覆盖配额。建议目标如下，允许每题带多个标签：

| 维度 | 当前观察 | v1.1 目标 |
|---|---:|---:|
| `answer` | 288 | 240–260 |
| `clarification_needed` | 10 | 20–30 |
| `refuse` | 2 | 10–20 |
| Join 题 | 8 | 36–48 |
| 分组/比较/Top-K | 0 或极少 | 30–45 |
| latest snapshot / point-in-time | 57 | 35–50，避免单类过密 |
| NULL/空集合/缺失关系 | 3 | 20–30 |
| 时间边界和窗口 | 27 类别、时间错误较多 | 35–45，覆盖 30/90/180 天、点时刻和边界日 |
| 权限/安全拒答 | 2 | 15–25 |
| 公开指标覆盖 | 28/30 | 30/30，且每个指标至少 2 个语义组合 |

这些是生成验收目标，不是新的评分权重。最终题包必须以独立语义 case 计数；同一 case 的改写和数据变体不重复计题。

## 4. 隐藏集扩展

隐藏集从 30 道增加到 **60 道作为第一目标，100 道作为稳定性目标**。扩展必须生成全新的 semantic family，不能把公开题改名或重新标记为 private。

建议分层：

- 40% answer：覆盖新增 Join、分组、latest snapshot、时间窗口和指标组合；
- 25% clarification：缺失时间、粒度、状态、客户范围或指标定义；
- 20% refuse：权限、敏感字段、明细导出和越权请求；
- 15% edge/error：NULL、空集合、重复 fanout、边界日期和未知字段。

隐藏集至少覆盖 4 个可执行 Join 路径、30 个指标中的 25 个、8 个模板以上，并保证 public/private 在完整 family、指标×过滤维度和数据分布三个层面分别有审计报告。四个私有变体继续使用 provenance 和 same-SQL replay；不得把隐藏 Gold、seed 或结果放进 Agent 输入。

当隐藏集达到 60 道后，报告 95% 置信区间和分层分数；在 100 道之前，private score 只作为诊断，不用于对外排序或模型结论。

## 5. 分阶段执行

### Phase E1：覆盖矩阵与契约冻结（已落地）

工作内容与交付：

1. 从当前 300 题包生成 coverage matrix，核查指标、模板、Join、时间语义、动作和偏斜；
2. 扩充 5 条可执行 Join 路径的元数据、契约支持与白名单模型（`JoinSpec`、`JoinPathCatalog`）；
3. 验证分组、Top-K、NULL、空集合与权限题的语义契约；
4. 编写专属契约测试套件 `tests/test_expansion_e1.py`（全部通过）。

### Phase E2：Join 和结果语义扩展（实现已落地，验收未完成）

工作内容与交付：

1. 已实现 5 条 Join 路径的编译、AST 校验与纯 Python 内存切片计算；
2. 专项测试覆盖重复计数和若干负例，但目前测试在校验 Guard 后使用原始 DuckDB connection 执行，没有覆盖 Gateway 的客户范围前置物化、子进程隔离和超时回收；
3. 完成真实受控 Gateway 的集成回归后，才能将 E2 标记为验收通过。

### Phase E3：任务包重平衡（实现已落地，生成契约专项测试通过）

工作内容与交付：

1. 重新生成 300 题，严格维持 180 train / 120 generated-dev 结构；
2. 实施分层配额选入算法（Tiered Quota Selection）；当前 seed-42 输出为 84 道客户过滤、37 道分组、38 道 Join、28 道澄清、15 道拒答、20 道 NULL 边界题；
3. 达成 30/30（100%）指标全覆盖保障；
4. 300 题自然语言改写与家族隔离审计 100% 通过（0 issue）；
5. `tests/test_expansion_e3.py` 的配额、改写和 family 隔离测试通过；公开 pack 的四变体独立语义验收仍须在新版本 pack 上运行。

### Phase E4：隐藏集和统计稳定性（生成实现已落地，语义验收未通过）

工作内容与交付：

1. 隐藏集从 30 题扩至 60 题（起始编号 `C360_4001`）；
2. 当前 seed-42 实际分布为 34 answer / 15 clarification / 11 refuse / 8 null_handling，覆盖 23 个指标；
3. 专项测试中的 family 隔离和改写检查通过，但尚无 metric×filter 正交审计的通过证据；
4. 对新生成的 60 题执行独立语义核验得到 `semantic_passed=false`；缺少 `JOIN_ERROR` 和 `SCHEMA_ERROR` 的可区分负例。

### Phase E5：Standard/Large 性能轨道（工具已具备，扩展验收待执行）

工作内容与定位：

1. 保持受控资源预算与数据集规模绑定；
2. 语义正确性与加权总分严格以 Tiny 为准，Standard (10k) 与 Large (100k) 作为独立的性能与资源诊断轨道，不改变语义分母；
3. 性能采集由 `c360 perf-baseline` 支撑；本次验收没有为扩展后的任务运行 Standard/Large 性能基线。

## 6. 版本和兼容性

扩展遵守以下规则：

- 只新增题目、fixture、文档和不改变行为的覆盖报告：保持 `protocol_version`，任务包升级 `task_version`；
- 新增指标、Join 或字段能力：升级 `metadata_version`，必要时升级 `task_version`；
- 改变 DSL 编译、结果比较、变体 replay 或硬门槛：升级 `evaluator_version`，旧报告不可混批；
- 改变 Agent 输入输出协议：升级 `protocol_version`，提供兼容适配层；
- 改变评分权重、分母或硬门槛：升级 `score_version`，重新生成回归基线并发布变更说明；
- 任何 Gold 口径修改都必须说明原因，更新 task/data 版本和摘要，不能只改期望值。

扩展期间固定保留 v1.0 基线包、seed-42 Tiny 摘要、20 道 human case 和当前正式报告，确保新旧结果可对照但不混算。

## 7. 验证命令和发布门

每个阶段至少运行：

```bash
uv run pytest -q
uv run ruff check src tests
uv run c360 doctor
uv run c360 generate-data --scale tiny --seed 42 --output outputs/exp-tiny
uv run c360 verify-pack --dataset outputs/exp-tiny --pack outputs/exp-public-300 \
  --variant outputs/exp-seed43 --variant outputs/exp-duplicate \
  --variant outputs/exp-null --variant outputs/exp-date \
  --output outputs/exp-verify-public
```

完成 E4 后增加：

```bash
uv run c360 verify-hidden --dataset outputs/exp-hidden-tiny \
  --pack outputs/exp-hidden-pack --output outputs/exp-verify-hidden
uv run c360 evaluate-public --dataset outputs/exp-tiny \
  --pack outputs/exp-public-300 --agent baseline --output outputs/exp-eval-public
uv run c360 evaluate-hidden --dataset outputs/exp-hidden-tiny \
  --pack outputs/exp-hidden-pack --formal --agent baseline \
  --output outputs/exp-eval-hidden
uv run c360 score --public-report outputs/exp-eval-public \
  --hidden-report outputs/exp-eval-hidden --agent baseline \
  --output outputs/exp-score
```

发布门保持不变：Gold 和独立 oracle 全部通过；SQL、权限和结果安全检查不回退；公开/隐藏隔离通过；固定 seed 摘要可解释；没有隐藏数据、Gold、私有结果或绝对路径泄漏；Linux 全量测试和最后的 Docker runtime evidence 由单一 owner 签署。

## 8. 不做的扩展

在 E1–E5 完成前不做以下事情：

- 不把公开题直接扩到 1,000 题来掩盖覆盖缺口；
- 不为了满足“20 条 Join”数字而添加未经审查的无业务意义路径；
- 不将 Standard/Large 的性能差异并入 Tiny 语义正确性分数；
- 不把更多同义改写当作新的独立 case；
- 不放宽 SQL Guard、权限、最小聚合粒度或结果行数限制；
- 不引入真实客户数据、外部网络模型或未经版本化的随机性。

## 9. 完成定义与达成核对

本扩展计划完成标准与当前状态对照如下：

1. **至少 4 条高价值 Join 可编译并有独立 oracle 和对抗 fixture**：
   - **部分实现**：5 条路径已编译并在内存 fixture 与 Python Oracle 对照；Gateway 行范围/进程隔离测试尚缺。
2. **300 道公开题达到覆盖配额，分组、澄清、拒答、NULL 和安全场景不再为空或极少**：
   - **部分达成**：当前生成器覆盖 30 个指标，配额与改写/family 隔离专项测试通过；实际计数为客户过滤 84、分组 37、Join 38、NULL 20、澄清 28、拒答 15。完整 300 题四变体语义验收尚未通过。
3. **隐藏集至少 60 道，并通过 family、组合正交性和数据分布审计**：
   - **未达成**：隐藏集扩至 60 题，当前语义验收 `semantic_passed=false`，缺少 JOIN/SCHEMA 错误 SQL 区分证据；组合正交性报告待补。
4. **Tiny 四变体语义验收、Standard/Large 性能基线和资源回收检查全部有证据**：
   - **未达成**：`perf-baseline` 和受控预算实现存在，但本轮没有 Standard/Large 扩展基线；`ExecutionGateway.execute_direct` 在当前进程运行，不能作为跨进程隔离证据。
5. **public_dev / private_hidden 仍分别报告，旧 v1.0 结果不与新协议混批**：
   - **实现保持**：代码仍将 public/private 分开报告且不排名；扩展后的 120/60 正式评测和版本兼容尚未验收。
6. **文档、CLI、manifest、版本字段和变更记录同步更新**：
   - **未达成**：契约/元数据/测试有未同步旧断言，且行为变更尚未升级 metrics、join-path、task 版本。
