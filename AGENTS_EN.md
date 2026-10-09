# AGENTS.md

[English](AGENTS_EN.md) | [简体中文](AGENTS.md)

This document specifies the development and collaboration conventions for the Customer360 Agent Benchmark, applicable to all agents, developers, and automated tasks working within this repository.

## 1. Project Objectives

This project is a reproducible, auditable Agent benchmark rather than a routine question-answering demo. Priorities in order:

1. Credible and auditable evaluation;
2. Unambiguous business semantics;
3. Safety enabled by default;
4. Reproducible results;
5. Straightforward integration and extensibility;
6. Task volume, model performance tuning, and speed optimization last.

For the comprehensive phased plan, see [ROADMAP.md](./ROADMAP.md). For foundational architecture, see [Customer360-Agent-Benchmark-Implementation-Plan.md](./Customer360-Agent-Benchmark-Implementation-Plan.md). For CLI usage, see the [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)). Before pushing to GitHub, review the [GitHub Publishing Checklist](docs/en/github-publish.md) ([中文](docs/github-publish.md)) and [CONTRIBUTING.md](CONTRIBUTING.md).

## 2. Working Boundaries

### Default Technical Baseline

- Python 3.11;
- DuckDB as default execution engine;
- SQLGlot for SQL AST parsing and static analysis;
- Pydantic for cross-module data contracts;
- Pytest for automated testing;
- Typer for the CLI framework;
- FastAPI for optional HTTP interfaces;
- YAML for configuration and business metadata;
- JSONL/Parquet for experiment records and batch metrics.

Replacing any component requires explicit justification: rationale, compatibility impact, migration strategy, and test coverage. Never introduce uncoordinated alternative libraries into isolated modules.

### Permitted Actions

- Adding implementations, tests, configs, documentation, and fixtures within task scope;
- Running local data generators, DuckDB queries, and evaluators to verify behavior;
- Adding public examples and regression fixtures without leaking hidden sets;
- Raising questions regarding existing designs while proceeding with semantic-preserving defaults.

### Prohibitions

- Never import, copy, or commit real customer PII, production credentials, real phone numbers, or real government IDs; test fixtures must use synthetic data;
- Never use an LLM directly as Gold SQL, Gold Answer, or final arbiter;
- Never disable or bypass SQL Guard, authorization checks, result masking, or row limits;
- Never alter scoring rules, hidden sets, or metric definitions simply to make something pass;
- Never introduce undocumented global randomness, network calls, or local absolute paths;
- Never prematurely implement PostgreSQL, multi-model orchestration, or marketing tables unless explicitly mandated by the task.

## 3. Before Starting a Task

1. Read this file, `ROADMAP.md`, and the foundational design documents;
2. Inspect the current workspace status to avoid overwriting uncommitted changes;
3. Identify target modules, I/O contracts, acceptance criteria, and blast radius;
4. Search existing implementations and tests; reuse rather than reinvent;
5. If architectural ambiguity arises, document explicit assumptions before proceeding.

## 4. Recommended Development Flow

1. Write/update data models, protocols, or business rules;
2. Write failing tests or minimal regression fixtures;
3. Implement the minimal correct path;
4. Run module-specific tests followed by Tiny regression;
5. Verify that data digests, task versions, evaluation records, and logs remain deterministic;
6. Update documentation, CLI help strings, and change logs;
7. Deliver final reports with changes, verification commands, and open risks.

## 5. Architectural Boundaries

Recommended directory responsibilities:

~~~text
src/customer360/synth       Data generation, distributions, constraints, snapshots
src/customer360/metadata    Metadata models, repository, search, tools
src/customer360/tasks       Semantic DSL, templates, generation, paraphrasing, verification
src/customer360/agent       Agent protocols, planning, SQL submission, clarification, baseline
src/customer360/safety      SQL guard, authorization, result masking
src/customer360/evaluator   Execution, semantic matching, interaction, safety, latency, reporting
src/customer360/cli.py      CLI entrypoint
tests                       Unit, integration, regression, and adversarial test suites
data                        Schemas, metadata, public/hidden datasets, task packs
configs                     Benchmark, generation, evaluation, and safety configurations
docs                        Architecture, dictionaries, tasks, evaluation, and user guides
~~~

Module dependency invariants:
- `synth` does not depend on `agent` or `evaluator`;
- `metadata` never executes arbitrary Agent SQL;
- `tasks` generates Gold deterministically from structured DSL; never calls an Agent to produce Gold;
- `agent` accesses metadata and execution solely through public tools and protocols;
- `evaluator` acts as the final judge and never invokes internal Agent heuristics as ground truth;
- `safety` enforces checkpoints before execution and before result emission.

## 6. Data and Versioning Rules

Track versioning across all layers in manifests:

~~~text
seed
snapshot_version
generator_version
metadata_version
task_version
protocol_version
~~~

### Synthetic Data
- Default seed is 42, but explicit seed overrides must be supported;
- The same seed and version must produce identical data and normalized content digests;
- Digests are computed over normalized tables sorted by primary key;
- Business constraints take precedence over statistical distributions;
- Financial amounts use fixed-precision Decimal; currency compatibility must be validated before summation;
- Date comparisons use the task anchor date with explicit boundary definitions; age is calculated dynamically from birth dates and reference dates;
- Tiny is the default regression dataset; Standard/Large are reserved for integration and performance benchmarks.

### Gold and Tasks
- Sequence: Semantic spec -> compile reference SQL -> execute reference query -> generate natural language;
- Natural language paraphrases must pass semantic consistency verification;
- Every task records an expected action: `answer`, `clarification_needed`, or `refuse`;
- Refusals record reason codes without fabricating executable Gold SQL;
- DSL features must reject unsupported constructs fail-closed rather than dropping clauses;
- Public and hidden sets are isolated across templates, metric combinations, join paths, and temporal semantics.

## 7. Agent Protocol Constraints

Tools use structured JSON serialization:

~~~json
{
  "tool": "search_metrics",
  "arguments": {"query": "customer assets"}
}
~~~

Final outputs adhere to the following states:
- `success`: Contains answer, SQL, column specs, assumptions, evidence, confidence, and verified query receipt;
- `clarification_needed`: Proposes minimal sufficient clarifying questions without guessing missing constraints;
- `refused`: Explains security/permission grounds and suggests compliant alternatives where appropriate;
- `error`: Records diagnosable execution failures (never treated as successful refusals).

## 8. Safety Rules

Safety is enabled by default across all layers.

### SQL Layer
- Allows only single, read-only SELECT queries;
- Rejects mutation statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`);
- Forbids unwhitelisted file/network access, extension loading, system table inspection, and side-effect functions;
- Enforces strict limits on returned rows, input materialization, and execution runtime;
- Blocks direct emission of restricted sensitive columns.

### Authorization Layer
- Enforces role, allowed tables, allowed columns, and customer row scopes;
- Roles originate from trusted caller context, not user prompts;
- Row-level customer scoping is materialized on the trusted side prior to aggregation;
- Preserves audit trails on permission denial without leaking protected schema details.

### Result Layer
- Validates sensitive fields, detail volume, minimum aggregation group sizes, and personal data leakage;
- Refusals, masking, and aggregation must match expected task actions.

## 9. Semantic Correctness Rules

- Correctness is determined by structured semantics, reference queries, and execution receipts;
- Never compare raw SQL strings;
- Default unordered results use multiset matching preserving row multiplicity;
- Comparators handle numeric absolute/relative tolerances, ISO dates, NULL semantics, and empty results;
- Formal answerable cases evaluate across baseline + 4 data variants, requiring all variants to pass;
- Erroneous candidate SQL must be differentiated from Gold by variant datasets.

## 10. Verification and Testing

Every modification requires verification:
- Unit tests: Model validation, parsing, comparator boundaries;
- Integration tests: DuckDB loading, metadata tools, task compilation;
- Regression tests: 20 human baseline cases and frozen seed digests;
- Adversarial tests: SQL injection, ungranted columns, cartesian products, date edge cases.

Always run prior to delivery:

~~~bash
uv run pytest -q
uv run c360 doctor
~~~

## 11. Completion Definition

A task is complete only when:
- Implementation complies with module boundaries and versioning rules;
- Targeted unit/regression tests pass;
- Safety checks and evaluator gates remain active;
- Results, logs, and reports are fully auditable;
- CLI, protocols, configs, and documentation remain synchronized.
