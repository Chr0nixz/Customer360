# 工程决策记录

状态：以下为本次架构实现采用的工程默认值；v1.0 产品默认见 D057，其余未决项仍以 ROADMAP 第10节为准。怎么跑命令见 [使用说明](user-guide.md)。

| 编号 | 决策 | 原因 / 后续影响 |
|---|---|---|
| D001 | 单一 Python 包，src 布局，uv 锁依赖，Python 3.11 | 当前无需服务拆分或复杂 DI 框架；FastAPI/模型 SDK 暂不安装 |
| D002 | contracts 分公开模型与私有 oracle，Agent 只依赖公共端口 | 避免把答案、完整语义或权限控制权交给被测对象 |
| D003 | catalog.yaml 为 schema 单一来源，运行时生成 DDL | 同步字段、权限类型、DDL 和 fixture；wheel 自带公开资源，无工作目录依赖 |
| D004 | 暂用六客户公开 fixture 验证链路 | 先独立人工核验 3、4、650.00；不冒充 Tiny 或20道正式题 |
| D005 | 只开放单表聚合 SQL 子集 | 简化权限传播，未设计的语法明确拒绝；扩展时须重新审查 |
| D006 | 候选 SQL 执行于授权行列物化后的独立内存库 | 不依赖 Agent 自觉添加 WHERE；避免把只读原库完整暴露给 SQL |
| D007 | spawn worker + 父进程超时回收 | Windows 可运行；记录启动成本，不把 smoke 延迟当性能成绩 |
| D008 | 当前数据 CNY-only，金额/数量固定精度 | 防止跨币种直接求和；多币种需新口径和数据版本 |
| D009 | 金额/日期用类型化字符串传输，整数保持整数 | JSON 序列化可精确复现；浮点类型后续另行明确容差 |
| D010 | min_group_size 默认1，零客户结果当前被抑制 | 空权限不表示全部客户；零贡献 Gold 在网关侧记为 POLICY_INCOMPATIBLE，不降低粒度、不算 Agent 答错 |
| D011 | 只提供真实实现的 CLI，不注册空壳成功命令 | generate-data 已实现；evaluate 等按里程碑逐步增加 |
| D012 | 保留五个正反例 smoke 检查，不生成总分 | evaluator/Agent 能力与 conformance 检查严格区分 |
| D013 | 生成器与 worker 的批量写入用类型化字面量分块（synth/schema.render_literal） | DuckDB executemany 逐行约 10ms，Tiny 规模会超时；字面量只接受 schema 类型白名单，类型外 fail-closed，语义与参数化一致 |
| D014 | 60 条命名质量断言在生成连接内执行，任一失败不发布 manifest | 失败目录（数据库+质量报告）保留供排查，不自动清理；不放宽断言换通过 |
| D015 | 已注销客户允许存在已终止（end_date 非空）的非主服务关系 | 不违反已冻结口径（service_ongoing_not_closed 只约束未终止关系）；收紧语义须先更新数据字典并升 generator 版本，禁止生成器内静默改 |
| D016 | 业务词表由 catalog 与 metrics 派生，不另建 glossary.yaml | 避免第二份口径来源；未出现在 schema/指标中的词不得被检索命中 |
| D017 | v0.1 catalog 禁止 phone/id_card 实体字段 | 安全集区分“字段不存在”与“字段存在但受限”；未先更新 schema 决策不得加入这些列 |
| D018 | 指定估值日指标使用显式 point_in_time，不得编译成 latest-snapshot | `snapshot_total_asset` / `snapshot_net_asset` 仍是单日等值过滤；逐客户最新快照改由 D039 的独立指标承担 |
| D019 | T3 用独立 Python oracle 交叉核验 Tiny 规划题，不把覆盖报告当成 M2 分数 | 防止编译器与 SQL 引擎共享同一错误；覆盖报告保持 m2_complete=false，不是加权总分 |
| D020 | Linux CI 在源码目录外安装 wheel；sdist 用白名单，制品不得含 outputs/隐藏集/密钥 | doctor/smoke 可在无仓库配置时使用打包默认值；CI 只验证公开资源和可安装性，不宣称完成 Docker/模型服务；远程 GitHub Actions 结果不能在本地伪造 |
| D021 | 澄清 oracle 使用一次确定性 slot 回放后再检查最终查询 | 防止只检查“问了正确槽位”却忽略补齐后的 SQL/结果；这是一轮回放，不扩展为完整多轮评分 |
| D022 | Gold 通过 `build-gold` 生成到显式私有目录 | SQL/结果属于可信侧，不进入 Agent 输入或 wheel；未支持能力和拒答题只保存原因/契约，不伪造 Gold SQL |
| D023 | evaluator 版本从 0.1 升为 0.2 | 新增澄清回放和拒答 reason code 判定，属于评测行为变更；协议、数据和指标版本保持不变 |
| D024 | M2 只开放 `customer_transactions` 一条 Join 路径 | 客户属性筛选连接交易明细后按 customer_id 去重，交易侧必须有 rolling 窗口；其他 Join 与窗口函数继续拒绝；分组见 D038 |
| D025 | 改写语义一致性用结构化槽位证据，不用 LLM judge | 对照 canonical SemanticSpec 检查日期/指标/过滤/Join；改写不是 Gold；catalog 加载与 `c360 check-rewrites` fail-closed；不改变评分权重或公开 split |
| D026 | 首个 Tiny 数据变体是 seed 43 分布变体，评测模式为 same-SQL 重放 | 不改 seed 42 生成器摘要；不把变体重放当成五变体计分或 Agent 重跑；覆盖报告与 replay 报告均保持 m2_complete=false |
| D027 | 公开 human_cases 与可信 oracles 分文件；catalog_version 0.3 | 参评包只含问题/改写；semantic spec、slots、reason codes 留在仓库 `data/trusted`，不进 wheel/sdist；不是隐藏评测集 |
| D028 | evaluator 升为 0.3：可序列化多轮 slot 脚本 + 逐轮审计 | 先冻结 outcome/reason code，不引入加权分数；缺省 replies 仍是一轮以保持 C360_0019；中途网关拒绝不可被后续 Success/Refusal 洗白 |
| D029 | Tiny 变体矩阵为 1 个分布变体 + 3 个变异变体；评测模式三分 | seed 43 仍是分布变体；duplicate/NULL/日期边界从 seed 42 变异并写独立 manifest；same_sql 与 agent_rerun 不能混记；scoring_applied 保持 false |
| D030 | Standard/Large 规模冻结；Tiny ID 宽度不随规模加宽 | Standard 1e4/3e5、Large 1e5/3e6；Tiny 保持 C001/T0001 与 seed-42 摘要；标识符宽度=max(Tiny 最小宽度, len(str(count)))；默认 pytest 不生成 Large |
| D031 | SQL Guard 先全树白名单，再单表/受限 Join 子集 | Join 不得跳过 CTE/HAVING/子查询/外部函数检查；IN 与 IS NULL 按 `.this` 解析，禁止 AttributeError；不扩大安全白名单 |
| D032 | Gold/coverage/variant 共用可信数据核验 | 执行前重算 catalog/行数/九表内容摘要；结果规范化一律 fetchall；篡改数据保留原 manifest 必须失败 |
| D033 | agent_rerun 必须注入独立 Agent | 编排层不得把 Gold SQL 塞进 SqlSubmissionAgent；same_sql 禁止调用 Agent；CLI `--mode agent_rerun` 无注入则 fail-closed |
| D034 | evaluator 升为 0.4：执行故障留痕与完整响应 | TIMEOUT/WORKER_CRASH/EXECUTION_ERROR 记入工具审计；RoundAudit 保存完整响应与回执结果；AgentError 不再记成 UNEXPECTED_ACTION；记录 task/metadata/policy 身份 |
| D035 | 改写检查覆盖极性与 canonical question | 非VIP/不成功/非空等否定不得因包含关键词而通过；未知表达仍拒绝；不用 LLM 当真值 |
| D036 | 空聚合与 D010 对齐，不豁免最小粒度 | 参考查询若 AGGREGATION_TOO_SMALL，评测为 POLICY_INCOMPATIBLE；变体重放标 policy_incompatible，不调用 Agent，不算答错 |
| D037 | Standard/Large 恢复 ≥5%/5%/3% 边界人群 | 配置与质量检查都按业务比例验收；snapshot 升为 standard-v2/large-v2；Tiny 仍 tiny-v1，九表内容摘要不变 |
| D038 | 分组仅开放 `active_customer_count` × `region` | 输出为观察到的组键 + 指标列；不补零组；NULL 按 SQL GROUP BY 自成为组；无序多重集；JOIN+GROUP BY / HAVING / ORDER BY 拒绝；min_group_size 仍按全局贡献客户数，不降为 0 |
| D039 | `latest_total_asset` 为逐客户 MAX(snapshot_date≤anchor) 再 SUM | 缺失快照排除不计 0；UNIQUE(customer_id,snapshot_date) 无并列；SQL 用 MAX+自连接，不用窗口函数；Tiny 全覆盖日不能区分 PIT，区分证据用手算切片；point-in-time 指标仍禁止 latest |
| D040 | semantic family 由模板、指标、Join、时间语义、过滤签名、分组和 expected action 构成 | 改写共享 family_id，不计新题；family_id 为规范化指纹的稳定摘要，不用 Python hash()；同源语义不得跨 split |
| D041 | split 隔离先于扩题；C360_0001–0020 永久 split=dev | 禁止把现有 20 题改标 train/test/private/hidden/challenge；隐藏集必须用独立新 case_id（C360_1001+）；本阶段只生成 train/dev，不创建隐藏评测集 |
| D042 | 通用 TaskPack 与冻结 20 题包分离 | HumanCaseCatalog 仍是 catalog 0.3、恰好 20 题；生成包 pack_id=generated-m3-0.1，不改 20 题校验；覆盖报告 m2_complete=false，生成包 scoring_applied=false |
| D043 | 20 条 Join 按经审查业务路径计数；仅 customer_transactions 可编译 | 反向同一条边不重复计数；时间有效性/预聚合不同可并列；其余 19 条 metadata_only，Guard/编译器仍拒绝；不新开窗口函数或 CTE |
| D044 | 矩阵评测：一次 Agent 提交的候选 SQL 在 baseline+4 变体上 same_sql 重放 | 不重放 Gold SQL 充当 Agent 成绩；agent_rerun 必须逐快照调用注入的 Agent；两模式不得写入同一鲁棒性分数；scoring_applied 必须为 false |
| D045 | 私有 JSONL 与公开脱敏报告分离 | 公开报告不含 Gold SQL/结果、semantic spec、missing slots、候选 SQL 和结果行；私有记录保留审计字段；C360_0001–0020 仍 split=dev |
| D046 | 适用变体、阶段和失败原因必须逐题记录 | policy_incompatible 不调用 Agent、不算答错；超时/崩溃/截断不得记成空结果成功；错误 SQL 在变体上仍须能与独立 oracle 区分 |
| D047 | 官方 Baseline 是独立本地 planner + 可替换 model adapter | `BaselineAgent` 只通过公开工具检索/执行，不读 Gold/spec；`LocalDeterministicAdapter` 为默认离线实现；外部网络 adapter fail-closed，直至 ROADMAP 第10节确认许可；TemplateAgent 仍是协议驱动，不得标成官方 baseline；不启用第8节权重；不接入 FastAPI/厂商 SDK |
| D048 | 隐藏集是独立 generated pack，case_id 从 C360_4001 起，split=private | 禁止把 C360_0001–0020 或公开 train/dev 改标 hidden；family 与 human/public 包隔离；公开 YAML 仍不含 spec；不进 wheel/sdist |
| D049 | 隐藏数据是带 hidden_profile 的 Tiny，默认 seed 1042 | 禁止复用公开 seed 42/43；缺少 profile 的公开 Tiny 不能当隐藏评测集；不改 seed-42 九表内容摘要 |
| D050 | 正式公开生成包目标 300 独立语义 case | `generate-tasks --count 300` 为 180 train / 120 generated-dev；m6_structure 只表示题包结构；human 20 题仍额外 split=dev；scoring_applied=false |
| D051 | 发布候选含 release manifest 与打包隔离，不含 Docker/分数/隐藏文件 | `prepare-release` / `check-release` 记录版本与公开摘要；Docker、许可证、运行位置仍按 ROADMAP 第10节未决；第8节权重仍不启用 |
| D052 | 阶段 F 复审采用 fail-closed 完整性检查 | 生成数据 sidecar 必须与 manifest 身份/摘要一致；SQL Guard 检查每层 SELECT 与字段字面量类型；隐藏报告/pack 校验计数与关联；release 只有 300（180 train/120 dev）结构才通过；工具策略拒绝和执行异常保留稳定审计码；不改变评分权重、业务口径或公开 split |
| D053 | evaluator 记录版本升为 0.5 | 阶段 F 复审将未捕获的 `QueryRejected` 从泛化 `AGENT_ERROR` 改为具体稳定失败码，并审计所有工具策略拒绝；新增 `INPUT_LIMIT` 表示 worker 物化输入超限，矩阵重放保留该码；0.4 记录保留为历史证据，不与 0.5 记录混批；不改变评分权重或 Gold 口径 |
| D054 | 生成/隐藏包语义验收独立于 `m6_structure` | `m6_structure` 只表示 300 题结构；`semantic_passed` 要求可编译题在绑定数据上独立 oracle 与编译 SQL 一致、8 类错误 SQL 可区分、改写槽位通过，变体存在时 same_sql 全部适用快照通过。公开 300 绑定 Tiny seed 42；隐藏包只绑定带 `hidden_profile` 的 Tiny（默认 1042）。零贡献 Gold 记 `POLICY_INCOMPATIBLE`，不是 Agent 答错，不降低 `min_group_size`。`coverage-report` 仍只服务 20 道 human case。`scoring_applied` 必须为 false |
| D055 | 受控资源预算按数据集规模绑定，Tiny 默认 10k 物化上限保留 | 预算 profile 为 `tiny`/`standard`/`large`，由 `DatasetManifest.scale` 决定，不能由 Agent 选择。Tiny：`max_input_rows=10000`、15s、128MB、`max_rows=100`（与现网关默认一致）。Standard：400000 行/60s/512MB。Large：4000000 行/180s/1024MB。0 或缺省不表示无限。预算与规模不一致 fail-closed。候选 SQL 仍只在授权行列物化后的隔离内存库执行（D006）。Tiny 仍用参数化提取 + 类型化 VALUES。Standard/Large 在 worker 内 ATTACH 只读源库，按授权列和 `customer_id` 做 `CREATE TABLE AS`，DETACH 并关闭外部访问后再跑候选 SQL；超限为 `INPUT_LIMIT`，不是扫描量。扫描量和 Token 标记 `unavailable`，禁止报 0。超时仍 terminate/kill/join（D007）。截断结果不能当完整正确答案。评测记录版本保持 0.5；性能报告是独立 `report_kind`，带 `budget_profile`，`scoring_applied=false`。Standard/Large 评测策略的 `customer_ids` 来自已核验 `dim_customer`，不硬编码 `C001`–`C100`。隐藏集仍是 Tiny。默认 pytest/smoke/`evaluate`/`verify-pack` 继续使用 tiny 预算 |
| D056 | 生成包变体契约与隐藏验收边界收紧 | `verify-pack` 对 `m6_structure=true` 的 300 题必须按固定顺序绑定 `tiny_seed_43_distribution`、`tiny_duplicate_fanout`、`tiny_null_empty_groups`、`tiny_date_boundary` 四个公开 Tiny 变体；120 题保留可选诊断变体兼容性。变体 `policy_incompatible` 只由执行网关返回的明确 `AGGREGATION_TOO_SMALL` 判定，不能从空结果猜测；权限范围外但合法的可信 Gold 不作为语义失败。隐藏验收拒绝任何公开变体，保持 baseline-only，避免隐藏包借由公开快照泄漏。报告协议由 0.1 升为 0.2，补充逐条计数、变体顺序和策略证据一致性校验。该收紧只影响语义验收契约，不启用官方加权分数。 |
| D057 | v1.0 正式路径冻结 ROADMAP 第 8/10 节默认值；RC 门看证据内容 | 本地离线 audit，`ranking_enabled=false`，public_dev 与 private_hidden 永不合并。网络 adapter / FastAPI / 厂商 SDK 仍 fail-closed。九张核心表、DuckDB-only。Token/扫描量 unavailable。Apache-2.0 覆盖代码；hidden/trusted/Gold 不进 wheel、sdist、镜像或公开 tar。历史 `prepare-release` 仍按 D051 无分数/无 Docker。正式 `c360 score` 使用冻结权重 0.45/0.20/0.15/0.15/0.05；硬门槛为 integrity、p0_safety、robustness_coverage、nonempty_denominators。Agent 90%/P95 目标是诊断，不是第九个 RC 门。八个 RC 门必须校验证据内容，文件存在不等于通过；未签署的 `docker_runtime` 不得携带 digest，不得打 `v1.0.0`。 |
| D058 | 公开 Git 树与分发制品分开；CI 记录 Docker image Id 作 RC 证据 | 源码仓库可含社区文件与 `data/trusted`（仅 20 道 human case）。`outputs/`、`tmp-*/`、`*.duckdb`、hidden pack、`.env` 必须 gitignore，且不得跟踪。wheel/sdist/镜像仍排除 trusted/hidden。CI `public-tree` 拒绝已跟踪的私有文件；Docker 作业用 `docker inspect` 的 image Id（`sha256:`+64 hex）写 `DockerRuntimeEvidence` 工件，不是伪造 digest，也不是自动打 `v1.0.0`。没有真实仓库 URL 时不写虚构 Homepage。 |

当前未实现 OS 级任意代码隔离，不支持运行不可信 Python Agent 或公开接收提交。v1.0 的运行位置是本地 CLI，外加可选非 root、`--read-only --network=none` 的 Docker；本机未安装 Docker 时 `docker_runtime` 保持未签署。

D056 补充：300 题不能通过把 `m6_structure` 改成 false 绕过四变体门；验证前校验变体 ID 唯一性、catalog/date-dimension 一致性，矩阵与验收共用冻结 ID 常量。`policy_block_code` 仅保存在私有逐题/变体记录，权限拒绝不会变成已授权成功。Gold 与独立 oracle 在所有已提供快照上都必须匹配，包括 `AGGREGATION_TOO_SMALL` 的快照；不适用 Agent 计分不等于免验 Gold。0.1 报告只作历史证据，升级需重新验收而非改写版本号；evaluator 0.5、任务/数据版本和官方评分权重不变。隐藏 baseline-only 仅为现状说明，不代表满足正式的隐藏多变体发布门。验证命令与结果见 [复审记录](review-s-g.md)。

更改这些默认值前，先记录受影响的契约、版本、测试和迁移方式。特别是 D002/D005/D006 不应由后续轻量 agent 在扩充数据时改动。
