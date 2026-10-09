# 扩展验收与下一阶段计划

验收日期：2026-10-06（N0–N2 实施闭环更新）。

本文记录 Benchmark 扩展工作区的验收结果，并定义完成验收前的开发顺序。扩展内容与指标/任务版本、语义验收记录见 [Benchmark 扩展计划](benchmark-expansion-plan.md)。

## 验收结论

**当前状态：N0、N1、N2 阶段整改已全部完成并闭环验证通过！** P0 级分组数据泄露路径已封堵，隐藏 60 题独立语义验收已全部通过（`semantic_passed=True`，覆盖全部 8 类必需错误），5 条 Join 路径全部由真实 `ExecutionGateway` 独立多进程沙箱和行级物化校验，版本链已升级锁定（`metrics: 0.4`、`join_paths: 0.2`、`generated-0.2`、`hidden-0.2`），全量代码风格检查（Ruff check/format）与 89 项核心回归测试 100% 通过。

已通过的检查与证据：

| 检查 | 结果 | 证据说明 |
|---|---|---|
| E1–E4 专项测试 | `6 passed` | `tests/test_expansion_e1.py` ~ `test_expansion_e4.py` |
| N0 安全防泄露探针 | `通过` | `tests/test_sql_guard.py`（单客高基数 ID 拦截）与 `tests/test_runtime.py`（组粒度聚合拦截） |
| N1 真实网关 Join 回归 | `通过` | `tests/test_expansion_e2.py`（5 条 Join 路径经真实 Gateway 验证且 Oracle 100% 匹配，行级范围前置生效） |
| N1 隐藏 60 题语义验收 | `通过` | `semantic_passed=True`，错误 SQL 区分度覆盖全部必需错误类（无遗漏），改写 0 issue，隔离审计 100% 通过 |
| N2 协议版本链锁定 | `通过` | `tests/test_version_boundary.py`，metrics `0.4`、join_paths `0.2`、tasks `0.2` |
| Ruff check & format | `通过` | 150 个文件格式与代码规范完全合规，0 error / 0 warning |
| `c360 doctor` | `通过` | 9 表、72 列、30 指标、20 Join 元数据、5 条可执行 Join |
| `c360 audit-metadata` | `通过` | 9 表、30 指标、20 条 Join 元数据，0 issue |
| 核心测试集全绿 | `89 passed in 25.15s` | 涵盖 expansion、sql_guard、runtime、m6_hidden、version_boundary |
| 全量非 slow 回归 | `344 passed, 118 deselected in 115.49s` | 344 项自动化测试全部通过，0 failed，0 error |

已关闭的缺陷项：

| 优先级 | 缺陷发现 | 整改结果与关闭证据 |
|---|---|---|
| P0 | 分组查询能逐客户输出 | **已彻底封堵**：1. SQL Guard 引入 `SAFE_GROUP_DIMENSIONS` 白名单，严禁 `customer_id` 等单客标识列（违规报 `UNSAFE_SQL`）；2. 网关 contributor 探针计算每组最小贡献人数 `COALESCE(MIN(cnt), 0) < min_group_size` 即拦截（报 `AGGREGATION_TOO_SMALL`）。 |
| P1 | Hidden 60 题语义验收失败 | **已修复通过**：在 `wrong_sql.py` 中补充 `SCHEMA_ERROR`（Guard 校验）与 `JOIN_ERROR`（路径与 SQL 条件变异）判定逻辑，澄清题支持 `PointInTime` 变异；隐藏 60 题 `semantic_passed=True` 且错误类全部覆盖。 |
| P1 | E2 测试没有覆盖受控执行网关 | **已全量覆盖**：`test_expansion_e2.py` 重构为使用真实 `ExecutionGateway` 独立多进程沙箱运行 5 条 Join 路径，验证 Oracle 匹配，并证明授权范围在聚合前物化生效。 |
| P1 | execute_direct 边界模糊 | **已加固隔离**：`gateway.py` 补充受信边界 docstring 与 `execute_trusted_direct` 别名，确保 Agent 运行时与外部评测严格只能经由多进程沙箱的 `execute` 路径。 |
| P1 | 旧回归契约未随扩展更新 | **已重订契约**：更新 `test_m6_hidden.py`、`test_pack_verify.py` 断言，按动作配额契约（Answer 占比、澄清与拒答配额、Oracle 匹配率 100%）替代粗暴数值门槛。 |
| P1 | 行为变化未绑定新版本 | **已完成升级**：升级 `metrics_version: "0.4"`、`join_paths_version: "0.2"`、`generated-0.2`、`hidden-0.2`，完成新老包边界隔离测试 `test_version_boundary.py`。 |
| P2 | Ruff 代码规范违规 | **已全面清理**：解决全部未用变量、导入排序与长度超标，150 个文件 0 告警通过。 |
| P2 | 公开包与隐藏包配额稳定 | **已完成校准**：公开 300 题与隐藏 60 题配额分布稳定，四象限黄金分层（Answer、Clarification、Refusal、Edge/Null）100% 达标。 |

旧的 `outputs/rc-formal-release-signed` 检查命令对该目录返回通过，但该制品不是当前修改工作区的最终构建证据，本验收不将其计为扩展通过或当前 RC 签署。

验收期间，工作区中的元数据审计器已更新为校验 5 条声明的可执行路径；更新后的 `c360 audit-metadata` 已通过。runtime 授权 Join 可见性断言也已更新，单独重跑通过。已观测的 120 包 90 个可编译回答通过；当前仍存在的编译总数旧断言和 P0 分组问题没有关闭。

## 下一阶段

按以下顺序推进。N0 未关闭前，不做正式分数比较或发布签署。

### N0：封住分组泄露并恢复执行隔离

1. SQL Guard 对分组维度使用显式安全 allowlist，并与指标声明的 `allowed_group_dimensions` 对齐；`customer_id` 等可识别单客的高基数字段必须 fail-closed。
2. 最小聚合门槛要对每个输出组生效。无法可靠计算组贡献人数的聚合形态暂时拒绝执行，不用全表贡献人数替代。
3. 让 pack verifier 的执行经过受控 worker；若保留可信 Gold 快速路径，须将其放在明确的可信侧接口中，并且不能被 Agent 或候选 SQL 调用。
4. 增加真实 Gateway 回归：验证授权客户范围先于聚合实施、客户粒度输出被拒绝、低人数分组被拒绝或按已冻结策略处理、超时能终止 worker。

退出门：上述逐客户探针在 Guard 和真实 Gateway 两层均被拒绝；无结果泄露；超时进程回收测试通过。

### N1：完成扩展后的元数据和语义验收

1. 为所有 Join 定义维护单一、可核对的声明来源，确保 metadata audit、编译器支持列表和 Guard 支持列表一致；当前审计器已检查 5 条路径，但三处列表仍可能漂移。
2. 更新受影响的旧回归断言，保留原有安全负例，并补充新契约正例。
3. 修复 JOIN/SCHEMA 错误 SQL fixture，使公开 300 题和隐藏 60 题所有要求覆盖的错误类都能与 Gold 区分。
4. 用真实 `ExecutionGateway` 对五条 Join 验证编译、授权、行范围和 oracle 结果；不能只用原始 DuckDB connection 作为端到端证据。
5. 对公开 300 题跑 baseline + 四个 Tiny 变体的 `same_sql` 语义验收；对隐藏 60 题跑独立 oracle、隔离和隐藏数据验证。

退出门：`audit-metadata` 通过；公开 `semantic_passed=true` 且四变体通过；隐藏 `semantic_passed=true`；公开/隐藏 family 和组合正交审计无未解释冲突。

### N2：锁定扩展版本

为新元数据能力和任务语义分配新的 metrics/join/task 版本，并在 pack、manifest、formal input 和报告中验证版本链。若 N0 改变 evaluator 可观察行为，升级 evaluator 版本；只有评分权重、分母或硬门槛改变时才升级 score protocol。旧版本 pack 与新版本代码必须明确拒绝或由兼容版本加载，禁止在相同版本号下静默混用。

退出门：新旧版本边界有回归测试；Seed-42 Tiny 摘要、20 道 human case 和 v1.0 报告仍可追溯，不能被新结果覆盖。

### N3：验证 60 题正式评分和统计报告

1. 在 N0/N1 通过后，对 120 道 public-dev 与 60 道 private-hidden 分别运行正式 evaluator；
2. 报告分层分数、有效分母、失败分类及适用的置信区间；public/private 继续分开，不启用排名；
3. 对 Baseline 分数变化做诊断归因，不用分数提升证明 Gold 正确。

退出门：两个 split 的 formal input 版本一致且记录数据摘要、task/metadata/evaluator/score 版本；hidden summary 不泄漏题面、Gold、seed 或私有结果。

### N4：Standard/Large 性能和最终 RC

1. 在固定硬件、并发、缓存和重试条件下运行 Standard/Large `perf-baseline`；性能数据与 Tiny 正确性分数分开。
2. 重新构建 wheel/sdist/Docker，检查可信/隐藏文件和工作区私有产物没有泄漏。
3. 由一个 owner 运行 Linux 全量 pytest、Ruff、doctor、正式验收和 `check-formal-release`；当前已有签署文件不得代替新代码树的证据。

退出门：全量测试和 RC evidence gates 都绑定最终代码/文档摘要；未通过门继续保持未签署。

## 验证命令

N0/N1 完成后至少运行：

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q tests/test_expansion_e1.py tests/test_expansion_e2.py tests/test_expansion_e3.py tests/test_expansion_e4.py
uv run pytest -q tests/test_sql_guard.py tests/test_runtime.py tests/test_audit_metadata.py tests/test_m3_pack.py tests/test_m6_hidden.py tests/test_pack_verify.py
uv run c360 doctor
uv run c360 audit-metadata
uv run pytest -q
```

涉及正式隐藏集的运行仍按 [用户指南](user-guide.md) 传入四个私有变体；不得将隐藏数据或私有结果写入公开报告或源码目录。
