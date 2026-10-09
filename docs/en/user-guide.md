# Customer360 User Guide

[English](user-guide.md) | [简体中文](../user-guide.md)

For users who want to **install, generate synthetic data, run Agents, and inspect evaluation reports**. For agent development conventions, see [AGENTS.md](../../AGENTS.md). For architectural trust boundaries, see [architecture.md](architecture.md). For formal v1.0 release criteria, see [formal-release.md](formal-release.md).

This project is a reproducible, secure-by-default, **local and offline** Agent benchmark—not an online question-answering service, nor a leaderboard.

Current protocol: package `1.0.0`, formal evaluator `0.6`, score protocol `1.0`. The `v1.0.0` release tag requires all eight RC gates to be cryptographically signed (in this repository `docker_runtime` may still be unsigned). Online ranking is permanently disabled.

## 1. Three Golden Rules

1. **The output directory must not already exist.** Commands will not overwrite existing directories. To rerun, specify a fresh path such as `outputs/tiny-2`.
2. **Always use `uv run`.** Do not invoke system `python` or `pytest`, which might resolve to different environments.
3. **Separate public inputs from trusted oracles.** Agents only receive the prompt, authorized public metadata YAML, and controlled tools. `pack.json`, `generated_oracles.yaml`, `hidden_oracles.yaml`, `data/trusted/`, Gold SQL, and hidden random seeds must never be provided to the evaluated Agent, nor packaged into wheels or images.

CLI Exit Codes:

| Code | Meaning |
|---|---|
| 0 | Command succeeded, and acceptance criteria were satisfied |
| 1 | Execution finished, but acceptance checks failed (e.g., `semantic_passed=false` or hard gate failures) |
| 2 | Invalid arguments, paths, contracts, or environment error; no publishable artifacts were generated |

## 2. Installation

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). Windows PowerShell and Unix-like shells use identical `uv` syntax.

From the repository root:

```bash
uv sync --locked
uv run c360 --help
uv run c360 version-info
uv run c360 doctor
```

Expected `doctor` diagnostic output: roughly `tables=9`, `columns=72`, `metrics=30`, `join_paths=20`, `executable_join_paths=1`, `foreign_keys=8`, `glossary_entries=111`.

When installed from a built wheel, `c360 doctor` and `c360 smoke` do not require the repository source tree or `configs/benchmark.yaml`. The following tasks still require repository files: `generate-data`, `coverage-report`, `check-rewrites`, `build-gold`, `replay-variant`, and evaluations with trusted oracles.

On Linux, execution via Docker is supported (non-root, read-only rootfs, zero-network). The Windows native/uv path remains fully supported. See Section 9 for Docker usage.

## 3. Five-Minute Sanity Check

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 coverage-report --dataset outputs/tiny-local --output outputs/coverage-local
uv run c360 smoke --output outputs/smoke-local
```

Understanding the outputs:

- Tiny dataset: 100 customers, 2,000 transactions, 7 asset valuation dates, 365 calendar days. Generates `dataset.duckdb`, `manifest.json`, `quality_report.json`, and `generation_config.json`. If any of the 60 data quality assertions fails, the manifest is not published.
- `coverage-report`: Evaluates against the **20 public human cases**. Expected output: `coverage_passed=true`, `m2_complete=false`. This is not a weighted composite score.
- `smoke`: Evaluates 3 valid SQL queries (must pass), 1 incorrect SQL (must fail), and 1 dangerous SQL (must be blocked). `verification_passed=true` indicates architectural integrity. Do not confuse 3/5 with agent accuracy, nor treat these 5 queries as benchmark cases.

By default, pytest only executes Tiny tests. Do not incorporate Large dataset generation into routine CI pipelines.

## 4. Workflows by Objective

Run all commands from the repository root. Paths can be customized, but do not reuse existing output directories.

### 4.1 Daily Development (20 Public Human Cases)

The 20 cases (`C360_0001–0020`) permanently belong to `split=dev` and are not hidden cases.

```bash
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 check-rewrites
uv run c360 run-case --case-id C360_0001 --agent baseline --dataset outputs/tiny-local --output outputs/case-0001
uv run c360 generate-variant --variant-id tiny_seed_43_distribution --output outputs/tiny-seed43
uv run c360 generate-variant --variant-id tiny_duplicate_fanout --output outputs/var-dup
uv run c360 generate-variant --variant-id tiny_null_empty_groups --output outputs/var-null
uv run c360 generate-variant --variant-id tiny_date_boundary --output outputs/var-date
uv run c360 evaluate --dataset outputs/tiny-local --distribution-variant outputs/tiny-seed43 --duplicate-variant outputs/var-dup --null-variant outputs/var-null --date-variant outputs/var-date --agent baseline --mode same_sql --output outputs/matrix-local
uv run c360 report --input outputs/matrix-local --format json
```

`evaluate --mode same_sql`: Calls the Agent once on the baseline, and then replays **the submitted candidate SQL** across the baseline plus all four variants. Using `--mode scoring` here will fail; historical matrix reports must record `scoring_applied=false`. Passing `--split private` will fail; use `evaluate-hidden` for the hidden set.

`replay-variant` replays only **Gold SQL** without invoking an Agent and does not produce a formal score.

### 4.2 Generating Public Task Packs (120 or 300)

```bash
uv run c360 generate-tasks --count 120 --seed 42 --output outputs/tasks-120
uv run c360 generate-tasks --count 300 --seed 42 --output outputs/tasks-300
uv run c360 check-isolation --pack outputs/tasks-300
```

| `--count` | Structure | Marker |
|---|---|---|
| 120 | Development pack | `m3_complete=true`, `m6_structure=false` |
| 300 | 180 train / 120 generated-dev | `m6_structure=true` |

Task IDs begin at `C360_1001`. Public YAML files contain only question prompts and paraphrases. `pack.json` and `generated_oracles.yaml` belong strictly to the trusted side. The `m6_structure` marker only verifies task count structure, not oracle verification.

### 4.3 Semantic Verification (Verifying Gold Oracles, Not Agent Score)

The 300-task pack must be verified against the four frozen public Tiny variants in a fixed order:

```bash
uv run c360 verify-pack --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --output outputs/verify-pack-local
```

For 120-task packs, `--variant` flags are optional and used for diagnostics.

Inspect `semantic_passed` in the public `summary.json`. Gold SQL, question definitions, and seeds are stored under `private/`. `semantic_passed` is not the weighted composite score described in ROADMAP Section 8.

### 4.4 Hidden Benchmark Set

Hidden tasks are **entirely new cases** (`C360_4001+`, `split=private`), not relabeled dev cases.

```bash
uv run c360 generate-hidden --public-pack outputs/tasks-300 --count 30 --output outputs/hidden-pack
uv run c360 generate-hidden-data --seed 1042 --output outputs/hidden-tiny
uv run c360 check-isolation --pack outputs/tasks-300 --hidden outputs/hidden-pack
uv run c360 verify-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --output outputs/verify-hidden-local
uv run c360 generate-hidden-variants --dataset outputs/hidden-tiny --output outputs/hidden-variants
```

`generate-hidden-data` explicitly rejects seeds 42 and 43. Hidden datasets must include `hidden_profile.json`. `verify-hidden` checks only the baseline and rejects public variants.

Informal hidden evaluation:

```bash
uv run c360 evaluate-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --agent baseline --output outputs/hidden-eval
```

Formal hidden evaluation (Agent called once on baseline; same-SQL replayed across 4 private variants):

```bash
uv run c360 evaluate-hidden --dataset outputs/hidden-tiny --pack outputs/hidden-pack --formal --variant outputs/hidden-variants/hidden_distribution --variant outputs/hidden-variants/hidden_duplicate_fanout --variant outputs/hidden-variants/hidden_null_empty_groups --variant outputs/hidden-variants/hidden_date_boundary --agent baseline --output outputs/hidden-eval-formal
```

The four `--variant` flags must strictly follow the order: distribution, duplicate, NULL, date. The public summary strips prompts, Gold, specs, candidate SQL, and hidden seeds.

### 4.5 Formal Local Scoring

Scoring subjects:

- public_dev = the **120 generated-dev tasks** from the 300 pack (excludes 20 human cases and 180 train cases)
- private_hidden = the independent hidden pack (default 30 tasks)

```bash
uv run c360 evaluate-public --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --agent baseline --output outputs/eval-public
uv run c360 score --public-report outputs/eval-public --hidden-report outputs/hidden-eval-formal --agent baseline --output outputs/score-local
```

`evaluate-public` and `evaluate-hidden --formal` produce `private/formal_input.json` (evaluator protocol 0.6). Legacy matrix reports from `evaluate` cannot be fed to `score`.

`c360 score` outputs separate reports for public_dev and private_hidden. `ranking_enabled=false` and the two scorecards are never merged. Weights: Correctness 45%, Safety 20%, Interaction 15%, Efficiency 15%, Robustness 5%. Token consumption and scan volumes are reported as `unavailable` rather than 0.

Hard Gates (if any fails, `score` exits with code 1, but still writes the report): `integrity`, `p0_safety`, `robustness_coverage`, `nonempty_denominators`. Agent accuracy ≥90% and P95 latency are diagnostic targets, not hard gates.

Negative control (WrongAgent must fail hard gates / scoring):

```bash
uv run c360 evaluate-public --dataset outputs/tiny-local --pack outputs/tasks-300 --variant outputs/tiny-seed43 --variant outputs/var-dup --variant outputs/var-null --variant outputs/var-date --agent wrong --output outputs/eval-wrong
```

### 4.6 Performance Benchmarking (Non-Scoring)

Resource budgets are bound to dataset scale and cannot be chosen by the Agent. Tiny caps materialization at **10,000** rows per table.

```bash
uv run c360 perf-baseline --dataset outputs/tiny-local --workload gold-execute --output outputs/perf-tiny
uv run c360 perf-baseline --workload generate --scale standard --seed 42 --dataset outputs/standard-local --output outputs/perf-std-gen
uv run c360 perf-baseline --dataset outputs/standard-local --workload gold-execute --output outputs/perf-std-gold
```

`--workload scoring` will fail. Public summaries omit prompts, Gold, SQL, and seeds. Data scan volume and tokens are unavailable. Large scale executes only upon explicit user request.

### 4.7 Release Candidate vs. Formal Release

Scoreless candidate (Docker, hidden files, and composite scores are excluded):

```bash
uv run c360 prepare-release --output outputs/release-candidate --public-pack outputs/tasks-300 --hidden-pack outputs/hidden-pack
uv run c360 check-release --input outputs/release-candidate
```

For the formal v1.0 release workflow, the eight RC gates, and the Docker smoke checklist, refer to [formal-release.md](formal-release.md). File presence does not imply gate satisfaction. Never populate a fake digest or tag `v1.0.0` when `docker_runtime` remains unsigned.

## 5. Directory Layout of Outputs

Synthetic dataset:

```text
outputs/tiny-local/
  dataset.duckdb
  manifest.json
  quality_report.json
  generation_config.json
```

Generated public task pack:

```text
outputs/tasks-300/
  pack.json                 # Trusted comprehensive blueprint
  public_cases.yaml         # Agent-visible prompts
  generated_oracles.yaml    # Trusted side, excluded from wheels
  isolation.json
```

Hidden task pack:

```text
outputs/hidden-pack/
  pack.json
  agent_cases.yaml
  hidden_oracles.yaml
  isolation.json
```

Evaluations and scores (Public / Private separation):

```text
outputs/eval-public/
  private/formal_input.json
  public/summary.json
outputs/score-local/
  private/score.json
  public/summary.json
```

Only files in `public/` are meant for external consumption. Private JSONL, Gold SQL, and candidate SQL must remain on the evaluator host.

## 6. Agent Identifiers

| `--agent` | Description |
|---|---|
| `baseline` | Official local Baseline: offline deterministic planner, does not read Gold |
| `template` | Protocol-driven mock agent for testing integration, **not** the official baseline |
| `wrong` | Negative control that deliberately fails |
| `gpt` / `openai` / `anthropic` / `network` / `llm` | Fails immediately: external models are rejected (fail-closed) |

Custom Agent implementation: Implement `Agent.respond(request, tools)` (see `src/customer360/agent/protocol.py` and the comprehensive [Agent Integration Guide](agent-integration-guide.md)). Available tools: `execute_sql`, `search_tables`, `search_columns`, `search_metrics`, `get_table_schema`, `get_metric_definition`, `get_business_glossary`, `get_join_paths`, `validate_query_plan`. Must execute as local trusted Python; CLI does not load arbitrary plugin scripts. Search results are pre-filtered based on authorized tables and columns.

A successful response requires: protocol state `success`, valid execution receipt, SQL matching receipt execution, and result matching reference. Emitting only a natural language sentence scores zero.

## 7. CLI Command Reference

For exhaustive parameter lists, run `uv run c360 <command> --help`.

| Command | Function |
|---|---|
| `version-info` | Package and protocol versions |
| `doctor` | Self-check catalogs, metrics, and join paths |
| `schema` | Export DuckDB DDL from catalog |
| `create-fixture` | 6-customer toy fixture (not Tiny) |
| `generate-data` | Synthetic data generation (Tiny / Standard / Large) |
| `generate-variant` | Generate one of the four frozen Tiny variants |
| `smoke` | Architectural smoke test (3 valid + 1 invalid + 1 dangerous SQL) |
| `coverage-report` | 20 human cases coverage analysis (non-scoring) |
| `check-rewrites` | Verify paraphrase slots for 20 human cases |
| `replay-variant` | Replay Gold SQL across data variants |
| `build-gold` | Generate private Gold for 20 human cases |
| `generate-tasks` | Generate public task packs (120 or 300) |
| `check-isolation` | Verify family / split isolation |
| `run-case` | Execute single human case |
| `evaluate` | Matrix evaluation for 20 human cases (non-scoring) |
| `report` | Generate sanitized public matrix report |
| `generate-hidden` | Generate independent hidden task pack |
| `generate-hidden-data` | Generate hidden Tiny dataset (default seed 1042) |
| `generate-hidden-variants` | Generate four private hidden variants |
| `verify-pack` / `verify-hidden` | Semantic verification of Gold oracles |
| `evaluate-public` | Evaluate generated-dev 120 tasks, emitting formal_input |
| `evaluate-hidden` | Evaluate hidden tasks; `--formal` emits formal_input |
| `score` | Calculate separate public_dev and private_hidden scorecards |
| `build-score-inputs` | Consolidate two formal_input summaries |
| `perf-baseline` | Collect latency and runtime metrics |
| `prepare-release` / `check-release` | Build / verify scoreless release candidate |
| `bind-rc-evidence` | Bind raw evaluation reports into RC evidence |
| `prepare-formal-release` / `check-formal-release` | Manage and audit the eight v1.0 RC gates |

Unimplemented commands will fail cleanly with an error message rather than silently reporting success.

Dataset Scales:

| `--scale` | Customers / Transactions | Default Budget |
|---|---|---|
| `tiny` | 100 / 2,000 | 10k rows/table, 15s timeout, 128MB memory |
| `standard` | 10,000 / 300,000 | 400k rows/table, 60s timeout, 512MB memory |
| `large` | 100,000 / 3,000,000 | 4M rows/table, 180s timeout, 1024MB memory |

Supported SQL Features: Single-table aggregations, `active_customer_count` grouped by `region`, self-join with MAX on `latest_total_asset`, and single join `customer_transactions`. CTEs, window functions, and other join topologies will be rejected by SQL Guard. Permissions are enforced by the gateway prior to aggregation.

## 8. Common Errors and Troubleshooting

| Symptom | Cause |
|---|---|
| Directory already exists / WinError 183 | Target output path must be fresh |
| `evaluate --mode scoring` fails | Formal scoring requires `c360 score`; legacy switch is disabled |
| `evaluate --split private` fails | Dev cases cannot be relabeled; use `evaluate-hidden` |
| `score` reports not `formal_input` | Must provide outputs from `evaluate-public` and `evaluate-hidden --formal` |
| `generate-hidden-data` rejects seed | Do not use seed 42 or 43 |
| `verify-pack` requires 4 variants | 300-pack verification requires four `--variant` flags in fixed order |
| `INPUT_LIMIT` | Materialized rows exceeded scale limit (not scan volume) |
| `POLICY_INCOMPATIBLE` | Zero-contribution Gold blocked by minimum aggregation threshold, not Agent error |
| Network-based `--agent` fails | External network models are disabled by default |
| `check-formal-release` fails only on `docker_runtime` | Real Docker smoke test has not run; do not forge digest |

## 9. Docker Execution

The container executes under user `c360` (UID 10001). Verification requires read-only root filesystem and disabled network:

```bash
docker build -t c360:local .
docker run --rm --read-only --network=none --user 10001 c360:local doctor
docker run --rm --read-only --network=none --user 10001 c360:local smoke --output /tmp/smoke-local
```

Do not bake private data, hidden packs, or trusted oracles into images. If needed, inject them via **explicit read-only mounts**. See [formal-release.md](formal-release.md) for full RC instructions.

## 10. Rules & Prohibitions

- Do not reclassify `C360_0001–0020` as train, test, private, or hidden.
- Do not call TemplateAgent the official Baseline.
- Do not compile the 19 `metadata_only` Joins into SQL Guard.
- Do not disable SQL Guard, authorization checks, masking, or row limits.
- Do not use LLMs as Gold or final arbiters.
- Do not package hidden packs or trusted oracles into wheels, sdists, or Docker images.
- Do not remove the default 10k row cap for Tiny, or treat 0 as infinity.
- Do not generate Large datasets in default pytest runs.
- Do not claim family isolation implies "no template, metric, or join ever appeared in the public set".
- Do not report scan volume or token count as 0.
- Do not commit `outputs/`, `tmp-formal-*`, hidden packs, or `*.duckdb` to GitHub.

## 11. Additional Documentation

| Document | Description |
|---|---|
| [README.md](../../README.md) ([English](../../README_EN.md)) | Project entry point and quickstart |
| [Agent Integration Guide](agent-integration-guide.md) ([中文](../agent-integration-guide.md)) | Custom agent protocol, interface contracts, and evaluation examples |
| [AGENTS.md](../../AGENTS.md) | Agent development and safety defaults |
| [HANDOFF.md](../../HANDOFF.md) | Current implementation and next steps |
| [ROADMAP.md](../../ROADMAP.md) | Milestones and scoring protocols |
| [architecture.md](architecture.md) ([中文](../architecture.md)) | Trust boundaries and components |
| [data_dictionary.md](data_dictionary.md) ([中文](../data_dictionary.md)) | Nine-table schema definitions |
| [task_format.md](task_format.md) ([中文](../task_format.md)) | Public/private contracts and task DSL |
| [decisions.md](decisions.md) ([中文](../decisions.md)) | Architectural decision records |
| [formal-release.md](formal-release.md) ([中文](../formal-release.md)) | Eight RC gates for v1.0 release |
| [github-publish.md](github-publish.md) ([中文](../github-publish.md)) | Pre-open-source checklist & CI artifacts |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | Pull request and public tree rules |
| [SECURITY.md](../../SECURITY.md) | Vulnerability disclosure policy |
| [development-plan.md](development-plan.md) ([中文](../development-plan.md)) | Phased development plan |
