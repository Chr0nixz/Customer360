# Customer360 Agent Benchmark Roadmap

[English](ROADMAP_EN.md) | [简体中文](ROADMAP.md)

> Document Version: v0.2; Created: 2026-09-16; Reviewed & Updated: 2026-09-18 (based on `Customer360-Agent-Benchmark-Implementation-Plan.md`)  
> Status: M0–M7, formal score protocol 1.0, evaluator 0.6, four private hidden variants with provenance/same-SQL replay, Apache-2.0 license, Dockerfile, SHA256/SBOM, and formal release tools are fully implemented; GitHub community files, public tree ignore rules, and publishing checklists are ready. Release candidate (RC) evidence gates are being signed (v1.0.0 tag withheld until all 8 gates pass). Public dev and private hidden evaluations report separately without competitive rankings. Online services, external model APIs, PostgreSQL, and OS sandboxes remain out of v1.0 scope. For CLI commands, see the [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)).  
> Objective: Implement a reproducible, auditable, and extensible Customer360 Agent benchmark.

## 1. North Star Objective

Deliver an agent benchmark that does not rely on real-world business data yet rigorously assesses Agent competencies across:

- Business semantics understanding and metric definition resolution;
- Multi-table joins, temporal semantics, customer filtering, and aggregation;
- SQL generation, execution, and structured result interpretation;
- Multi-turn clarification and non-answerable judgment;
- SQL, authorization, and output result security;
- Robustness against metadata drift, distribution shifts, and boundary edge cases;
- Engineering efficiency indicators such as latency, tool invocation counts, and data scan volumes.

The final benchmark ensures Gold answers are generated deterministically from structured semantics and code, results are fully reproducible, errors are attributable, and third-party agents can integrate via a standard protocol.

## 2. Scope & Non-Goals

### In Scope for v1.0

1. 9 core business tables, with DuckDB as the default execution engine;
2. Reproducible synthetic datasets across Tiny, Standard, and Large scales;
3. Five metadata categories: tables, columns, metrics, joins, and access policies;
4. Structured task DSL, reference SQL compiler, reference results, and natural language prompts;
5. Single-turn, multi-turn clarification, security refusal, and metadata drift tasks;
6. Official Baseline Agent, tool protocols, and automated evaluator;
7. Public Train, Dev, Private Test (hidden), and Challenge splits;
8. CLI, Docker, JSONL/HTML evaluation reports, and integration documentation.

### Explicitly Out of Scope for v1.0

- Never using real customer data or unredacted production credentials;
- Never using LLMs as the final correctness arbiter;
- Multi-database dialect support (PostgreSQL is targeted for post-v1.0);
- Prioritizing task count over reliability (the initial 20 human cases and core pipeline must be 100% credible first);
- Treating raw natural language paraphrasing quality as Gold (all paraphrases must map back to structured semantic verification).

## 3. Core Invariants

These rules apply across all phases without temporary relaxation:

1. Fixed `seed + snapshot_version + generator_version + config_digest + locked_dependencies` must deterministically generate identical normalized data.
2. Gold queries are compiled from semantic specs and reference compilers, never authored directly by LLMs.
3. Result set comparison is semantic-driven; never compare raw SQL strings.
4. The evaluator must pass static AST checks and authorization policies before executing any agent query.
5. Hidden task sets, data variants, and test authorization credentials must never leak into distribution packages.
6. Every metric must define technical name, business name, granularity, temporal semantics, nullability rules, fixed filters, and version.
7. Tasks, Agent outputs, tool calls, and evaluation results must be serializable and auditable.
8. Failures must be categorized into stable, diagnostic error classifications rather than a generic "wrong".

### Semantic Baseline Decisions

- "Last 90 days" is fixed as 90 calendar days inclusive of the anchor date: `[anchor_date - 89 days, anchor_date]`. Phrases like "last 3 months" or "this quarter" cannot be interchanged.
- Default unordered result comparisons use multisets, preserving row multiplicity. Deduplication occurs only when explicitly declared in the task DSL. Queries with `ORDER BY`/Top-K must define tie-breakers.
- Snapshot queries (assets, transactions, holdings) must specify anchor dates, whether to take the latest per-customer snapshot, and how missing records are handled.
- Only `answer` cases require reference SQL and results; `clarification_needed` cases require missing slots and scripted replies; `refuse` cases require reason codes and compliant alternatives.
- Benchmark quality gates are decoupled from Agent performance scores: the former verifies benchmark code correctness, while the latter measures Agent ability.
- The catalog does not define `phone` or `id_card`. Security test cases must differentiate "column does not exist" from "column exists but is restricted".
- The 20 audited join paths represent vetted business relationships rather than forcing 20 direct foreign keys on the 9 tables.

## 4. Milestone Overview

| Milestone | Objective | Key Deliverables | Exit Criteria |
|---|---|---|---|
| M0 | Engineering baseline & decision freeze | `pyproject.toml`, directory structure, configs, ADRs | Clean install, CLI runnable, baseline decisions documented |
| M1 | Data & semantic foundation | DDL, synthetic data generator, Tiny data, metadata | 9 tables loadable, deterministic generation, quality assertions pass |
| M2 | Gold & minimal evaluation loop | Semantic DSL, reference SQL compiler, 20 human cases, security gateway | All 20 cases have action-discriminated oracles; answer cases verifiable |
| M3 | Automated tasks & metadata tools | Metadata search tools, task templates, 120-case generator | Task semantics verified, covering at least 8 failure categories |
| M4 | Evaluator & security guard | Evaluator, SQL Guard, semantic matcher, multi-variant execution | Accurately arbitrates answer/clarification/refusal/timeout; blocks violations |
| M5 | Official Baseline & protocol | Baseline Agent, tool JSON protocols, multi-turn adapter | Executes single/multi-turn/security tasks conforming to protocol |
| M6 | Formal benchmark release | 300 tasks, splits, Docker, reporting, documentation | Public dev and hidden sets runnable; reproducible release package |
| M7 | Performance & extensions | Standard/Large baselines, PostgreSQL adaptation design | Audited performance benchmarks, extension interfaces documented |

## 5. Phased Execution Details

### M0: Engineering Baseline & Decision Freeze
Established project structure, dependencies (Python 3.11, DuckDB, Pydantic, SQLGlot, Typer, Pytest), shared contracts, SQL gateway architecture, and CLI entrypoint.

### M1: Data & Semantic Foundation
Implemented 9 core tables, deterministic synthetic data generator across Tiny (100 customers / 2,000 transactions), Standard (10,000 / 300,000), and Large (100,000 / 3,000,000) scales, 60 named quality assertions, and baseline metadata.

### M2: Gold & Minimal Evaluation Loop
Implemented semantic DSL, 20 human baseline cases (`C360_0001–0020`), deterministic SQL compiler, independent Python calculation oracles, paraphrase consistency checks, and frozen Tiny variants.

### M3: Automated Task Generation & Metadata Tools
Implemented metadata discovery tools (`search_tables`, `search_columns`, `search_metrics`, etc.), 30 business metrics, 20 audited join paths, semantic family isolation, and 120-task development packs.

### M4: Evaluator & Security Guardrails
Implemented AST security validation, authorization projections, multiset matching, timeout reapers, multi-variant execution matrices, and 12 structured error classifications.

### M5: Official Baseline & Multi-Turn Protocol
Implemented official offline `BaselineAgent`, deterministic local planner adapter, tool JSON protocol, multi-turn clarification state machine, and refusal reason code handling.

### M6: Formal Benchmark Release
Expanded to 300 tasks (180 train / 120 dev), independent hidden set (`C360_4001+`), public/private scorecard separation, reproducible build verification, and eight formal RC release gates.

### M7: Performance & Extensions
Established resource budget profiles (`tiny`, `standard`, `large`), performance collection tool (`c360 perf-baseline`), and architectural design for PostgreSQL adaptation and metric deprecation lifecycle.

## 6. Scoring Protocol and Weights

### Automated Evaluation Dimensions

| Dimension | Weight | Scope |
|---|---:|---|
| Correctness | 45% | Semantic result matching (35%), format/columns (5%), explanation completeness (5%) |
| Safety | 20% | SQL injection defense, access control, sensitive masking, compliant refusals |
| Interaction | 15% | Ambiguity recognition, clarification quality, minimal turns, tool efficiency |
| Efficiency | 15% | P50/P95 latencies, token consumption, tool invocation count, scan volume |
| Robustness | 5% | Resilience across data variants, paraphrases, null values, and boundary dates |

### Benchmark Hard Gates

1. Reference compiler, semantic matcher, and security gateway pass 100% of regressions;
2. All benchmark cases trace to deterministic Gold compilation or verified oracles;
3. Zero unhandled P0 evaluator defects permitted;
4. Hard gates: integrity, P0 safety, robustness coverage, non-empty denominators.

## 7. Definition of Done for v1.0

1. Deterministic generation of 9 tables across data scales;
2. 30 business metrics and 20 audited joins accessible via metadata tools;
3. 300 public structured tasks + independent hidden benchmark pack;
4. Every case backed by semantic spec, reference query, and versioned oracle;
5. Evaluator supporting semantic comparison, multi-variant replay, and failure attribution;
6. SQL Guard, authorization projection, and masking enabled by default;
7. Baseline Agent supporting single-turn, multi-turn, and secure refusal;
8. CLI, Docker, protocols, and documentation fully usable by third parties;
9. All 8 formal release candidate gates verified and signed with cryptographic evidence.
