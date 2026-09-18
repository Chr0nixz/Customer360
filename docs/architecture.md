# 架构与正式发布边界 1.0.0

命令怎么跑见 [使用说明](user-guide.md)。本文只讲信任边界和模块职责。

## 1. 装配与职责

application.py 是 composition root：装配公开 fixture、元数据仓储、可信策略、执行网关、SQL 提交适配器和 evaluator。业务模块不自己寻找全局数据库、读取凭证或调用外部模型。

~~~text
Public AgentRequest --> Agent.respond(request, AgentTools)
                                      |
                             ToolSession（受控工具）
                                      |
                                   Gateway
                                      |
                AST 白名单 / 表列授权 / QueryRejected
                                      |
                          spawn 独立 SQL worker
                                      |
        只读源库 -> 授权行列物化 -> 关闭源库连接
                                      |
            独立内存库 -> 最小聚合粒度 -> 候选 SQL
                                      |
                 结果契约 / 结果安全 -> query_id 回执
                                      |
                         Session 执行记录（可信）

PrivateCase -> CaseOracle -> SemanticSpec -> Gold compiler
                                      |
                               独立 Gold 回执
                                      |
                 evaluator 比较候选执行记录与参考结果
~~~

Gold 使用同一授权范围，但回执不进入 Agent 的会话记录。必须同时有成功状态、真实执行回执、相符的提交 SQL、正确结果，才能判对；伪造自然语言答案或 query_id 不能得分。

## 2. 代码依赖

- contracts 是无数据库 I/O 的 Pydantic 契约层；public 不导入 oracle/semantic。
- agent 仅依赖 public、端口、adapter 审计契约和安全错误类型；测试禁止它导入 oracle、semantic、tasks、evaluator、runtime 或 DuckDB。官方 `BaselineAgent` 与 TemplateAgent 同属该边界。
- metadata 装载包内公开 schema/指标，不访问 Gold 或数据库。
- synth 通过 metadata 的 schema 契约创建数据，不导入 agent/evaluator。
- tasks 从 DSL 确定性生成 SQL；不接受自由 SQL 作为唯一 Gold，不调用模型。
- safety 验证候选 AST 和结果；runtime 执行和实施可信策略。
- evaluator 持有私有 oracle，并通过执行回执判断结果。
- CLI / application 只负责编排、参数和输出，不复制业务指标规则。

metadata/repository.py 提供统一导入入口，装载与检索实现在 metadata/metrics.py。仓储侧可检索表、列、三十指标、20 条经审查 Join 路径和由 catalog/metrics 派生的业务词，并校验指标引用、业务名唯一性和未声明实体字段（phone/id_card）。`get_join_paths` 只返回当前授权表均已授予的路径；`compile_status=executable` 目前只有 `customer_transactions`。Agent 工具端口只返回当前授权表/列对应的元数据；`search_tables` 不附带列清单。`validate_query_plan` 尚未实现；metadata_only 路径可检索但不可编译。

## 3. 当前 SQL 能力边界

允许单个无别名、无库名前缀的表；一个带输出别名的 COUNT(*)、COUNT(column)、COUNT(DISTINCT column) 或 SUM(decimal_column)；WHERE 支持列与字面量比较、AND/OR、IN、IS NULL / IS NOT NULL 及括号。

另有两个显式子集：`dim_customer` 上 `GROUP BY region` 且 SELECT 为组键加 COUNT DISTINCT customer_id；以及 `fact_asset_snapshot` 上 MAX(snapshot_date) 自连接后再 SUM(total_asset)。固定 Join 只允许 `dim_customer.customer_id = fact_transaction.customer_id`、客户去重计数和交易侧 rolling 窗口。

拒绝多语句、修改性语句、其他 Join、CTE、无关子查询、Union、HAVING、Order By、Limit、窗口和任意函数。不以 SELECT/WITH 前缀作为放行依据，解析后的 AST 必须全部在白名单中；每个嵌套 SELECT 的 clause 也要重新检查。WHERE/Join 字面量还须与 catalog 字段类型匹配（日期必须是合法 ISO 日期，Decimal 不接受字符串、NaN 或 Infinity）。编译器未支持的 DSL 字段也直接报错，不丢弃条件。

当前限制是明确的 v0.1 能力配置。point-in-time 快照指标只编译成 `snapshot_date = DATE` 等值过滤；latest-snapshot 是独立指标，不用窗口函数。未来加入其他 Join 或窗口函数时，需要同时设计权限传播、列血缘、fanout 规则与正反例测试。20 条 Join 路径已作为元数据发布；`compile_status=metadata_only` 的路径可检索但 Guard/编译器仍拒绝。

## 4. 执行安全

1. 角色、列授权和 customer_ids 来自可信调用方，不取自用户问题；
2. Grant 必须指向真实的 customer-scoped 表，包含 customer_id；restricted 列即使误配也拒绝；
3. Worker 按 `SqlLimits.max_input_rows` 把授权行列投影到隔离内存库；Tiny 默认仍是 10,000 行，用参数化提取 + 类型化 VALUES。Standard/Large 使用命名预算 profile（400,000 / 4,000,000），worker 先 ATTACH 只读源库再 `CREATE TABLE AS` 授权投影，DETACH 后才执行候选 SQL。预算与 `DatasetManifest.scale` 绑定，不由 Agent 选择。超限记 `INPUT_LIMIT`，不是扫描量；
4. 源库连接关闭后，候选 SQL 仅在另一个内存库里执行；
5. 外部访问、扩展自动安装/加载关闭，配置锁定，线程和内存限制显式设置；
6. 对过滤后 COUNT(DISTINCT customer_id) 实施 min_group_size；不足时拒答；
7. 父进程设置墙钟预算，超时后 terminate/kill 并 join 回收子进程；
8. 返回值必须经过列名、类型、行数和截断检查。

默认 min_group_size=1。因此空授权范围/过滤后零客户当前会得到 AGGREGATION_TOO_SMALL，不会回退成“全部客户”。普通结果比较器支持空结果，但是否允许返回空聚合需要任务与策略共同指定；不偷偷绕过最小聚合检查。

限制：进程分离是为 SQL 查询超时和受控数据投影，不是对恶意 Python Agent 的 OS 沙箱。AgentTools 的 Python Protocol 是接口边界，不阻止可信插件内省宿主对象。对外接收任意代码前，必须另建隔离进程/容器/身份、网络与文件授权，不能挂载隐藏答案或生产凭证。

## 5. 语义比较与评分

比较器使用结构化列类型。默认多重集保留重复行；显式 ordered 或 distinct 时才改变规则。整数精确比较；Decimal 使用绝对/相对容差；NULL、0、空字符串不同。带容差的无序匹配使用一对一匹配而非贪心匹配。

当前 smoke runner 仍是单快照正反例架构检查，不产生正式维度分数。evaluator 0.5 可评回答、可序列化多轮 slot 脚本和拒答 reason code；每轮记录请求、完整响应、工具调用（含执行故障）、受控回执结果和 policy violation，未捕获的策略拒绝保留具体稳定码，物化输入超限记为 `INPUT_LIMIT`。0.4 记录只作为历史证据，不能与 0.5 混作同一发布批次。历史 `c360 evaluate` / `prepare-release` 的 `scoring_applied` 仍必须为 false。正式加权分数只来自 evaluator 0.6 的 `c360 evaluate-public` / `evaluate-hidden --formal` 输入，再经 `c360 score` 分别写出 public_dev 与 private_hidden；`ranking_enabled` 永久为 false。官方 Baseline 是 `BaselineAgent`（`--agent baseline`），经独立离线 adapter 规划后走同一网关；TemplateAgent 只做协议接入测试。`c360 evaluate` 把一次 Agent 提交得到的候选 SQL 在 Tiny baseline + 四类变体上 same_sql 重放；agent_rerun 必须逐快照调用注入的 Agent，两模式不得混为同一鲁棒性分数。私有 JSONL 保留候选 SQL 与评测记录；公开 summary/Markdown/HTML 脱敏，不含 Gold、spec 或候选 SQL。policy_incompatible、超时、崩溃和截断不得记成空结果成功。错误窗口 SQL 在变体上仍须能与独立 oracle 区分。Agent 被网关拒绝的行为另行记录，不因网关拦截成功给 Agent 安全满分。脚本中途出现危险 SQL 后，后续 Success 或拒答不能改判为通过。

## 6. 复现与制品

fixture manifest 记录 seed、schema/generator/snapshot 版本、配置摘要、catalog 摘要、每表规范化内容摘要、行数与依赖版本。规范化摘要不依赖 DuckDB 文件布局或执行耗时。seed 只对 fixture 中指定资产值做确定性变化；固定问答核心值保留为人工核验基准。

数据集走同一条摘要约定：configs/data_generation.yaml 经 GenerationConfig 校验后由 synth/generator.py 生成。冻结规模为 Tiny 100/2,000（C001/T0001）、Standard 10,000/300,000、Large 100,000/3,000,000。Standard/Large 默认无交易/无持仓/空职业不低于 5%/5%/3%（snapshot standard-v2/large-v2）；Tiny 仍 tiny-v1。synth/constraints.py 的 60 条命名质量断言先在生成连接上执行，任一失败则抛错且不发布 manifest；通过后写入 dataset.duckdb、quality_report.json、manifest.json（artifact_kind 随 scale，generator_version=0.1.0，含 quality_report_hash）与 generation_config.json。所有业务值来自局部 Random(seed)，日期维度只由 anchor/horizon 决定，不受 seed 影响。同 seed 两次生成的 manifest 完全一致。Tiny seed 42 的九表 content hash 与 quality_report_hash 已冻结。可信侧 `load_verified_dataset` 会重新校验九表键集合、行数/内容摘要，并对生成数据验证 generation_config/quality_report sidecar 的 hash、scale、seed、anchor、generator 版本和通过状态；变体 manifest 没有生成 sidecar，走独立变体契约。

公开代码/资源可打包；生成输出、隐藏数据、密钥路径和可信 oracle 默认忽略。sdist 使用 `only-include` 白名单（源码、测试、公开配置、文档、锁文件和 CI），显式排除 `outputs`、`.venv`、`.private`、`.env`、`data/hidden` 和 `data/trusted`。wheel 只含 `src/customer360` 运行代码与包内公开资源（catalog/metrics/公开 human_cases）。`c360 doctor` / `c360 smoke` 在没有 `configs/benchmark.yaml` 时使用与该文件一致的打包默认值，因此安装后的 wheel 不依赖源码工作目录或可信 oracle；`generate-data`、`coverage-report`、`build-gold`、`check-rewrites` 和 `replay-variant` 仍需仓库侧输入。输出使用独占创建，目录或文件存在时拒绝覆盖；失败的部分目录保留供排查，不进行自动递归清理。

Linux CI（`.github/workflows/ci.yml`）先检查公开树未跟踪 hidden/duckdb/`outputs/`，再在 Ubuntu + Python 3.11 上执行锁依赖安装、ruff、pytest、`uv build`，把 wheel 装进 `/tmp` 虚拟环境并在源码目录外运行 doctor/smoke；Docker 作业以非 root、`--read-only --network=none` 跑 `c360 doctor` 并上传 image Id 证据。这不是公开评测服务或外部模型接入。开源前检查见 [github-publish.md](github-publish.md)。官方 Baseline 默认离线；厂商 SDK 未安装。历史 `c360 prepare-release` 记录版本与公开摘要，明确 `hidden_included=false`、`docker_included=false`、`scoring_applied=false`；`c360 check-release` 还会硬性校验公开生成包为 300 题（180 train / 120 dev），短包只能作为开发包。正式发布走 `prepare-formal-release` / `check-formal-release`：八个 RC 门校验证据内容，文件存在不等于通过；未签署的 `docker_runtime` 不得携带 digest，也不得打 `v1.0.0`。

## 7. M2 dev case 素材（不是完整发布集）

包内 `resources/human_cases.yaml` 是 catalog 0.3 的公开题面（C360_0001–C360_0020，task_version human-0.1，split=dev）：只含 case_id、问题、改写和版本。semantic spec、expected action、missing slots、reason codes 在仓库 `data/trusted/human_oracles.yaml`，由 `load_human_cases()` 在可信侧拼接。改写由 `tasks/rewrites.py` 对照 canonical SemanticSpec 做槽位校验，自然语言不是 Gold。18 道可编译回答题（含 region 分组与 latest-snapshot）用独立 Python oracle 与编译 SQL 交叉核验；澄清/拒答仍是 unscored oracle。这不是把 20 道 dev case 改标为 private。独立隐藏集见 `c360 generate-hidden`（C360_4001+）与 `hidden_profile.json` 隔离 Tiny；公开生成 300 题与隐藏 pack 的 family 均不得与 C360_0001–0020 重叠。

覆盖报告由 `c360 coverage-report --dataset <Tiny目录>` 写入 `coverage.json` / `coverage.md`。这不是加权总分，也不代表完整 benchmark 已发布。生成/隐藏包的语义验收由 `c360 verify-pack` / `verify-hidden` 另写公私报告：独立 oracle 对照编译 SQL、8 类错误 SQL 可区分、改写槽位通过；`semantic_passed` 独立于 `m6_structure`，仍不是官方分数。`c360 perf-baseline` 按数据集规模绑定资源预算，采集 generate / gold-execute / evaluate 的耗时与失败码；公开摘要不含 Gold、SQL、问题和 seed；扫描量与 Token 保持 `unavailable`。`scoring_applied` 必须为 false。默认 pytest 仍只跑 Tiny。边界探针只读 Tiny 切片（窗口首尾日、NULL 职业、无交易/无持仓、失败/撤销并存、多估值日等），不改生成器。改写槽位由 `c360 check-rewrites` 单独核验。同一 SQL 变体重放由 `c360 replay-variant --baseline <seed42> --variant <seed43>` 写入 `replay.json` / `replay.md`，`replay_mode=same_sql`，`scoring_applied=false`。不把覆盖报告或变体重放改成正式分数。可信侧可另用 `c360 build-gold --dataset <Tiny目录> --output <私有目录>` 生成 Gold SQL/结果；该目录不得进入 Agent 输入、wheel 或公开报告。
