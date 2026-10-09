# Customer360 Agent Integration and Usage Guide

[English](agent-integration-guide.md) | [简体中文](../agent-integration-guide.md)

This guide is designed for developers who wish to build, integrate, and evaluate custom intelligent question-answering Agents within the **Customer360 Agent Benchmark**. Before proceeding, refer to the [User Guide](user-guide.md) for environment setup and foundational CLI commands.

---

## 1. Core Integration Principles

1. **Protocol Adherence**: Agents must implement the standard Python `Agent` protocol (`respond(request, tools) -> AgentResponse`).
2. **Security & Isolation**: Agents access metadata discovery and SQL execution capabilities strictly through the controlled `AgentTools`. Direct connections to the underlying database, reading raw disk files, or initiating unauthorized network calls are prohibited.
3. **Execution Receipts**: Successful answers must return the `query_id` provided by the execution gateway, along with the submitted SQL and the answer text. Emitting only a natural language sentence or fabricating a fake `query_id` will fail the evaluation.
4. **Deterministic Multi-Turn Interaction**: For ambiguous questions, Agents must ask minimal sufficient questions and declare missing slots (`requested_slots`). Guessing missing constraints without clarification is forbidden.
5. **Compliant Refusals**: For unauthorized columns, undeclared metrics, or unsafe operations, Agents must proactively recognize constraints and return a refusal with a standard `reason_code`.

---

## 2. Agent Protocol Specification

The core contracts reside in `customer360.agent.protocol` and `customer360.contracts.public`.

### 2.1 Agent Interface

```python
from typing import Protocol
from customer360.contracts.public import AgentRequest, AgentResponse
from customer360.agent.protocol import AgentTools

class Agent(Protocol):
    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        """Processes the request using controlled tools and returns an AgentResponse."""
        ...
```

### 2.2 AgentRequest Structure

On every `respond` invocation, the Agent receives an immutable `AgentRequest`:

```python
class AgentRequest:
    case_id: str                   # Unique case identifier (e.g. "C360_0001")
    question: str                  # Natural language prompt from the user
    anchor_date: date              # Business time anchor (e.g. 2025-06-30); all "last N days" derive from this
    metadata_version: str          # Metadata version (e.g. "0.3")
    protocol_version: str = "0.1"  # Protocol version
    conversation: tuple[Message]   # Conversation history for multi-turn clarification rounds
```

### 2.3 AgentTools Reference

The execution gateway injects an `AgentTools` instance containing 9 controlled methods:

| Tool Method | Parameters | Return Type | Description |
|---|---|---|---|
| `execute_sql(sql: str)` | `sql: str` | `QueryReceipt` | Submits SQL to the gateway for execution; returns execution receipt with `query_id` and structured results |
| `search_tables(query: str)` | `query: str` | `tuple[dict, ...]` | Searches authorized table names and descriptions (column lists are withheld) |
| `search_columns(query: str)` | `query: str` | `tuple[dict, ...]` | Searches authorized column names, types, and sensitivity classifications |
| `search_metrics(query: str)` | `query: str` | `tuple[dict, ...]` | Searches defined business metrics and aliases |
| `get_table_schema(table_name: str)` | `table_name: str` | `tuple[dict, ...]` | Retrieves column definitions for a specified authorized table |
| `get_metric_definition(metric_name: str)` | `metric_name: str` | `dict` | Retrieves technical specification, measure column, fixed filters, and supported dimensions |
| `get_business_glossary(term: str)` | `term: str` | `tuple[dict, ...]` | Searches business glossary terms and associated metrics |
| `get_join_paths(query: str)` | `query: str` | `tuple[dict, ...]` | Searches audited table join paths (only `customer_transactions` is executable in v1.0) |
| `validate_query_plan(plan: dict)` | `plan: dict` | `dict` | Pre-validates a logical query plan before execution, returning validity and issues |

#### `execute_sql` and `QueryReceipt`
```python
receipt = tools.execute_sql("SELECT COUNT(*) AS customer_count FROM dim_customer WHERE status = 'active'")
print(receipt.query_id)     # Unique receipt token, required in Success response
print(receipt.result.rows)  # Structured results: (('6',),)
print(receipt.elapsed_ms)   # Execution latency in milliseconds
```

### 2.4 AgentResponse Status Variants

The Agent must return exactly one of the following four response types:

1. **`Success`**: Successful answer
   ```python
   from customer360.contracts.public import Success

   return Success(
       answer="There are 6 active customers.",
       sql=candidate_sql,
       query_id=receipt.query_id,  # Must strictly match the query_id from tools.execute_sql
       assumptions=("Excludes dormant and closed customers",),
       evidence=("dim_customer.status = 'active'",),
       confidence=1.0,
   )
   ```

2. **`Clarification`**: Request clarification
   ```python
   from customer360.contracts.public import Clarification

   return Clarification(
       questions=("Would you like to count all customers, or only active customers?",),
       requested_slots=("status",),  # Declares missing business slots
   )
   ```

3. **`Refusal`**: Compliant refusal
   ```python
   from customer360.contracts.public import Refusal

   return Refusal(
       reason_code="PERMISSION_DENIED",  # Stable refusal reason code
       reason="Current role is not authorized to access customer phone numbers or ID cards.",
       alternative="You may query aggregated customer counts by region or customer tier.",
   )
   ```
   Standard reason codes: `PERMISSION_DENIED`, `UNSAFE_SQL`, `UNKNOWN_METRIC`, `UNKNOWN_FIELD`, `UNSUPPORTED_QUERY`, `AGGREGATION_TOO_SMALL`.

4. **`AgentError`**: Operational failure
   ```python
   from customer360.contracts.public import AgentError

   return AgentError(
       reason_code="INTERNAL_ERROR",
       message="Unhandled exception in query planner",
   )
   ```

---

## 3. Custom Agent Implementation Example

Below is a self-contained custom Agent demonstrating metadata discovery, query plan pre-validation, and controlled execution:

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
    """A custom question-answering Agent conforming to Customer360 protocol."""

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        # 1. Proactively detect restricted/non-existent fields
        if "phone" in request.question.lower() or "id_card" in request.question.lower():
            return Refusal(
                reason_code="UNKNOWN_FIELD",
                reason="Phone numbers and national IDs do not exist in the data catalog.",
                alternative="You can query statistics by customer region or tier.",
            )

        # 2. Check for ambiguity requiring clarification
        if "asset" in request.question and "total" not in request.question and "net" not in request.question:
            if not request.conversation:  # First turn
                return Clarification(
                    questions=("Do you mean total assets or net assets?",),
                    requested_slots=("asset_type",),
                )

        # 3. Retrieve metric definition
        metrics = tools.search_metrics(request.question)
        if not metrics:
            return Refusal(
                reason_code="UNKNOWN_METRIC",
                reason="Could not match the question to a defined business metric.",
            )

        target_metric = metrics[0]["name"]
        metric_def = tools.get_metric_definition(target_metric)

        # 4. Pre-validate logical query plan
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
                message=f"Query plan pre-validation failed: {issues}",
            )

        # 5. Generate and execute compliant SQL
        sql = f"SELECT {metric_def['measure_expression']} AS {metric_def['output_column']} FROM {metric_def['source_table']}"
        try:
            receipt = tools.execute_sql(sql)
        except Exception as e:
            return AgentError(reason_code="TOOL_ERROR", message=f"SQL execution failed: {e}")

        # 6. Parse structured result and return Success
        rows = receipt.result.rows
        value = rows[0][0] if rows and rows[0] else 0
        return Success(
            answer=f"The calculated value is {value}.",
            sql=sql,
            query_id=receipt.query_id,
            confidence=0.95,
        )
```

---

## 4. Local Evaluation and Verification Workflows

### 4.1 Evaluating a Single Case via Python API

```python
from pathlib import Path
from customer360.application import load_catalog, load_human_cases
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import ExecutionPolicy
from customer360.metadata.metrics import MetadataRepository
from customer360.evaluator.runner import evaluate_case

# 1. Initialize metadata repository and execution gateway
catalog = load_catalog()
repository = MetadataRepository(catalog)
db_path = Path("outputs/tiny-local/dataset.duckdb")  # Generated via `c360 generate-data`
policy = ExecutionPolicy(role="analyst", allowed_tables=("dim_customer",))
gateway = ExecutionGateway(db_path, policy, catalog)

# 2. Load public cases with trusted oracles
cases = load_human_cases(Path("data/trusted/human_oracles.yaml"))
test_case = cases[0]  # C360_0001

# 3. Execute evaluation
agent = MyCustomAgent()
record = evaluate_case(test_case, agent, gateway, repository)

print("Outcome:", record.outcome)      # "passed" or "failed"
print("Reason Code:", record.reason_code)
print("Latency (ms):", record.elapsed_ms)
```

### 4.2 Running Full Evaluation via CLI

Generate baseline data and variants first:

```bash
# 1. Generate Tiny dataset and 4 frozen variants
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 generate-variant --variant-id tiny_seed_43_distribution --output outputs/var-dist
uv run c360 generate-variant --variant-id tiny_duplicate_fanout --output outputs/var-dup
uv run c360 generate-variant --variant-id tiny_null_empty_groups --output outputs/var-null
uv run c360 generate-variant --variant-id tiny_date_boundary --output outputs/var-date

# 2. Run a single case on official baseline
uv run c360 run-case --case-id C360_0001 --agent baseline --dataset outputs/tiny-local --output outputs/run-0001

# 3. Run matrix evaluation on 20 human cases
uv run c360 evaluate --dataset outputs/tiny-local --distribution-variant outputs/var-dist --duplicate-variant outputs/var-dup --null-variant outputs/var-null --date-variant outputs/var-date --agent baseline --mode same_sql --output outputs/matrix-eval

# 4. Generate public sanitized HTML/JSON report
uv run c360 report --input outputs/matrix-eval --format html
```

---

## 5. Failure Attribution and Error Codes

Evaluation matches results against ground truth using multiset comparison across the baseline and 4 variants. Common failure codes:

| Failure Code | Root Cause | Remediation |
|---|---|---|
| `TIME_RANGE_ERROR` | Date window endpoints misaligned (e.g. open vs. closed interval) | Strictly follow `[anchor - 89, anchor]` closed interval semantics |
| `FILTER_ERROR` | Missing fixed filter conditions defined by the metric | Inspect `fixed_filters` in `get_metric_definition` and enforce them |
| `JOIN_ERROR` | Unauthorized join topology or missing deduplication after join | Use only `customer_transactions` join and deduplicate by `customer_id` |
| `UNSAFE_SQL` | Submitting CTEs, window functions, subqueries, or unwhitelisted functions | Adhere to single-table aggregation AST whitelist |
| `AGGREGATION_TOO_SMALL` | Query matches zero customers, violating `min_group_size=1` | Proactively detect zero-contribution cases and return refusal |
| `INPUT_LIMIT` | Materialized rows exceed scale budget (10k rows/table on Tiny) | Add filter conditions to prevent cartesian products |
| `CLARIFICATION_FAILURE` | Asking superfluous questions or mismatching requested slots | Extract only missing essential slots without conversational filler |

---

## 6. Developer Best Practices

1. **Leverage `validate_query_plan`**: Run the logical plan validator before executing queries to intercept policy violations before gateway errors occur.
2. **Strict Temporal Anchoring**: Always use `request.anchor_date` as the temporal reference point. Never invoke `CURRENT_DATE` or system clocks.
3. **Unidirectional State Flow**: In multi-turn dialogues, inspect previous answers in `request.conversation` and compile the final query as soon as required slots are filled.
4. **Preserve Fresh Output Paths**: Always write evaluation results to a new, non-existent directory (e.g., `outputs/my-eval-1`). Overwriting historical runs is blocked by the CLI.
