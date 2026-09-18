# Customer360 使用说明

面向要**安装、生成数据、跑 Agent、看报告**的人。开发约定见 [AGENTS.md](../AGENTS.md)，架构边界见 [architecture.md](architecture.md)，正式发布关卡见 [formal-release.md](formal-release.md)。

这是一套可复现、默认可安全执行的**本地离线** Agent benchmark，不是在线问数服务，也不是排行榜。

当前协议：package `1.0.0`，formal evaluator `0.6`，score protocol `1.0`。`v1.0.0` 标签还要等八个 RC 门全部签署（本仓库的 `docker_runtime` 可能仍未签署）。没有在线排名。

## 1. 三条硬规则

1. **输出目录必须还不存在。** 命令不会覆盖已有结果。重跑请换新路径，例如 `outputs/tiny-2`。
2. **用 `uv run`。** 不要调用系统里可能指向别的环境的 `python` / `pytest`。
3. **分清公开输入和可信侧。** 交给 Agent 的只有问题、公开 YAML 和受控工具。`pack.json`、`generated_oracles.yaml`、`hidden_oracles.yaml`、`data/trusted/`、Gold SQL、隐藏种子都不得发给被评对象，也不得打进 wheel。

退出码约定：

| 码 | 含义 |
|---|---|
| 0 | 命令成功，且该命令的验收位为真 |
| 1 | 跑完了，但验收未过（例如 `semantic_passed=false`、hard gates 失败） |
| 2 | 参数、路径、契约或环境错误，没有写出可发布结果 |

## 2. 安装

需要 Python 3.11 和 [uv](https://docs.astral.sh/uv/)。Windows PowerShell 与常见 Unix shell 使用同一套 `uv` 命令。

仓库根目录：

```bash
uv sync --locked
uv run c360 --help
uv run c360 version-info
uv run c360 doctor
```

`doctor` 预期大致为：`tables=9`、`columns=72`、`metrics=30`、`join_paths=20`、`executable_join_paths=1`、`foreign_keys=8`、`glossary_entries=111`。

从已构建的 wheel 安装时，`c360 doctor` / `c360 smoke` 不需要源码树或 `configs/benchmark.yaml`。下面这些仍需要仓库文件：`generate-data`、`coverage-report`、`check-rewrites`、`build-gold`、`replay-variant`，以及带可信 oracle 的评测。

Linux 上可用 Docker（非 root、只读、无网络）。Windows 源码/uv 路径保持可用。镜像用法见第 10 节。

## 3. 五分钟确认安装

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 coverage-report --dataset outputs/tiny-local --output outputs/coverage-local
uv run c360 smoke --output outputs/smoke-local
```

如何读结果：

- Tiny：100 客户、2,000 交易、7 个资产估值日、365 天日期维。写出 `dataset.duckdb`、`manifest.json`、`quality_report.json`、`generation_config.json`。60 条质量断言任一失败则不发布 manifest。
- `coverage-report`：针对 **20 道 human case**。预期 `coverage_passed=true`、`m2_complete=false`。这不是加权总分。
- `smoke`：3 条正确 SQL 判对、1 条错误 SQL 判错、1 条危险 SQL 拦截。`verification_passed=true` 只表示架构链路通。不要把 3/5 当成 Agent 正确率，也不要把这 5 条当成正式题。

默认 pytest 只跑 Tiny。不要把 Large 生成放进日常 CI。

## 4. 按目的选路径

下面每条路径都从仓库根目录执行。路径名可改，但同一目录不要复用。

### 4.1 日常开发（human 20 题）

20 道 `C360_0001–0020` 永远是 `split=dev`，不是隐藏集。

```bash
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 check-rewrites
uv run c360 run-case --case-id C360_0001 --agent baseline --dataset outputs/tiny-local --output outputs/case-0001
uv run c360 generate-variant --variant-id tiny_seed_43_distribution --output outputs/tiny-seed43
uv run c360 generate-variant --variant-id tiny_duplicate_fanout --output outputs/var-dup
uv run c360 generate-variant --variant-id tiny_null_empty_groups --output outputs/var-null
uv run c360 generate-variant --variant-id tiny_date_boundary --output outputs/var-date
uv run c360 evaluate --dataset outputs/tiny-local --distribution-variant outputs/tiny-seed43 --duplicate-variant outputs/var-dup --null-variant outputs/var-null --date-variant outputs/var-date --agent baseline --mode same_sql --output outputs/matrix-local
uv run c360 report --input outputs/matrix-local --format json
```

`evaluate --mode same_sql`：只在 baseline 上调用一次 Agent，再把**这次提交的候选 SQL**重放到 baseline + 四个变体。`--mode scoring` 会失败；历史矩阵报告的 `scoring_applied` 必须是 false。`--split private` 会失败，隐藏集请用 `evaluate-hidden`。

`replay-variant` 只重放 **Gold SQL**，不调用 Agent，也不是正式分数。

### 4.2 生成公开题包（120 或 300）

```bash
uv run c360 generate-tasks --count 120 --seed 42 --output outputs/tasks-120
uv run c360 generate-tasks --count 300 --seed 42 --output outputs/tasks-300
uv run c360 check-isolation --pack outputs/tasks-300
```

| `--count` | 结构 | 标记 |
|---|---|---|
| 120 | 开发包 | `m3_complete=true`，`m6_structure=false` |
| 300 | 180 train / 120 generated-dev | `m6_structure=true` |

题号从 `C360_1001` 起。公开 YAML 只有问题与改写。`pack.json` 和 `generated_oracles.yaml` 是可信侧。`m6_structure` 只表示题量结构，不表示答案已核验。

### 4.3 语义验收（Gold 对不对，不是 Agent 分数）

300 题必须按固定顺序绑四个公开 Tiny 变体：

```bash
uv run c360 verify-pack --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --output outputs/verify-pack-local
```

120 题的 `--variant` 可选，只作诊断。

看公开 `summary.json` 的 `semantic_passed`。Gold、SQL、问题、seed 在 `private/`。`semantic_passed` 不是 ROADMAP 第 8 节加权分数。

### 4.4 隐藏集

隐藏题是**新 case**（`C360_4001+`，`split=private`），不是把 20 道 dev 题改标。

```bash
uv run c360 generate-hidden --public-pack outputs/tasks-300 --count 30 --output outputs/hidden-pack
uv run c360 generate-hidden-data --seed 1042 --output outputs/hidden-tiny
uv run c360 check-isolation --pack outputs/tasks-300 --hidden outputs/hidden-pack
uv run c360 verify-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --output outputs/verify-hidden-local
uv run c360 generate-hidden-variants --dataset outputs/hidden-tiny --output outputs/hidden-variants
```

`generate-hidden-data` 拒绝 seed 42 和 43。隐藏数据必须带 `hidden_profile.json`。`verify-hidden` 只验 baseline，不接受公开变体。

非正式隐藏评测：

```bash
uv run c360 evaluate-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --agent baseline --output outputs/hidden-eval
```

正式隐藏评测（baseline 调一次 Agent，四个私有变体 same-SQL replay）：

```bash
uv run c360 evaluate-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --formal --variant outputs/hidden-variants/hidden_distribution --variant outputs/hidden-variants/hidden_duplicate_fanout --variant outputs/hidden-variants/hidden_null_empty_groups --variant outputs/hidden-variants/hidden_date_boundary --agent baseline --output outputs/hidden-eval-formal
```

四个 `--variant` 顺序必须是 distribution、duplicate、NULL、date。公开摘要不含问题、Gold、spec、候选 SQL、隐藏 seed。

### 4.5 正式本地打分

计分对象：

- public_dev = 300 包里的 **generated-dev 120**（不计 human 20，不计 train）
- private_hidden = 独立隐藏包（默认 30 题）

```bash
uv run c360 evaluate-public --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --agent baseline --output outputs/eval-public
uv run c360 score --public-report outputs/eval-public --hidden-report outputs/hidden-eval-formal --agent baseline --output outputs/score-local
```

`evaluate-public` / `evaluate-hidden --formal` 写出 `private/formal_input.json`（evaluator 0.6）。历史 `evaluate` 矩阵报告不能拿来 `score`。

`c360 score` 分别写 public_dev 与 private_hidden，`ranking_enabled=false`，两套分数永不合并。权重：正确性 45%、安全 20%、交互 15%、效率 15%、鲁棒性 5%。Token 和扫描量是 `unavailable`，不会报 0。

硬门槛（任一失败则 `score` 退出码 1，但仍会写出报告）：`integrity`、`p0_safety`、`robustness_coverage`、`nonempty_denominators`。Agent 正确率 ≥90%、P95 时延等是诊断目标，不是这四个硬门槛。

负对照（WrongAgent 必须不能拿满分）：

```bash
uv run c360 evaluate-public --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --agent wrong --output outputs/eval-wrong
```

### 4.6 性能采集（不是分数）

预算跟数据集规模绑定，不能由 Agent 选择。Tiny 默认每表最多物化 **10,000** 行。

```bash
uv run c360 perf-baseline --dataset outputs/tiny-local --workload gold-execute --output outputs/perf-tiny
uv run c360 perf-baseline --workload generate --scale standard --seed 42 --dataset outputs/standard-local --output outputs/perf-std-gen
uv run c360 perf-baseline --dataset outputs/standard-local --workload gold-execute --output outputs/perf-std-gold
```

`--workload scoring` 会失败。公开摘要没有问题、Gold、SQL、seed。扫描量/Token 为 unavailable。Large 只在你显式指定时跑。

### 4.7 候选发布 vs 正式发布

无分数候选（Docker/隐藏文件/加权分数都不进包）：

```bash
uv run c360 prepare-release --output outputs/release-candidate --public-pack outputs/tasks-300 --hidden-pack outputs/hidden-pack
uv run c360 check-release --input outputs/release-candidate
```

正式 v1.0 路径、八个 RC 门和 Docker smoke 清单见 [formal-release.md](formal-release.md)。文件存在不等于门通过。未签署 `docker_runtime` 时不要填 digest，也不要打 `v1.0.0`。

## 5. 输出目录长什么样

生成数据：

```text
outputs/tiny-local/
  dataset.duckdb
  manifest.json
  quality_report.json
  generation_config.json
```

生成题包：

```text
outputs/tasks-300/
  pack.json                 # 可信侧完整蓝图
  public_cases.yaml         # Agent 可见题面
  generated_oracles.yaml    # 可信侧，不进 wheel
  isolation.json
```

隐藏包：

```text
outputs/hidden-pack/
  pack.json
  agent_cases.yaml
  hidden_oracles.yaml
  isolation.json
```

评测 / 分数（公私分离）：

```text
outputs/eval-public/
  private/formal_input.json
  public/summary.json
outputs/score-local/
  private/score.json
  public/summary.json
```

只把 `public/` 给人看。私有 JSONL/Gold/候选 SQL 留在本机。

## 6. Agent 标识

| `--agent` | 用途 |
|---|---|
| `baseline` | 官方本地 Baseline。离线确定性 planner，不读 Gold |
| `template` | 协议驱动，只测接入，**不是**官方 Baseline |
| `wrong` | 负对照，故意失败 |
| `gpt` / `openai` / `anthropic` / `network` / `llm` | 立即失败。未许可外部模型 |

自己写 Agent：实现 `Agent.respond(request, tools)`（见 `src/customer360/agent/protocol.py`）。工具包括 `execute_sql`、`search_tables`、`search_columns`、`search_metrics`、`get_table_schema`、`get_metric_definition`、`get_business_glossary`、`get_join_paths`。必须是本机可信 Python；CLI 不接收任意上传插件。检索结果已按授权表/列过滤。

成功回答需要：协议 `success`、真实执行回执、SQL 与回执一致、结果与参考一致。只写一句自然语言答案不得分。

## 7. 命令速查

完整参数以 `uv run c360 <命令> --help` 为准。

| 命令 | 做什么 |
|---|---|
| `version-info` | 包和协议版本 |
| `doctor` | catalog / 指标 / Join 自检 |
| `schema` | 从 catalog 打 DuckDB DDL |
| `create-fixture` | 六客户公开样本，不是 Tiny |
| `generate-data` | Tiny / Standard / Large 合成数据 |
| `generate-variant` | 四个冻结 Tiny 变体之一 |
| `smoke` | 3 正 + 1 错 + 1 危险 SQL |
| `coverage-report` | 20 题独立 oracle，非分数 |
| `check-rewrites` | 20 题改写槽位 |
| `replay-variant` | 同一 Gold SQL 打到变体上 |
| `build-gold` | 20 题私有 Gold，勿发布 |
| `generate-tasks` | 公开生成包 120 或 300 |
| `check-isolation` | family / split 隔离 |
| `run-case` | 单道 human case |
| `evaluate` | human 20 题矩阵，非分数 |
| `report` | 矩阵公开脱敏报告 |
| `generate-hidden` | 独立隐藏题包 |
| `generate-hidden-data` | 隐藏 Tiny（默认 seed 1042） |
| `generate-hidden-variants` | 四个私有隐藏变体 |
| `verify-pack` / `verify-hidden` | Gold 语义验收 |
| `evaluate-public` | generated-dev 120，formal_input |
| `evaluate-hidden` | 隐藏评测；加 `--formal` 才是正式输入 |
| `score` | 分开的 public_dev / private_hidden 分数 |
| `build-score-inputs` | 绑定两份 formal_input 摘要 |
| `perf-baseline` | 耗时采集 |
| `prepare-release` / `check-release` | 无分数候选 |
| `bind-rc-evidence` | 把原生报告绑成 RC 证据 |
| `prepare-formal-release` / `check-formal-release` | v1.0 正式门 |

尚未实现的命令（例如 `build-metadata-index`）会报错，不会假装成功。

数据规模：

| `--scale` | 客户 / 交易 | 默认预算 |
|---|---|---|
| `tiny` | 100 / 2,000 | 每表 10k 行、15s、128MB |
| `standard` | 10,000 / 300,000 | 400k 行、60s、512MB |
| `large` | 100,000 / 3,000,000 | 4M 行、180s、1024MB |

SQL 能力：单表聚合、`active_customer_count` 按 `region` 分组、`latest_total_asset` 的 MAX 自连接、唯一 Join `customer_transactions`。CTE、窗口函数、其它 Join 会被拒绝。权限在聚合前由网关实施。

## 8. 常见失败

| 现象 | 原因 |
|---|---|
| 目录已存在 / WinError 183 | 输出路径必须是新的 |
| `evaluate --mode scoring` 失败 | 正式分数走 `c360 score`，不要翻历史开关 |
| `evaluate --split private` 失败 | 20 题不能改标；用 `evaluate-hidden` |
| `score` 说不是 `formal_input` | 要用 `evaluate-public` 和 `evaluate-hidden --formal` 的输出 |
| `generate-hidden-data` 拒绝 seed | 不要用 42 或 43 |
| `verify-pack` 要四个变体 | 300 题必须按冻结顺序传四个 `--variant` |
| `INPUT_LIMIT` | 物化行数超过该规模的 cap，不是扫描量 |
| `POLICY_INCOMPATIBLE` | 零贡献 Gold 被最小聚合拦住，不是 Agent 答错 |
| 网络类 `--agent` 失败 | 外部模型默认关闭 |
| `check-formal-release` 只报 `docker_runtime` | 本机没跑真实 Docker smoke；不要填假 digest |

## 9. Docker

镜像以用户 `c360`（uid 10001）运行。验收时应关闭网络、根文件系统只读：

```bash
docker build -t c360:local .
docker run --rm --read-only --network=none --user 10001 c360:local doctor
docker run --rm --read-only --network=none --user 10001 c360:local smoke --output /tmp/smoke-local
```

私有数据、隐藏 pack、trusted oracle 不要打进镜像。需要时用**显式只读 mount** 注入，不要把 `data/trusted` 或 `outputs` 写进镜像层。完整 RC 步骤见 [formal-release.md](formal-release.md)。

## 10. 不要做的事

- 把 `C360_0001–0020` 改成 train / test / private / hidden
- 把 TemplateAgent 叫成官方 Baseline
- 把 19 条 `metadata_only` Join 编译进 Guard
- 关掉 SQL Guard、权限检查、脱敏或行数上限
- 用 LLM 当 Gold 或最终裁判
- 把 hidden pack、trusted oracle 打进 wheel / sdist / 镜像
- 删除 Tiny 默认 10k 物化上限，或把 0 当成无限
- 在默认 pytest 里生成 Large
- 声称 family 隔离等于「每个模板 / 每个指标 / 每条 Join 都没在公开集出现过」
- 扫描量或 Token 报 0
- 把 `outputs/`、`tmp-formal-*`、hidden pack 或 `*.duckdb` 提交到 GitHub

## 11. 其它文档

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) | 项目入口和最短验证 |
| [AGENTS.md](../AGENTS.md) | 开发协作与安全默认 |
| [HANDOFF.md](../HANDOFF.md) | 当前完成范围和下一步 |
| [ROADMAP.md](../ROADMAP.md) | 里程碑和评分协议 |
| [architecture.md](architecture.md) | 信任边界与模块 |
| [data_dictionary.md](data_dictionary.md) | 九表口径 |
| [task_format.md](task_format.md) | 公开/私有契约与 DSL |
| [decisions.md](decisions.md) | 工程决策 |
| [formal-release.md](formal-release.md) | v1.0 RC 命令与八个门 |
| [github-publish.md](github-publish.md) | 开源前检查项、忽略规则、CI 工件 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | PR 与公开树范围 |
| [SECURITY.md](../SECURITY.md) | 漏洞私下报告 |
| [development-plan.md](development-plan.md) | 阶段计划 |
