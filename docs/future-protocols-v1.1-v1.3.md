# Customer360 协议与能力演化设计规范 (v1.1 – v1.3)

[English](en/future-protocols-v1.1-v1.3.md) | [简体中文](future-protocols-v1.1-v1.3.md)

文档版本：v1.3-implemented  
实施状态：v1.1 诊断增强 (已落地)、v1.2 元数据演化 (已落地)、v1.3 引擎适配 (已落地)  
约束条件：不改变 v1.0 评分权重、不改变 30 个指标业务口径、不泄漏隐藏集、不放宽 SQL Guard 与权限边界。

---

## 1. 概述与核心原则

在 v1.0 正式发布（纯离线 DuckDB Benchmark、8 项 RC 门签署）之后，Customer360 将进入协议演化与能力扩展阶段。为确保评测体系的可信度与可审计性，任何协议和实现的演化必须严格遵循以下原则：

1. **显式行为变更与版本绑定**：区分“纯文档/测试补充”与“改变可观察协议行为”。任何影响 Agent 输入输出、工具接口、语义编译、评测比较规则的变更，必须升级对应的版本字段，绝不隐式漂移。
2. **Fail-Closed 安全优先**：未知或未声明的能力、表、字段、Join 路径一律显式拒绝，并返回确定性原因码，严禁吞咽异常或静默降级为成功。
3. **可信隔离边界**：Agent 始终只能访问已声明的公开元数据和受控执行工具；Gold 编译、独立 Oracle、隐藏集生成逻辑和评测比较器内部状态严格驻留可信侧。

---

## 2. validate_query_plan 能力矩阵与拒绝码设计 (v1.2 已落地)

### 2.1 动机与定位
当前 Agent 在生成 SQL 前若缺乏前置校验手段，容易直接提交语法或权限非法的 SQL 触发网关报错。`validate_query_plan` 是在 v1.2 引入的受控规划校验工具接口（`contracts/validation.py`、`runtime/validator.py`），旨在让 Agent 验证其逻辑查询计划（QueryPlan）是否符合当前授权策略、指标口径与 Join 拓扑，而不实际执行查询，也不暴露可信数据。BaselineAgent 已在前置规划阶段默认调用该工具进行自检短路。

### 2.2 契约定义
- **工具名称**：`validate_query_plan`
- **请求参数**：
  ```json
  {
    "source_table": "dim_customer",
    "operation": "count_distinct",
    "measure_column": "customer_id",
    "output_column": "customer_count",
    "predicates": [
      {"field": "customer_level", "operator": "eq", "values": ["VIP"], "alias": "c"}
    ],
    "join_path": "customer_transactions",
    "group_by": []
  }
  ```
- **响应契约**：
  ```json
  {
    "is_valid": false,
    "issues": [
      {
        "code": "DISALLOWED_FILTER_COLUMN",
        "field": "customer_level",
        "message": "Column 'customer_level' is not in allowed filter columns for this table/metric."
      }
    ]
  }
  ```

### 2.3 稳定拒绝码矩阵
| 拒绝码 | 触发条件 | 说明 |
|---|---|---|
| `UNKNOWN_SOURCE_TABLE` | `source_table` 不在 catalog 或未授权 | 保护未授权表名 |
| `UNSUPPORTED_OPERATION` | 聚合非 `count` / `count_distinct` / `sum` | 限制在支持的聚合算子 |
| `INVALID_MEASURE_COLUMN` | 度量列不存在、类型不匹配或未授权 | 防止非数值列求和 |
| `DISALLOWED_FILTER_COLUMN` | 过滤列不在指标的 `allowed_filter_columns` | 遵循指标白名单约束 |
| `INVALID_PREDICATE_LITERAL`| 过滤字面量类型不匹配（如字符串赋给日期） | 严格类型校验 |
| `UNSUPPORTED_JOIN_PATH` | Join 路径非经审查的白名单（如非 `customer_transactions`） | 防止笛卡尔积和任意 Join |
| `INVALID_JOIN_PREDICATES` | Join 侧缺少必选条件（如缺少 `status='success'`） | 强制业务口径约束 |
| `INVALID_GROUP_DIMENSION` | 分组维度不在指标声明的 `allowed_group_dimensions` | 防止细粒度越权聚合 |

---

## 3. 指标版本演化与废弃规范 (v1.2 已落地)

### 3.1 动机与定位
金融与客户分析场景中，指标口径会随业务演因而更新（例如：活跃客户由“近30天交易”调整为“近60天交易或登录”）。为支持历史基准重现，并防范口径漂移，元数据必须支持多版本共存与生命周期管理。v1.2 已在 `MetricDef` 中引入 `status`（active/deprecated/retired）与 `replaced_by`，并在 `c360 audit-metadata` 中建立了死链与循环废弃拓扑审计。

### 3.2 指标元数据模型扩展
在 `MetricDef` 中引入版本控制字段：
```yaml
- metric_name: active_customer_count
  metric_version: "1.1"
  status: "active"             # 可选: active | deprecated | retired
  effective_date: "2025-01-01"
  deprecation_date: null
  replaced_by: null
  previous_version: "1.0"
  business_name: 活跃客户数
  ...
```

### 3.3 演化与变更策略
1. **禁止就地修改（In-Place Modification）**：若指标计算逻辑、固定过滤、时间语义或粒度发生任何调整，禁止直接覆盖已有 `metric_name` 的定义，必须创建带有新 `metric_version` 的定义。
2. **废弃周期（Deprecation Cycle）**：
   - 处于 `deprecated` 状态的指标在检索工具中带 warning 标记，但仍可执行；
   - 处于 `retired` 状态的指标直接返回稳定拒绝码 `DEPRECATED_METRIC_REJECTED`，并提示合规替代版本 `replaced_by`。
3. **任务包版本锁定**：每个 Task Case 必须在元数据中绑定 `metadata_version`，编译器与 Evaluator 严格按任务创建时锁定的版本加载指标，杜绝由于元数据升级导致的历史测试集失效。

---

## 4. PostgreSQL 执行引擎适配能力矩阵 (v1.3 已落地)

### 4.1 动机与定位
当前 Customer360 仅支持 DuckDB 作为官方基准评测唯一裁判引擎。v1.3 已完成跨引擎方言转译器（`runtime/dialects.py`）、多引擎执行网关抽象（`BaseExecutionGateway`、`DuckDBExecutionGateway`、`PostgreSQLExecutionGateway`）以及 CLI 命令 `c360 transpile-sql`。由于不同 SQL 引擎在方言、类型隐式转换、空值排序和时区处理上存在固有差异，已建立形式化适配矩阵与 AST 等价性断言。

### 4.2 引擎能力与差异矩阵
| 特性维度 | DuckDB 基线行为 | PostgreSQL 目标要求 | 适配层处理策略 |
|---|---|---|---|
| **SQL 方言与引用** | 双引号引用表/列：`"dim_customer"` | 双引号引用：`"dim_customer"`（保留小写） | 统一通过 AST 生成标准 ANSI SQL |
| **日期时间运算** | `DATE '2025-06-30' - INTERVAL 89 DAY` | `DATE '2025-06-30' - INTERVAL '89 days'` | SQL 编译器按目标方言渲染语法 |
| **数值精度与 Decimal** | `DECIMAL(18, 2)`，除法保留小数 | `NUMERIC(18, 2)`，除法需显式精度截断 | 提取结果统一转换为 Python `Decimal` |
| **NULL 与三值逻辑** | `NULL` 默认排序在末尾（ASC） | `NULLS FIRST` / `NULLS LAST` 默认不同 | 强制显式生成 `NULLS LAST` 保证排序稳定 |
| **无序多重集比较** | 结果拉取至 Python 内存按元组计数比较 | 同一 Python 比较器 | 保持 Evaluator 逻辑完全独立于数据库引擎 |
| **安全执行与超时** | 独立子进程启动 DuckDB，进程超时强制 kill | 连接级 `statement_timeout` + 线程级取消信号 | 双重超时守护：引擎层超时 + 评测进程超时回收 |
| **权限与行级限制** | 在临时只读 DuckDB 连接中前置物化视图/表 | 独立只读 Session 用户 + 临时只读 Schema | 确保测试数据库无写权限，物理防穿透 |

---

## 5. Split 泛化审计机制 (v1.1 已落地)

### 5.1 动机与定位
目前公开集与隐藏集使用 `family_id` 判重（由模板、指标、Join、时间、过滤签名联合哈希）。但这只能保证“完整特征组合”不重复，无法保证公开集与隐藏集在“单指标”或“单过滤谓词”维度的统计解耦。v1.1 已通过 `c360 audit-splits` 命令（`tasks/audit.py`）落地三层泛化与正交性审计。

### 5.2 泛化审计维度
在 v1.1 中将构建 `c360 audit-splits` 命令，提供三层泛化重合度审计：
1. **Template Generalization（模板级泛化）**：
   - 检查隐藏集是否包含公开集未曾出现过的问句模板形态（如否定句、比较句、多约束嵌套句）。
2. **Metric × Filter Orthogonality（组合正交性）**：
   - 审计隐藏集所使用的 `(metric_name, filter_dimension)` 组合是否在公开训练集中出现。若组合完全在公开集中已知，该题目仅属于“参数插值题”而非“组合泛化题”。
3. **Data Distribution Drift（数据分布泛化）**：
   - 验证四个私有隐藏变体（Distribution, Fanout, NULL, Date Boundary）与基准数据集之间的差异区分度，保证没有单道题目能靠“空结果巧合”同时蒙混通过基线和四个变体。

---

## 6. 版本升级与变更影响表 (Upgrade Impact Table)

当项目后续迭代中涉及以下改动时，必须严格按照本表决定升级哪一层版本字段：

| 变更范围 | 触发场景 | 升级字段 | 兼容性与处理方式 |
|---|---|---|---|
| **Agent 通信契约** | `AgentRequest` / `AgentResponse` 新增字段、改变状态枚举（如新增 `clarification_needed` 字段） | `protocol_version` | 必须提供向下兼容适配层；旧协议报告标记为旧版本不可混批 |
| **评测与比较逻辑** | 改变浮点容差算法、改变变体重放策略、新增硬门槛检查项 | `evaluator_version` | 旧评测结果不可直接换算；旧报告归档保存 |
| **评分体系与权重** | 修改准确率/鲁棒性/安全性权重、调整扣分规则 | `score_version` | 属于重大基准变更，需发布 Benchmark 升级说明，旧 Agent 须重跑 |
| **任务与 DSL** | 新增 DSL 结构（如多指标组合、子查询）、调整自然语言问法规则 | `task_version` | 新旧任务包可按版本并行加载；禁止就地篡改旧题包 |
| **业务指标与元数据** | 新增业务表、新增字段、新增指标、调整指标过滤口径 | `metadata_version` | 旧题包必须绑定旧 `metadata_version`，新题包使用新版本 |
| **合成数据生成逻辑** | 调整数据分布参数、新增实体关联、变更数据校验断言 | `generator_version` | Tiny seed-42 摘要若变化，必须发布新 snapshot 并保留旧版本迁移说明 |
| **测试数据快照** | 数据集因版本升级重新生成并发布 | `snapshot_version` | 更新 manifest 中的 hash 与质量报告，各层制品显式绑定 |

---

## 7. 结语

本设计规范作为 Customer360 Benchmark 后续演进的基础技术指南，确保在提升 Baseline 质量、丰富指标库与适配生产级数据库的过程中，评测结果的严谨性、权威性和可重复性始终处于第一位。
