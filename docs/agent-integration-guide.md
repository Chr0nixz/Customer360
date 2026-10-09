# Customer360 Agent 接入与使用指南

[English](en/agent-integration-guide.md) | [简体中文](agent-integration-guide.md)

本文档面向希望在 **Customer360 Agent Benchmark** 中开发、接入和评测自定义智能问数 Agent 的开发者。阅读前请先查阅 [使用说明](user-guide.md) 了解环境安装与基础命令。

---

## 1. 核心接入原则

1. **协议规范化**：Agent 必须实现标准 Python `Agent` 协议（`respond(request, tools) -> AgentResponse`）。
2. **安全隔离**：Agent 只能通过受控的 `AgentTools` 访问元数据检索与 SQL 执行能力，禁止直接连接底层数据库、读取磁盘文件或发起未授权网络请求。
3. **真实执行回执**：回答成功必须携带受控执行器返回的 `query_id`、实际提交的 SQL 及答案；仅返回自然语言文本或伪造 query_id 无法通过评测。
4. **确定性多轮交互**：对于歧义问题，Agent 应提出最小且足够的问题并声明缺失的槽位（`requested_slots`）；不可在缺乏必要约束时擅自脑补。
5. **合规拒答**：对于越权字段、未声明指标或不安全操作，Agent 须主动识别并返回带标准 `reason_code` 的拒答。

---

## 2. Agent 协议定义

核心契约位于 `customer360.agent.protocol` 与 `customer360.contracts.public`。

### 2.1 Agent 接口

```python
from typing import Protocol
from customer360.contracts.public import AgentRequest, AgentResponse
from customer360.agent.protocol import AgentTools

class Agent(Protocol):
    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        """根据用户请求和受控工具返回响应。"""
        ...
```

### 2.2 AgentRequest 输入结构

每次调用 `respond` 时，Agent 会收到一个不可变的 `AgentRequest`：

```python
class AgentRequest:
    case_id: str                   # 评测用例唯一标识 (如 "C360_0001")
    question: str                  # 用户自然语言提问
    anchor_date: date              # 业务时间锚点 (如 2025-06-30)，所有“近 N 天”均以此为基准
    metadata_version: str          # 元数据版本 (如 "0.3")
    protocol_version: str = "0.1"  # 协议版本
    conversation: tuple[Message]   # 历史对话记录，多轮澄清时包含往轮提问与回复
```

### 2.3 AgentTools 工具集说明

执行引擎向 Agent 注入 `tools: AgentTools` 实例，包含以下 9 个受控工具方法：

| 工具方法 | 参数 | 返回值说明 | 用途 |
|---|---|---|---|
| `execute_sql(sql: str)` | `sql: str` | `QueryReceipt` | 提交 SQL 到网关执行，返回执行回执（含 `query_id` 与结构化结果） |
| `search_tables(query: str)` | `query: str` | `tuple[dict, ...]` | 模糊搜索授权可见的表名与描述（不泄露列清单） |
| `search_columns(query: str)` | `query: str` | `tuple[dict, ...]` | 模糊搜索授权可见的字段名、数据类型与敏感级别 |
| `search_metrics(query: str)` | `query: str` | `tuple[dict, ...]` | 搜索已定义的业务指标列表与别名 |
| `get_table_schema(table_name: str)` | `table_name: str` | `tuple[dict, ...]` | 获取指定授权表的字段元数据定义 |
| `get_metric_definition(metric_name: str)` | `metric_name: str` | `dict` | 获取指标的技术口径、度量字段、固定过滤、支持维度等 |
| `get_business_glossary(term: str)` | `term: str` | `tuple[dict, ...]` | 检索业务术语词典及关联指标 |
| `get_join_paths(query: str)` | `query: str` | `tuple[dict, ...]` | 检索经过安全审查的表关联路径（v1.0 仅 `customer_transactions` 可编译） |
| `validate_query_plan(plan: dict)` | `plan: dict` | `dict` | 在执行前对逻辑查询计划进行自检，返回合法性与问题列表 |

#### `execute_sql` 返回的 `QueryReceipt`
```python
receipt = tools.execute_sql("SELECT COUNT(*) AS customer_count FROM dim_customer WHERE status = 'active'")
print(receipt.query_id)     # 唯一执行凭证，用于在 Success 中回填
print(receipt.result.rows)  # 结构化结果集: (('6',),)
print(receipt.elapsed_ms)   # 物理执行耗时
```

### 2.4 AgentResponse 输出状态

Agent 必须返回且仅返回以下四种响应对象之一：

1. **`Success`**：成功回答
   ```python
   from customer360.contracts.public import Success

   return Success(
       answer="当前正常状态的客户共有 6 位。",
       sql=candidate_sql,
       query_id=receipt.query_id,  # 必须与 tools.execute_sql 得到的 receipt.query_id 严格一致
       assumptions=("统计不含注销与休眠客户",),
       evidence=("dim_customer.status = 'active'",),
       confidence=1.0,
   )
   ```

2. **`Clarification`**：请求多轮澄清
   ```python
   from customer360.contracts.public import Clarification

   return Clarification(
       questions=("请问您想统计的是全量客户，还是仅处于活跃状态的客户？",),
       requested_slots=("status",),  # 声明缺失的关键业务槽位
   )
   ```

3. **`Refusal`**：合规拒答
   ```python
   from customer360.contracts.public import Refusal

   return Refusal(
       reason_code="PERMISSION_DENIED",  # 稳定拒答码
       reason="当前角色无权查询客户手机号或身份证敏感信息。",
       alternative="您可以查询客户所在省份或客户等级统计。",
   )
   ```
   标准拒答码包括：`PERMISSION_DENIED`、`UNSAFE_SQL`、`UNKNOWN_METRIC`、`UNKNOWN_FIELD`、`UNSUPPORTED_QUERY`、`AGGREGATION_TOO_SMALL`。

4. **`AgentError`**：运行异常
   ```python
   from customer360.contracts.public import AgentError

   return AgentError(
       reason_code="INTERNAL_ERROR",
       message="查询规划器发生未捕获异常",
   )
   ```

---

## 3. 自定义 Agent 实现范例

以下是一个结合元数据检索、逻辑计划前置自检与受控执行的自定义 Agent 示例：

```python
from datetime import date
from customer360.agent.protocol import Agent, AgentTools
from customer360.contracts.public import (
    AgentRequest,
    AgentResponse,
    Success,
    Clarification,
    Refusal,
    AgentError,
)

class MyCustomAgent:
    """一个遵循 Customer360 协议的自定义问数 Agent 范例。"""

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        # 1. 检测是否需要拒答（例如涉及不存在的手机号或敏感字段）
        if "手机" in request.question or "身份证" in request.question:
            return Refusal(
                reason_code="UNKNOWN_FIELD",
                reason="当前数据字典中不包含手机号或身份证字段。",
                alternative="可按客户地区或等级进行统计。",
            )

        # 2. 检查多轮澄清槽位：如果问题包含模糊词（如“资产”）且未指定类型
        if "资产" in request.question and "总资产" not in request.question and "净资产" not in request.question:
            if not request.conversation:  # 第一轮提问
                return Clarification(
                    questions=("请明确您指的是客户的总资产还是净资产？",),
                    requested_slots=("asset_type",),
                )

        # 3. 检索指标口径
        metrics = tools.search_metrics(request.question)
        if not metrics:
            return Refusal(
                reason_code="UNKNOWN_METRIC",
                reason="未能从业务指标库中匹配到相关指标口径。",
            )

        target_metric = metrics[0]["name"]
        metric_def = tools.get_metric_definition(target_metric)

        # 4. 构建前置逻辑计划自检
        plan = {
            "source_table": metric_def["source_table"],
            "operation": metric_def["operation"],
            "measure_column": metric_def.get("measure_column") or "customer_id",
            "output_column": metric_def["output_column"],
            "predicates": [],
            "join_path": None,
            "group_by": [],
        }
        validation = tools.validate_query_plan(plan)
        if not validation.get("is_valid", False):
            issues = validation.get("issues", [])
            return AgentError(
                reason_code="UNSUPPORTED_REQUEST",
                message=f"逻辑计划自检失败: {issues}",
            )

        # 5. 生成合规 SQL 并经由网关执行
        sql = f"SELECT {metric_def['measure_expression']} AS {metric_def['output_column']} FROM {metric_def['source_table']}"
        try:
            receipt = tools.execute_sql(sql)
        except Exception as e:
            return AgentError(reason_code="TOOL_ERROR", message=f"SQL 执行失败: {e}")

        # 6. 解析结构化结果并返回 Success
        rows = receipt.result.rows
        value = rows[0][0] if rows and rows[0] else 0
        return Success(
            answer=f"统计结果为 {value}。",
            sql=sql,
            query_id=receipt.query_id,
            confidence=0.95,
        )
```

---

## 4. 本地评测与验证流程

编写好 Agent 之后，可以通过 Python 代码或 CLI 工具对其进行全方位评测。

### 4.1 在 Python 代码中快速评测单道用例

```python
from pathlib import Path
from customer360.application import load_catalog, load_human_cases
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import ExecutionPolicy
from customer360.metadata.metrics import MetadataRepository
from customer360.evaluator.runner import evaluate_case

# 1. 准备元数据仓储与执行网关
catalog = load_catalog()
repository = MetadataRepository(catalog)
# 关联已生成的 Tiny 数据库 (见 `c360 generate-data`)
db_path = Path("outputs/tiny-local/dataset.duckdb")
policy = ExecutionPolicy(role="analyst", allowed_tables=("dim_customer",))
gateway = ExecutionGateway(db_path, policy, catalog)

# 2. 加载公开测试题目及可信 Oracle
cases = load_human_cases(Path("data/trusted/human_oracles.yaml"))
test_case = cases[0]  # C360_0001

# 3. 运行评测
agent = MyCustomAgent()
record = evaluate_case(test_case, agent, gateway, repository)

print("评测结果:", record.outcome)  # "passed" 或 "failed"
print("原因码:", record.reason_code)
print("耗时(ms):", record.elapsed_ms)
```

### 4.2 通过 CLI 运行评测链路

评测前先生成基础数据与变体：

```bash
# 1. 生成 Tiny 数据集与 4 个冻结变体
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 generate-variant --variant-id tiny_seed_43_distribution --output outputs/var-dist
uv run c360 generate-variant --variant-id tiny_duplicate_fanout --output outputs/var-dup
uv run c360 generate-variant --variant-id tiny_null_empty_groups --output outputs/var-null
uv run c360 generate-variant --variant-id tiny_date_boundary --output outputs/var-date

# 2. 针对官方 Baseline 进行单道题目调试
uv run c360 run-case --case-id C360_0001 --agent baseline --dataset outputs/tiny-local --output outputs/run-0001

# 3. 针对 20 道公开用例运行 Baseline 矩阵评测
uv run c360 evaluate --dataset outputs/tiny-local --distribution-variant outputs/var-dist --duplicate-variant outputs/var-dup --null-variant outputs/var-null --date-variant outputs/var-date --agent baseline --mode same_sql --output outputs/matrix-eval

# 4. 生成公开可阅读的 HTML/JSON 评测报告
uv run c360 report --input outputs/matrix-eval --format html
```

---

## 5. 评测判定与常见错误分类

评测系统采用多重集比对算法，要求 Agent 的候选 SQL 在基准数据集及 4 个变体数据集上均得出正确结果。常见失败分类如下：

| 错误分类码 | 典型原因 | 优化指引 |
|---|---|---|
| `TIME_RANGE_ERROR` | 时间窗口首尾端点偏移（如将闭区间写成开区间） | 严格遵守 `[anchor - 89, anchor]` 两端闭区间定义 |
| `FILTER_ERROR` | 遗漏指标声明的固定过滤条件（如未过滤 `status='success'`） | 在 `get_metric_definition` 中提取 `fixed_filters` 并合并 |
| `JOIN_ERROR` | 使用了未经审查的 Join 路径，或在 Join 后未去重 | 仅使用 `customer_transactions` 路径，并对 `customer_id` 去重 |
| `UNSAFE_SQL` | 提交包含 CTE、窗口函数、子查询或未授权函数的 SQL | 保持单表单聚合结构，避免生成复杂 SQL 语法 |
| `AGGREGATION_TOO_SMALL` | 查询命中零客户或低于 `min_group_size=1` 阈值 | 对小样本聚合场景识别并合规拒答 |
| `INPUT_LIMIT` | 扫描或物化行数超出该规模上限（Tiny 每表上限 10,000 行） | 避免笛卡尔积，确保带有过滤条件 |
| `CLARIFICATION_FAILURE` | 提出了多余的问题，或请求的槽位与题目需求不符 | 仅提取未决的关键槽位，不展开无关发散询问 |

---

## 6. 开发者最佳实践

1. **善用 `validate_query_plan`**：在调用 `execute_sql` 前，先使用逻辑计划验证工具拦截非法操作，避免触发网关安全拦截。
2. **严守时间语义**：永远使用 `request.anchor_date` 作为基准时间，不要调用 `CURRENT_DATE` 或本地系统时间。
3. **保持状态单向流**：在多轮对话中，通过 `request.conversation` 获取前序轮次的回答内容，在槽位补齐后立即生成最终查询。
4. **不要篡改公共文件**：测试与评测的输出必须输出到全新的本地目录（如 `outputs/my-eval-1`），避免覆盖已有试验记录。
