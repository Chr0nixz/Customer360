# 后续开发计划（2026-09-17 审阅后）

状态：第一阶段 H1–H8、阶段 B/C/D/E/F、阶段 S（生成/隐藏包语义验收）、阶段 G（受控资源预算与性能采集）与阶段 R（RC 证据内容校验）已实施。命令用法见 [使用说明](user-guide.md)。本文补充 ROADMAP 第 4 节，不改变评分权重、SQL 权限或公开范围。

## 1. 当前判断

保留单 Python 包、DuckDB、Pydantic 契约、独立 Python oracle 和受控执行网关。当前主要风险来自规则重复实现、不同执行入口检查不一致，以及测试没有覆盖跨模块的行为组合；不需要重写整个项目。

M2-06 的公开包与可信文件隔离已验收。H1–H8 与阶段 B 已关闭分组/latest-snapshot 的 unsupported 缺口，并用确定性 TemplateAgent 验证 answer/clarification/refuse 接入。阶段 C 已交付 30 指标、20 条 Join 路径和 120 独立语义 case。阶段 D 已交付矩阵评测与脱敏报告。阶段 E 已交付官方本地 Baseline 与独立 adapter。阶段 F/S/G 已交付独立隐藏语义 case、隔离 Tiny、300 题公开结构、四个私有隐藏变体 provenance/same-SQL replay、release manifest 与资源预算。正式评分协议 1.0 通过 `c360 score` 分别生成 public_dev/private_hidden；Docker、Apache-2.0、SHA256/SBOM 和 formal release 检查已启用。外部模型、在线排名和在线服务仍未启用。

评分/Docker/许可证工具链已落地。GitHub 公开准备（D058）已补社区文件、忽略规则、CI 公开树检查和 Docker image Id 工件；推送仍由维护者执行，且不得把 `outputs/` 或 hidden pack 上传。当前剩余是八个 RC evidence gates 的真实签署：本机可完成内容校验与七项 Windows 可采集门，`docker_runtime` 需 Linux/CI 上的真实镜像 digest。接外部模型前仍须确认网络许可。完整证据由维护者保存在本地 outputs；公开计划不复制 Gold 或私有执行轨迹。

## 1.1 阶段 F 复审与代码质量修复（2026-09-18）

阶段 F 的结构验收通过，但复审没有把“能生成默认样例”当作边界正确性：

- 生成器现在能安全处理 `managers=1`、`products=1` 和最短合法日期区间；默认 seed-42 规范化摘要保持不变；
- SQL Guard 对每个嵌套 `SELECT` 重新检查 clause，Join 只接受显式 inner 形态，过滤字面量按 catalog 类型校验（非法日期、Decimal 字符串/非有限值等 fail-closed）；
- 可信数据读取在九表键集合、DuckDB 错误、`generation_config.json`、`quality_report.json` 与 manifest 身份不一致时拒绝继续；变体 manifest 仍走独立契约；
- 隐藏 profile 绑定 Tiny 生成器/快照版本，隐藏评测报告校验 case/compilable 计数，隐藏 pack 必须标识对应的公开生成包；
- release manifest 记录 train/dev 数量，`check-release` 只有 300（180 train / 120 dev）且隔离/打包检查通过才返回 `passed=true`；120 题包仍可用于开发，但不会伪装为 M6 候选；
- ToolSession 将所有策略拒绝纳入审计；evaluator 保留已知 `QueryRejected` 原因码，工具基础设施异常统一为 `EXECUTION_ERROR`，不把它们静默成成功或空结果。由于未捕获策略拒绝的失败分类发生变化，evaluator 记录版本由 0.4 升为 0.5；0.4 记录只保留作历史证据，不与新记录混批。

本次新增的边界回归覆盖：最小合法生成配置、sidecar 篡改、SQL 类型/日期攻击、未捕获策略拒绝、隐藏报告计数/profile 版本漂移和短题包 release 拒绝。交付时应报告 `uv run pytest -q`、`uv run ruff check src tests` 与 `uv run ruff format --check src tests` 的实际输出。`pack.json`、`generated_oracles.yaml`、`hidden_oracles.yaml` 始终属于可信侧；Agent 只能接收公开 YAML 和受控工具。

本轮不改变评分权重、业务指标口径或公开 split；evaluator 记录版本变更已在上面明确。`INPUT_LIMIT` 是新增的资源失败码，表示物化输入超限，不代表扫描量统计。旧 release manifest 缺少 train/dev 数量时，应重新运行 `prepare-release`；旧评测报告应使用对应版本读取或重新评测，不应只改版本标签。缺少 config/quality sidecar 的生成数据应从完整原制品恢复或重新生成。极小配置测试仅验证构造过程不会随机访问空集合；自定义日期仍须满足全部质量检查后才能发布数据 manifest。

尚未完成的 M6/M7 项仍包括正式加权分数、Docker/运行位置、许可证、PostgreSQL 适配、真实扫描量统计和不可信 Python Agent 的 OS 级隔离。Standard/Large 受控资源预算与 `perf-baseline` 采集命令已交付；未测扫描量仍必须标为 unavailable。隐藏隔离目前按完整 semantic family 指纹判重；它不保证模板、单个指标或 Join 路径各自从未在公开包出现，不能据此宣称具备严格的跨模板泛化评测。release 检查验证 manifest/配置层；最终分发仍须检查实际 wheel/sdist 内容。300 道生成题的结构与编译通过也不能替代逐题独立 oracle 和正常数据加四变体的正式语义验收。

## 2. 第一阶段：修复与收敛

每个工作包单独交付。可以先建立失败测试，但不得把已知失败测试改成宽松断言或靠 xfail 宣称修复完成。

| 顺序 / 工作包 | 交付范围 | 负责人 | 退出标准 |
| --- | --- | --- | --- |
| H1：SQL Guard 与编译能力对齐 | 安全入口先检查整棵 AST，再进入单表/受限 Join 子集；正确处理 IN、IS NULL 等节点；明确未支持语法 | 已完成 | Join 中 CTE/子查询/系统与外部函数不能绕过检查；声明支持的 DSL 编译后可通过对应授权下的 Guard；未知构造给稳定拒绝码，不抛 AttributeError |
| H2：可信数据读取统一 | baseline/variant/gold/coverage 共用数据载入、manifest/九表内容/行数/catalog 检查；结果规范化共用轻量函数 | 已完成 | 修改任一输入数据而保留 manifest 均失败；四类原始变体通过；日期不变结论来自已核验的数据；不修改摘要排序算法来迁就测试 |
| H3：明确重放对象与 Agent 边界 | 分清 Gold 诊断、候选 SQL 重放、完整 Agent 重跑；接收外部注入的可信本地 Agent/factory，或对未实现模式显式报错 | 已完成 | Agent 仅收到公开请求及授权工具；固定错误 Agent 会失败；不能通过注入 Gold SQL 取得重跑成绩；same_sql 不调用 Agent |
| H4：多轮状态与审计 | 完整响应、执行故障、策略拒绝、工具次数、回执结果/持久化引用；规范化 slot 脚本；运行身份与版本记录 | 已完成 | 超时/崩溃/异常/重试全部留痕；四种响应可重放；矛盾 slot 回复被拒绝；记录能追溯任务、数据、策略、Agent 与 evaluator 版本 |
| H5：语言校验边界 | 检查否定、比较符、附加条件、计数对象和 canonical question；冻结当前支持的表达/模板语法 | 已完成 | VIP/非 VIP、成功/不成功、空/非空、客户数/交易数可区分；未知指标或表达明确不支持；不得因含有关键词就宣称语义等价 |
| H6：题目与权限策略预检 | 参考语义与 trusted policy 在 Agent 调用前检查；区分正常空结果、低于聚合粒度、oracle 错误；记录变体适用性 | 已完成 | 可回答 case 没有未解释的 oracle error；策略不兼容不可算 Agent 答错或静默跳过；空聚合决策写入决策记录后再改变行为 |
| H7：Standard/Large 分布修正 | 对照原方案恢复至少 5% 无交易、5% 无持仓、3% 空值人群；独立比例检查及版本迁移 | 已完成 | 不仅与配置数量相等，还满足业务比例；Tiny 九表内容摘要不变；新旧配置/生成器/快照版本可识别；Standard 重跑一致，Large 在指定验证任务运行 |
| H8：共享契约与测试边界收敛 | 收敛重复 case/action 校验、显式类型与枚举；保留固定 20 题包的兼容校验；同步当前文档状态 | 已完成 | 公开 catalog 类型不携带可信字段；旧包加载兼容或明确迁移报错；测试检查真实结果和错误码；历史验证记录不被改写成当前完成结论 |

依赖与顺序：H1 最先；H2/H3 完成后验收可信重放；H4 与 H6 共用异常及策略契约，应由同一主 agent 顺序处理。H5 在自动任务扩展前完成。H7 可独立实施，但更新生成版本后需重新验证 H2 的兼容范围。H8 随相关修复小步收敛，不另起大规模重构。

第一阶段总退出门：上述行为回归、Tiny 全量、制品隔离全部通过；已有正确路径不退化；所有高优先级问题关闭或保留明确阻塞状态。不能以测试总数增长代替退出证据。

## 3. 小范围重构约束

### 允许收敛的重复逻辑

- Gold、coverage、variant 的可信数据载入与结果行规范化。目前一处检查实际摘要、一处只校验 manifest 类型、另一处仅检查 artifact kind；结果读取又有 fetchone/fetchall 两种实现。收敛为明确的可信侧服务，避免扩展分组后丢行。
- `TrustedCaseOracle` / `HumanCaseBlueprint` 的动作约束。优先用组合或共享纯校验函数，公开类型、可信 oracle 和诊断报告保持不同的数据边界。
- 工具审计、运行错误码与 evaluator 状态映射。把返回类型从任意 str/dict 收敛到共享契约，避免靠 type-ignore 隐藏状态不一致；业务失败、策略拒绝和基础设施错误仍分别记录。
- 任务/运行身份。固定 20 题包的校验保留在包 profile；可扩展 case 模型不再固定 `fixture-0.1`。不把多个模型中的 20 批量替换为 120。

### 必须保持独立的逻辑

独立 Python oracle 不导入 SQL 编译器或共用其过滤/聚合算法。允许共享 schema、类型和传输规范，禁止为消除重复代码而使 Gold 与交叉核验走同一计算路径。

Agent 协议不得依赖具体 baseline 实现。Agent 重跑编排由可信 evaluator/runtime 负责；任务模块仍负责语义、模板和参考素材。Gold SQL 的直接执行限于可信诊断，不作为参评能力。

不提前引入微服务、向量数据库、第二种 SQL 引擎、复杂插件系统或全量异步重写。

## 4. 第二阶段及以后

| 阶段 | 主要工作 | 前置依赖与完成证据 | 主/轻量分工 |
| --- | --- | --- | --- |
| B：补齐 M2，并做最小接入 | 已完成：D038/D039 冻结后编译 C360_0017/0018；独立 oracle 与 Guard 子集；TemplateAgent 覆盖三类动作。覆盖仍 m2_complete=false | 18 道可编译 + 2 道 unscored；PIT/全局最大日错误 SQL 在不均匀切片上可区分；TemplateAgent 不读 Gold | 已交付 |
| C：M3 120 题 | 已完成：family 指纹、train/dev 隔离、30 指标、20 条 Join 路径（1 条可编译）、120 独立 case（C360_1001+）。C360_0001–0020 未改标 | 生成包 m3_complete 只表示结构验收；覆盖仍 m2_complete=false；metadata_only Join 不能编译 | 已交付 |
| D：M4 评测与报告 | 已完成：一次 Agent 候选 SQL 在 baseline+4 变体 same_sql 重放；agent_rerun 分记；逐题记录适用变体/阶段/失败原因；私有 JSONL 与公开脱敏报告分离。scoring_applied=false | 错误窗口 SQL 在变体上仍能与独立 oracle 区分；UNSAFE_SQL 仍拒绝；公开报告无 Gold/spec/候选 SQL | 已交付 |
| E：M5 官方 baseline | 已完成：公开元数据检索、计划、SQL、澄清和拒答；`BaselineAgent` + `LocalDeterministicAdapter`；记录模型参数、重试、缓存和调用信息；`c360 run-case` / `--agent baseline`。TemplateAgent 仍非官方。网络 adapter fail-closed | 不得读取 Gold/spec；不得启用第8节权重；FastAPI/厂商 SDK 仍按 D001/D047 延后 | 已交付 |
| F：M6 发布 | 已完成：独立隐藏 pack（C360_4001+，split=private）、隔离 Tiny（seed 1042 + hidden_profile）、300 公开生成题、release manifest、公私报告。正式 `score` 与 Dockerfile 由后续 RC 工具链交付；候选 `prepare-release` 仍无分数 | 不把 C360_0001–0020 改标 private；隐藏 family 与 public/human 隔离；wheel 不含 hidden | 已交付 |
| S：生成/隐藏语义验收 | 已完成：独立 oracle 与编译 SQL 交叉核验、8 类错误 SQL 对照、生成改写槽位；300 题强制四个冻结 Tiny 变体，120 题可选诊断变体；`verify-pack` / `verify-hidden`；`semantic_passed` 独立于 `m6_structure` | 公开包绑定 Tiny seed 42；隐藏包绑定 hidden Tiny 且 baseline-only；策略不兼容由网关显式判定，不是 Agent 答错；scoring_applied=false | 已交付 |
| G：M7 性能扩展 | 已完成：D055 命名预算、流式物化、`c360 perf-baseline`；Tiny 默认 10k 保留；扫描量 unavailable | 预算与 scale 绑定；对抗测试通过后才允许 Standard/Large profile；默认 pytest 仍 Tiny | 已交付 |

不虚设日期承诺。每阶段以通过的契约和验收门作为下一阶段起点；小范围实现可交接，不能把共享契约和安全边界拆给多个任务同时改。

## 5. 测试与验证策略

1. 为 H1/H5 建立合法输入与单一语义变异成对用例，尤其覆盖 Join 与禁止构造的组合；不要仅测孤立语法。
2. H2 使用原始数据与独立篡改副本，分别覆盖 baseline/variant/gold/coverage 所有入口。
3. H3/H4 使用真实计数的正确/错误/抛错/重试 Agent 测试驱动，断言调用记录与最终结果；保留 SQL worker 的真实超时回收集成测试。
4. H7 校验业务比例及 manifest 一致性；比例断言以独立业务阈值为准，不能只把配置原值复写为期望值。
5. 每包先运行目标模块测试，修改实现后运行 Tiny 全量与相关 CLI；涉及打包/数据出口再跑隔离测试。Linux 工作流结果由平台提供，本地不代称已跑；Windows spawn 回归继续保留。
6. Standard/Large 与性能验证单独执行，日常默认仍为 Tiny。是否引入覆盖率或静态类型工具以新增约束的价值决定，不设未经测量的百分比门槛。

## 6. 版本与决策关卡

- H1/H3/H4 改变评测行为/失败分类时，须升相应 evaluator/协议版本并说明迁移；当前 0.3 不应继续承载相互不兼容的记录。
- H5 如果发现已发布题面与 spec 矛盾，修改题目必须升 task 版本；只新增校验也要说明兼容影响。
- H7 改变 Standard/Large 数据内容，须明确配置、生成器/快照版本及旧 manifest 读取策略。冻结的是 Tiny 规范化数据内容；manifest 或质量报告摘要若因明确版本变更而变化，应单独解释，不能伪称逐字节不变。
- H6 开始行为变更前必须解决 D010 的空聚合语义：零贡献何时允许输出、何时策略拒绝、是否属于可回答题及变体适用范围。当前默认保持既有最小聚合限制，不作临时豁免。
- C/F 前确认内部回归或公开评测定位、隐藏评测运行形态；E 前确认模型网络许可；D 正式计分前确认分母、缺失值、超时和硬门槛关系。现有 ROADMAP 第 8 节权重不在本计划中改动。

这些决策不阻塞当前代码审阅，也不阻塞不改变业务语义的 H1/H2 等修复；进入依赖该决策的实现时再确认，不能视为本计划已获授权冻结。

## 7. 下一次开发任务

H1–H8 与阶段 B/C/D/E/F/S/G 的当前结构、语义验收与资源预算范围已实施。后续按以下顺序推进；语义通过和性能采集不等于正式发布完成。

| 顺序 | 工作 | 分工与交付门 |
| --- | --- | --- |
| 1 | 300 题/隐藏包的语义验收补全 | 已交付：`c360 verify-pack` / `verify-hidden`；独立 oracle、8 类错误 SQL、改写槽位；300 题绑定四个冻结 Tiny 变体，隐藏验收 baseline-only；策略状态由执行网关显式判定；`semantic_passed` 不是官方分数 |
| 2 | G1：受控资源预算设计 | 已交付：D055；Tiny 10k 默认保留；`SqlLimits.max_input_rows` 流式物化；预算与 scale 不一致 fail-closed |
| 3 | G2：Standard 基线，再到 Large | 已交付：`c360 perf-baseline` 已采集 Standard/Large generate 与 gold-execute；P50/P95 为诊断对照；扫描量/Token unavailable；Large 为显式命令，默认 pytest 不跑 |
| 3a | 隐藏变体鲁棒性 | 已交付：隐藏 baseline 的四个私有变体带 parent/child manifest provenance，`evaluate-hidden --variant` 严格按冻结顺序加载并执行 same-SQL replay；公开摘要不含私有路径/种子/Gold |
| 4 | 正式 M6 发布关卡 | 工具链已交付（评分分母/hard gates、Apache-2.0、Dockerfile、SHA256/SBOM、`prepare-formal-release/check-formal-release`）。RC 证据改为内容校验（D057）；本机 Docker 未安装，`docker_runtime` 未签署，不打 `v1.0.0` |
| 5 | Linux/CI Docker RC 后打标签 | 真实 `docker build` + `--read-only --network=none` smoke，写入不可变 digest；八门全过后再由维护者打 `v1.0.0`。不伪造 digest，不在无 git 的工作区擅自 init |

不要把 C360_0001–0020 改标 private，不要放宽 min_group_size，不要把 metadata_only Join 编译进 Guard，不要把可信 pack 打进 wheel。语义回归与性能采集可以在各自冻结的边界内推进，无须提前启用正式分数或外部模型。

本轮修复与报告 0.2 迁移规则见 [S/G 复审记录](review-s-g.md)。`policy_incompatible` 只描述最小聚合策略；`PERMISSION_DENIED` 必须另存真实诊断码，不能当作查询已授权。任何策略诊断均不能豁免可信 Gold 的独立 oracle 核验。
