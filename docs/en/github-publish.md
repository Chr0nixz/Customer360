# GitHub Public Publishing Checklist

[English](github-publish.md) | [简体中文](../github-publish.md)

For maintainers pushing this repository to **public GitHub**. For routine usage, see the [User Guide](user-guide.md). Tagging `v1.0.0` still requires satisfying all eight RC gates detailed in [formal-release.md](formal-release.md).

Prepare files locally first. Never forge Docker digests, and never tag `v1.0.0` while `docker_runtime` remains unsigned.

## 1. Public Tree vs. Never Upload

**Contents expected to enter GitHub:**

- `src/`, `tests/`, `configs/`, `docs/`, `.github/`
- `data/trusted/human_oracles.yaml` (Gold oracles for the 20 public human cases `C360_0001–0020` only)
- Apache-2.0 files: `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`
- Community files: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`
- Lock files and builds: `pyproject.toml`, `uv.lock`, `.python-version`, `Dockerfile`

**Do NOT `git add`, package into wheels/sdists, or bake into container images:**

| Path | Reason |
|---|---|
| `outputs/` | RC evaluation results, hidden Tiny datasets, private JSONL logs |
| `tmp-formal-*`, other `tmp-*/` | Local test workspaces containing hidden packs / Gold |
| `dist/`, `dist-ci/`, `dist-m2-final/` | Build artifacts; reproduce via CI or `uv build` |
| `data/hidden/` | Private benchmark datasets |
| `*.duckdb` | Generated database files |
| `.env`, credentials, real data | The project requires no production credentials or real PII |
| `hidden_oracles.yaml`, `hidden_profile.json`, `generated_oracles.yaml` | Trusted oracles; generated task packs belong in local `outputs/` |

`data/trusted` is intentionally preserved in the **source repository** to allow contributors to clone and run coverage, Gold compilation, and paraphrase checks on the 20 public human cases; it is **never** included in wheels, sdists, or Docker images. Never write hidden sets into this directory.

Verify using `git status` prior to pushing that `outputs/`, `tmp-*/`, and `*.duckdb` remain unstaged and ignored.

## 2. Pre-Push Local Checks

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
```

On Windows PowerShell, use the exact same `uv` commands. Do not invoke system Python interpreters.

## 3. Initializing the Git Repository

If the workspace already has `git init -b main` with public files staged, review `git status` directly. Otherwise, from the repository root:

```bash
git init -b main
git add -A
git status
```

`git status` must **not** display: `outputs/`, `tmp-formal-`, `*.duckdb`, wheels in `dist/`, `.venv`, or `.env`. If any appear, update `.gitignore` before committing.

Recommended initial commit message: `Initial public snapshot of Customer360 Agent Benchmark.`  
Do not tag `v1.0.0` on the initial commit.

## 4. Recommended GitHub Repository Settings

- Visibility: Public
- Do not overwrite repository files with GitHub's auto-generated LICENSE or README templates
- Enable Issues
- Enable **Private vulnerability reporting**
- Disable Wikis unless subject to strict review to prevent accidental trace disclosure
- Description (About): `Local offline Agent benchmark over synthetic Customer360 data. Not a leaderboard.`
- Recommended Topics: `benchmark`, `agent`, `evaluation`, `nl2sql`, `duckdb`, `apache2`
- Default branch: `main`
- Branch protection (recommended): `main` must pass `customer360-ci`; require signed tags for releases

Public repository target: https://github.com/Chr0nixz/Customer360

```bash
git remote add origin https://github.com/Chr0nixz/Customer360.git
git branch -M main
git push -u origin main
```

## 5. What CI Validates

`.github/workflows/ci.yml`:

1. `public-tree`: Fails if tracked `.duckdb`, hidden oracles, `outputs/`, or `tmp-formal-*` exist.
2. Linux: `uv sync --locked`, ruff, pytest, `uv build`, running `c360 doctor` and `smoke` outside the source directory.
3. Windows: Dependency lock, ruff, pytest, CLI smoke.
4. Docker: Runs `c360 doctor` as non-root with `--read-only --network=none`, and records the container **image Id** into a `DockerRuntimeEvidence` artifact. Leak scanning matches specifically `hidden_profile.json`, `hidden_variant_manifest.json`, `hidden_oracles.yaml`, `generated_oracles.yaml`, `data/trusted/`, and `*.duckdb`. Verifying evidence JSON requires `/app/.venv/bin/python`.

Default workflow runs with `PYTHONUTF8=1`. Pytest builds wheels dynamically if `dist/` is absent. The CLI entry point sets stdio to UTF-8 to prevent Windows cp1252 crashes on JSON output.

Docker artifacts do not automatically grant v1.0.0. Maintainers download `docker-runtime-evidence` and bind it via `prepare-formal-release --docker-smoke-report ...`. The digest must be `sha256:` followed by 64 hexadecimal digits.

## 6. Prohibited Actions at this Stage

- Do not tag `v1.0.0` before all eight RC gates are verified and signed.
- Do not push hidden packs or RC private evaluation traces to GitHub.
- Do not enable online ranking (`ranking_enabled` is permanently false).
- Do not connect unapproved external model APIs.
- Do not designate `TemplateAgent` as the official Baseline.
- Do not redirect README badges to other repositories.

The command sequence for tagging `v1.0.0` is specified in [formal-release.md](formal-release.md).
