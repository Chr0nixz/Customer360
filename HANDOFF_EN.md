# Customer360 Architecture and Operational Handoff

[English](HANDOFF_EN.md) | [简体中文](HANDOFF.md)

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

**Protocol Evolution Closure (v1.1–v1.3)**:
- **v1.1**: 4-tuple fine-grained failure attribution (`contracts/diagnostics.py`, `evaluator/diagnostics.py`), `c360 audit-splits` generalization and orthogonality auditing, Baseline multi-turn clarification state machine, and offline HTML diagnostic dashboard.
- **v1.2**: Controlled query plan validation engine `validate_query_plan` (8 stable rejection codes), metric lifecycle management (`active`, `deprecated`, `retired`), Baseline pre-planning self-check interceptor, and `c360 audit-metadata` topology closure audit.
- **v1.3**: SQLGlot cross-engine transpiler (DuckDB <-> PostgreSQL), multi-engine gateway abstractions (`BaseExecutionGateway`, `DuckDBExecutionGateway`, `PostgreSQLExecutionGateway`), dual timeout process reapers, phase-split performance sampling (`plan_ms`, `guard_ms`, `exec_ms`, `e2e_ms` and P50/P90/P95/P99 percentiles), and `c360 transpile-sql` CLI.

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
| Formal RC Release Gates | 8 gates with cryptographic content validation; 7 of 8 signed; `docker_runtime` awaiting Linux CI run |
| v1.1 Diagnostics | 4-tuple failure attribution, `c360 audit-splits`, multi-turn clarification state machine, offline HTML dashboard |
| v1.2 Plan Validation | `validate_query_plan` (8 rejection codes), metric lifecycle (`active`/`deprecated`/`retired`), static topology audit (`c360 audit-metadata`) |
| v1.3 Engine Adaptation | SQLGlot transpilation (DuckDB <-> PostgreSQL), multi-engine gateways, dual timeout reapers, phase performance sampling (`plan_ms`/`guard_ms`/`exec_ms`/`e2e_ms`), `c360 transpile-sql` |
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
