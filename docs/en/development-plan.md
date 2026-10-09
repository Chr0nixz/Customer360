# Development Plan and Execution Roadmap

[English](development-plan.md) | [简体中文](../development-plan.md)

Document Status: `2026-10-05 Review Edition`.

This document specifies the execution plan for the repository, complementing [ROADMAP.md](../../ROADMAP.md). It does not alter scoring weights, Gold SQL, public/hidden splits, SQL Guard, or authorization semantics. Historical milestones remain recorded in `HANDOFF.md` and git history; this document sets forth the active baseline for future work.

## 1. Current Baseline

The project implements a complete, end-to-end benchmark pipeline:

- 9 core tables, synthetic data across Tiny/Standard/Large scales, fixed seeds, and deterministic quality assertions.
- 30 business metrics, 20 audited Join paths (with `customer_transactions` as the sole executable join in v1.0).
- Semantic DSL, deterministic Gold compiler, independent Python oracles, public 120/300 task packs, and an independent hidden pack.
- SQL AST Guard, pre-aggregation authorization projection, result masking, timeout reapers, and structured audit error codes.
- Official offline `BaselineAgent`, Evaluator 0.6, Score Protocol 1.0, and 4 public/hidden data variants.
- Dockerfile, SHA256/SBOM generation, formal release tools, and GitHub Actions CI.

Current Release Status:

| Item | Current Status |
|---|---|
| Git | `main` and `origin/main` commit identical, but working tree has uncommitted modifications; historical `v1.0.0` tag was set on older commit (09d5c648), HEAD is subsequent commits; formal release blocked until all RC gates pass |
| `c360 doctor` | Passing: 9 tables, 72 columns, 30 metrics, 20 Joins, 8 FKs |
| Ruff | `ruff check` and `ruff format --check` passing |
| Tests | 468 test cases collected; 8-case hidden pack CLARIFICATION_FAILURE issue fixed; locally all pass except 5 skipped PostgreSQL live tests (463 passed, 5 skipped, 0 failed) |
| Formal RC Gates | `docker_runtime` requires re-generation on Linux/CI bound to current tree; PostgreSQL live verified via CI |
| Formal Verification | `c360 check-formal-release` requires fresh evidence bundle on current commit before final release tagging |
| Baseline Diagnostics | Weighted score ~0.75; safety and efficiency are solid; accuracy ~52%, robustness ~38% |

Baseline failures center around multi-predicate filter combinations. The deterministic adapter's filter resolution focuses on core dimensions, while generated tasks cover customer tier, risk level, transaction type, channel, and cash flow direction. This concerns Agent capability improvement rather than benchmark infrastructure release gates.

## 2. Immediate Priorities

1. Capture genuine Docker runtime evidence to sign the final RC gate (`docker_runtime`).
2. Establish a single, auditable Linux regression run replacing historical test counters.
3. Enhance Baseline filter and Join coverage without modifying evaluator rules.
4. Harmonize documentation state and finalize actionable designs for post-v1.0 protocols.
5. Freeze scoring weights, Gold oracles, splits, SQL whitelists, and permissions until release evidence passes.

## 3. Three Workstreams

### Agent A: Release & Evidence Closure

**Responsibilities**
- Build the container image from the current commit on Linux/CI.
- Execute `doctor` and `smoke` using `--read-only --network=none --user 10001`.
- Generate genuine container image Id evidence via `.github/scripts/record_docker_runtime.py`.
- Rebuild wheels/sdists, binding `docker_runtime` and reproducible build evidence.
- Run `prepare-formal-release` and `check-formal-release`.

**Permitted Modifications**
- `.github/` workflows and Docker verification scripts.
- Isolated `outputs/` evidence directories.
- Minimal CI fixes required for release commands.

**Prohibitions**
- Altering scoring weights, Gold, task splits, SQL Guard, or authorization policies.
- Forging dummy digests (`sha256:<64 hex>`).
- Tagging `v1.0.0` before all eight gates pass.

### Agent B: Baseline Quality & Regression

**Responsibilities**
- Expand deterministic adapter parsing for metadata filter fields and values.
- Support customer tier, risk level, transaction type, channel, and cash flow filters.
- Re-audit customer-transaction Join deduplication, rolling windows, and permission bounds.
- Add minimal regression fixtures for each failure category.
- Recompute public_dev and private_hidden diagnostic scores with an untouched evaluator.

**Permitted Modifications**
- `src/customer360/agent/adapter.py`.
- `src/customer360/agent/baseline.py`.
- `tests/test_baseline.py` and new baseline regression tests.
- Baseline diagnostic documentation.

**Prohibitions**
- Modifying Gold compilers, independent oracles, matchers, or scoring weights.
- Relaxing Guard, permissions, or minimum aggregation policies to artificially inflate scores.
- Converting wrong answers into refusals to avoid semantic failures.

### Agent C: Documentation, Versioning & Protocol Design

**Responsibilities**
- Harmonize historical references across `ROADMAP.md`, `HANDOFF.md`, and `docs/task_format.md`.
- Clarify boundaries between legacy evaluator 0.5 and formal evaluator 0.6 / score protocol 1.0.
- Clarify that the sole release blocker is Docker runtime signing.
- Document designs for `validate_query_plan`, metric versioning, PostgreSQL capability matrix, and split generalization audits.
- Maintain an upgrade impact matrix mapping changes to protocol/evaluator/task/metadata versions.

**Permitted Modifications**
- `ROADMAP.md`, `HANDOFF.md`.
- `docs/*.md` and decision records.

**Prohibitions**
- Changing the 30 metric definitions.
- Modifying public/hidden data splits.
- Altering code protocols, scoring implementations, or SQL capabilities.

## 4. Integration Order and Unified Verification

Workstreams may proceed concurrently. Merge in the following sequence:

1. Merge Agent B (Baseline enhancements and regression tests), verifying security boundaries remain unchanged.
2. Merge Agent C (Documentation and protocol specifications).
3. Freeze the release branch against scoring, Gold, split, and Guard changes.
4. Merge Agent A (Docker runtime evidence).
5. Execute end-to-end verification under a single owner:

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
uv run c360 check-formal-release --input outputs/<final-formal-release>
```

## 5. Version Roadmap

### v1.0.0: Formal Release Closure
- Offline DuckDB-only benchmark; no new semantic features.
- All eight RC gates signed with verified cryptographic evidence.
- Full Linux CI pass: ruff, pytest, doctor, and formal release audit.
- Tagged `v1.0.0` following human maintainer review.

### v1.1: Baseline & Diagnostic Observability
- Enhanced filter field parsing and constrained Join planning in Baseline.
- Fine-grained failure categorization (metric/filter/time/join).
- Regression coverage for multi-turn clarifications and refusals.
- Three-layer split generalization auditing (`c360 audit-splits`).

### v1.2: Metadata and Metric Evolution
- `validate_query_plan` capability matrix and stable rejection codes.
- Metric versioning, deprecation lifecycle, and migration audits (`c360 audit-metadata`).
- Regression fixtures for column renames, metric deprecations, and business aliases.
- Explicit task manifest binding to prevent metadata drift.

### v1.3: Performance & Multi-Engine Adaptation
- PostgreSQL capability matrix and execution gateway adapter (`c360 transpile-sql`).
- Cross-engine equivalence fixtures for dates, decimals, null ordering, and permissions.
- Stable performance benchmarks on Standard and Large datasets.

### v2.0: Optional Platform Extensions
Subject to future strategic decisions:
- External model APIs and vendor SDKs.
- FastAPI evaluation services.
- OS-level sandboxing for untrusted Python code.
- Online leaderboards and multi-engine formal competitions.

## 6. Permanent Invariants

- Never commit real customer data, production credentials, or real PII.
- Never use an LLM as Gold or as the final judge.
- Never mask empty results, truncations, policy denials, or crashes as successes.
- Never claim unverified snapshots or candidate releases as formal releases.
- Never disable SQL Guard, authorization checks, minimum aggregation, or masking for score gains.
