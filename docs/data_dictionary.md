# 数据字典与初始化口径

怎么生成 Tiny/Standard/Large 见 [使用说明](user-guide.md)。字段名、类型、可空性、敏感级别、主键、唯一约束和外键的权威来源是 `src/customer360/resources/catalog.yaml`；不要维护第二份手写 DDL。使用 `c360 schema` 查看生成 SQL。

## 九表与粒度

| 表 | 粒度 / 键 | 时间与关系 |
|---|---|---|
| dim_customer | customer_id 主键 | 当前客户快照；registration_date 不是业务查询 anchor |
| dim_service_manager | manager_id 主键 | 服务经理维表；当前网关不允许全局表查询 |
| dim_product | product_id 主键 | 产品维表；初始化数据统一 CNY |
| fact_service_relation | UNIQUE(customer_id,manager_id,start_date,relation_type) | 客户/经理外键；服务区间约定 [start_date,end_date)，NULL end 表示持续 |
| dim_date | date_id 主键 | calendar_date 对应日历日期；生成器覆盖 2024-07-01 至 2025-06-30 全部 365 天，fixture 只含 3 个公开示例日期 |
| fact_holding | UNIQUE(snapshot_date,customer_id,product_id) | 客户/产品外键；指定日持仓 |
| fact_asset_snapshot | UNIQUE(snapshot_date,customer_id) | 客户外键；指定估值日资产 |
| fact_transaction | transaction_id 主键 | 客户/产品外键；按 transaction_date 过滤 |
| fact_cash_flow | flow_id 主键 | 客户外键；按 flow_date 过滤 |

数据库约束已覆盖主键、上述唯一键、可空性及 8 个直接外键；服务经理时间重叠等业务约束不等同于数据库唯一约束，由 synth/constraints.py 的 60 条命名质量断言在每次生成时检测，任一失败则不发布 manifest。

## 初始化语义

- 日期采用 DATE，不使用系统今天决定业务值。公共 smoke anchor 固定为 2025-06-30。
- 日期型“近 N 天”为 [anchor-(N-1),anchor]，两端含；近90天从 2025-04-02 开始。
- 服务关系为左闭右开区间；主服务经理在任一日期最多一个。后续生成器需为此补充检测。
- 金额和当前数量用 DECIMAL(24,2)，不使用二进制 float；第一阶段生成数据统一 CNY。
- amount 为非负交易金额；买卖/申赎由 transaction_type 表示。交易金额总和不是净流入或收益。
- 客户状态编码 active / dormant / closed；客户等级 VIP / standard。
- 交易状态 success / cancelled / failed，业务交易指标仅统计 success。
- 资金流 in 为正、out 为负；净流入按 signed_amount 相加。
- asset 必须满足 total=cash+investment、net=total-liability；不假设持仓样本覆盖全部投资资产。
- age 是依据 birth_date 和显式日期计算的派生字段，不是实体列。
- customer_name、birth_date、manager_name 为 restricted；financial 字段只能在授权且满足聚合规则时使用。
- phone / id_card 不存在。需要分别测试“字段不存在”和“字段存在但被拒绝”，不能混记。MetadataRepository 加载时若发现这些列名会直接失败。
- 业务词检索（get_business_glossary）只返回表、列、指标上已声明的名称与别名，不额外解释“资产规模”“最近三个月”等未定义说法。

## 当前三十指标

| 技术名 | 输出列 | 口径 |
|---|---|---|
| distinct_customer_count | customer_count INTEGER | 按 customer_id 去重；默认包括 closed，需显式 status=active 才限制正常客户；没有历史时间窗口；允许按 occupation 过滤（含 IS NULL） |
| active_customer_count | active_customer_count INTEGER | 固定 status=active 的去重客户数；不含 dormant/closed |
| successful_transaction_count | transaction_count INTEGER | 指定 rolling 窗口内 status=success，COUNT(transaction_id) |
| successful_transaction_amount | transaction_amount DECIMAL | 相同窗口与状态，SUM(amount)，不扣费、不按买卖抵消 |
| failed_transaction_count | failed_transaction_count INTEGER | 指定 rolling 窗口内 status=failed；不是成功交易指标 |
| successful_net_cash_flow | net_cash_flow DECIMAL | 窗口内 success 的 signed_amount 之和；in 正、out 负，不取绝对值 |
| successful_cash_inflow | cash_inflow DECIMAL | 窗口内 success 且 flow_type=in 的 signed_amount 之和 |
| current_primary_service_relation_count | primary_service_relation_count INTEGER | is_primary 且 end_date IS NULL 的关系条数，不是去重客户数 |
| snapshot_total_asset | total_asset DECIMAL | 指定 snapshot_date 当天 SUM(total_asset)；不是最新快照，不能跨日相加 |
| snapshot_net_asset | net_asset DECIMAL | 指定 snapshot_date 当天 SUM(net_asset)；同样必须给出估值日 |
| latest_total_asset | latest_total_asset DECIMAL | 每个客户取 snapshot_date≤anchor 的最近一次快照，再 SUM(total_asset)；缺快照排除，不是指定估值日合计 |
| closed_customer_count | closed_customer_count INTEGER | status=closed 的去重人数 |
| dormant_customer_count | dormant_customer_count INTEGER | status=dormant 的去重人数 |
| high_risk_customer_count | high_risk_customer_count INTEGER | risk_level=high 的去重人数 |
| cancelled_transaction_count | cancelled_transaction_count INTEGER | 窗口内 status=cancelled 笔数 |
| cancelled_transaction_amount | cancelled_transaction_amount DECIMAL | 窗口内撤销交易金额 |
| failed_transaction_amount | failed_transaction_amount DECIMAL | 窗口内失败交易金额，不是失败笔数 |
| successful_buy_transaction_count | successful_buy_transaction_count INTEGER | 窗口内成功买入笔数 |
| successful_app_transaction_count | successful_app_transaction_count INTEGER | 窗口内成功 App 渠道笔数 |
| successful_cash_outflow | cash_outflow DECIMAL | 窗口内成功流出 signed_amount 之和，流出为负 |
| successful_cash_flow_count | cash_flow_count INTEGER | 窗口内成功资金流笔数 |
| snapshot_holding_market_value | holding_market_value DECIMAL | 指定估值日持仓市值合计 |
| snapshot_holding_cost_value | holding_cost_value DECIMAL | 指定估值日持仓成本合计 |
| snapshot_holding_unrealized_profit | holding_unrealized_profit DECIMAL | 指定估值日未实现盈亏合计 |
| snapshot_holding_count | holding_count INTEGER | 指定估值日持仓条数 |
| snapshot_active_holding_count | active_holding_count INTEGER | 指定估值日 holding_status=active 条数 |
| snapshot_cash_asset | cash_asset DECIMAL | 指定估值日现金资产合计 |
| snapshot_investment_asset | investment_asset DECIMAL | 指定估值日投资资产合计 |
| snapshot_liability | liability DECIMAL | 指定估值日负债合计 |
| current_service_relation_count | service_relation_count INTEGER | end_date IS NULL 的服务关系条数，不限是否主服务 |

所有指标带有版本、描述、粒度、去重/空值规则、固定过滤、允许过滤、禁止场景和示例问题，定义位于 resources/metrics.yaml（metrics_version 0.3）。经审查的 20 条 Join 路径位于 resources/join_paths.yaml；仅 `customer_transactions` 可编译。空 SUM 的 SQL 语义为 NULL；当前网关还会先执行最小聚合策略。point-in-time 使用 `{"type": "point_in_time", "snapshot_date": "..."}`；latest-snapshot 使用 `{"type": "latest_snapshot", "anchor_date": "..."}`。二者不能与 rolling 互换，也不能编译成窗口函数。`active_customer_count` 允许按 `region` 分组。

## 公开 fixture，不等于 Tiny

6 客户、3 经理、3 产品、4 服务关系、3 日期、2 持仓、3 资产快照、7 交易、3 资金流。只用来核验链路：

- VIP 客户 C001/C003/C006，共 3 人；
- 近90天成功交易 T001–T004，共 4 笔；
- 金额 100 + 200 + 50 + 300 = 650.00 CNY；
- T005 超出窗口，T006 失败，T007 撤销；
- C006 没有交易；样本中有无持仓、NULL 职业和历史服务关系。

seed 影响 C001 的现金/总资产/净资产同额偏移，固定问答核心值不变。不能用这个样本宣称达到业务分布比例、历史快照覆盖、30 个质量断言或 Tiny 规模。

## Tiny 生成器已实现的口径

HANDOFF 的 T1 已实现（configs/data_generation.yaml + synth/generator.py）：

- Tiny 规模严格为 100 客户、2,000 交易、10 经理、8 产品、800 资金流，标识符为 C001/T0001；Standard 为 10,000/300,000，Large 为 100,000/3,000,000；非法行数 fail-closed；
- 无交易/无持仓/空职业人数不得低于客户数的 5%/5%/3%；Standard 默认 500/500/300，Large 默认 5,000/5,000/3,000，snapshot 为 standard-v2/large-v2；Tiny 仍是 5/5/3 与 tiny-v1；
- anchor=2025-06-30；全部业务日期落在 [2024-07-01, 2025-06-30]，dim_date 覆盖其中每一天（365 行）；
- 资产含 7 个月末估值日（2024-12-31 至 2025-06-30），每个估值日覆盖全部客户，恒等式逐行成立；
- 恰好 5 客户无交易、5 客户无持仓（其投资资产恒为 0）、3 客户职业为空；VIP 资产均值高于 standard 但分布有重叠；
- 交易状态配额 success/failed/cancelled 全出现，仅 success 计入指标；近 90 天窗口边界日（2025-04-01 外一天、2025-04-02 首日、2025-06-30 anchor）都有成功交易，且存在重复金额；
- 资金流 in 为正、out 为负，状态均为 success；服务关系每客户至少一条主关系，区间左闭右开且主关系互不重叠；
- 同 seed/同配置/同版本输出一致的规范化摘要（generator_version=0.1.0，snapshot_version=tiny-v1，独立于 fixture-0.1）；seed 只影响业务值，不影响日历维度。

更改以上口径需要说明版本影响，不在生成器里静默改定义。

## T3 Tiny 边界素材

M2 dev case 包不生成新的业务数据，只从 Tiny 读取命名边界探针，并用独立 Python oracle 交叉核验 20 个版本化 case（catalog 0.2）：

- 近 90 天窗口外一天（2025-04-01）、窗口首日（2025-04-02）和 anchor 日都有成功交易；把窗口外那一天写进 rolling 条件后，编译结果必须为 0；
- 职业为空的客户数等于生成配置（默认 3）；无交易/无持仓客户数等于配置；
- 失败与撤销交易同时出现，不能把 cancelled 算进 failed 或 success；
- 资产估值日集合与配置一致，指定估值日必须用等值过滤；2024-12-31 与 2025-06-30 的净资产合计不可互换；
- 存在已结束或非主服务关系，因此 `end_date IS NULL` 与 `is_primary` 会改变计数；
- `customer_name` 为 restricted；catalog 中不存在 phone/id_card。

按地区分组与 latest-snapshot 已进入可编译 Gold（C360_0018 / C360_0017）；其他 Join 与窗口函数仍拒绝。这不是隐藏评测集。
