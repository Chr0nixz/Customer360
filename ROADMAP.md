# Customer360 Agent Benchmark Roadmap

> 文档版本：v0.2；编写日期：2026-09-16；审阅更新：2026-09-18（基于 `Customer360-Agent-Benchmark-Implementation-Plan.md`）  
> 状态：M0–M7、正式评分协议 1.0、evaluator 0.6、四个私有隐藏变体 provenance/same-SQL replay、Apache-2.0、Docker、SHA256/SBOM 和 formal release 工具链已实现；GitHub 社区文件、公开树忽略规则和发布清单已就绪。RC evidence gates 尚未在本地全部签署，因此暂不打 v1.0.0 标签。public_dev/private_hidden 分开报告且不排名。在线服务、在线排行榜、外部模型 API、PostgreSQL 和不可信 Python OS 沙箱仍明确不在范围内。本文版本不代表软件或评测协议版本。Linux/Windows 工作流已入库，远程运行结果以平台记录为准。  
> 目标：把方案落成一个可复现、可审计、可扩展的 Customer360 Agent 评测基准。CLI 用法见 [使用说明](docs/user-guide.md)。

## 1. 北极星目标

交付一套不依赖真实业务数据、但能真实检验 Agent 能力的 benchmark，覆盖：

- 业务语义理解与指标口径识别；
- 多表关联、时间语义、客户筛选与聚合；
- SQL 生成、执行和结果解释；
- 多轮澄清与不可回答判断；
- SQL、数据权限和结果输出安全；
- 元数据变化、数据分布变化和边界数据下的鲁棒性；
- 延迟、工具调用次数和扫描量等工程效率指标。

最终结果必须满足：Gold Answer 可由结构化语义和程序生成，评测结果可重复，错误可以归因，第三方 Agent 可以通过统一协议接入。

## 2. 范围与非目标

### 本期范围

1. 9 张核心业务表，DuckDB 作为默认执行引擎；
2. Tiny、Standard、Large 三档可复现合成数据；
3. 表、字段、指标、Join、权限策略五类元数据；
4. 结构化任务 DSL、参考 SQL、参考结果和自然语言任务；
5. 单轮、澄清、多轮、安全拒答、元数据漂移任务；
6. 官方 Baseline Agent、工具协议和自动化 evaluator；
7. Public Train、Dev、Private Test、Challenge 数据切分；
8. CLI、Docker、JSONL/HTML 评测报告和接入文档。

### 明确不在第一版的范围

- 不接入真实客户数据或任何不可公开的生产凭证；
- 不把 LLM Judge 作为最终正确性裁判；
- 不先支持多种数据库方言；PostgreSQL 作为后续适配目标；
- 不先追求题量，先保证 20 道人工题和评测核心链路可信；
- 不把自然语言改写质量当成 Gold，所有改写必须回到结构化语义校验。

## 3. 关键不变量

这些规则贯穿所有阶段，不能为了赶进度临时放宽：

1. 固定 `seed + snapshot_version + generator_version + 配置摘要 + 锁定依赖` 必须生成相同规范化数据；文件级字节一致性与数据内容一致性分开验证；
2. Gold 由 semantic spec、参考查询编译器和执行结果生成，不能由模型直接编写；
3. 结果比较以语义为中心，不比较 SQL 字符串；
4. evaluator 在执行 Agent SQL 前必须经过静态安全检查和访问策略检查；
5. 隐藏集、隐藏数据变体和测试权限不能随提交物泄漏；
6. 任何指标都必须有业务名称、技术名称、粒度、时间语义、空值规则、默认过滤和版本；
7. 任务、Agent 输出、工具调用和评测结果都必须可序列化、可审计；
8. 错误必须尽量归入稳定的失败分类，而不是只返回“wrong”。

### 方案中的口径冻结项

- 首版日期型字段的“近 90 天”暂定为含 anchor date 的 90 个自然日，即 `[anchor_date - 89 天, anchor_date]`；时间戳版本须另定时区和端点。“最近三个月”“本季度”等表达不能与之互换；
- 结果比较默认按无序多重集，保留重复行数；只有 semantic spec 明确集合语义时才去重。带 `ORDER BY`/Top-K 的题必须定义并列处理或稳定 tie-breaker；
- 资产、交易、持仓等快照题必须明确 anchor date、是否取每个客户最新快照、是否允许缺失快照；
- `answer` 题才需要参考 SQL 和参考结果；`clarification_needed` 题需要缺失 slot 与合格澄清判定；`refuse` 题需要 reason code 和合规替代方案；
- benchmark 质量门槛与官方 Baseline 的模型成绩分开：前者验证数据/Gold/evaluator 正确，后者才衡量 Agent 能力。
- 原方案未列出 phone/id_card 实体字段，安全集必须区分“不存在字段”与“存在但受限字段”；首版用已有 customer_name/金融字段测试真实权限阻断，用 phone/id_card 测试未知字段，新增合成敏感字段需先更新 schema 决策。
- 原方案“至少 20 条 Join”按经审查的有效关系/业务路径计，不强行给九表补造 20 条直接外键；连接键、方向、基数、时间有效性和预聚合要求必须明确，反向同一条边不重复计数。

## 4. 里程碑总览

建议按依赖顺序推进。可以先做无依赖的设计和 stub，但依赖验收未通过时不能宣称下游集成完成。没有人员投入和目标日期前不虚设日历工期；各阶段用可核验证据退出。

### 当前检查点（2026-09-18 复审）

- [x] M0 工程配置、锁依赖、CLI、共享契约、catalog、执行网关和测试基线；
- [x] 一条公开六客户 fixture 纵向链路：Gold 编译、授权执行、结果比较、错误 SQL 和危险 SQL 负例；
- [x] M1 Tiny/Standard/Large 生成实现：Tiny 100/2,000（C001，seed-42 内容摘要冻结）、Standard 10,000/300,000、Large 100,000/3,000,000；60 条命名质量断言与生成 CLI；Standard/Large 边界人群 ≥5%/5%/3%（standard-v2/large-v2），默认 pytest 不跑 Large；
- [x] M1（部分）T2a 元数据检索：catalog/metrics 一致性、字段/业务词检索、授权过滤；外键只读列出，Join 编译未开放；
- [x] M1（部分）T2b 十个单表指标：含 rolling 与显式 point-in-time，Tiny 独立切片交叉核验；
- [x] M1（部分）T3 Tiny 边界探针、20 个 case 的独立 Python oracle 与覆盖报告；
- [x] M2（部分）可信侧 Gold 构建、三类动作基本链路、受限客户→交易 Join、catalog 0.3 公开/可信分离、固定改写检查（含极性）与核验后的 Gold SQL 重放；分组/latest-snapshot 已可编译；仍不能宣称通用自然语言保真或正式发布；
- [x] M2-06 公开任务输入与可信 Gold/slot/oracle 物理分离；wheel/sdist 不含 trusted oracles；独立隐藏评测集由阶段 F 单独交付；
- [x] M4-01 修复关卡：evaluator 0.5 多轮脚本、执行故障留痕、完整响应、矛盾 slot 拒绝与稳定策略拒绝分类；0.4 仅保留历史记录；不计算加权分数；
- [x] M4-02 修复关卡：四类变体核验真实数据摘要；agent_rerun 注入独立 Agent；空聚合 POLICY_INCOMPATIBLE；尚未应用鲁棒性计分；
- [x] M1 Standard/Large 分布：默认无交易/无持仓/空职业 ≥5%/5%/3%，snapshot standard-v2/large-v2；Tiny 内容摘要不变；
- [x] M2 20 道 dev case 动作链路：18 道可编译回答（含分组/latest-snapshot）+ 澄清/拒答 oracle；覆盖仍 m2_complete=false，不是隐藏切分或正式分数；
- [x] M2 隐藏切分：独立新 case C360_4001+，split=private；C360_0001–0020 仍为 split=dev；
- [x] M3 30 指标、20 条有效 Join 路径、120 道独立语义 case；family/split 隔离已落地；仅 `customer_transactions` 可编译；不是隐藏切分或正式分数；
- [x] M4 矩阵评测与脱敏报告：一次 Agent SQL 在 baseline+4 变体 same_sql 重放，agent_rerun 分记；scoring_applied=false；worker 10k 限额仍在；
- [x] M4 正式加权分数与完整资源控制：formal evaluator input、固定分母/hard gates、超时/缺失/执行失败计分规则与 token/scan unavailable 已实现；
- [x] M5 官方 Baseline、独立 model adapter 与 CLI runner（本地离线；网络/FastAPI 仍 fail-closed）；多轮 runner 使用 evaluator 0.5，0.4 记录不混批；
- [x] T4 Linux CI / 打包回归：锁依赖、pytest/ruff、wheel/sdist 内容检查与源码目录外 doctor smoke；公开树泄漏检查、Windows 作业、Docker image Id 证据工件与社区文件已纳入 GitHub 准备；
- [x] M6（部分）独立隐藏集、300 公开生成题、release manifest 与打包隔离；候选 `prepare-release` 仍无 Docker/分数；
- [x] M6 代码质量复审：默认 seed-42 摘要保持；最小配置的随机访问边界、SQL AST/字面量边界、数据 sidecar、隐藏 profile/报告契约和 release 300 题硬验收均有回归；可信 pack 与 Agent 公开输入边界已写入文档；2026-09-18 全量 `pytest` 372 passed，ruff 通过；
- [x] M6 生成/隐藏包语义验收与正式发布工具链：独立 oracle、8 类错误 SQL、改写槽位；300 题绑定四个公开 Tiny 变体，私有隐藏 baseline 绑定四个带 provenance 变体并执行 same-SQL replay；正式 `score`、Apache-2.0、Docker、SHA256/SBOM 和 `check-formal-release` 已实现；
- [x] M7（部分）受控资源预算与性能采集：D055 命名 profile；Tiny 默认 10k 物化上限保留；`c360 perf-baseline`；扫描量/Token unavailable；
- [x] GitHub 开源准备：Apache-2.0 社区文件、CONTRIBUTING/SECURITY、issue/PR 模板、gitignore 覆盖 `outputs/`/`tmp-*/`/`*.duckdb`、发布清单；维护者仍需自建远程并审查 `git status`；
- [ ] M6 剩余：完成八个 RC evidence gates 并签署 v1.0.0；M7 后续：PostgreSQL 适配设计、指标版本演化。

### 下一阶段执行顺序（先修复，再扩展）

详细工作包、依赖、验收标准与主/轻量 agent 分工见 [后续开发计划](docs/development-plan.md)。H1–H8 与阶段 B–F/S/G 及正式评分工具链已实施；剩余是签署八个 RC evidence gates（本机 docker_runtime 未签署）与 M7 PostgreSQL/指标演化。

1. **H1–H8 修复关卡**：已实施。
2. **M2 补齐与最小接入**：已实施分组/latest-snapshot（D038/D039）与确定性 TemplateAgent；覆盖仍非官方分数。
3. **M3 自动任务扩展**：已实施 semantic family 与 split 隔离、30 指标、20 条有效 Join 路径和 120 独立语义 case；C360_0001–0020 仍为 split=dev。
4. **M4 评测/报告**：已实施矩阵评测与公私报告；正式分母/缺失/超时策略确认前不得启用计分。**M5 baseline**：已实施官方本地 Baseline 与独立 adapter；TemplateAgent 不是官方 baseline；接外部模型前仍须确认网络许可。
5. **M6 隐藏集与发布**：已实施独立隐藏 pack、300 题结构、语义验收、正式 `score` 与 formal release 工具链（D057）。剩余是签署八个 RC evidence gates；本机 `docker_runtime` 未签署，不打 v1.0.0。**M7 性能**：已实施受控资源预算与 `perf-baseline`；不得删除 Tiny 10k 默认上限；PostgreSQL 适配仍未做。

| 里程碑 | 目标 | 主要产物 | 退出标准 |
|---|---|---|---|
| M0 | 工程基线与决策冻结 | `pyproject.toml`、目录骨架、配置约定、决策记录 | 可安装、可运行 hello CLI、关键决策已记录 |
| M1 | 数据与语义底座 | DDL、生成器、Tiny 数据、基础元数据 | 9 表可加载，固定 seed 可复现，质量断言通过 |
| M2 | Gold 与最小评测闭环 | DSL、参考 SQL、20 道人工题、基础安全执行/比较 | 20 题都有按动作分类的 oracle，回答题可执行/人工核验 |
| M3 | 自动任务与元数据能力 | 指标/Join 检索、任务模板、120 题生成器 | 任务语义校验通过，覆盖至少 8 类错误场景 |
| M4 | 评测器与安全围栏 | evaluator、SQL Guard、结果比较、多快照变体 | 能判定正确/错误/澄清/拒答，安全违规可拦截 |
| M5 | 官方 Baseline 与多轮协议 | Baseline Agent、工具协议、接入 API/CLI | 单轮、多轮、安全题跑通，输出符合协议 |
| M6 | 正式 benchmark 发布 | 300 题、分片、Docker、报告、文档 | 开发集和隐藏集可独立运行，发布包可复现 |
| M7 | 性能与扩展 | Standard/Large 性能基线、PostgreSQL 适配设计 | 受控环境记录性能差距，扩展点和兼容性有测试覆盖 |

## 5. 分阶段执行计划

### M0：工程基线与决策冻结

**工作内容**

- 创建 `src/customer360`、`tests`、`configs`、`data`、`docs`、`outputs` 目录；
- 建立 Python 3.11、DuckDB、Pydantic、SQLGlot、Pytest、Typer 的最小依赖与锁文件；FastAPI 和模型 SDK 延至对应模块需要时作为可选依赖；
- 定义统一配置加载、日志、随机种子和版本信息；
- 定义核心数据契约：semantic spec、Agent response、tool call、evaluation record 和版本 manifest；
- 固化一个独立的 SQL execution gateway：任何 Agent SQL 都必须经过 AST、权限、资源和结果检查，禁止把执行权限直接暴露给 baseline；
- 记录数据集版本、指标版本、协议版本和报告版本；
- 先实现 `c360 --help`；其余命令随里程碑逐步实现，不用返回假成功的空壳充当验收。

**退出标准**

- 新环境可安装依赖并运行测试；
- `c360 --help` 可用；
- 配置不依赖硬编码绝对路径或本机密钥；
- M0 决策项（见第 10 节）有明确结论或显式默认值。

**首批可领取事项（尚未完成）**

- [x] M0-01：工程配置、锁文件、CLI 安装及最小测试；
- [x] M0-02：确定各表主键/粒度、金额币种、时间窗口、服务关系有效区间和状态口径，写入数据字典草案；
- [x] M0-03：定义公开 Agent 输入与私有 CaseOracle 的分离模型及字段校验；
- [x] M0-04：确定执行网关、策略来源、私有制品路径与报告脱敏边界；
- [x] M0-05：添加公开合成 fixture 的测试目录；尚无实现的命令在文档中标为计划项。

### M1：数据与语义底座

**工作内容**

- 实现 9 张核心表 DDL 和关系定义；
- 实现 Tiny 数据生成器，再扩展到 Standard/Large；
- 实现客户、服务关系、资产、交易、资金流业务约束；
- 生成日期快照、空值、重复值、边界日期和极端金额；
- 实现数据质量检查：外键、金额关系、主服务经理唯一性、状态枚举、快照粒度等；
- 建立表、字段、敏感级别和 Join 元数据初版。

**退出标准**

- Tiny 数据可用 DuckDB 加载并完成基础查询；
- 固定 seed/配置/版本生成的规范化数据摘要稳定；
- 至少 30 个数据质量断言通过；
- 至少 10 个核心指标定义可被读取。

### M2：Gold 任务链路

**工作内容**

- 设计并冻结 semantic DSL；
- 先手工编写 20 道可解释题，覆盖单表、多表、时间、聚合、客户筛选、澄清和拒答，并为每题标记 expected action；
- 从 DSL 编译参考 SQL，不允许任务作者绕过 DSL 手写唯一 Gold；
- 对 answer 题执行参考 SQL，保存标准化结果、列定义、假设和证据；澄清题保存缺失 slot 与补充后的 Gold，拒答题保存 reason code 与替代方案；
- 用人工可算的 Tiny fixture 或独立计算逻辑交叉验证 Gold，防止 DSL 编译器与 evaluator 共享同一个错误；
- 上线最小 execution gateway、比较器和只读权限检查后，才允许执行任何待评 SQL；完整对抗覆盖留在 M4；
- 为每题生成 3～5 个自然语言表达，并进行语义一致性校验；
- 建立人工核验清单，记录预期失败模式。

**退出标准**

- 20 题都有 `semantic_spec` 和自然语言问题；其中 `answer` 题有参考 SQL/结果，澄清和拒答题有可机器检查的 slot/reason code；
- 结果在 Tiny 数据和至少一个变体上可复现；
- 每题至少映射一个预期错误分类；
- 任何 Gold 改动都能追溯到 DSL 或编译器变更。

### M3：自动任务与元数据能力

**工作内容**

- 实现 `search_tables`、`get_table_schema`、`search_columns`、`search_metrics`、`get_metric_definition`、`get_join_paths`、`get_business_glossary`、`validate_query_plan`、`get_access_policy`；
- 补齐至少 30 个业务指标和至少 20 条有效 Join 关系/业务路径（按第 3 节口径计数）；
- 实现模板组合器，控制任务难度、覆盖率和切分隔离；
- 生成 120 道可执行题，并加入同义表达、空值、重复值、边界日期和多义描述；
- 实现多轮澄清任务的缺失 slot 标注和补充轮次；
- 实现安全、不可回答、指标不存在和元数据漂移任务。

**退出标准**

- 生成的任务均通过结构校验；回答路径通过参考查询执行和结果合理性检查，澄清/拒答路径通过 slot/reason code 校验；
- 训练/开发/测试按模板、指标组合、Join 路径和数据分布隔离；
- 至少覆盖 8 类失败场景；
- 任务生成可用 seed 重放。

**题量预算说明**

原方案按类型列出的数量合计为 330，而正式目标是 300。本路线图暂按“300 道唯一 case + 多个标签可重叠”管理，不把类型配额当作冻结协议；进入 M6 前需确认最终配额。若需要严格按 300 道互斥类型分配，建议先采用 45/25/55/35/25/35/40/25/15（依次对应原方案九类），再由实际覆盖率校准。

### M4：评测器与安全围栏

**工作内容**

- 使用 SQLGlot AST 检查语句类型、表列存在性、危险操作、Join 风险、重复计数、行数和资源限制；
- 对 DuckDB 外部文件读取、扩展加载、函数副作用和非白名单数据源做显式封禁/隔离；AST 检查不能替代执行环境隔离；
- 在执行前应用角色、表、字段和结果粒度策略；
- 实现无序集合、有序结果、数值容差、日期、NULL、小数精度和空结果比较；
- 支持正常数据 + 至少 4 个数据变体的多快照执行；
- 明确评测模式：同一 Agent 会话的 SQL 是否在每个变体上重跑，或只重放 SQL；两者不得混为同一鲁棒性分数；
- 实现语义正确性、输出格式、安全、交互、延迟和鲁棒性评分；
- 生成 JSONL 原始记录与 HTML 摘要报告；
- 建立失败分类：`SCHEMA_ERROR`、`METRIC_ERROR`、`FILTER_ERROR`、`TIME_RANGE_ERROR`、`JOIN_ERROR`、`DUPLICATE_COUNT_ERROR`、`AGGREGATION_ERROR`、`NULL_HANDLING_ERROR`、`PERMISSION_ERROR`、`UNSAFE_SQL`、`CLARIFICATION_FAILURE`、`TIMEOUT`。

**退出标准**

- evaluator 能区分回答、澄清、拒答、超时和异常；
- 同一输入重复评测结果一致；
- P0 安全违规可被可靠阻断；
- 错误报告包含 case、变体、阶段、失败分类和可审计证据。

### M5：官方 Baseline 与多轮协议

**工作内容**

- 实现 Router → Intent Parser → Metadata Retriever → Metric Resolver → Planner → SQL Generator → Guard → Executor → Validator → Composer 链路；
- 固化工具调用 JSON 协议和最终输出协议；
- 支持 `success`、`clarification_needed`、`refused`、`error` 等状态；
- 支持多轮对话上下文、最少且足够的澄清问题和补充后重规划；
- 将 baseline 接入 evaluator 与 CLI；FastAPI 按 D001/D047 延后，网络模型 adapter fail-closed；
- 提供一个不依赖特定厂商 SDK 的可替换模型/Agent adapter。

**退出标准**

- Baseline 能完成 M2 的单轮任务；
- 能在多轮题中识别缺失条件且不擅自假设；
- 不执行危险 SQL，不越权输出敏感字段；
- 所有输出可被 evaluator 直接消费。

### M6：正式 benchmark 发布

**工作内容**

- 扩展到 300 道正式题；
- 生成 Train/Dev/Private Test/Challenge；
- 封装 Docker 一键运行、数据版本和配置；
- 发布任务格式、评测协议、Agent 接入、数据字典和提交说明；
- 固化评分权重和硬门槛；
- 建立 release manifest、校验和、变更日志和回归基线。

**退出标准**

- 新环境按文档可完成生成、运行、评测和报告；
- Private Test 不出现在公开构建产物和日志中；
- 官方 baseline 在发布版本上有可复现的基准成绩；
- 所有交付物与版本号、commit/构建摘要关联。

### M7：性能与扩展

**工作内容**

- 已实施：命名资源预算（D055）、流式物化、`c360 perf-baseline` 采集 generate/gold-execute/evaluate 的耗时、失败码、P50/P95；
- Token 与扫描量在未实现测量前标记 unavailable，禁止报 0；
- Tiny 默认 10k 物化上限保留；Standard/Large 使用有限更高 cap，并与 scale 绑定；
- 尚未实施：PostgreSQL 适配层、指标版本演化、字段改名/废弃矩阵。

**退出标准**

- 简单任务 P95 ≤ 30 秒，中等任务 P95 ≤ 90 秒，复杂任务 P95 ≤ 180 秒（采集报告作诊断对照，不是官方分数）；
- 同一 semantic spec 在不同规模数据上仍使用同一口径和比较规则；数据量带来的业务结果变化不应被误判为回归；
- 适配层有明确能力矩阵和回归测试（PostgreSQL 仍未做）。

## 6. 并行工作流与依赖关系

```text
M0 基线
  ├── M1 数据/Schema ───────┐
  ├── M1 元数据初版 ────────┼──> M2 Gold 任务
  └── 协议/配置契约 ────────┘          │
                                      v
                              M3 自动任务与检索
                                      │
                    ┌─────────────────┴─────────────────┐
                    v                                   v
              M4 evaluator/安全                    M5 Baseline Agent
                    └─────────────────┬─────────────────┘
                                      v
                               M6 正式发布
                                      v
                               M7 性能扩展
```

建议按五条工作流拆分，但每条工作流必须以共享契约为边界：

| 工作流 | 负责范围 | 不能自行改变的内容 |
|---|---|---|
| Data | DDL、生成器、快照、质量检查 | semantic DSL、评分规则 |
| Metadata | 表列指标 Join 权限和检索 | Gold 结果和测试切分 |
| Tasks | DSL、模板、参考查询、语言变体 | SQL Guard 规则 |
| Evaluator | 执行、比较、安全、报告 | 指标业务口径 |
| Baseline | Agent、工具、协议和适配器 | evaluator 最终裁判逻辑 |

## 7. 版本与验收门

### v0.1 研究原型

- 9 表、Tiny、10 指标、20 人工题；
- 能生成 Gold、执行 Agent SQL、比较结果；
- 只支持单轮和基础安全检查。

### v0.2 开发版

- 30 指标、20 Join、120 自动题；
- 多数据变体、澄清题、安全题和失败归因可用；
- 官方 baseline 可跑通。

### v1.0 发布版

- 300 题、完整切分、Docker、报告、协议、文档；
- 固定评分权重和硬门槛；
- 至少一次完整发布候选回归。

### 每个 PR 的最小验收

- 改动范围内有测试；
- 不破坏固定 seed 的现有摘要；
- 不绕过安全围栏；
- 不修改 Gold/评分规则而不更新版本和变更说明；
- CLI 或协议变更同步更新文档和样例。

## 8. 评分协议与发布门槛

### 自动评测权重

| 维度 | 权重 | 主要内容 |
|---|---:|---|
| 结果正确性 | 45% | 语义结果 35%、字段/格式 5%、解释完整性 5% |
| 安全性 | 20% | SQL 安全、权限、敏感数据、拒答和安全替代方案 |
| 多轮交互 | 15% | 歧义识别、澄清质量、轮数和工具调用效率 |
| 响应效率 | 15% | P50/P95、Token、工具调用次数、扫描量 |
| 鲁棒性 | 5% | 数据变体、同义表达、空值、边界和元数据小幅变化 |

进入 M6 前必须冻结每项分母、缺失值处理、超时计分、置信区间和软/硬门槛关系；解释完整性优先依据结构化证据字段校验，LLM 只辅助抽检。延迟记录必须包含硬件、并发、模型、缓存状态和计时边界，避免把不同运行条件下的 P95 直接排名。

### benchmark 质量门

- 参考查询编译器、结果比较器和安全围栏的人工回归必须 100% 通过；
- 所有发布 case 都必须有可审计的 Gold 生成路径；
- P0 评测器缺陷未解释前，不能发布排名结果。

### Agent 成绩门槛

- 可回答任务最终正确率 ≥ 90%；
- P0 安全违规 = 0；
- 不可回答任务错误回答率 ≤ 5%；
- 简单任务 P95 ≤ 30 秒；中等任务 P95 ≤ 90 秒；复杂任务 P95 ≤ 180 秒。

Agent 成绩门槛是官方 Baseline/参评 Agent 的目标，不得用 Agent 分数掩盖 benchmark 自身缺陷。硬门槛优先于加权总分；任何 P0 安全违规都不能通过 Agent 发布门，即使总分达标。

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 指标口径含糊 | Gold 不可信、题目不可审计 | 指标版本化；每题保存口径、时间语义和空值规则 |
| 任务模板泄漏 | 测试集被模板记忆而非理解 | 按模板、组合、Join、分布做切分隔离 |
| SQL 字符串比较 | 错误拒绝或错误放行 | 以多变体执行结果和语义比较为准 |
| 随机数据过于理想 | Agent 只学表面模式 | 加入空值、重复、边界和分布变体 |
| 评测器自身有 bug | 排名失真 | 20 道人工题、对抗 SQL、变体回归和人工抽检 |
| 安全只做 SQL 静态检查 | 合法 SQL 仍可能越权/泄露 | SQL、策略、结果三层防线 |
| 过早扩展多数据库 | 方言和结果差异拖慢主线 | DuckDB 先冻结语义，PostgreSQL 后置 |
| 过度依赖 LLM Judge | 评测不可重复 | Judge 只做解释、归因辅助和人工复核排序 |
| 大数据集拖慢开发 | 反馈周期过长 | Tiny 作为默认回归，Standard/Large 作为 nightly/perf |

## 10. 需要确认的产品/赛制决策

以下事项的 v1.0 默认值已由 D057 冻结（本地离线、无排名、Apache-2.0、DuckDB-only、Token/扫描量 unavailable）。外部模型网络许可仍未开放：

1. benchmark 第一目标是内部研发回归，还是公开竞赛/论文评测？
2. 参评 Agent 是否允许调用外部模型 API，还是必须离线运行？
3. 是否必须纳入营销活动扩展表；如果纳入，首版是否仍保持 9 张核心表为最低基线？
4. Private Test 的运行方式是本地容器、远程评测服务，还是两者并存？
5. 是否需要从第一版开始兼容 PostgreSQL，还是接受 DuckDB-only 发布？
6. 评分中是否要把模型成本、Token 或调用次数换算成硬门槛/排名项？
7. 项目和数据集的许可证、公开范围、是否允许商业使用？
8. 是否有目标发布日期或外部演示节点？这会决定 M6 的题量和 M7 的优先级。

## 11. 完成定义（Definition of Done）

只有同时满足以下条件，才称为“第一版完成”：

1. 可复现地生成 9 张核心表和多档数据；
2. 至少 30 个业务指标和 20 条 Join 关系可检索；
3. 至少 120 道结构化任务可生成，正式版扩展到 300 道；
4. 每道题拥有 semantic spec、参考查询、参考结果和版本信息；
5. evaluator 支持语义比较、多变体执行、失败归因和报告；
6. SQL、权限和结果安全围栏默认开启；
7. Baseline 支持单轮、多轮和安全拒答；
8. CLI、Docker、接入协议和文档可供第三方使用；
9. 固定数据、任务和评分版本有校验和及变更记录；
10. 发布候选在全量回归中无未解释的 P0/P1 问题。
