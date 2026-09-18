# 阶段 S / G 复审修复与交接（2026-09-18）

## 本轮修复

- 变体策略状态不再由空结果、0、NULL 推断，统一经真实 `ExecutionGateway` 执行。只有 `AGGREGATION_TOO_SMALL` 标记 `policy_incompatible`；`PERMISSION_DENIED` 独立保留在私有 `policy_block_code`，表示可信 Gold 超出当前 Tiny Agent 授权范围，不表示允许 Agent 执行。
- Gold 正确性与 Agent 策略适用性是两回事。即使策略拒绝，也必须比较编译 SQL 与独立 oracle；变体差异会生成 `variant_independent_oracle_mismatch`，不能被策略诊断掩盖。执行异常、其他 Guard 拒绝、截断均中止验收。
- 300 题必须提供四个冻结变体，按分布 seed43、duplicate fanout、NULL/empty groups、date boundary 顺序传入。缺失、重复、错误顺序均提前拒绝，清除 `m6_structure` 标志不能绕过门槛。120 题仍支持不提供或只提供诊断变体。
- 变体只加载核验一次，随后复用已验证的 manifest/database；catalog 与日期维度必须和 baseline 一致。矩阵与 pack 验收共用冻结变体常量，防止入口定义漂移。
- 报告逐条检查计数、split、oracle 匹配数、策略证据、变体数量/ID/顺序和 `semantic_passed` 一致性，拒绝篡改汇总值。已有输出目录在执行昂贵验收前即被拒绝，不覆盖历史报告。

## 版本与未完成边界

仅 pack 语义验收私有/公开报告协议从 0.1 升到 0.2；evaluator 仍为 0.5，Gold、任务、生成数据和评分权重未改。保留旧文件，只能通过重跑原始题包和快照取得 0.2 证据，不能只改 JSON 版本字段。

隐藏包当前只验证其隔离 Tiny baseline。公开变体仍明确拒绝，`variant_count=0` / `replay_mode=none` 和 limitations 保留该范围。本轮没有实现可信隐藏变体，不应宣称隐藏集达到正式多变体鲁棒性发布门。G1/G2 资源预算未放宽；本轮不重跑 Standard/Large 性能采集，也不声称完成 Linux 远程 CI 或正式发布。

## 验证

- `uv run pytest -q tests/test_pack_verify.py`：33 passed（1385.62s），包含真实 300 题 baseline + 四变体、120 题兼容、隐藏包、CLI、公私隔离、空/零/NULL、策略拒绝、异常/截断、伪造报告与拒绝覆盖。
- 真实 300 题四变体验收另单独跑过：1 passed（1038.27s）。以上均实际调用网关，没有用 mock 替代端到端验收；故障注入测试单独使用 mock 构造反例。
- 最终全量回归：`uv run pytest -q` 372 passed（1870.81s）；这是报告 0.2、策略/Gold 分离和新增反例回归后的最终结果。此前 348 passed 属于收紧 oracle 证据之前的中间结果。

## 接手事项

轻量 agent 可在冻结边界内维护测试 fixture、CLI 示例、版本读取报错和迁移说明，不得放宽网关或更改评分含义。

后续主 agent 工作：独立隐藏变体的 provenance/生成/重放设计及隔离验收；正式发布前确认评分分母、运行位置、许可证、网络许可。不得通过允许 hidden pack 使用公开四变体来关闭该缺口。
