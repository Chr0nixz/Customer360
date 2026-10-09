# Architecture and Formal Release Boundaries 1.0.0

[English](architecture.md) | [简体中文](../architecture.md)

For execution instructions, refer to the [User Guide](user-guide.md). This document specifies trust boundaries and module responsibilities.

## 1. Assembly and Responsibilities

`application.py` is the composition root: it assembles public fixtures, the metadata repository, trusted security policies, execution gateways, SQL submission adapters, and the evaluator. Business modules must never resolve global databases on their own, read credentials, or call external models directly.

~~~text
Public AgentRequest --> Agent.respond(request, AgentTools)
                                      |
                             ToolSession (Controlled Tools)
                                      |
                                   Gateway
                                      |
                AST Whitelist / Table-Column Auth / QueryRejected
                                      |
                          spawn isolated SQL worker
                                      |
        Read-only Source DB -> Authorized Projection -> Close Source DB
                                      |
            Isolated In-Memory DB -> Min Aggregation Granularity -> Candidate SQL
                                      |
                 Result Contract / Result Safety -> query_id Receipt
                                      |
                         Session Execution Log (Trusted)

PrivateCase -> CaseOracle -> SemanticSpec -> Gold compiler
                                      |
                               Isolated Gold Receipt
                                      |
                 evaluator compares candidate execution against reference
~~~

Gold queries execute within the same authorization scope, but their receipts never enter the evaluated Agent's session log. To pass, the evaluation requires a successful status, a verified execution receipt, candidate SQL matching the receipt, and a matching result. Natural language answers or fabricated query IDs score zero.

## 2. Code Dependencies and Boundaries

- **contracts**: Pure Pydantic contract layer free of database I/O. The public contract does not import oracle or semantic definitions.
- **agent**: Only depends on public contracts, ports, adapter audit contracts, and safety error types. Tests forbid the agent package from importing oracle, semantic, tasks, evaluator, runtime, or DuckDB. Both the official `BaselineAgent` and `TemplateAgent` operate within this boundary.
- **metadata**: Loads public schemas and metrics packaged within the library; does not access Gold or databases.
- **synth**: Generates synthetic data strictly through metadata schema contracts without importing agent or evaluator modules.
- **tasks**: Deterministically generates SQL from structured DSL specifications. Never accepts raw arbitrary SQL as sole Gold, and never calls LLMs.
- **safety**: Validates candidate ASTs and result contracts; runtime executes queries and enforces trusted policies.
- **evaluator**: Maintains private oracles and verifies correctness against controlled execution receipts.
- **CLI / application**: Manages orchestration, CLI parameters, and output reporting without duplicating business metric definitions.

`metadata/repository.py` provides a unified entry point, while loading and querying logic reside in `metadata/metrics.py`. The repository can retrieve tables, columns, 30 defined metrics, 20 audited join paths, and business glossary terms derived from catalog metrics. It validates metric references, business term uniqueness, and undeclared entity fields (such as phone and ID card). `get_join_paths` only returns paths where all required tables are authorized; currently, only `customer_transactions` has `compile_status=executable`. Agent tool ports only return metadata for authorized tables and columns; `search_tables` does not return column lists. `validate_query_plan` is currently unimplemented; `metadata_only` join paths can be queried via tools but cannot be compiled into executable queries.

## 3. Current SQL Capability Boundaries

Permitted queries: A single table with no aliases or catalog prefixes; a single aggregated column with an output alias (`COUNT(*)`, `COUNT(column)`, `COUNT(DISTINCT column)`, or `SUM(decimal_column)`); WHERE clauses supporting column-to-literal comparisons, `AND`/`OR`, `IN`, `IS NULL` / `IS NOT NULL`, and parentheses.

Explicit permitted sub-patterns:
- `dim_customer` with `GROUP BY region`, selecting the grouping key and `COUNT(DISTINCT customer_id)`.
- `fact_asset_snapshot` with a `MAX(snapshot_date)` self-join followed by `SUM(total_asset)`.
- Fixed join: strictly `dim_customer.customer_id = fact_transaction.customer_id`, customer deduplication counts, and rolling window filters on the transaction side.

Rejected queries: Multi-statement scripts, mutation statements (`INSERT`/`UPDATE`/`DELETE`/`DROP`), unauthorized joins, CTEs, arbitrary subqueries, `UNION`, `HAVING`, `ORDER BY`, `LIMIT`, window functions, and unwhitelisted functions. The presence of a `SELECT` or `WITH` prefix is not accepted as proof of safety; the parsed AST must strictly comply with the whitelist, and nested clauses in subqueries are re-inspected. Literal types in WHERE and JOIN clauses must match catalog types (dates must be valid ISO-8601 strings; Decimals reject arbitrary strings, NaN, and Infinity). Unsupported DSL fields raise explicit errors instead of silently dropping conditions.

These constraints represent the frozen v0.1 baseline. Point-in-time snapshot metrics compile strictly to `snapshot_date = DATE` equality filters; latest-snapshot metrics are treated as distinct metrics without window functions.

## 4. Execution Safety

1. Roles, column grants, and customer ID filters originate from the trusted execution context, not user prompts.
2. Grants must point to verified customer-scoped tables containing `customer_id`; restricted columns are denied even if accidentally granted.
3. Workers project authorized rows and columns into an isolated in-memory database based on `SqlLimits.max_input_rows`. Tiny defaults to 10,000 rows via parameterized extraction and typed `VALUES`. Standard and Large use named budget profiles (400,000 and 4,000,000 rows); workers attach the read-only source database, create tables via `CREATE TABLE AS`, and detach the source database before executing candidate SQL. Budgets are bound to `DatasetManifest.scale`. Exceeding limits records `INPUT_LIMIT` rather than scan volume.
4. Once the source database connection is severed, candidate SQL executes strictly within the isolated in-memory database.
5. External file access and extension loading are disabled, database configurations are locked, and CPU thread and memory caps are explicitly set.
6. A `min_group_size` threshold is enforced on filtered `COUNT(DISTINCT customer_id)`. If the sample is too small, the query is rejected.
7. The parent process enforces a wall-clock timeout budget; if exceeded, the child process is terminated/killed and reaped via `join`.
8. Result sets are validated against expected column names, types, row counts, and truncation thresholds.

Default `min_group_size=1`. An empty authorization scope or zero filtered customers yields `AGGREGATION_TOO_SMALL` rather than falling back to all customers.

*Note on Process Isolation*: Process isolation guarantees SQL execution timeouts and data projection containment, but does not serve as an OS sandbox against arbitrary Python code execution. Evaluated agents must execute as local trusted Python.

## 5. Semantic Comparison and Scoring

Result set comparison uses structured column types. Unordered results default to multiset semantics, preserving row multiplicity; deduplication occurs only when the task DSL specifies distinct semantics. Integers require exact equality; Decimals use absolute and relative tolerances; `NULL`, `0`, and empty strings are treated as distinct values. Unordered matching with tolerance uses 1-to-1 optimal matching rather than greedy matching.

The smoke runner provides a single-snapshot sanity check for architectural verification rather than formal multi-dimensional scoring. Evaluator 0.5 evaluates question answers, multi-turn serialized slot scripts, and refusal reason codes. Evaluator 0.6 produces the inputs for formal weighted scoring via `c360 evaluate-public` and `c360 evaluate-hidden --formal`. Final weighted scores are computed by `c360 score`, generating separate scorecards for `public_dev` and `private_hidden`. `ranking_enabled` is permanently set to `false`.

The official baseline is `BaselineAgent` (`--agent baseline`), which plans offline without reading Gold and executes via the same gateway. `TemplateAgent` is reserved for protocol integration testing. `c360 evaluate` replays the single candidate SQL generated on the baseline across the Tiny baseline and four data variants in `same_sql` mode. Private JSONL logs retain candidate SQL and trace records, while public summaries and reports are sanitized.

## 6. Reproducibility and Artifacts

Every dataset and task package records seed, schema/generator/snapshot versions, configuration digest, catalog digest, normalized per-table content digests, row counts, and dependency versions. Normalized content digests do not depend on DuckDB internal physical layout or runtime execution timing.

Data generation follows strict reproducibility: `configs/data_generation.yaml` is validated via `GenerationConfig` and generated by `synth/generator.py`. Frozen scales:
- Tiny: 100 customers / 2,000 transactions
- Standard: 10,000 customers / 300,000 transactions
- Large: 100,000 customers / 3,000,000 transactions

Standard and Large maintain at least 5% zero-transaction, 5% zero-holding, and 3% empty-occupation distributions. All business attributes derive from a deterministic `Random(seed)`, and calendar dimensions depend only on anchor dates and time horizons. Tiny seed 42 content digests and quality report hashes are frozen. `load_verified_dataset` re-verifies table keys, row counts, and content hashes on load.

Packaging rules: The source distribution (sdist) uses an explicit whitelist excluding `outputs/`, `.venv`, `.private`, `.env`, `data/hidden`, and `data/trusted`. The built wheel contains only runtime code under `src/customer360` and public resource files. Formal releases are managed via `prepare-formal-release` and `check-formal-release`, validating all eight RC gates.

## 7. M2 Dev Case Assets (Human Baseline Cases)

`resources/human_cases.yaml` contains the public prompts for 20 human baseline cases (`C360_0001–C360_0020`, `split=dev`). Semantic specs, expected actions, missing slots, and refusal reason codes are stored in `data/trusted/human_oracles.yaml` and loaded exclusively on the trusted side via `load_human_cases()`. 18 answerable cases are verified by cross-checking compiled SQL against independent Python calculation oracles.

The independent hidden benchmark set is generated via `c360 generate-hidden` (`C360_4001+`) and evaluated on isolated hidden datasets. Task families in the public 300-pack and hidden pack never overlap with `C360_0001–0020`.
