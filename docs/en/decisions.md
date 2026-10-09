# Architecture Decision Records (ADR)

[English](decisions.md) | [简体中文](../decisions.md)

Status: The following are the engineering default decisions adopted for the current architecture implementation. For v1.0 product defaults, see D057; remaining open questions are governed by ROADMAP Section 10. For CLI commands, see the [User Guide](user-guide.md).

| ID | Decision | Rationale & Implications |
|---|---|---|
| D001 | Single Python package, `src/` layout, `uv` locked dependencies, Python 3.11 | No immediate need for microservices or complex DI frameworks; FastAPI and cloud model SDKs are not bundled in v1.0. |
| D002 | Contracts strictly split into public schemas and private oracles; Agent depends only on public ports | Prevents leaking answers, full semantics, or authorization controls to evaluated agents. |
| D003 | `catalog.yaml` is the single source of truth for database schema; DDL generated at runtime | Keeps columns, permissions, DDL, and fixtures synchronized. Wheel packages public resources without repo directory dependencies. |
| D004 | Public 6-customer toy fixture used solely for pipeline sanity checks | Allows independent manual verification of ground truths (3, 4, 650.00). Must not be passed off as Tiny or benchmark cases. |
| D005 | Restrict SQL capability to a single-table aggregation whitelist | Simplifies permission enforcement; unwhitelisted syntax is explicitly rejected. Expansion requires re-auditing. |
| D006 | Candidate SQL executes exclusively within an isolated in-memory DB containing authorized row/column projections | Avoids relying on the Agent to remember `WHERE` clauses; prevents exposing the raw source database. |
| D007 | Subprocess worker spawned per query + parent wall-clock timeout | Cross-platform on Windows/Linux; startup latency is audited and not conflated with execution performance. |
| D008 | Data is CNY-only; amounts and quantities use fixed-precision Decimal | Prevents cross-currency addition errors. Multi-currency support requires new semantics and schema versioning. |
| D009 | Amounts/dates transmitted as typed strings; integers remain integers | Enables deterministic JSON serialization; floating-point approximations are avoided. |
| D010 | Default `min_group_size=1`; zero-customer aggregations are suppressed | Empty authorization scopes do not imply all customers; zero-contribution queries are recorded as `POLICY_INCOMPATIBLE`. |
| D011 | CLI exposes only implemented commands; no hollow stubs | Commands are implemented iteratively across milestones; missing commands fail-closed. |
| D012 | Retain 5-query sanity check (`smoke`) without computing composite scores | Strict separation between architectural conformance and formal Agent evaluation. |
| D013 | Bulk insertions in generator and workers use chunked typed literals (`synth/schema.render_literal`) | Avoids DuckDB `executemany` per-row latency overhead; typed literals enforce schema whitelists. |
| D014 | 60 named quality assertions executed during data generation; any failure halts manifest publication | Failed output directories are preserved for debugging; assertions are never relaxed to force a pass. |
| D015 | Closed customers may retain terminated non-primary service relations | Complies with business rules; semantic changes require updating the data dictionary and generator version. |
| D016 | Business glossary derived directly from catalog and metrics; no standalone `glossary.yaml` | Prevents divergent definitions; terms not in schemas or metrics cannot match queries. |
| D017 | v0.1 catalog strictly excludes `phone` and `id_card` columns | Differentiates "column does not exist" from "column exists but is restricted". |
| D018 | Valuation date metrics require explicit `point_in_time`; never compile to latest snapshot | `snapshot_total_asset` and `snapshot_net_asset` require single-day equality filters. |
| D019 | Independent Python oracle cross-verifies Tiny planning cases; coverage reports are non-scoring | Prevents shared errors between compiler and SQL engine; `m2_complete=false`. |
| D020 | Linux CI installs wheels outside source tree; sdist uses strict whitelist | `doctor` and `smoke` use packaged defaults; prevents committing private artifacts or outputs. |
| D021 | Clarification oracle executes one deterministic slot replay before checking final query | Verifies that asking the right question leads to the correct query after slot completion. |
| D022 | Gold assets generated via `build-gold` into an explicit private directory | Gold SQL and results are strictly trusted assets; never included in agent inputs or wheels. |
| D023 | Evaluator protocol bumped from 0.1 to 0.2 | Accommodates clarification replays and refusal reason code validations. |
| D024 | M2 enables only the `customer_transactions` join path | Customer filtering joined with transaction details deduplicated by `customer_id`. |
| D025 | Paraphrase semantic consistency checked via structured slot evidence, not LLM judges | Verified against canonical `SemanticSpec`; paraphrases are not Gold. |
| D026 | First Tiny data variant is seed 43 distribution; evaluated via same-SQL replay | Preserves seed 42 digest; does not count as full multi-variant formal score. |
| D027 | Public `human_cases.yaml` split from trusted `human_oracles.yaml`; catalog 0.3 | Task pack contains only prompts/paraphrases; semantic specs remain in repository `data/trusted`. |
| D028 | Evaluator bumped to 0.3: serializable multi-turn slot scripts + per-turn auditing | Freezes outcome/reason codes without premature scoring weights; gateway rejections cannot be overridden. |
| D029 | Tiny variant matrix consists of 1 distribution + 3 perturbation variants | Perturbations modify duplicate fanout, NULL empty groups, and date boundaries; `same_sql` distinct from `agent_rerun`. |
| D030 | Standard/Large scales frozen; Tiny ID widths do not expand dynamically | Tiny maintains `C001`/`T0001` with frozen seed 42 digest; Large generation excluded from default pytest. |
| D031 | SQL Guard validates entire AST whitelist before checking single-table/join subsets | AST checks cannot be bypassed by CTEs, subqueries, or function wrappers. |
| D032 | Trusted data verification shared across Gold, coverage, and variant runs | Recomputes catalog, row count, and content digests before execution; tampered data fails immediately. |
| D033 | `agent_rerun` mode requires injecting a standalone Agent | Orchestrator never injects Gold SQL into `SqlSubmissionAgent`; missing injection fails-closed. |
| D034 | Evaluator bumped to 0.4: execution failure audit trail + full responses | Audits `TIMEOUT`, `WORKER_CRASH`, and `EXECUTION_ERROR`; records task, metadata, and policy identities. |
| D035 | Paraphrase checks enforce polarity and negation | Negations (e.g. non-VIP, unsuccessful) cannot pass merely by keyword presence. |
| D036 | Empty aggregations aligned with D010; minimum granularity is never waived | If reference query triggers `AGGREGATION_TOO_SMALL`, evaluated as `POLICY_INCOMPATIBLE`. |
| D037 | Standard/Large reinstate ≥5%/5%/3% boundary populations | Validated against business ratios (`standard-v2`/`large-v2`); Tiny remains `tiny-v1`. |
| D038 | Grouping restricted strictly to `active_customer_count` grouped by `region` | Emits observed group keys + metric; does not zero-fill missing groups; unordered multiset matching. |
| D039 | `latest_total_asset` computes per-customer `MAX(snapshot_date <= anchor)` before summing | Missing snapshots are excluded; SQL uses self-join without window functions. |
| D040 | Semantic family fingerprint derived from template, metric, join, temporal semantics, and filters | Paraphrases share `family_id`; identical semantics must never cross train/dev/hidden splits. |
| D041 | Split isolation precedes task expansion; `C360_0001–0020` permanently assigned to `split=dev` | Dev cases cannot be relabeled as train, hidden, or challenge; hidden cases use new IDs (`C360_4001+`). |
| D042 | General `TaskPack` decoupled from frozen 20-case human pack | Public generation produces `pack_id=generated-m3-0.1` without altering human case verification. |
| D043 | 20 join paths counted by audited business paths; only `customer_transactions` executable | Other 19 paths are `metadata_only`; SQL Guard and compiler reject them in v1.0. |
| D044 | Matrix evaluation: candidate SQL submitted once on baseline replayed across 4 variants | Replays candidate SQL, not Gold SQL; `scoring_applied` remains false. |
| D045 | Private JSONL decoupled from sanitized public reports | Public reports omit Gold SQL, specs, candidate SQL, and raw result rows. |
| D046 | Applicable variants, execution stages, and failure reasons audited per case | Timeouts, crashes, and truncations must never be recorded as successful empty results. |
| D047 | Official Baseline is an offline deterministic planner + pluggable adapter | `BaselineAgent` uses public tools; external network models fail-closed until licensed. |
| D048 | Hidden set is an independent pack starting at `C360_4001` with `split=private` | Family IDs isolated from human/public cases; excluded from wheels and distributions. |
| D049 | Hidden data is a Tiny dataset with `hidden_profile.json` (default seed 1042) | Prohibits public seeds 42 and 43; missing profile cannot be used for hidden evaluation. |
| D050 | Public generated benchmark targets 300 independent semantic cases | `generate-tasks --count 300` splits into 180 train / 120 dev; `m6_structure=true`. |
| D051 | Release candidates include manifest and artifact isolation, excluding Docker/scores/hidden | `prepare-release` records versions and summaries without claiming formal scoring. |
| D052 | Phase F audit enforces fail-closed integrity checks | Sidecar manifests must match data; SQL Guard inspects all subqueries and literal types. |
| D053 | Evaluator record version bumped to 0.5 | Unhandled `QueryRejected` mapped to stable failure codes; `INPUT_LIMIT` audited explicitly. |
| D054 | Semantic verification decoupled from `m6_structure` | `semantic_passed` requires matching Python oracle, distinguishing 8 error queries, and passing variants. |
| D055 | Controlled resource budgets bound to dataset scale; Tiny 10k row cap preserved | Budgets: Tiny (10k rows/15s/128MB), Standard (400k rows/60s/512MB), Large (4M rows/180s/1024MB). Token and scan volume are `unavailable` rather than 0. |
| D056 | Variant contracts and hidden verification boundaries tightened | 300-pack verification requires four variants in fixed order; hidden verification is baseline-only. |
| D057 | v1.0 formal release freezes ROADMAP Section 8/10 defaults; RC gates require evidence | Local offline audit, `ranking_enabled=false`, public_dev and private_hidden never merged. Scoring weights: 0.45/0.20/0.15/0.15/0.05. Hard gates: integrity, p0_safety, robustness_coverage, nonempty_denominators. All 8 RC gates must be signed with evidence. |
| D058 | Public Git tree cleanly separated from distribution artifacts; CI records Docker image Id | Source repository includes community files and public `data/trusted` (20 cases only). Artifacts like `outputs/`, `*.duckdb`, hidden packs are gitignored. |

Before changing any defaults, document impacted contracts, versions, tests, and migration paths. In particular, core security defaults (D002, D005, D006) must remain intact.
