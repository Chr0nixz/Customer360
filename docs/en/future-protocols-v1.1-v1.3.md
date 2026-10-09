# Customer360 Protocol and Capability Evolution Design Specification (v1.1 – v1.3)

[English](future-protocols-v1.1-v1.3.md) | [简体中文](../future-protocols-v1.1-v1.3.md)

Document Version: `v1.3-implemented`  
Implementation Status: v1.1 Diagnostic Enhancements (Implemented), v1.2 Metadata Evolution (Implemented), v1.3 Engine Adaptation (Implemented)  
Constraints: Does not alter v1.0 scoring weights, does not alter 30 business metric definitions, does not leak hidden sets, does not loosen SQL Guard or authorization boundaries.

---

## 1. Overview and Core Principles

Following the formal v1.0 release (pure offline DuckDB benchmark, 8 signed RC gates), Customer360 enters the protocol evolution and capability expansion phase. To guarantee credibility and auditability, protocol evolution adheres strictly to:

1. **Explicit Behavior Changes and Version Binding**: Distinguish pure documentation/test improvements from observable protocol changes. Any modification affecting Agent I/O, tool interfaces, semantic compilation, or evaluation matching rules must bump its corresponding version field.
2. **Fail-Closed Safety First**: Unknown or undeclared capabilities, tables, columns, or join paths are explicitly rejected with deterministic reason codes. Silently swallowing exceptions or downgrading errors to success is strictly forbidden.
3. **Trusted Isolation Boundaries**: Agents access only declared public metadata and controlled execution tools. Gold compilation, independent oracles, hidden set generation, and evaluation matchers reside strictly on the trusted side.

---

## 2. `validate_query_plan` Capability Matrix and Rejection Codes (v1.2 Implemented)

### 2.1 Motivation and Positioning
When agents lack pre-execution validation tools, they frequently submit syntactically invalid or unauthorized SQL, triggering gateway errors. `validate_query_plan` was introduced in v1.2 as a controlled query plan validation interface (`contracts/validation.py`, `runtime/validator.py`), enabling agents to verify that a logical `QueryPlan` complies with authorization policies, metric definitions, and join topologies without executing queries or exposing data. `BaselineAgent` leverages this tool during pre-planning to short-circuit invalid attempts.

### 2.2 Contract Definition
- **Tool Name**: `validate_query_plan`
- **Request Parameters**:
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
- **Response Contract**:
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

### 2.3 Rejection Code Matrix
| Rejection Code | Trigger Condition | Description |
|---|---|---|
| `UNKNOWN_SOURCE_TABLE` | `source_table` not in catalog or unauthorized | Protects unauthorized table names |
| `UNSUPPORTED_OPERATION` | Aggregation not `count`, `count_distinct`, or `sum` | Enforces supported aggregation operators |
| `INVALID_MEASURE_COLUMN` | Measure column missing, type mismatched, or unauthorized | Prevents summing non-numeric columns |
| `DISALLOWED_FILTER_COLUMN` | Filter column not in metric's `allowed_filter_columns` | Enforces metric filter whitelist |
| `INVALID_PREDICATE_LITERAL` | Filter literal type mismatch (e.g. string passed to date) | Strict type checking |
| `UNSUPPORTED_JOIN_PATH` | Join path not on vetted whitelist (e.g. not `customer_transactions`) | Prevents cartesian products and unverified joins |
| `INVALID_JOIN_PREDICATES` | Join side missing required predicates (e.g. missing `status='success'`) | Enforces business rule constraints |
| `INVALID_GROUP_DIMENSION` | Grouping dimension not in metric's `allowed_group_dimensions` | Prevents unauthorized granular aggregation |

---

## 3. Metric Versioning and Deprecation Guidelines (v1.2 Implemented)

### 3.1 Motivation and Positioning
In financial and customer analytics, metric definitions evolve over time (e.g., active customer criteria shifting from "transactions in last 30 days" to "transactions or logins in last 60 days"). To enable historical benchmark reproducibility and prevent metric drift, metadata supports multi-version coexistence and lifecycle management. v1.2 introduced `status` (`active`, `deprecated`, `retired`) and `replaced_by` into `MetricDef`, backed by `c360 audit-metadata` for dead-link and circular-deprecation auditing.

### 3.2 Metric Metadata Model Extension
```yaml
- metric_name: active_customer_count
  metric_version: "1.1"
  status: "active"             # Options: active | deprecated | retired
  effective_date: "2025-01-01"
  deprecation_date: null
  replaced_by: null
  previous_version: "1.0"
  business_name: 活跃客户数
  ...
```

### 3.3 Evolution and Transition Rules
1. **No In-Place Modifications**: If calculation logic, fixed filters, temporal semantics, or granularity change, overwriting an existing definition is forbidden. A new entry with an incremented `metric_version` must be created.
2. **Deprecation Cycle**:
   - `deprecated` metrics return a warning in discovery tools but remain executable.
   - `retired` metrics return the deterministic rejection code `DEPRECATED_METRIC_REJECTED` and indicate the compliant replacement in `replaced_by`.
3. **Task Pack Version Pinning**: Every Task Case pins a `metadata_version`. Compilers and Evaluators load the exact version pinned at task creation time, preventing regression test breakage.

---

## 4. PostgreSQL Execution Engine Adaptation Matrix (v1.3 Implemented)

### 4.1 Motivation and Positioning
Customer360 uses DuckDB as the official benchmark referee engine. v1.3 implemented cross-engine dialect transpilation (`runtime/dialects.py`), multi-engine gateway abstractions (`BaseExecutionGateway`, `DuckDBExecutionGateway`, `PostgreSQLExecutionGateway`), and the CLI command `c360 transpile-sql`. Formal adaptation matrices and AST equivalence assertions reconcile differences in dialects, implicit casting, null ordering, and timezone handling.

### 4.2 Engine Capabilities and Differences Matrix
| Feature Dimension | DuckDB Baseline | PostgreSQL Target | Adaptation Strategy |
|---|---|---|---|
| **SQL Dialect & Quoting** | Double quotes for tables/columns: `"dim_customer"` | Double quotes: `"dim_customer"` (lowercase preserved) | Standard ANSI SQL emitted via AST |
| **Datetime Arithmetic** | `DATE '2025-06-30' - INTERVAL 89 DAY` | `DATE '2025-06-30' - INTERVAL '89 days'` | Dialect-specific interval rendering in compiler |
| **Numeric & Decimal** | `DECIMAL(18, 2)`, division retains decimals | `NUMERIC(18, 2)`, explicit truncation for division | Results converted uniformly to Python `Decimal` |
| **NULL Ordering** | `NULL` sorts last by default (ASC) | `NULLS FIRST` / `NULLS LAST` defaults differ | Explicit `NULLS LAST` generated for stability |
| **Unordered Multiset** | Pulled into Python memory for multiset tuple comparison | Same Python comparator | Evaluator logic remains engine-agnostic |
| **Safety & Timeout** | Subprocess worker per query; killed on timeout | Connection-level `statement_timeout` + cancel signal | Dual timeout guards (engine-level + process reaper) |
| **Permissions & Isolation** | Materialized view/table in ephemeral read-only DB | Dedicated read-only role + temporary schema | Ensures read-only access and physical containment |

---

## 5. Split Generalization Auditing (v1.1 Implemented)

### 5.1 Motivation and Positioning
While public and hidden task sets use `family_id` hashes to prevent exact duplicates, full feature combinations do not guarantee statistical decoupling across individual metrics or filter predicates. v1.1 implemented three-layer generalization and orthogonality auditing via `c360 audit-splits` (`tasks/audit.py`).

### 5.2 Generalization Audit Dimensions
1. **Template Generalization**: Checks whether the hidden set introduces syntactic structures unseen in the public set (e.g., negations, comparisons, nested constraints).
2. **Metric × Filter Orthogonality**: Audits whether `(metric_name, filter_dimension)` pairs in the hidden set appeared in the training set. If pairs are fully seen, tasks test parametric interpolation rather than compositional generalization.
3. **Data Distribution Drift**: Verifies that the four private hidden variants (Distribution, Fanout, NULL, Date Boundary) create measurable divergence against the baseline, ensuring no task passes via accidental empty result sets.

---

## 6. Version Upgrade and Impact Table

When introducing changes in subsequent iterations, strictly follow this table to identify which version field to bump:

| Change Scope | Trigger Scenario | Version Field | Compatibility & Migration |
|---|---|---|---|
| **Agent Protocol Contract** | Adding fields to `AgentRequest`/`AgentResponse`, modifying status enums | `protocol_version` | Must provide backwards compatibility adapter; old reports cannot be mixed with new runs |
| **Evaluator & Comparison Logic** | Modifying numeric tolerance, variant replay strategy, or hard gates | `evaluator_version` | Old results cannot be converted directly; archive previous reports |
| **Scoring Weights** | Modifying accuracy/robustness/safety weights or penalty rules | `score_version` | Constitutes a major benchmark protocol change; requires re-running agents |
| **Tasks & Semantic DSL** | Adding DSL constructs (e.g. multi-metric combinations, subqueries), modifying paraphrasing rules | `task_version` | Old and new packs load side-by-side by version; in-place mutation of old packs is forbidden |
| **Business Metrics & Metadata** | Adding tables, columns, metrics, or adjusting filter rules | `metadata_version` | Old tasks retain pinned `metadata_version`; new tasks reference new version |
| **Data Generation Logic** | Adjusting distribution parameters, entity relations, or data quality assertions | `generator_version` | If Tiny seed-42 content digests change, release a new snapshot with migration notes |
| **Dataset Snapshot** | Re-generating and publishing synthetic datasets | `snapshot_version` | Updates manifest hashes and quality reports, explicitly bound across layers |

---

## 7. Conclusion

This specification provides the technical baseline for Customer360 evolution, ensuring that evaluator rigor, benchmark authority, and reproducibility remain uncompromising priorities as capabilities expand.
