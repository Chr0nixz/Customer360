# Customer360 架构交接

## 1. 从这里接手

怎么跑命令见 [使用说明](docs/user-guide.md)。本轮 v1.0 交接见 [正式发布记录](docs/formal-release.md)。语义验收报告协议保持 **0.2**，正式评分协议为 **1.0**，formal evaluator 为 **0.6**；旧 0.5/no-score 报告保留为历史证据，不能改写成正式分数。隐藏四变体 provenance 与 same-SQL replay、`score`/`build-score-inputs`、Apache-2.0、Docker、SHA256/SBOM 和 `prepare-formal-release/check-formal-release` 已落地。

本次交付包含 M0 技术基线 + 公开 fixture 闭环；T1 Tiny 生成器与 M1 Standard/Large 规模；T2a 元数据检索；T2b 十个单表指标；T3 Tiny 边界探针与独立 oracle；T4 Linux CI / 打包回归；M2 Gold、answer/clarification/refuse 评测、受限 Join、版本化 20 道 dev case 包、改写语义一致性校验、四类 Tiny 变体，以及公开题面与可信 oracle 的物理分离；M4-01 可序列化多轮 evaluator；阶段 C / M3 三十指标、20 条经审查 Join 路径、semantic family / split 隔离和 120 道独立生成题；阶段 D / M4 矩阵评测（一次 Agent 候选 SQL 在 baseline+4 变体上 same_sql 重放，agent_rerun 分记，私有 JSONL 与公开脱敏报告分离）；阶段 E / M5 官方本地 Baseline 与独立 model adapter；阶段 F / M6 独立隐藏 pack、隔离 Tiny、300 公开生成题和 release 候选；阶段 S 生成/隐藏包语义验收（300 题强制四个冻结 Tiny 变体，隐藏验收 baseline-only，策略状态由真实执行网关判定）；阶段 G 受控资源预算与 `c360 perf-baseline`。正式评分工具链与 Dockerfile 已落地；八个 RC 门尚未全部签署，因此不打 v1.0.0。分组/latest-snapshot 已按 D038/D039 进入可编译 Gold。C360_0001–0020 仍全部 split=dev。历史 `evaluate` 的 `scoring_applied` 与 `m4_scored` 必须为 false。TemplateAgent 不是官方 baseline。

**2026-09-17 加固收敛**：H1–H8 已按验收/代码审阅修复。M4-01/M4-02 的异常审计、真实 Agent 注入、数据摘要核验和空聚合策略预检已落地；evaluator 0.4。阶段 E 已落地官方本地 Baseline。阶段 F 已落地独立隐藏集与 release 候选。第 9 节旧记录保留为历史证据。

**2026-09-18 阶段 S**：生成/隐藏包不再只验收结构。`c360 verify-pack` / `verify-hidden` 用独立 Python oracle 对照编译 SQL，区分 8 类错误 SQL，校验生成改写槽位，并可在 Tiny 四变体上 same_sql 重放 Gold。`semantic_passed` 独立于 `m6_structure`；`scoring_applied` 仍为 false。公开包绑定 Tiny seed 42；隐藏包绑定带 `hidden_profile` 的 Tiny。`coverage-report` 仍只服务 20 道 human case。

**2026-09-18 阶段 G**：冻结 D055 命名资源预算。Tiny 默认仍是每表 10,000 行物化上限；Standard/Large 分别 400,000 / 4,000,000 行，并提高超时与内存，但仍是有限 cap。Tiny worker 仍用参数化提取 + VALUES；Standard/Large 在 worker 内 ATTACH 只读源库做授权 `CREATE TABLE AS`，DETACH 后再跑候选 SQL。`c360 perf-baseline` 已采集 generate 与 gold-execute（human 20）；公开摘要不含问题/Gold/SQL/seed；扫描量与 Token 保持 `unavailable`。评测记录版本仍为 0.5。默认 pytest 不生成 Large。

**2026-09-19 阶段 R / M6 RC**：D057 冻结第 8/10 节 v1.0 默认值。RC 门改为内容校验；空文件和伪造 digest 失败。本机已签署 license、public_artifacts、reproducible_build、semantic_acceptance、conformance、negative_control、score_inputs。`docker_runtime` 因未安装 Docker 保持未签署；`check-formal-release` 仅因此失败。未 `git init`，未打 `v1.0.0`。官方 Baseline 本地分数 hard_gates_passed=true，加权约 0.75（public_dev/private_hidden 分开，不排名）。

**2026-09-19 GitHub 开源准备**：D058。已补 CONTRIBUTING/SECURITY/CODE_OF_CONDUCT、issue/PR 模板、`.gitattributes`、gitignore（`outputs/`、`tmp-*/`、`*.duckdb`、`dist-*/`）、CI 公开树检查与 Docker image Id 证据工件，以及 [docs/github-publish.md](docs/github-publish.md)。`data/trusted` 仍只覆盖 C360_0001–0020。本机工作区里的 `outputs/` 与 `tmp-formal-*` 含 hidden 制品，已被 gitignore。公开仓库为 https://github.com/Chr0nixz/Customer360 。未打 `v1.0.0`。

**2026-09-18 阶段 F 复审**：全量回归与 ruff 通过；本轮修复了极小合法生成配置的空集合随机访问、每层 SELECT 的 SQL clause/字面量类型边界、生成数据 sidecar 与 manifest 绑定、隐藏 profile/评测报告契约、隐藏 pack 对应的公开 pack 校验，以及 release 的 300（180 train/120 dev）硬验收。ToolSession 现在审计所有策略拒绝并将工具基础设施异常稳定归类为 `EXECUTION_ERROR`；因未捕获策略拒绝的分类行为变化，evaluator 记录版本升为 0.5，0.4 只作为历史格式。`pack.json`、`generated_oracles.yaml`、`hidden_oracles.yaml` 仍只属于可信侧，交给 Agent 的只能是公开 YAML 与受控工具。

阅读顺序：要跑命令先读 [使用说明](docs/user-guide.md)；改代码读 AGENTS.md → 本文件 → docs/architecture.md → docs/data_dictionary.md → ROADMAP.md；公开到 GitHub 读 [docs/github-publish.md](docs/github-publish.md) 与 [CONTRIBUTING.md](CONTRIBUTING.md)。原方案继续保留，矛盾处理见 ROADMAP。

## 2. 已完成与尚未完成

| 内容 | 状态 / 证据 |
|---|---|
| Python 工程与依赖 | pyproject.toml、uv.lock、.python-version；uv sync --locked 可安装 |
| 共享契约 | 公开输入/响应、私有三类 oracle、DSL、执行回执、manifest、评测记录；T1 新增 GenerationConfig/DatasetManifest/QualityReport |
| 九表 schema | 包内 catalog，生成 DDL；主键/可空性/唯一键/8个外键 |
| 公开数据样本 | 6客户 fixture，规范化摘要和可重复 seed 变化；不是 Tiny |
| Tiny 生成器 | T1 已完成：configs/data_generation.yaml、synth/generator.py、synth/constraints.py、c360 generate-data；100客户/2,000交易/7估值日/365天日期维度，同seed复现 |
| Standard/Large | 生成规模已实现：Standard 10,000/300,000、Large 100,000/3,000,000；默认无交易/无持仓/空职业 ≥5%/5%/3%（snapshot standard-v2/large-v2）；Tiny 内容摘要冻结 |
| 生成质量断言 | 60 条独立命名检查（规模/枚举/FK/粒度/恒等式/区间/边界日期/无交易无持仓NULL/分布相关性），任一失败不发布 manifest |
| 元数据 | T2a 检索 + 三十指标（metrics 0.3）：catalog/metrics 一致性、8 条 FK 只读列出、20 条经审查 Join 路径（仅 `customer_transactions` 可编译）、search_tables/columns/metrics、get_metric_definition、get_join_paths、派生 glossary；Agent 工具按授权过滤 |
| Gold 编译 | 单表、单指标、有限过滤、rolling / point-in-time / latest-snapshot；`active_customer_count` 可按 region 分组；唯一 `customer_transactions` Join；其他 Join/窗口函数直接报错 |
| 执行网关 | AST 白名单、授权行列前置物化、聚合粒度、子进程超时与结果校验；T1 修复物化写入性能（executemany→类型化字面量分块），语义不变 |
| Agent 端口 | 可信本地 Agent Protocol + SQL submission conformance adapter + 确定性 TemplateAgent（20 题接入测试驱动，非官方 baseline）+ 官方本地 `BaselineAgent`（独立 adapter，默认离线，不读 Gold）；外部网络 adapter fail-closed；无厂商 SDK |
| 评测闭环 | 三类动作正常路径可运行；evaluator 0.5 记录执行故障、完整响应、回执结果、slot 回复一致性与运行身份；0.4 仅为历史格式；无官方分数 |
| M2 Gold 素材 | `c360 build-gold` 生成 20 个 case 的可信侧私有素材：16 个可编译 Gold、2 个未支持能力、2 个非回答 oracle；不得交给 Agent |
| M2 dev case 素材 | catalog 0.3：公开 `human_cases.yaml` 只有问题/改写/case/version/split；可信 oracle 在仓库 `data/trusted/human_oracles.yaml`，不进 wheel/sdist；18 道可编译回答（含 Join/分组/latest-snapshot）；2 道澄清/拒答 unscored；覆盖报告 m2_complete=false，不是最终分数 |
| M2-04 改写语义校验 | 固定 60 条改写回归通过；极性检查拒绝非VIP/不成功等否定改写；canonical question 走同一检查；仍不是自由自然语言保真 |
| M2-05 Tiny 变体重放 | 冻结 seed 43 为 Tiny 分布变体；`c360 replay-variant` 重放同一编译 SQL；独立 oracle 交叉核验；不是五变体计分或 Agent 重跑 |
| M4-02 变体矩阵 | 四类变体在核验后的真实数据上 same_sql 重放；agent_rerun 必须注入独立 Agent；空聚合标 policy_incompatible；`scoring_applied=false` |
| M2-06 公开/可信制品分离 | 参评侧可读资源不含 expected action、semantic spec、missing slots、reason codes；`c360 doctor`/`smoke` 在无 oracle 文件时可运行；coverage/gold/rewrites/replay 需可信文件 |
| M4-01 多轮 evaluator | evaluator 0.5：多轮脚本、执行故障留痕、完整响应、具体策略拒绝与矛盾 slot 拒绝；0.4 仅为历史格式；无官方分数 |
| T4 打包 / CI | `.github/workflows/ci.yml`：公开树泄漏检查、Ubuntu 锁依赖/ruff/pytest/`uv build`、Windows 作业、Docker `--read-only --network=none` doctor 与 image Id 证据工件；sdist `only-include` 白名单；wheel 安装到独立 venv 后在源码目录外 doctor/smoke。远程 GitHub Actions 未在本地伪造 |
| GitHub 开源准备 | CONTRIBUTING/SECURITY/CODE_OF_CONDUCT、issue/PR 模板、gitignore 覆盖 outputs/tmp/duckdb、`docs/github-publish.md`；hidden pack 仍不进公开树。已本地 `git init -b main` 并暂存公开文件；未 commit / remote / tag |
| 报告 | 公共 smoke 的 manifest.json / records.jsonl / report.json，无正式分数；Tiny 另有 manifest/quality_report/生成配置快照；T3 另有 coverage.json / coverage.md；M2-05 另有 replay.json / replay.md；M4 矩阵私有 `private/matrix.json`+`records.jsonl` 与公开 `public/summary.json`+Markdown/HTML |
| M3 生成任务包 | `c360 generate-tasks --count 120 --seed 42`：独立 case_id C360_1001+，train/dev family 隔离，8 类错误场景；`c360 check-isolation` 拒绝把 C360_0001–0020 改标 hidden；m3_complete 只表示题包结构，不是官方分数 |
| M6 300 题结构 | `c360 generate-tasks --count 300 --seed 42`：180 train / 120 generated-dev；`m6_structure=true` 只表示结构验收；scoring_applied=false |
| M6 独立隐藏集 | `c360 generate-hidden`：C360_4001+，split=private，family 与 human/public 隔离；`generate-hidden-data --seed 1042` 写 hidden_profile；禁止 seed 42/43；不进 wheel |
| M6 隐藏评测 / 发布候选 | `c360 evaluate-hidden` 公开摘要不含问题/Gold/seed；`evaluate --split private` 仍拒绝改标 20 题；`prepare-release`/`check-release`：hidden_included=false、docker_included=false、scoring_applied=false，且必须有 300（180 train/120 dev）公开题 |
| M6 生成/隐藏语义验收 | `c360 verify-pack` / `verify-hidden`：独立 oracle 与编译 SQL 一致、8 类错误 SQL 可区分、改写槽位通过；300 题必须提供四个冻结 `--variant`，120 题可选诊断变体；隐藏验收 baseline-only；公开摘要不含问题/Gold/seed；`semantic_passed` 不是官方分数 |
| M7 受控资源预算与性能采集 | D055：Tiny 默认 10k 物化上限保留；Standard/Large 命名预算与 ATTACH 投影；`c360 perf-baseline` 已跑 Standard/Large generate + gold-execute；扫描量/Token unavailable；`scoring_applied=false`；默认 pytest 不跑 Large |
| M4 矩阵评测 | `c360 evaluate --agent template --mode same_sql`：一次提交的候选 SQL 在 Tiny baseline+四变体上重放；`--mode scoring` 拒绝；公开报告不含 Gold/spec/候选 SQL；不是加权总分 |
| M5 官方 Baseline | `c360 run-case --agent baseline` 与 `evaluate --agent baseline`：公开元数据检索→本地 adapter 规划→候选 SQL→网关；记录参数/重试/缓存/network_used；TemplateAgent 仍可选用但不是官方；外部 gpt/openai/network 标识 fail-closed |
| 正式评分协议 1.0 | 已实现：`c360 evaluate-public` / `evaluate-hidden --formal` 写 evaluator 0.6 `formal_input`；`c360 score` 分别输出 public_dev / private_hidden；`ranking_enabled=false`。历史 `evaluate --mode scoring` 仍拒绝 |
| 正式 RC 发布关卡 | 工具链已落地：Apache-2.0、Dockerfile、SHA256/SBOM、`prepare-formal-release`/`check-formal-release`。八个 RC 门改为内容校验（D057）。本机无 Docker、无 git：`docker_runtime` 未签署，不打 `v1.0.0` |
| FastAPI、任意插件沙箱、私有竞赛部署、外部模型 | 未实现；网络 adapter 仍 fail-closed |

本地使用 uv 管理的 Python 3.11.15 和项目 .venv；未替换系统默认 Python。已 `git init -b main` 并暂存公开树（gitignore 挡住 outputs/tmp/duckdb）；未 commit、未配置 remote、未打标签。

## 3. 验证与复跑

~~~bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
uv run c360 check-rewrites
uv run c360 generate-tasks --count 300 --seed 42 --output outputs/<生成题包目录>
uv run c360 check-isolation --pack outputs/<上述生成题包目录>
uv run c360 generate-hidden --public-pack outputs/<上述生成题包目录> --count 30 --output outputs/<隐藏题包目录>
uv run c360 check-isolation --pack outputs/<上述生成题包目录> --hidden outputs/<隐藏题包目录>
uv run c360 generate-hidden-data --seed 1042 --output outputs/<隐藏Tiny目录>
uv run c360 verify-pack --dataset outputs/<Tiny seed42> --pack outputs/<生成题包目录> --variant outputs/<seed43> --variant outputs/<fanout> --variant outputs/<null> --variant outputs/<date> --output outputs/<语义验收目录>
uv run c360 verify-hidden --dataset outputs/<隐藏Tiny目录> --pack outputs/<隐藏题包目录> --output outputs/<隐藏语义验收目录>
uv run c360 perf-baseline --dataset outputs/<Tiny seed42> --workload gold-execute --output outputs/<性能目录>
uv run c360 evaluate-hidden --dataset outputs/<隐藏Tiny目录> --pack outputs/<隐藏题包目录> --agent baseline --output outputs/<隐藏评测目录>
uv run c360 prepare-release --output outputs/<发布目录> --public-pack outputs/<生成题包目录> --hidden-pack outputs/<隐藏题包目录>
uv run c360 check-release --input outputs/<发布目录>
uv run c360 prepare-formal-release --output outputs/<正式发布目录> --public-pack outputs/<生成题包目录>
uv run c360 check-formal-release --input outputs/<正式发布目录>
uv run c360 evaluate --dataset outputs/<Tiny seed42> --distribution-variant outputs/<seed43> --duplicate-variant outputs/<fanout> --null-variant outputs/<null> --date-variant outputs/<date> --agent template --mode same_sql --output outputs/<矩阵目录>
uv run c360 run-case --case-id C360_0001 --agent baseline --dataset outputs/<Tiny seed42> --output outputs/<单题目录>
uv run c360 report --input outputs/<上述矩阵目录> --format json
uv run c360 generate-data --scale tiny --seed 42 --output outputs/<新目录>
uv run c360 generate-data --scale standard --seed 42 --output outputs/<Standard目录>
uv run c360 generate-data --scale tiny --seed 43 --output outputs/<变体目录>
uv run c360 coverage-report --dataset outputs/<上述 Tiny 目录> --output outputs/<覆盖报告目录>
uv run c360 replay-variant --baseline outputs/<上述 Tiny 目录> --variant outputs/<变体目录> --output outputs/<重放目录>
uv run c360 smoke --output outputs/<另一个新目录>
uv build
# 可选：把构建出的 wheel 装进独立虚拟环境，在源码目录外运行 c360 doctor / c360 smoke
~~~

验证基线以本节最新一轮 pytest 计数为准。测试包括合约边界、schema/FK、固定 seed、独立人工答案、比较器、AST 攻击、授权范围、最小聚合、超时回收、伪造回执、元数据检索、Tiny 复现性/seed 变化/质量断言/十指标独立切片/显式 Tiny 授权/T3 独立 oracle 与覆盖报告、受限 Join 的重复计数与权限测试、T4 wheel/sdist 泄漏检查和源码目录外 doctor/smoke、M2-04 改写槽位正例/负例、M2-05 同一 SQL 变体重放，以及 M2-06 公开题面/可信 oracle 泄漏检查。

H1–H8 加固后全量 `uv run pytest -q` 为 253 passed。阶段 B 后为 268 passed；阶段 C 后为 275 passed；阶段 D 后为 283 passed；阶段 E 后为 293 passed；阶段 F 初验为 302 passed；2026-09-18 复审全量回归为 313 passed，最后收尾的安全/隐藏包等定向回归为 88 passed。阶段 S 全量为 326 passed。阶段 G 全量为 345 passed。阶段 R 全量为 390 passed。GitHub 开源准备新增 `tests/test_public_tree.py`；定向 `pytest tests/test_public_tree.py tests/test_formal_release.py tests/test_packaging.py` 为 23 passed，ruff 通过。当前 evaluator 0.5（历史矩阵）/ 0.6（formal_input）；metrics 0.3；Tiny seed-42 九表 content hashes 与 quality_report_hash 不变。旧 Standard/Large 制品若仍是 standard-v1/large-v1，需按新默认比例重新生成，默认 pytest 不跑 Large。

smoke 预期为 3 pass + 2 fail（错误 SQL 和危险 SQL 是负例）；verification_passed=true 才表示架构检查成功。generate-data 预期输出 manifest/quality_report/generation_config/dataset.duckdb，60 条质量断言全部通过。coverage-report、check-rewrites、build-gold 和 replay-variant 需要仓库 `data/trusted/human_oracles.yaml`。coverage-report 预期 coverage_passed=true、m2_complete=false、18 道独立 oracle 与编译 SQL 一致；澄清/拒答不计分。check-rewrites 预期 passed=true、60 条改写、issue_count=0。replay-variant 预期 passed=true、replay_mode=same_sql、18/18 独立 oracle 匹配、至少一题结果与 seed 42 不同、m2_complete=false、scoring_applied=false。doctor 预期 tables=9、columns=72、metrics=30、join_paths=20、executable_join_paths=1、foreign_keys=8、glossary_entries=111。generate-tasks --count 120 预期 case_count=120、m3_complete=true、m6_structure=false、isolation_passed=true、scoring_applied=false；`--count 300` 预期 case_count=300、m6_structure=true、180 train/120 generated-dev。公开 YAML 不含 expected_action/spec。check-isolation 在无 pack 时只核验 C360_0001–0020 仍为 split=dev。generate-hidden 预期 case_id 从 C360_4001 起、split=private、isolation_passed=true。generate-hidden-data 拒绝 seed 42/43。verify-pack 预期 semantic_passed=true、scoring_applied=false、独立 oracle 匹配全部可编译题，公开 summary 不含 question/Gold/seed。verify-hidden 拒绝缺少 hidden_profile 的公开 Tiny。perf-baseline 预期 scoring_applied=false、scan_count_status=unavailable、token_status=unavailable，公开 summary 不含 question/Gold/SQL/seed；Tiny 默认 max_input_rows=10000。evaluate-hidden 公开 summary 不含 question/Gold/seed；scoring_applied=false。prepare-release 预期 hidden_included=false、docker_included=false、scoring_applied=false。prepare-formal-release 在缺少 docker_runtime 证据时 gates.docker_runtime=false，check-formal-release 必须失败。evaluate 预期 integrity_passed=true、scoring_applied=false、m4_scored=false；公开 summary 不含 candidate_sql/semantic_spec；`--mode scoring` 与 `--split private` 均 fail-closed。`c360 run-case --agent baseline` 预期 scoring_applied=false、network_used=false，并写出 adapter_calls.json。wheel 内 human_cases.yaml 不得含 expected_action/metric/missing_slots。输出目录必须不存在，重复检查用新路径，不要删除或覆盖已有结果。

## 4. 当前交接边界与下一步

已固定模块输入输出、可信/不可信数据方向、受控执行入口、最小语义子集、公开元数据检索、十个可编译单表指标、唯一受限 Join、版本化 20 个 dev case（含固定改写与结构化改写校验）、seed 43 同一 SQL 变体重放，以及可在源码目录外安装的 wheel。T4 与 M2-03/04/05 未改变 SQL 白名单、Gold 比较或 seed 42 生成器摘要；覆盖报告仍不是正式分数。

H1–H8、阶段 B–G/S 与正式评分工具链已落地。GitHub 公开文件已就绪，本地 git 已初始化且公开树已暂存。下一步是维护者按 [docs/github-publish.md](docs/github-publish.md) 审查 `git status`、用自己的身份 commit、创建 GitHub 远程并 push；**Linux/CI 签署 `docker_runtime` 后再打 `v1.0.0`**。本机 Windows 无 Docker：不得伪造 digest。不要把本机 `outputs/` 或 `tmp-formal-*` 推进 GitHub。历史 `evaluate`/`prepare-release` 仍 `scoring_applied=false`；正式分数只走 `c360 score`。当前 family 判重不能证明模板/指标/Join 各自隔离。不得把现有 20 道 dev case 改标成 private，不得把 TemplateAgent 标成官方 baseline，不得接未许可的外部模型，不得把 metadata_only Join 当成可编译路径，不得删除 Tiny 默认 10k 物化上限，不得把隐藏 pack 打进 wheel。

同一共享契约不要并行修改。SQL 安全、Gold/独立 oracle 边界、评分分母、隐藏切分、Agent 接入和空聚合语义由主 agent 负责；轻量 agent 接受冻结的输入输出、文件范围和行为验收标准。

## 5. T1 完成记录（Tiny 生成器，已交付）

### 交付物

- configs/data_generation.yaml：Tiny 唯一配置来源（scale/seed/anchor/horizon/规模/指定客户组）；
- src/customer360/contracts/generation.py：GenerationConfig（tiny 固定 100/2000，其余规模直接校验失败）、DatasetManifest（artifact_kind=tiny_dataset，generator_version=0.1.0）、QualityReport（≥30 条唯一命名检查）；
- src/customer360/synth/generator.py：generate_dataset(config, output_dir)，全部业务值来自局部 Random(seed)，输出 dataset.duckdb + manifest.json + quality_report.json + generation_config.json，目录独占创建；
- src/customer360/synth/constraints.py：60 条独立命名质量断言（CHECKS 表），生成连接内执行，任一失败抛错且不写 manifest；
- contracts/manifest.py：抽取 NineTableDigests 共用基类，FixtureManifest 字段与校验不变；
- runtime/worker.py：物化写入从 executemany 改为类型化字面量分块（synth/schema.render_literal），投影语义不变，解决 Tiny 规模下 10ms/行导致的网关超时；
- c360 generate-data --scale tiny\|standard\|large --seed 42 --output <新目录>；规模行数冻结，未知 scale 仍 fail-closed；
- tests/test_data_generation.py（17 项）+ test_config_and_cli.py 更新（原"generate-data 未实现应报错"改为真实命令断言）。

### 验收对照

1. 同 seed/同配置两次生成 manifest 与九表规范化摘要完全一致 ✓（测试 + CLI 双路径验证）；
2. 不同 seed 改变八张表内容（dim_date 为纯日历不受 seed 影响），不只改 manifest ✓；
3. 九表加载，客户 100、交易 2,000，其余表计数入 manifest ✓；
4. 60 条独立业务命名断言（≥30），无循环凑数 ✓；
5. 测试覆盖无交易/无持仓/NULL、FK、粒度、状态枚举、边界日期、金额符号、资产恒等式、服务区间 ✓；
6. 三指标在 Tiny 上执行并与独立 Python 切片核验一致 ✓；
7. 授权测试显式创建 Tiny customer_ids 策略（tiny_policy），沿用六客户 fixture_policy 的做法被明确排除 ✓；
8. pytest -q（118 passed）、ruff check/format、旧 smoke（verification_passed=true）全部通过 ✓；
9. README、ROADMAP、数据字典、本文已同步 ✓；
10. 无新增安全开关，SQL 白名单未放宽 ✓。

## 6. 可随后交给轻量 agent 的任务

- T3（已交付）：完善 Tiny 的边界 fixture、独立计算 oracle 和覆盖报告；为后续20题准备素材，未实现的题型仍标为未支持；
- T4（已交付）：Linux CI / 打包回归；wheel 不依赖源码工作目录，制品不含隐藏集、outputs、环境或密钥。
- M2-04（已交付）：为现有 3 条改写接入结构化语义一致性校验，覆盖日期、指标、过滤和 Join 路径；只扩展测试与可信侧校验，未改变 Agent 协议、评分权重或公开 split。
- M2-05（已交付）：冻结 Tiny seed 43 为分布变体，重放同一编译 SQL 并与独立 oracle 交叉核验；未引入五变体计分或 Agent 重跑。
- M2-06（已交付）：公开题面与可信 oracle 物理分离；wheel/sdist 不含 `data/trusted`；未把 dev case 当隐藏集，也未改 Agent 协议或评分权重。
- 隐藏切分（独立 C360_4001+）已由阶段 F 交付；五变体计分 / Docker / 正式加权分数仍需主 agent 在 ROADMAP 第8/10节确认后设计，不能作为便利修改。

每项单独交付、有测试再合并。共享契约与 catalog 同一时段应由一个任务负责修改，避免相互漂移。

## 7. 不应顺手改动的边界

以下工作要重新做设计/安全评审，不能作为后续便利修改：

- Join / CTE / 窗口 / 分组支持和行级权限传播；
- 任意 Python Agent、模型 API、网络访问、真实私有数据、公开竞赛服务；
- 多轮用户模拟、隐藏 slot 回放和完整交互评分；
- 同一 SQL 的五数据变体重放与完整 Agent 重跑的计分区别；
- 修改 Gold、比较容差、评分权重或用 LLM 判正确；
- 将 materialization 行数当作实际扫描量，将超时结果当空结果；
- 绕过最小聚合策略以让空结果题通过；
- 直接提交生成数据、私有答案、日志或发布包到外部服务。

ROADMAP 第10节产品默认已由 D057 冻结为本地离线 audit、Apache-2.0、DuckDB-only、无排名。外部模型网络许可仍未开放。这些不阻塞当前本地回归。

## 8. 给下一位 agent 的可复制任务

> 阅读 AGENTS.md、HANDOFF.md、ROADMAP.md、docs/user-guide.md、docs/development-plan.md。H1–H8 与阶段 B/C/D/E/F/S/G/R 及正式评分工具链已完成。下一步是 Linux/CI 签署 docker_runtime 后打 v1.0.0。不要伪造 Docker digest，不要 git init 打标签，不要把 C360_0001–0020 改标 hidden，不要放宽 min_group_size，不要把 19 条 metadata_only Join 编译进 Guard，不要把 TemplateAgent 标成官方 baseline，不要接未许可的外部模型，不要删除 Tiny 默认 10k 物化上限，不要把隐藏 pack 打进 wheel。历史 evaluate/prepare-release 保持 scoring_applied=false。

## 9. 最终验证记录

阶段 G / 受控资源预算与性能采集（本轮）已完成：

- 冻结 D055：命名预算 `tiny`/`standard`/`large` 绑定 `DatasetManifest.scale`；Tiny 默认 `max_input_rows=10000` 保留；
- Tiny 仍 VALUES 物化；Standard/Large 用 ATTACH + 授权 `CREATE TABLE AS`，DETACH 后执行候选 SQL；未删 10k Tiny 默认限额；
- `c360 perf-baseline` 公开摘要不含问题、Gold、SQL 和 seed；扫描量/Token unavailable；`scoring_applied=false`；
- 本机采集（诊断，不是官方分数）：Standard generate ~71s（10,000/300,000）；Large generate ~491s（100,000/3,000,000）；Standard gold-execute P50/P95 ≈ 0.46s/0.69s；Large gold-execute P50/P95 ≈ 0.87s/3.15s；17 道可执行 Gold 通过，C360_0012 为 POLICY_INCOMPATIBLE；
- 零贡献 Gold 经网关仍为 `POLICY_INCOMPATIBLE`，不计为资源失败；
- Tiny seed-42 九表 content hashes 不变；C360_0001–0020 仍 split=dev；未启用 ROADMAP 第 8 节权重；未实现 PostgreSQL；
- 阶段 G 原始验收：`uv run pytest -q` 345 passed；ruff check/format 通过；`c360 doctor` tables=9 columns=72 metrics=30 join_paths=20 executable_join_paths=1 glossary=111。本轮结果另见复审记录。

阶段 S / 生成与隐藏包语义验收（本轮）已完成：

- 冻结 D054：`semantic_passed` 独立于 `m6_structure`；公开包绑定 Tiny seed 42，隐藏包绑定 hidden Tiny；零贡献 Gold 为 POLICY_INCOMPATIBLE；
- `c360 verify-pack` / `verify-hidden`：独立 oracle 与编译 SQL 交叉核验、8 类错误 SQL 可区分、生成改写槽位通过；300 题按冻结顺序绑定四个 `--variant`，120 题可选诊断变体；隐藏验收 baseline-only；策略不兼容由执行网关显式判定；
- 公开摘要不含问题、Gold、spec、SQL 和 dataset seed；`scoring_applied=false`；`coverage-report` 仍只覆盖 20 道 human case；
- Tiny seed-42 九表 content hashes 不变；C360_0001–0020 仍 split=dev；未启用 ROADMAP 第 8 节权重；未删除 worker 10k 限额；
- 阶段 S 原始验收：`uv run pytest -q` 326 passed；ruff check/format 通过；`c360 doctor` tables=9 columns=72 metrics=30 join_paths=20 executable_join_paths=1 glossary=111。本轮 0.2 协议验证另见复审记录。

阶段 F / M6 隐藏集与发布准备（本轮）已完成：

- 冻结 D048–D051：独立隐藏 pack（C360_4001+，split=private）、隔离 Tiny seed 1042、300 公开生成题、release manifest 不含 Docker/分数/隐藏文件；
- `c360 generate-tasks --count 300`：180 train / 120 generated-dev，m6_structure=true，scoring_applied=false；C360_0001–0020 仍 split=dev；
- `c360 generate-hidden` / `generate-hidden-data` / `evaluate-hidden` / `prepare-release` / `check-release`；
- 隐藏 family 与 human/public 隔离；公开隐藏摘要不含问题、Gold、spec、候选 SQL 和隐藏 seed；
- wheel/sdist 仍排除 `data/hidden` 与 `data/trusted`；未启用 ROADMAP 第 8 节权重；未接入 Docker/FastAPI/厂商 SDK；
- Tiny seed-42 九表 content hashes 不变；阶段 F 复审 `uv run pytest -q`：313 passed；最后收尾定向回归 88 passed；ruff check/format 通过；release check 已硬性要求 300（180 train/120 dev）公开题结构。

阶段 E / M5 官方 Baseline（本轮）已完成：

- 冻结 D047：官方 Baseline 是 `BaselineAgent` + 可替换 model adapter；默认 `LocalDeterministicAdapter` 离线；外部网络 adapter fail-closed；TemplateAgent 仍是协议驱动；
- 流水线：公开元数据检索 → 计划 → SQL → 网关执行 → 组答；支持 success / clarification_needed / refused / error；不读 Gold/spec；
- `c360 run-case --agent baseline` 写出 record/summary/adapter_calls；`evaluate --agent baseline` 可接入矩阵评测；`--agent gpt/openai/network` 拒绝；
- adapter 记录参数、重试、缓存命中、prompt digest 与 `network_used=false`；
- `scoring_applied=false`、`m4_scored=false`；C360_0001–0020 仍 split=dev；未启用 ROADMAP 第 8 节权重；未接入 FastAPI/厂商 SDK；
- Tiny seed-42 九表 content hashes 不变；`uv run pytest -q`：293 passed；ruff check/format 通过。

阶段 D / M4 矩阵评测（本轮）已完成：

- 冻结 D044–D046：一次 Agent 候选 SQL 在 Tiny baseline+四变体上 same_sql 重放；agent_rerun 分记；私有 JSONL 与公开脱敏报告分离；policy_incompatible/超时/截断不得记成空结果成功；
- `c360 evaluate --agent template --mode same_sql` 写出 `private/matrix.json`、`private/records.jsonl`、`public/summary.json`、Markdown/HTML；`--mode scoring` 与 `--split private` fail-closed；
- `c360 report --input <evaluate输出>` 只渲染脱敏摘要；公开制品不含 Gold/spec/候选 SQL；
- `scoring_applied=false`、`m4_scored=false`；覆盖报告仍 `m2_complete=false`；C360_0001–0020 仍 split=dev；
- `uv run pytest -q`：283 passed；ruff check/format 通过；Tiny seed-42 九表 content hashes 不变；未启用 ROADMAP 第 8 节权重。

阶段 C / M3（本轮）已完成：

- 冻结 D040–D043：semantic family、split 隔离、通用 TaskPack 与 20 题包分离、20 条 Join 仅 `customer_transactions` 可编译；
- metrics 0.3 共 30 个指标，沿用已有 count/sum/count_distinct 编译路径；AgentRequest metadata_version=0.3；
- `resources/join_paths.yaml` 20 条经审查业务路径；反向同一条边不重复计数；19 条 metadata_only；
- `c360 generate-tasks --count 120 --seed 42` 生成独立 C360_1001+，90 train / 30 dev，改写不计新题；`c360 check-isolation` 拒绝改标 C360_0001–0020；
- 至少覆盖 8 类错误场景；覆盖报告仍 `m2_complete=false`，生成包 `scoring_applied=false`；
- `uv run pytest -q`：275 passed；ruff check/format 通过；doctor metrics=30、join_paths=20、glossary_entries=111；check-rewrites 60/0；
- Tiny seed-42 九表 content hashes 与 quality_report_hash 不变；未启用正式分数或隐藏切分。

M2 基础闭环（本轮）已完成：

- `c360 build-gold --dataset outputs/tiny-t3 --output outputs/gold-m2-20260916` 成功生成私有 Gold 素材：20 个 case、16 个可编译回答、2 个未支持能力、2 个非回答 oracle；
- `evaluate_case` 支持 answer、clarification_needed、refuse；澄清按隐藏 SlotReply 回放一轮，并校验最终 SQL/结果；拒答校验 reason code；网关违规记录不会因最终拒答而被算作通过；评测记录版本升为 evaluator 0.2；
- 新增 Gold 构建和三类 oracle 回归测试；定向测试 14 passed，ruff check/format 通过；
- 本轮没有把 2 个未支持 case 伪装成 Gold，也没有宣称完整多轮或最终评分已经完成。
- 全量回归：`uv run pytest -q` 为 156 passed；ruff check/format 通过；
- CLI 回归：coverage `coverage_passed=true`、16/16 独立 oracle 匹配、`m2_complete=false`；smoke `verification_passed=true` 且 fixture manifest hash 仍为 `06524a1e…`；`uv build --out-dir dist-m2-final` 成功。

M2-01 语义与评测边界复核（本轮追加）已完成：

- 澄清回放的最终查询错误会得到 `RESULT_MISMATCH`，不会因第一轮槽位提问正确而通过；
- Agent 先提交危险 SQL 后返回拒答时，记录 `agent_policy_violation=true` 并判失败；
- `EvaluationRecord` 增加 `clarification_rounds` 和 `mode`，evaluator 回归版本保持 0.2；
- Gold 构建校验 Tiny manifest 的 catalog hash、九表行数和内容 hash，防止在错误数据上生成可审计性不足的 Gold；
- 定向测试 7 passed，全量 `pytest -q` 为 158 passed，ruff check/format 通过。

M2-02 最小 Join（本轮追加）已完成：

- 冻结并实现唯一 `customer_transactions` 路径：`dim_customer.customer_id → fact_transaction.customer_id`；只支持按客户去重计数，交易侧必须有 rolling 时间窗口；
- 元数据仓储与 Agent 工具可检索该 Join，并要求两侧表均在授权范围内；
- SQL 编译器、AST guard、授权投影 worker 和独立 Python oracle 均支持该路径；任意其他 Join、错误键、缺少窗口、重复计数写法继续拒绝；
- C360_0016 已从未支持能力升级为可编译回答，当前 20 个 case 为 16 个可编译、2 个未支持、2 个非回答 oracle；
- coverage：16/16 独立 oracle 匹配，`coverage_passed=true`；全量 `pytest -q` 为 164 passed，ruff check/format 通过。

M2-03 正式 dev case 包（本轮追加）已完成：

- `HumanCaseCatalog` 升为 `catalog_version=0.2`；每个 C360_0001–C360_0020 都固定 `task_version=human-0.1`、`split=dev` 和 3 条不重复的自然语言改写；canonical question 不得出现在改写中；
- 契约校验保持 answer/unsupported/clarification/refuse 的状态边界，并额外约束 Join case 的 category/spec 一致性；
- Gold 记录携带 task_version、split、rewrites，包级 task_version 改为 `human-0.1`；coverage 记录同样保留这些审计字段；
- 分组与 latest-snapshot 仍明确为 unsupported，当前没有声称 train/private split、五变体计分或完整多轮评分；改写自动语义判定已由 M2-04 补齐；同一 SQL 变体重放已由 M2-05 补齐；
- 定向契约/coverage/Gold 测试与全量回归见本次最终验证记录。

M2-04 改写语义一致性校验（本轮追加）已完成：

- 可信侧 `tasks/rewrites.py` 按 canonical SemanticSpec 检查日期、指标、过滤和 Join 路径；不调用编译器、DuckDB、Agent 或模型 judge；
- 20 个 case × 3 条改写全部通过；加载 catalog / `c360 check-rewrites` fail-closed；负例覆盖 90 天→三个月、笔数↔金额、总资产↔净资产、VIP/华东增减、Join 路径增减、澄清槽位被填满、拒答改写到姓名；
- C360_0006 第三条改写补上「近90天」，避免只有锚点、没有窗口长度；Gold SQL、catalog_version 和 split 未变；
- 未改变 SQL 白名单、评分权重、公开 split、覆盖报告分数语义或 Tiny 生成器。

M2-04 最终验收记录：

- `uv run ruff check src tests`：通过；`uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：189 passed；
- `c360 check-rewrites`：passed=true、60 条改写、issue_count=0，报告不含 m2_complete；
- `c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- 本轮未改变 Tiny 数据、manifest 摘要、SQL 安全白名单、评分权重或隐藏数据。

M2-05 Tiny 同一 SQL 变体重放（本轮追加）已完成：

- 冻结 seed 43 为 `tiny_seed_43_distribution`；baseline 必须是 seed 42 Tiny，变体必须是 seed 43 Tiny；公开 fixture 和种子对调 fail-closed；
- `c360 replay-variant` 只重放一次编译得到的 Gold SQL，不调用 Agent，不改评分权重；16 道可编译回答的独立 oracle 在变体上与 SQL 一致，且至少一题结果与 seed 42 不同；dim_date 保持不变；
- 已知错误窗口 SQL（90 天 Gold vs 30 天）在变体上仍能与独立 oracle 区分，避免空结果偶然通过；
- 报告 `m2_complete=false`、`scoring_applied=false`；覆盖报告仍不是正式分数；未实现五变体或 Agent 重跑模式。

M2-05 最终验收记录：

- `uv run ruff check src tests`：通过；`uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：193 passed；
- `c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `c360 check-rewrites`：passed=true、60 条改写、issue_count=0；
- 本轮未改变 seed 42 Tiny 摘要、SQL 安全白名单、Gold 比较容差、评分权重或隐藏数据。

M2-06 公开/可信制品分离（本轮追加）已完成：

- 包内 `human_cases.yaml` 升为 catalog 0.3 的 `public_human_cases`：只含 case_id、task_version、split、question、rewrites；
- 可信 overlay 在 `data/trusted/human_oracles.yaml`，含 expected action、semantic spec 字段、missing slots、reason codes；不进 wheel/sdist；
- `load_public_cases()` 可在无仓库 oracle 时使用；`load_human_cases()` / coverage / gold / rewrites / replay 缺少可信文件则 fail-closed；
- wheel 隔离测试：公开 20 题可加载，完整 catalog 在无 oracle 时失败；doctor 输出不含 missing_slots/reason codes；
- 未把 20 道 dev case 改标为 hidden/private，未改 Agent 协议、SQL 白名单或评分权重。

M1 Standard/Large（本轮追加）已完成：

- 冻结规模：Tiny 100/2,000、Standard 10,000/300,000、Large 100,000/3,000,000；非法行数或 Tiny 冒充其他规模 fail-closed；
- Tiny 仍用 C001/T0001 宽度，seed 42 九表 content_hashes 与 quality_report_hash `4684c2cdc41c…` 不变；
- `c360 generate-data --scale standard --seed 42` 两次摘要一致；Large 同 seed 生成 100k/3M 且质量断言通过；默认 pytest 不跑 Large。

M1 最终验收与复盘加固：

- `uv run pytest -q`：228 passed；ruff check/format 通过；
- `c360 generate-data --scale standard --seed 42` 两次：dim_customer=10000、fact_transaction=300000、all_passed=true、content_hashes 一致；
- `c360 generate-data --scale large --seed 42`：100000/3000000、all_passed=true；
- Tiny 控制生成 quality_report_hash 仍为 `4684c2cdc41cf97b5b5a6b9a2ebe602db2491be4d28c072cc6101b62f4dde683`；
- `c360 doctor` / `check-rewrites` / `smoke` / `coverage-report`：通过，fixture hash `06524a1e…`，coverage m2_complete=false；
- 复盘加固：Standard/Large 错行数、Tiny 标成 standard 的 manifest 均 fail-closed；
- 本轮未改变 SQL 白名单、Gold 比较、评分权重或公开 split。

M4-02 变体矩阵（本轮追加）已完成：

- 保留 `tiny_seed_43_distribution`；新增 `tiny_duplicate_fanout`、`tiny_null_empty_groups`、`tiny_date_boundary`；各自有 manifest/version；
- `c360 generate-variant --variant-id …` 从 seed 42 Tiny 做确定性变异（分布变体仍是 seed 43 生成）；
- `c360 replay-variant --mode same_sql|agent_rerun|scoring`：same_sql 不调用 Agent；agent_rerun 必须调用 Agent；scoring 直接拒绝且 `scoring_applied` 不能为 true；
- 四类变体均 16/16 独立 oracle 匹配、至少一题与 baseline 不同、dim_date 不变、90 天 Gold vs 30 天错误 SQL 仍能区分。

M4-02 最终验收与复盘加固：

- `uv run pytest -q`：223 passed；ruff check/format 通过；
- `c360 doctor` / `c360 check-rewrites` / `c360 smoke`：通过，fixture hash 仍为 `06524a1e…`；
- `c360 replay-variant` 对 seed 43 与 duplicate/fan-out 均 `passed=true`、`scoring_applied=false`、`m2_complete=false`；
- 复盘加固：变体目录不能当 baseline；same_sql 报告不能改标 agent_rerun；scoring 不能设 scoring_applied=true；
- 本轮未改变 Tiny seed 42 摘要、SQL 白名单、Gold 比较或评分权重。

M4-01 完整多轮 evaluator（本轮追加）已完成：

- `evaluate_case` 按隐藏 `ClarificationTurn` 脚本逐轮回放；缺省时现有 `replies` 仍是一轮，catalog C360_0019 行为不变且 `split=dev`；
- 每轮 `RoundAudit` 记录 request、response_status、requested_slots、tool_calls、receipts 和 policy_violation；`clarification_rounds` 不再限制为 1；
- 冻结 outcome/reason code：至少区分 CLARIFICATION_FAILURE、RESULT_MISMATCH、UNSAFE_SQL、REFUSAL_OK/REFUSAL_FAILURE、AGENT_ERROR、ORACLE_EXECUTION_ERROR；`EvaluationRecord` 无 score 字段；evaluator 0.3；
- 网关拒绝后即使后续 Success/Refusal 也不改判为通过；覆盖报告仍 `m2_complete=false`。

M4-01 最终验收与复盘加固：

- `uv run ruff check src tests`：通过；`uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：211 passed；
- `c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `c360 check-rewrites`：passed=true、60 条改写、issue_count=0；
- `c360 smoke`：verification_passed=true，fixture manifest hash 仍为 `06524a1e…`，evaluator_version=0.3；
- `c360 coverage-report --dataset outputs/tiny-t4`：coverage_passed=true、16/16、m2_complete=false；
- 复盘加固：脚本中途危险 SQL 后即使给出正确 Success 或拒答仍 fail；顺序脚本不允许一次要齐所有槽位；
- 本轮未改变 Tiny 数据、manifest 摘要、SQL 安全白名单、Gold 比较容差、评分权重或隐藏评测集。

M2-06 最终验收记录：

- `uv run ruff check src tests`：通过；`uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：200 passed；
- `c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `c360 check-rewrites`：passed=true、60 条改写、issue_count=0；
- 本轮未改变 seed 42 Tiny 摘要、SQL 安全白名单、Gold 比较容差、评分权重或隐藏评测集。

M2-03 最终验收记录：

- `uv run ruff check src tests`：通过；`uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：164 passed；
- `c360 coverage-report --dataset outputs/tiny-t3 --output <新目录>`：`coverage_passed=true`、16/16 independent oracle 匹配、2 unsupported、2 unscored、`m2_complete=false`；
- `c360 build-gold --dataset outputs/tiny-t3 --output <新目录>`：20 cases、16 compilable、2 unsupported、2 non-answer，Gold task_version 为 `human-0.1`；
- `c360 doctor`：9 tables、72 columns、10 metrics、8 foreign keys、91 glossary entries，`checks_passed=true`；
- `c360 smoke --output <新目录>`：3 expected pass + 2 expected fail，`verification_passed=true`，fixture manifest hash 仍为 `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`；
- 本轮未改变 Tiny 数据、manifest 摘要、SQL 安全白名单、评分权重或隐藏数据；新 CLI 输出目录均使用独占创建。

T4 轮次（本轮）已完成：

- `.github/workflows/ci.yml`：Ubuntu + Python 3.11，`uv sync --locked`、ruff、pytest、`uv build`；把 wheel 装进 `/tmp` 独立 venv，在源码目录外运行 `c360 doctor` 与 `c360 smoke`（不传仓库 `--config`，不使用 `--no-deps`）；
- `pyproject.toml` sdist `only-include` 白名单，显式排除 `outputs` / `.venv` / `.private` / `.env` / `data/hidden`；wheel 仅含 `src/customer360`；
- `c360 doctor` / `c360 smoke` 在缺少 `configs/benchmark.yaml` 时使用与该文件一致的打包默认值；
- `tests/test_packaging.py`：制品泄漏分类、wheel/sdist 必含公开资源、源码目录外 PYTHONPATH 安装后 doctor/smoke；
- 本地将 wheel 装入独立 venv 后，`customer360.__file__` 位于 site-packages 且不含 `src`，doctor/smoke 通过；
- GitHub Actions 的远程 Ubuntu 执行结果需在仓库启用 CI 后由平台记录，不能在本地伪造为已通过；
- `uv run ruff check src tests` / `uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：154 passed（原 149 项 + T4 5 项，旧测试未删除未放宽）；
- `uv run c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `uv run c360 smoke --output outputs/smoke-t4`：verification_passed=true，fixture manifest hash 仍为 `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`；
- `uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-t4`：九表 content_hashes 与 quality_report_hash `4684c2cdc41c…` 与加固后 Tiny 基线一致；
- `uv run c360 coverage-report --dataset outputs/tiny-t4 --output outputs/coverage-t4`：coverage_passed=true，m2_complete=false，16/16 oracle 匹配；
- `uv build --out-dir dist-ci`：wheel 53 个文件 / sdist 81 个文件；不含 outputs/.venv/.private/.env/duckdb；含 catalog/metrics/human_cases 与 CI 工作流；
- 未改 SQL 白名单、Gold 比较、Tiny 生成器或评分规则。

T3 轮次（上一轮）已完成：

- 20 个 case 写入 `resources/human_cases.yaml`（C360_0001–C360_0020）：15 道可编译单表回答题、1 道受限 Join、分组/latest-snapshot 两道未支持、澄清/拒答两道仅保存 oracle 契约；后续 M2-03 补齐了 task_version/split/三条改写。
- 独立 Python oracle（`tasks/independent.py`）不导入编译器、DuckDB、Agent 或 evaluator；空 SUM 为 NULL；与编译 SQL 交叉核验；
- Tiny 边界探针覆盖窗口外一天/首日/anchor、NULL 职业、无交易/无持仓、失败与撤销并存、多估值日、主服务 IS NULL、restricted 字段存在而 phone/id_card 不存在；
- `c360 coverage-report --dataset outputs/tiny-t3 --output outputs/coverage-t3`：coverage_passed=true，m2_complete=false，16/16 oracle 匹配，2 个未支持能力，2 个 unscored oracle；公开 fixture 不能冒充 Tiny；
- `distinct_customer_count` 允许 occupation 过滤（含 IS NULL），不是新指标口径；
- `uv run ruff check src tests` / `uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：149 passed（原 140 项 + T3 9 项，旧测试未删除未放宽）；
- `uv run c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `uv run c360 smoke --output outputs/smoke-t3`：verification_passed=true，fixture manifest hash 仍为 `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`；
- `uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-t3`：九表 content_hashes 与 quality_report_hash `4684c2cdc41c…` 与加固后 Tiny 基线一致；
- 未改 SQL 白名单、Gold 比较、Tiny 生成器或评分规则。

T2b 轮次已完成：

- 指标从 3 个扩到 10 个：活跃客户数、失败交易笔数、成功资金净流入/流入、当前主服务关系数、指定估值日总资产/净资产合计；口径写在 metrics.yaml 与数据字典；
- DSL 增加 `point_in_time`（显式 snapshot_date）；rolling 与 point-in-time 不能互换；`latest_snapshot` 直接拒绝；
- 编译器支持 boolean 固定过滤与 `fixed_null_columns`（当前主服务关系：is_primary=TRUE 且 end_date IS NULL）；快照指标编译为等值过滤，不含窗口函数或 Join；
- 公开 fixture 上手算切片与 Tiny 上 10 指标独立 Python 切片均与编译结果一致；
- `uv run ruff check src tests` / `uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：140 passed（原 130 项 + T2b 10 项量级，旧测试未删除未放宽）；
- `uv run c360 doctor`：tables=9、columns=72、metrics=10、foreign_keys=8、glossary_entries=91、checks_passed=true；
- `uv run c360 smoke --output outputs/smoke-t2b`：verification_passed=true，fixture manifest hash 仍为 `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`；
- `uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-t2b`：九表 content_hashes 与 quality_report_hash 与加固后 Tiny 基线一致；
- 未改 SQL 白名单、Gold 比较、Tiny 生成器或评分规则。

T2a 轮次已完成：

- 仓储新增 `search_columns`、`get_business_glossary`、`list_foreign_keys`、`consistency_report`；`search_metrics` 可用业务名/描述/示例问题检索，不把“资产规模”“最近三个月”映射到现有指标；
- glossary 由 catalog + metrics 派生，不另维护 glossary.yaml；phone/id_card 若写入 catalog 则 fail-closed；
- Agent 工具按授权表/列过滤，`search_tables` 不返回列清单，restricted 列不能通过检索泄漏；未知指标与未授权指标分别返回 `UNKNOWN_METRIC` / `PERMISSION_DENIED`；
- `c360 doctor` 输出 tables/columns/metrics/foreign_keys/glossary_entries/checks_passed；
- `uv run ruff check src tests` / `uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：130 passed（原 118 项 + T2a 12 项，旧测试未删除未放宽）；
- `uv run c360 doctor`：tables=9、columns=72、metrics=3、foreign_keys=8、glossary_entries=84、checks_passed=true；
- `uv run c360 smoke --output outputs/smoke-t2a`：verification_passed=true，fixture manifest hash 仍为 `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`；
- `uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-t2a`：九表 content_hashes 与 quality_report_hash 与加固后 Tiny 基线一致；
- 未改 SQL 白名单、Gold 比较、Tiny 生成器或评分规则。

T1 轮次已完成：

- `uv run ruff check src tests`：通过；
- `uv run ruff format --check src tests`：通过；
- `uv run pytest -q`：118 passed（M0 基线 92 项 + T1 新增 17 项及 CLI 断言更新 + 加固轮 7 项，旧测试未删除未放宽）；
- `uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-t1`：成功，100 客户/2,000 交易/365 日期维度/7 资产估值日/145 服务关系/982 持仓/800 资金流，60 条质量断言全部通过；
- 同 seed 重跑（独立目录）manifest 逐字节一致；seed 43 改变八张表内容，dim_date 不变（纯日历）；
- `--scale standard` 显式拒绝（exit 2，"not supported"），不创建目录；
- 授权链路：显式 Tiny customer_ids 策略下，网关对范围外客户返回 AGGREGATION_TOO_SMALL，restricted 列误配返回 PERMISSION_DENIED，evaluate_case 在 Tiny 上得到 pass/RESULT_MISMATCH/UNSAFE_SQL 三态；
- `uv run c360 smoke --output outputs/smoke-t1`：verification_passed=true（3 pass + 2 expected fail），manifest hash `06524a1e1e233d8c196620c6195a0f2f244cc7ad740c22b985a66da719428208`，与 M0 基线一致，fixture 行为未受 T1 影响；
- `uv build`：wheel（47 个文件）与 sdist（71 个文件）构建成功，不含 outputs/.venv/.private/生成数据集；configs/data_generation.yaml 留在仓库配置目录，不打进 wheel（与 benchmark.yaml 同策略）。

性能说明：DuckDB `executemany` 在本机约 10ms/行，Tiny 的 2000 行交易经网关物化会超过 15 秒预算。生成器与 worker 均改为类型化字面量分块插入（250 行/块），全量 pytest 从超时恢复到约 20 秒。下一位 agent 不要把当前耗时当作性能基线，也不要改回 executemany。

### 加固轮（T1 复审，本轮追加）

对 T1 做了独立复审，共修复/加固 6 项。**所有变更均为校验、检查和测试层面，业务数据零变更**——加固后重跑 seed 42，九表 content_hashes 与加固前逐项一致（row_counts 也一致），仅 quality_report_hash 因新增检查而变化。

1. 修正 GenerationConfig 校验 bug：指定客户组（无交易+无持仓+可空属性）上界原误写为 `2 * customers`；三组按构造互斥，正确上界为 `customers`；
2. 新增第 60 条命名检查 `date_dim_id_matches_calendar`（date_id 主键与 calendar_date 的 ISO 日期一致），补上 join 键正确性的空洞；
3. `load_generation_config` 对 YAML 中直接写非法 scale 的情况给出与 CLI 一致的 "not supported" 明确错误（原先漏出 pydantic 原始报错）；
4. 新增 fail-closed 发布测试：monkeypatch 使质量断言失败，验证 ValueError 抛出、manifest 与 generation_config 不落盘、quality_report 与部分目录保留——此前"任一失败不发布 manifest"只写在文档里没有测试；
5. 新增 `render_literal` 单测：类型覆盖、单引号转义、float/bytes 拒绝（fail-closed）、DuckDB 往返一致性。该函数被 worker 物化路径共享，转义错误属安全敏感面；
6. 新增 manifest 类型隔离测试：tiny_dataset 载荷不能通过 FixtureManifest 校验，反之亦然——落实交接要求的"不能把 Tiny 标记成 public_fixture_not_tiny"。

加固后回归：`pytest -q` 118 passed；`ruff check` / `format --check` 通过；旧 smoke verification_passed=true 且 fixture manifest hash 仍为 `06524a1e…`。

复审时明确不改动的一项：已注销客户在主服务关系结束后仍可能出现一段已终止的非主服务关系（is_primary=false 且 end_date 非空）。它不违反任何已冻结口径（`service_ongoing_not_closed` 只约束 end_date IS NULL 的关系），不属于已确认业务规则，为避免无依据地变更数据而保留现状；若需要更紧的语义，应先在数据字典冻结口径再改生成器并升版本。

M0 轮次记录保留如下：92 项测试通过；wheel 44 文件/sdist 66 文件的边界检查通过；从源码目录外用构建 wheel 运行 doctor/smoke 通过；`uv run --offline --no-project --with wheel` 因本机无 DuckDB 离线缓存不可用，非源码问题。
