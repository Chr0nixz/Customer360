# Customer360 Architecture and Operational Handoff

[English](HANDOFF_EN.md) | [简体中文](HANDOFF.md)

> The active plan as of 2026-10-18 is [Development Plan](docs/en/development-plan.md), WP-01–WP-07. Local full Tiny regression: 466 passed and five PostgreSQL live skips. Artifact integrity, experimental-engine safety, Dev coverage, and same-revision RC evidence remain open. The existing v1.0.0 tag belongs to a historical revision; dated entries below do not certify current main or additional released versions.

## 1. Taking Over

For command execution, see the [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)). For v1.0 formal release procedures, see [Formal Release](docs/en/formal-release.md) ([中文](docs/formal-release.md)). The pack semantic verification report protocol remains at **0.2**, the formal score protocol is at **1.0**, and the formal evaluator protocol is at **0.6**. Legacy 0.5/no-score reports are preserved as historical evidence and cannot be converted into formal scorecards. Four private hidden variants with provenance and same-SQL replay, `score`/`build-score-inputs`, Apache-2.0, Docker, SHA256/SBOM, and `prepare-formal-release`/`check-formal-release` are fully implemented.

The current implementation encompasses:
- M0 technical baseline and public fixture end-to-end loop;
- T1 Tiny generator and M1 Standard/Large scales;
- T2a metadata search and discovery;
- T2b 10 single-table metrics;
- T3 Tiny boundary probes and independent Python calculation oracles;
- T4 Linux CI and packaging regression;
- M2 Gold, answer/clarification/refuse evaluations, constrained join, versioned 20 dev cases, paraphrase semantic checks, four Tiny variants, and public/trusted physical separation;
- M4-01 serializable multi-turn evaluator;
- Phase C / M3 30 metrics, 20 audited join paths, semantic family / split isolation, and 120 generated cases;
- Phase D / M4 matrix evaluation (single candidate SQL replayed across baseline + 4 variants via same_sql; agent_rerun tracked separately; private JSONL decoupled from sanitized public reports);
- Phase E / M5 official local Baseline with pluggable model adapter;
- Phase F / M6 independent hidden pack, isolated Tiny, 300 public generated cases, and release candidate manifests;
- Phase S semantic verification for generated and hidden packs (300 cases enforce 4 frozen Tiny variants, hidden verification is baseline-only, policy statuses audited via real execution gateway);
- Phase G controlled resource budgets and `c360 perf-baseline`;
- Formal scoring toolchain and Dockerfile. 7 of 8 RC gates are signed (v1.0.0 tag withheld until `docker_runtime` is signed on Linux CI). Region grouping and latest snapshot are supported in compiled Gold (D038/D039). `C360_0001–0020` permanently remain `split=dev`. TemplateAgent is not the official baseline.

**Protocol & Infrastructure Evolution (WP-01–WP-07, v1.1–v1.3)**:
- **WP-01–WP-07 Release Integrity & Stratified Dev**: Complete closure of release anti-tampering (recomputing SHA256 digests, symlink/path traversal defense, CycloneDX SBOM verification), PostgreSQL default fail-closed boundary with live fixture fix, 300-task 240/36/24 quota re-allocation (Train 150/18/12, Dev 90/18/12) with full metric and join coverage, and Baseline quality hardening.
- **v1.1 Multi-Turn Dynamic Clarification & Distractor Resistance**: Implemented `protocol_version: "1.1"`, optional `turn` tracking on `Message`, `SlotReply` counterfactual noise/distractor support (`distractor`, `distractor_role`), over-clarification guard, and `MAX_CLARIFICATION_TURNS = 4` fail-closed limit (`tests/test_v1_1_multiturn.py`).
- **v1.2 Query Plan Validation & Metadata Lifecycle**: Implemented controlled plan validation graceful degradation (`INVALID_PLAN_SCHEMA`), time column existence/authorization/date-type validation, `MetricDef` chronology constraints (`deprecation_date >= effective_date`), `BaselineAgent` refusal with `replaced_by` alternative guidance for `DEPRECATED_METRIC_REJECTED`, and complete foreign key closure auditing in `c360 audit-metadata` (`tests/test_v1_2_metadata_plan.py`).
- **v1.3 Cross-Engine Adaptation & Phase-Split Performance** (Commits `983851e`, `dfd2287`): Implemented statement-level AST parsing in `transpile_sql` to prevent false-positive string semicolon rejections, expanded `_FORBIDDEN_AST_NODES` to block ALTER, TRUNCATE, MERGE, TRANSACTION, GRANT, REVOKE, and SET, closed the phase breakdown timing model in `QueryReceipt` and `ReceiptAudit` (`plan_ms`, `guard_ms`, `exec_ms`, `e2e_ms`), verified PostgreSQL fail-closed boundary with pre-connection SQL Guard, and added dedicated test suite `tests/test_v1_3_engine_adaptation.py`. All 154 files pass Ruff check/format, and 369 non-slow tests pass.
- **2026-10-19 Remote CI Full Green Verification & Cross-Engine Live Integration** (Run ID: `39257741810`, Commit `6ba59a9`):
  1. Task pack generator rewrite decoupling: mapped missing metric clarification drafts to `t_clarify_metric` in `infer_template_id`, generating date-free and filter-free distinct drafts for `latest_total_asset`, satisfying 30-metric Dev coverage while strictly preserving date-free paraphrase invariants;
  2. PostgreSQL live multi-engine equivalence: fixed `compare_results` signature in `tests/test_postgres_live.py` with explicit `ComparisonPolicy`, and reused `guarded.output_kinds` in `PostgreSQLExecutionGateway` for strict 1:1 Schema parity;
  3. CI service container dynamic port & driver injection: bound dynamic mapped port `${{ job.services.postgres.ports[5432] }}` in GitHub Actions, and injected binary driver via `uv run --with "psycopg[binary]"` with connection pre-check;
  4. 100% All-Green CI completion: all 6 jobs (`public-tree`, `fast-gate-windows`, `fast-gate-linux`, `postgres-integration`, `docker`, and `full-release-gate-linux`) passed cleanly. The `docker` job successfully generated and archived the genuine `docker-runtime-evidence` artifact under non-root `--read-only --network=none` sandbox conditions.
- **2026-10-20 Formal Release v1.1.0 & Artifact Validation Hardening** (Commits `e2b71c3`, `d181e7c`):
  1. Formal release & version evolution: `pyproject.toml`, `src/customer360/__init__.py`, and `uv.lock` bumped to `1.1.0`; `FormalReleaseManifest` and `ReproducibleBuildEvidence` updated to accept and lock `1.1.0`; officially tagged and pushed annotated Git tag `v1.1.0`;
  2. Release distribution checker parameterization: `_formal_distributions`, `_distributions_in`, `_sbom_document`, and `public_artifacts_evidence` dynamically inspect `__version__`, removing historic hardcodings;
  3. Full documentation synchronization: `README.md`, `user-guide.md`, `formal-release.md`, and roadmaps aligned with package `1.1.0` and formal release status.
- **2026-10-20 Hidden Benchmark Expansion to 100 Cases & Stratification Quotas** (Commit `3e5b62a`, D064):
  1. Candidate pool capacity proof: with Public 300 and Human 20 blocked (320 families), 313 independent semantic families remain in candidate pool, safely supporting 100-case expansion;
  2. Scientific stratification quota: established `count >= 100` stratification quota (61 Answer / 23 Clarification / 16 Refusal), covering 26 distinct metrics and 100% of 8 required error classes;
  3. Semantic verification & Oracle closure: all 61 compilable answers pass 1:1 cross-checking with independent Python oracles on isolated Tiny data, 100% rewrites pass, all 8 error classes distinguished;
  4. Contract & testing hardening: `HIDDEN_DEFAULT_COUNT` and CLI default count updated to 100; added end-to-end regression `test_hidden_100_pack_stratified_and_isolated`.
- **2026-10-20 Local Offline Model Adapter & Strict Loopback Network Defense (D065)**:
  1. Local LLM endpoint support: implemented `LocalModelAdapter` and `create_local_model_agent` for local OpenAI-compatible inference servers (defaulting to `http://127.0.0.1:11434/v1`);
  2. Strict loopback defense: `assert_local_endpoint` enforces local loopback host whitelisting (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`), rejecting external network connections fail-closed;
  3. Purity & graceful degradation: in-method dynamic imports avoid static network dependencies in `agent` modules (preserving `_denied_imports` pureness); supports structured prompt injection and JSON intent extraction with graceful fallback; CLI and matrix evaluation accept `--agent local-model`;
  4. Dedicated test suite: added `tests/test_local_model_adapter.py` covering external blocking, Answer end-to-end, Clarify, Refusal, network fallback, and Agent resolution.
- **2026-10-20 Automated GitHub Release Pipeline & v1.1.0 Formal Publication**:
  1. Release pipeline: added `.github/workflows/release.yml` triggered on `v*.*.*` tag push and `workflow_dispatch`;
  2. Automatic build & checksum generation: builds distribution packages (`.whl`, `.tar.gz`) and computes `SHA256SUMS`;
  3. GitHub Release publication: uses `softprops/action-gh-release@v2` with `docs/releases/v1.1.0.md` release notes and uploaded distribution assets; first workflow run `39310579161` completed with 100% success ([Release Page](https://github.com/Chr0nixz/Customer360/releases/tag/v1.1.0)).
- **2026-10-20 v1.4 DSL Semantic Extensions & Deterministic Total Ordering for Ties (Top-K, D066)**:
  1. Contract extensions: extended `SemanticSpec` with `limit`, `order_by`, and `order_direction`, validating explicit ordering dependencies on limit queries;
  2. Deterministic total ordering for ties: compiler `compile_semantic` and independent Oracle `compute_independent` strictly enforce the total ordering tie-breaker rule ("primary DESC/ASC + group dimensions ASC"), eliminating cross-engine nondeterminism;
  3. Two-pass stable sorting: implemented two-pass stable sorting with decimal coercion in memory slices for exact limit truncation;
  4. Strict ordered parity verification: evaluator uses `ComparisonPolicy(ordered=True)` for strict ordered row parity; added dedicated test suite `tests/test_v1_4_dsl_topk.py` (5/5 passed).
- **2026-10-20 Local Offline LLM Evaluation, Mock Server & Benchmark Reporting (D067)**:
  1. Zero-dependency mock inference server: implemented `LocalInferenceServer` serving OpenAI-compatible `/v1/chat/completions`, `/v1/models`, `/health`, and CORS OPTIONS preflights; added CLI command `c360 serve-local-mock` with clean port error handling;
  2. Model prompt & parser hardening: enriched `LocalModelAdapter` prompt with filter columns, fixed filters, and source table metadata; added non-dict validation, safe string-digit coercion for `days`, and date deserialization with anchor fallback;
  3. Agent ID normalization: evaluator normalizes `local-model` to `local_model` conforming to Pydantic `Identifier` contract;
  4. End-to-end benchmark suite: added `tests/test_local_model_benchmark.py` (8/8 tests passed) validating CLI run-case, 20-case 4-variant matrix evaluation, HTML/Markdown report generation, CORS, and error fallback.
- **2026-10-20 Controlled Three-Table Composite Join & Set Intersection Oracle (Composite Join, D068)**:
  1. Controlled three-table join: implemented `customer_transactions_and_holdings` spanning `dim_customer`, `fact_transaction`, and `fact_holding` for distinct customer aggregations;
  2. SQL Guard defense: upgraded `_validate_join_query` to admit 1 or 2 INNER JOINs, strictly checking table permissions, alias conventions (`t`, `h`), and blocking Cartesian products;
  3. Independent Oracle set intersection: pure in-memory set intersection (`set_cust & set_tx & set_h`) matching DuckDB executed results 100%;
  4. Dedicated test suite: added `tests/test_v1_4_composite_join.py` (12/12 passed).
- **2026-10-20 Task Generator Synthesis Expansion for Top-K & Composite Joins (Generator Synthesis, D069)**:
  1. Task generator feature flag: `generate_task_pack` supports `include_v1_4: bool = False` (backward compatible by default), CLI command `c360 generate-tasks --v1-4`;
  2. Pool & contract enhancement: `_pool_drafts` incorporates composite joins and Top-K grouping drafts; `GeneratedCaseBlueprint` and `TrustedGeneratedOracle` extended with `limit`, `order_by`, and `order_direction` protected under `PRIVATE_ORACLE_FIELDS`;
  3. Paraphrase synthesis & audit: `_render` automatically synthesizes natural language and paraphrased rewrites, audited via `check_generated_rewrite`; `pack_verify` automatically injects `ComparisonPolicy(ordered=...)` strict row parity checking;
  4. Dedicated test suite: added `tests/test_v1_4_generator_expansion.py` (6/6 passed).

## 2. Completed vs. Uncompleted Status

| Component | Status / Evidence |
|---|---|
| Python Project & Deps | `pyproject.toml`, `uv.lock`, `.python-version`; `uv sync --locked` clean install |
| Shared Contracts | Public inputs/responses, 3 private oracle types, DSL, execution receipts, manifests, evaluation records; `GenerationConfig`/`DatasetManifest`/`QualityReport` |
| 9-Table Schema | Catalog in package, runtime DDL generation; PK, nullability, unique keys, 8 foreign keys |
| Public Fixture Sample | 6-customer toy fixture with normalized content digests and reproducible seed offsets |
| Tiny Data Generator | T1 complete: `configs/data_generation.yaml`, `synth/generator.py`, `synth/constraints.py`, `c360 generate-data`; 100 customers / 2,000 transactions / 7 valuation dates / 365 calendar days |
| Standard / Large Scales | Generation implemented: Standard 10k/300k, Large 100k/3M; zero-transaction/holding/occupation ≥ 5%/5%/3% (`standard-v2`/`large-v2`); Tiny content digests frozen |
| Data Quality Assertions | 60 independent named assertions executed on generation connection; failure halts manifest publication |
| Metadata & Discovery | 30 metrics, catalog/metrics consistency, 8 read-only FKs, 20 audited join paths (only `customer_transactions` executable), search tools, derived glossary; tools filter by grant |
| Gold Compiler | Single-table, single-metric, constrained filters, rolling / point-in-time / latest-snapshot; region grouping on `active_customer_count`; sole `customer_transactions` join; unsupported constructs fail-closed |
| Execution Gateway | AST whitelist, pre-aggregation authorized projection, minimum group size, subprocess timeout, result validation; typed literal chunked insertion |
| Agent Interfaces | Local `AgentProtocol`, SQL submission adapter, deterministic `TemplateAgent` (20-case test driver), official local `BaselineAgent` (offline planner); external network models fail-closed |
| Evaluation Loop | All 3 action paths runnable; evaluator 0.5/0.6 audits runtime failures, complete responses, receipts, slot consistency, and identities |
| M2 Baseline Dev Cases | Catalog 0.3: `resources/human_cases.yaml` has prompts only; `data/trusted/human_oracles.yaml` contains specs; 18 answerable cases + 2 clarification/refusal oracles; `C360_0001–0020` permanently `split=dev` |
| Paraphrase Checks | 60 fixed paraphrases pass regression; polarity validation rejects negated expressions |
| Data Variant Replay | Frozen seed 43 Tiny distribution variant; `c360 replay-variant` replays compiled SQL against independent Python oracle |
| Matrix Evaluation | 4 variant types replayed across verified data via same_sql; `agent_rerun` tracked separately; `scoring_applied=false` |
| Public / Trusted Separation | Agent-visible assets exclude expected actions, semantic specs, missing slots, and reason codes; `c360 doctor` and `smoke` run without trusted files |
| Multi-Turn Evaluator | Evaluator 0.5: multi-turn scripts, execution failure audits, full responses, specific policy rejections |
| Packaging & CI | `.github/workflows/ci.yml`: public tree leak checks, Ubuntu locked dependencies/ruff/pytest/`uv build`, Windows workflow, Docker read-only network-none doctor and image Id evidence; sdist whitelist |
| GitHub Open Source Prep | Apache-2.0, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue/PR templates, gitignore covering outputs/tmp/duckdb, `docs/github-publish.md` |
| Reporting | Manifests, records, summaries; separate private JSONL and sanitized public summaries |
| 300 Public Task Pack | `c360 generate-tasks --count 300`: 180 train / 120 dev; `m6_structure=true`; family/split isolation enforced |
| Independent Hidden Set | `c360 generate-hidden`: `C360_4001+`, `split=private`, family isolated from public/human cases; `generate-hidden-data --seed 1042` with `hidden_profile.json` |
| Pack Semantic Verification | `c360 verify-pack` / `verify-hidden`: independent oracle matches compiled SQL, differentiates 8 error SQLs, verifies paraphrases; 300 pack requires 4 frozen variants |
| Resource Budgets | D055: Tiny 10k row cap; Standard/Large named budget profiles (400k / 4M rows) with ATTACH projection; `c360 perf-baseline`; token/scan unavailable |
| Formal Score Protocol 1.0 | `c360 evaluate-public` / `evaluate-hidden --formal` emit formal inputs; `c360 score` produces separate public_dev and private_hidden scorecards |
| Formal RC Release Gates | 8 gates with cryptographic content validation; 7 of 8 locally signed; `docker_runtime` verified and archived as genuine artifact on CI (Run 39257741810) |
| v1.1 Clarification & Distractor | `protocol_version: "1.1"`, `Message.turn` tracking, `SlotReply.distractor` counterfactual noise injection, over-clarification guard, and `MAX_CLARIFICATION_TURNS = 4` (`tests/test_v1_1_multiturn.py`) |
| v1.2 Plan Validation & Metadata | Controlled validator `validate_query_plan` (9 rejection codes incl. `INVALID_PLAN_SCHEMA` and `time_column`), metric lifecycle (`deprecation_date >= effective_date`), static FK topology audit in `c360 audit-metadata` (`tests/test_v1_2_metadata_plan.py`) |
| v1.3 Engine Adaptation | SQLGlot transpilation (DuckDB <-> PostgreSQL), read-only AST defense (ALTER/TRUNCATE/MERGE blocked), multi-engine gateways, dual timeout reapers, phase performance sampling (`plan_ms`/`guard_ms`/`exec_ms`/`e2e_ms`), `c360 transpile-sql` (`tests/test_v1_3_engine_adaptation.py`) |
| WP-01–WP-07 Delivery | WP-01 baseline unified, WP-02 release integrity dynamic digests & path escape protection, WP-03 PostgreSQL fail-closed gateway & live fixture fixed, WP-04 Dev stratified 90/18/12 quotas & full metric/join coverage, WP-05–07 regression all-green |
| FastAPI / Remote Services / External Models | Out of scope for v1.0; network adapters fail-closed |

## 3. Verification Commands

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
uv run c360 check-rewrites
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 smoke --output outputs/smoke-local
```

For formal release checks:

```bash
uv run c360 check-formal-release --input outputs/rc-formal-release
```

## 4. Key Rules and Architectural Constraints

- Never commit real customer data, production secrets, real phone numbers, or government IDs.
- Never use an LLM directly as Gold SQL, Gold Answer, or the final arbiter.
- Never bypass or disable SQL Guard, authorization checks, result masking, or row limits.
- Never modify scoring rules, hidden test sets, or metric definitions to force a pass.
- Never package `data/trusted`, `data/hidden`, `outputs/`, or generated Gold into wheels, sdists, or Docker images.
- Unhandled errors must be classified into stable error categories.
