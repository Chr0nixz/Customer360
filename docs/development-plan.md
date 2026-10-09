# 后续开发计划

[English](en/development-plan.md) | [简体中文](development-plan.md)

文档状态：2026-10-05 复审版。

本文是当前代码库的执行计划，补充 [ROADMAP.md](../ROADMAP.md)，不改变评分权重、Gold、公开/隐藏切分、SQL Guard 或权限语义。历史阶段记录仍保留在 `HANDOFF.md` 和 git 历史中，但本文件只把当前有效状态作为后续工作的依据。

针对数据库规模、题目规模和覆盖程度的专项扩展计划见 [Benchmark 扩展计划](benchmark-expansion-plan.md)。扩展优先补齐可执行 Join、分组和隐藏集代表性，不以简单增加行数或题目总数作为完成标准。

当前扩展验收未通过；SQL 分组粒度泄露、隐藏语义验证、元数据审计和版本锁定需先处理。详见[扩展验收与下一阶段计划](acceptance-and-next-plan.md)。

## 1. 当前基线

项目已经具备可运行的 benchmark 主链路：

- 9 张核心表、Tiny/Standard/Large 合成数据、固定 seed 和质量检查；
- 30 个指标、20 条 Join 元数据，其中只有 `customer_transactions` 是当前可编译 Join；
- semantic DSL、Gold 编译、独立 oracle、120/300 题公开包和独立 hidden pack；
- SQL AST Guard、权限前置物化、结果安全检查、超时回收和审计错误码；
- 官方离线 `BaselineAgent`、evaluator 0.6、score protocol 1.0、四个公开/隐藏变体；
- Dockerfile、SHA256/SBOM、formal release 和 GitHub CI 工具链。

当前发布状态：

| 项目 | 当前状态 |
|---|---|
| Git | `main` 与 `origin/main` 提交相同，但工作区有未提交代码；历史 `v1.0.0` tag 存在于旧提交（09d5c648），HEAD 当前为后续提交，发布门全通过前不应视为正式发布 |
| `c360 doctor` | 通过：9 表、72 列、30 指标、20 Join、8 FK |
| Ruff | `ruff check` 与 `ruff format --check` 通过 |
| 测试 | 468 项收集；8 题 hidden pack CLARIFICATION_FAILURE 验收问题已修复，本地全量除 5 项 PostgreSQL live skip 外全部通过（463 passed, 5 skipped, 0 failed） |
| 正式 RC 门 | `docker_runtime` 需在 Linux/CI 重新生成并绑定当前代码树证据；PostgreSQL live 测试由 CI 验证 |
| 正式检查 | `c360 check-formal-release` 必须在当前提交重新生成证据包后完成全门校验，再行收口打正式 tag |
| Baseline 诊断 | public/private 加权分约 0.75；安全和效率良好，但正确性约 52%、鲁棒性约 38% |

Baseline 的主要失败集中在客户过滤组合。当前 adapter 对 VIP、地区等过滤支持有限，而公开生成题还覆盖客户等级、风险等级、交易类型、渠道和资金流类型。这个问题属于 Agent 质量线，不是 benchmark 发布门。

## 2. 近期目标

近期目标按以下顺序执行：

1. 完成真实 Docker runtime 证据，签署最后一个 RC gate；
2. 让一份单一、可复核的 Linux 全量回归替代历史测试计数；
3. 提升官方 Baseline 的过滤和 Join 语义覆盖，不改变 evaluator 判定规则；
4. 清理文档状态冲突，并为 v1.1 之后的协议演化留下可执行设计；
5. 在所有发布证据通过前，不修改评分权重、Gold、split、SQL 白名单或权限策略。

## 3. 三个 Agent 工作包

三个工作包可以并行开始。每个 agent 使用独立分支或 worktree，只修改自己的文件边界；共享契约由主负责人最终合并。

### Agent A：发布与证据收口

**职责**

- 在 Linux/CI 上构建当前提交的 Docker image；
- 使用 `--read-only --network=none --user 10001` 运行 `doctor` 和 smoke；
- 使用 `.github/scripts/record_docker_runtime.py` 生成真实 image Id 证据；
- 重新构建 wheel/sdist，绑定 `docker_runtime` 和 reproducible build 证据；
- 运行 `prepare-formal-release` 和 `check-formal-release`。

**允许修改**

- `.github/` 工作流和 Docker 验证脚本；
- 独立的 `outputs/` 证据目录；
- 发布命令所需的最小 CI 修复。

**禁止修改**

- 评分权重、Gold、任务 split、SQL Guard、权限策略；
- 伪造 `sha256:<64 hex>` digest；
- 在八个 gate 全通过前创建 `v1.0.0` tag。

**验收标准**

- `DockerRuntimeEvidence.passed=true`；
- image digest 是真实的 64 位 SHA256；
- 镜像无 hidden/trusted/duckdb/outputs 泄漏；
- `check-formal-release` 返回 `passed=true`，八个 gate 全为 true；
- 证据绑定的是最终代码和最终文档树，而不是旧构建产物。

### Agent B：Baseline 质量与回归

**职责**

- 扩展确定性 adapter 对公开 metadata 中过滤字段和值的解析；
- 覆盖客户等级、风险等级、交易类型、渠道、资金流类型和组合过滤；
- 复查客户交易 Join 的去重、时间窗口和权限边界；
- 为每类失败补充最小回归 fixture；
- 在 evaluator 不变的前提下重新运行 public_dev/private_hidden 诊断分数。

**允许修改**

- `src/customer360/agent/adapter.py`；
- `src/customer360/agent/baseline.py`；
- `tests/test_baseline.py` 及新增 Baseline 回归测试；
- Baseline 相关诊断文档。

**禁止修改**

- Gold compiler、independent oracle、evaluator 比较器和评分权重；
- 通过放宽 Guard、权限或最小聚合策略来提高分数；
- 把错误回答改成拒答以规避语义失败。

**验收标准**

- 新增过滤组合都能由公开元数据解释，并通过真实网关执行；
- 未支持或歧义值仍 fail-closed；
- 没有读取 Gold、trusted oracle 或 hidden profile；
- public/private score 的失败分类、输入 digest 和协议版本可追溯；
- 正确性和鲁棒性较当前基线有可解释提升，安全项不回退。

### Agent C：文档、版本与未来协议设计

**职责**

- 清理 `ROADMAP.md`、`HANDOFF.md`、本文和 `docs/task_format.md` 中的过时状态；
- 明确“历史 no-score evaluator 0.5”和“正式 evaluator 0.6/score 1.0”的边界；
- 记录当前唯一发布阻塞是 Docker runtime，而不是正式评分工具缺失；
- 为 `validate_query_plan`、指标版本演化、PostgreSQL capability matrix 和 split 泛化审计写设计文档；
- 建立未来版本的变更影响表，说明何时需要升级 protocol/evaluator/task/metadata 版本。

**允许修改**

- `ROADMAP.md`；
- `HANDOFF.md`；
- `docs/*.md` 和决策记录。

**禁止修改**

- 当前 30 个指标的业务口径；
- 当前公开/隐藏数据；
- 代码协议、评分实现或 SQL 能力范围。

**验收标准**

- 文档不再把已实现的 score、Dockerfile、Apache-2.0 或 formal release 写成“尚未实现”；
- 明确 `pyproject` 的 package version 不是已打出的 Git tag；
- 未来设计能够区分“只加文档/测试”和“改变可观察协议行为”；
- 不泄漏 Gold、hidden seed、私有结果或本地绝对路径。

## 4. 合并顺序与统一验证

Agent A、B、C 可以并行开发。合并时按以下顺序执行：

1. 先合并 Agent B 的代码和回归测试，确认 Baseline 没有扩大安全边界；
2. 合并 Agent C 的状态文档，确保命令和版本说明与代码一致；
3. 冻结发布树，停止评分、Gold、split 和 Guard 变更；
4. 合并 Agent A 的 Docker evidence；
5. 只由一个 owner 执行最终验证：

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
uv run c360 check-formal-release --input outputs/<final-formal-release>
```

全量测试不能由多个 agent 同时运行。Windows 本地结果不能代替 Linux Docker runtime 证据。输出目录中的 Gold、hidden pack、formal input 和私有 JSONL 只能留在可信侧。

## 5. 版本路线

### v1.0.0：正式发布收口

目标是发布当前已经实现的 DuckDB-only、本地离线 benchmark，不新增语义能力。

必须完成：

- Docker runtime 真实证据；
- 八个 RC gates 全通过；
- 最终 wheel/sdist/Docker/public tree 内容检查；
- 一份 Linux 全量 pytest、ruff、doctor 和 formal release 记录；
- 维护者人工审查后创建 `v1.0.0` tag。

保持不变：`ranking_enabled=false`、public/private 分开、Token/scan unavailable、外部模型和在线服务关闭。

### v1.1：Baseline 与评测可诊断性

目标是提升官方 Baseline 的业务覆盖和失败可解释性，不改变正式评分协议。

计划内容：

- 完整过滤字段解析和受限 Join 规划；
- 失败按 metric/filter/time/join 分类统计；
- 补充 Baseline 的多轮澄清和拒答回归；
- 增加 public_dev 与 private_hidden 的稳定诊断报告；
- 完善 family-only isolation 的模板、指标、Join 维度审计。

如果修改 Agent 输出协议或 evaluator 行为，必须分别升级 protocol/evaluator 版本并提供迁移说明。

### v1.2：元数据和指标演化

目标是支持业务元数据变化，同时保持旧任务可审计。

计划内容：

- `validate_query_plan` 的能力矩阵和稳定拒绝码；
- metric version、rename、deprecation 和迁移检查；
- 字段改名、指标废弃、业务别名变化的回归 fixture；
- manifest 绑定 metadata/task/protocol 版本，拒绝隐式漂移。

这一版本不得把 metadata-only Join 自动升级成可执行 Join，也不得静默改变已有指标口径。

### v1.3：性能与数据库适配设计

目标是为扩展执行引擎建立边界，而不是立即引入第二套生产路径。

计划内容：

- PostgreSQL capability matrix 和 adapter interface；
- DuckDB/PostgreSQL 在日期、Decimal、NULL、聚合和权限上的差异 fixture；
- Standard/Large 的稳定性能基线；
- 如要启用真实 scan/token 统计，先升级评分协议、报告契约和版本记录。

在适配层和回归覆盖完成前，官方 benchmark 仍以 DuckDB 为唯一执行引擎。

### v2.0：可选平台能力

只有产品决策明确后才进入此版本：

- 外部模型 API 或厂商 SDK；
- FastAPI/远程评测服务；
- 不可信 Python Agent 的 OS 级隔离；
- 在线排行榜、提交服务或多数据库正式评分。

这些能力会改变信任边界、网络策略或发布范围，不能作为 v1.x 的顺手扩展。

## 6. 永久边界

- 不提交真实客户数据、生产凭证、真实手机号或身份证号；
- 不用 LLM 生成 Gold 或作为最终裁判；
- 不把空结果、截断结果、策略拒绝或执行失败伪装成成功；
- 不把历史测试计数、候选 release 或本地 score 宣称为正式发布；
- 不为了 Baseline 分数关闭 SQL Guard、权限检查、最小聚合或结果脱敏。

每个 agent 交付时必须附上：改动文件、验证命令、证据路径、版本影响、未通过 gate 和已知限制。
