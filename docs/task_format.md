# 协议与任务格式 0.1

命令怎么跑见 [使用说明](user-guide.md)。本文描述公开/私有契约和当前 DSL。Python 类型定义是权威来源，Pydantic 拒绝未知字段与无效状态组合。正式本地分数走 `c360 score`（协议 1.0），不是在线竞赛提交。

## 公开输入与私有 oracle

AgentRequest 仅含 case_id、question、anchor_date、metadata_version、protocol_version 和 conversation。不能附带 expected_action、semantic_spec、Gold、missing_slots 或隐藏种子。

PrivateCase 属于可信 evaluator。其 CaseOracle 是按 expected_action 区分的联合类型：

- answer：SemanticSpec；
- clarification_needed：脚本化 SlotReply 列表、可选多轮 ClarificationTurn 和补齐后的 SemanticSpec；
- refuse：允许的 reason code，不要求 SQL。

当前 evaluator 0.5 支持 answer、clarification_needed 和 refuse：澄清按隐藏 ClarificationTurn 脚本逐轮回放（缺省时全部 SlotReply 仍是一轮，且顶层 replies 必须与 turns 文本一致），比较最终受控查询，并记录每轮请求、完整响应、工具（含超时/崩溃/物化输入超限）和回执结果；拒答校验 reason code，未捕获的策略拒绝保留具体稳定码。零贡献参考查询记为 POLICY_INCOMPATIBLE。这已是可序列化多轮契约，但不是正式评分。evaluator 0.4 记录仍是历史格式，不与 0.5 混作同一发布批次。官方 Baseline runner 是本地 `BaselineAgent`（`--agent baseline` / `c360 run-case`），仍不计算加权分数。

包内 `resources/human_cases.yaml` 是 `catalog_version: 0.3` 的公开题面：20 个 case 只有 `case_id`、`task_version: human-0.1`、`split: dev`、canonical question 和 3 条改写。semantic spec、expected action、missing slots、slot replies 和 reason codes 在仓库 `data/trusted/human_oracles.yaml`，不进入 wheel/sdist 或 Agent 输入。改写只作为输入变体，Gold 仍由 canonical semantic spec 编译。可信侧用 `c360 check-rewrites --oracles data/trusted/human_oracles.yaml` 核验槽位；漂移会得到 TIME_RANGE_ERROR / METRIC_ERROR / FILTER_ERROR / JOIN_ERROR 等稳定分类。当前 18 道可编译回答题（含分组与 latest-snapshot）的 Gold 是 semantic spec → 编译器；澄清/拒答仍是 unscored oracle。该包是 M2 的 dev 起点，不是完整评分集或隐藏集。C360_0001–0020 不得改标 train/test/private/hidden。

M3 生成包与 20 题包分离：`c360 generate-tasks --count 120 --seed 42` 写出独立 `generated-m3-0.1` 包（case_id 从 C360_1001 起）。`--count 300` 为 M6 公开结构（180 train / 120 generated-dev），`m6_structure=true` 只表示题包结构。family_id 由模板、指标、Join、时间语义（含具体日期）、过滤签名、分组和 expected action 规范化得到；改写共享 family 不计新题；train/dev 不得共享 family。公开 YAML 仍不含 spec/slots。`c360 check-isolation` 核验隔离。生成包 `m3_complete` 只表示结构验收，`scoring_applied` 必须为 false。`pack.json` 与 `generated_oracles.yaml` 含可信侧素材，不能作为 Agent 输入；Agent 只接收公开 YAML 和受控工具。

隐藏集是独立 pack：`c360 generate-hidden --public-pack <公开包> --count 30` 写出 `hidden-m6-0.1`（case_id 从 C360_4001 起，split=private）。family 不得与 human 20 题或公开 train/dev 重叠。Agent 可见题面写在 `agent_cases.yaml`，oracle 在 `hidden_oracles.yaml`，二者都不进 wheel；`pack.json` 仍是可信侧完整蓝图，不能交给 Agent。隐藏数据是带 `hidden_profile.json` 的 Tiny，默认 seed 1042，禁止复用 42/43，profile 必须与 manifest 的生成器/快照版本一致。`c360 evaluate-hidden` 在隔离数据上评独立隐藏包；公开摘要不含问题、Gold、spec、候选 SQL 和隐藏 seed。`evaluate --split private` 仍拒绝把 C360_0001–0020 改标。`c360 prepare-release` 写出候选 release manifest，`hidden_included=false`、`docker_included=false`、`scoring_applied=false`；`c360 check-release` 只有在 300（180 train/120 dev）公开结构完整时才通过。

结构通过不等于答案正确。`c360 verify-pack --dataset <Tiny seed42> --pack <生成包>` 用独立 Python oracle 对照编译 SQL，并要求 8 类错误 SQL 在绑定数据上可区分；`--variant` 重放同一 Gold SQL，不调用 Agent。`c360 verify-hidden` 只接受带 `hidden_profile` 的 Tiny。公开 summary 只有计数与 `semantic_passed`；Gold/spec/SQL/问题/seed 留在 `private/verify.json`。`m6_structure` 不变；`semantic_passed` 不是 ROADMAP 第 8 节加权分数。

可信侧可用 `c360 build-gold --dataset <Tiny目录> --output <私有目录>` 生成当前 20 个 case 的 Gold 素材。该目录包含 task_version/split/rewrites 元数据、18 个可编译回答的 SQL/结构化结果，以及 2 个非回答 oracle 的契约记录；不得交给 Agent 或发布。

数据变体默认重放同一编译 SQL。已冻结四类 Tiny 变体：`tiny_seed_43_distribution`、`tiny_duplicate_fanout`、`tiny_null_empty_groups`、`tiny_date_boundary`。`c360 replay-variant --mode same_sql` 校验 18 道可编译回答在变体上仍与独立 Python oracle 一致，并要求至少一题结果与 baseline 不同；dim_date 作为纯日历应保持不变。`--mode agent_rerun` 必须注入独立 Agent（CLI 无注入则拒绝，不会把 Gold SQL 当作重跑）；`--mode scoring` 尚未启用权重且不能把 `scoring_applied` 设为 true。

`c360 evaluate --agent template --mode same_sql` 与单变体 Gold 重放不同：它先在 baseline 上调用 Agent，再把**该次提交的候选 SQL**重放到 baseline+四变体，并逐题记录适用快照、阶段和失败原因。公开报告脱敏。这不是官方鲁棒性分数，也不把变体目录当作隐藏集。

## 语义 DSL 当前子集

~~~json
{
  "semantic_version": "0.1",
  "metric": "successful_transaction_count",
  "filters": [],
  "time_window": {
    "type": "rolling",
    "days": 90,
    "anchor_date": "2025-06-30"
  }
}
~~~

默认是单指标、单表。另支持唯一固定 Join 路径 `customer_transactions`：`dim_customer.customer_id` 连接 `fact_transaction.customer_id`，结果只能按客户去重计数；客户条件和交易条件分别在对应表侧执行，交易 Join 必须显式提供 rolling 时间窗口。`group_by` 目前只允许 `active_customer_count` 按 `region`；输出为组键加指标列，不补零组，比较为无序多重集。`time_window` 可以是 rolling、point_in_time 或 latest_snapshot（仅 `latest_total_asset`：逐客户 `MAX(snapshot_date) <= anchor` 再 SUM）。Join 与分组不能组合；窗口函数、HAVING、ORDER BY 和其他 Join 仍拒绝。Filter 指定 field、operator、values；支持 eq/ne/gte/lte/in/is_null/is_not_null。NULL 使用专用操作，IN 非空，类型必须与字段匹配。三种时间语义不能互换。

latest_snapshot 示例：

~~~json
{
  "semantic_version": "0.1",
  "metric": "latest_total_asset",
  "time_window": {
    "type": "latest_snapshot",
    "anchor_date": "2025-06-30"
  }
}
~~~

point_in_time 示例：

~~~json
{
  "semantic_version": "0.1",
  "metric": "snapshot_total_asset",
  "filters": [],
  "time_window": {
    "type": "point_in_time",
    "snapshot_date": "2025-06-30"
  }
}
~~~

编译器从指标定义确定 source、measure、固定过滤和输出列，结构化参数仅生成正确转义的字面量，不能插入自由 SQL。Metric 定义不知道 Agent 内部实现。

## Agent 接入

实现 agent/protocol.py 的 Agent.respond(request, tools)。当前工具端口包括 execute_sql、search_tables、search_columns、search_metrics、get_table_schema、get_metric_definition、get_business_glossary、get_join_paths。Join 检索返回当前授权表均已授予的路径；可编译的仍只有 `customer_transactions`。协议适配器为可信本地代码；不支持上传任意 Python 插件。检索结果已按授权表/列过滤，不能用来发现 restricted 字段或未授权表。

execute_sql 返回 QueryReceipt，包含随机 query_id、结构化结果和 elapsed_ms。Success 必須返回该 query_id、实际提交 SQL、answer、confidence；假设和证据可选。evaluator 只认可当前会话登记的回执。

四种状态：

- success；
- clarification_needed：非空 questions 和去重后的 requested_slots；
- refused：机器可读 reason_code、reason、可选 alternative；
- error：运行故障，不等于正确拒答。

当前 SqlSubmissionAgent 是显式 SQL 的协议检查适配器。TemplateAgent 是覆盖 20 道公开题的确定性本地接入测试驱动，使用公开工具、不读 Gold/oracle，不是官方 baseline。官方 Baseline 是 `BaselineAgent`：检索公开元数据、由独立 `LocalDeterministicAdapter` 生成计划、编译候选 SQL 并经网关执行；记录 adapter 参数/重试/缓存/是否用网。外部网络 adapter 在许可确认前 fail-closed。不得读取 Gold/spec。

## 结构化结果

QueryResult.columns 声明名字和类型；rows 使用对应位置值。支持 string、integer、decimal、date、boolean。Decimal 以字符串传输，日期使用 YYYY-MM-DD，整数/布尔不得互相替代。NULL 用 JSON null，truncated 显式标识截断。

~~~json
{
  "columns": [{"name": "transaction_amount", "kind": "decimal"}],
  "rows": [["650.00"]],
  "truncated": false
}
~~~

截断、列类型/名称不符、无回执、回执 SQL 与提交 SQL 不符，都不能判正确。脚本化多轮、变体重放和执行审计已实现；正式的答案解释质量、延迟/Token/扫描统计和加权总分尚未实现。
