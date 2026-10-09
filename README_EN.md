# Customer360 Agent Benchmark

[English](README_EN.md) | [简体中文](README.md)

[![CI](https://github.com/Chr0nixz/Customer360/actions/workflows/ci.yml/badge.svg)](https://github.com/Chr0nixz/Customer360/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

A local, offline, secure-by-default Agent benchmark featuring synthetic 9-table customer data, structured task DSL, controlled SQL gateway, an official Baseline, and strictly separated public_dev / private_hidden scores. Not an online question-answering service, nor a competitive leaderboard.

**Quick Start:** Read the [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)).  
**Custom Agent Integration:** Read the [Agent Integration & Usage Guide](docs/en/agent-integration-guide.md) ([中文](docs/agent-integration-guide.md)).  
**Development Conventions:** Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [HANDOFF.md](HANDOFF.md).  
**GitHub Publishing Checklist:** Read [GitHub Publishing Checklist](docs/en/github-publish.md) ([中文](docs/github-publish.md)).

Current protocol baseline: package `1.0.0`, formal evaluator `0.6`, score protocol `1.0`. All eight RC gates are verified by cryptographic evidence; `v1.0.0` cannot be tagged without a signed `docker_runtime`. `ranking_enabled` is permanently set to `false`.

## Quick Verification

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). Run from the repository root:

```bash
uv sync --locked
uv run c360 doctor
uv run pytest -q
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 smoke --output outputs/smoke-local
```

The output directory must not already exist. Always use `uv run` rather than system Python interpreters. Note that `smoke` executes an architectural sanity check (3 valid SQL queries + 1 incorrect SQL + 1 dangerous SQL) rather than formal scoring.

For daily development workflows, 300-task evaluation packs, hidden test sets, official scoring, Docker execution, and common troubleshooting, see the [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)).

## Commands Quick Reference

| Purpose | Command |
|---|---|
| Self-check | `c360 doctor`, `c360 smoke` |
| Generate Tiny/Standard/Large data | `c360 generate-data` |
| 20 public human cases | `c360 run-case`, `c360 evaluate`, `c360 coverage-report` |
| Public 120/300 task packs | `c360 generate-tasks`, `c360 verify-pack` |
| Hidden benchmark set | `c360 generate-hidden`, `c360 evaluate-hidden` |
| Official local scoring | `c360 evaluate-public`, `c360 score` |
| Performance diagnostics (non-scoring) | `c360 perf-baseline` |
| Formal release gates | `c360 prepare-formal-release`, `c360 check-formal-release` |

Full CLI parameters can be viewed via `uv run c360 --help` or `uv run c360 <command> --help`. Unimplemented commands fail with explicit errors rather than silently pretending success. Unregistered external model agents fail-closed.

## Rules & Restrictions

- Do NOT re-label `C360_0001–0020` as hidden/private cases.
- Do NOT use `TemplateAgent` as the official baseline (the official baseline is `--agent baseline`).
- Do NOT package hidden packs or `data/trusted` into wheels or container images.
- Do NOT use LLMs as Gold or as final arbiters.
- Do NOT disable SQL Guard, permission checks, or result row limits.
- Do NOT report token consumption or data scan volume as 0.
- Do NOT commit `outputs/`, hidden packs, or `*.duckdb` databases to Git.

## Building

```bash
uv build
```

The wheel artifact contains only runtime code and public resources. The sdist is strictly whitelisted to exclude `outputs`, `.venv`, `.private`, `.env`, `data/hidden`, and `data/trusted`. Cloning the repository includes `data/trusted` (covering only the 20 public human cases for local verification), but never commit `outputs/`, hidden test packs, or `*.duckdb` files.

## Documentation

| Document | Description |
|---|---|
| [User Guide](docs/en/user-guide.md) ([中文](docs/user-guide.md)) | Installation, commands, evaluation workflows, troubleshooting |
| [Agent Integration Guide](docs/en/agent-integration-guide.md) ([中文](docs/agent-integration-guide.md)) | Custom agent protocol, interface contracts, and evaluation examples |
| [Agent Collaboration](AGENTS.md) | Safety defaults, module boundaries, architectural constraints |
| [Contributing Guide](CONTRIBUTING.md) | PR guidelines and public tree scope |
| [Security Policy](SECURITY.md) | Responsible vulnerability disclosure |
| [GitHub Publishing](docs/en/github-publish.md) ([中文](docs/github-publish.md)) | Pre-open-source checklist and sanitization |
| [Handoff & Next Steps](HANDOFF.md) | Completed scope and operational handoff |
| [Roadmap](ROADMAP.md) | Milestones and scoring protocol definitions |
| [Architecture](docs/en/architecture.md) ([中文](docs/architecture.md)) | Trust boundaries and component dependencies |
| [Data Dictionary](docs/en/data_dictionary.md) ([中文](docs/data_dictionary.md)) | Nine-table schema definitions and business metrics |
| [Task Format](docs/en/task_format.md) ([中文](docs/task_format.md)) | Public/private schemas and DSL specifications |
| [Decision Records](docs/en/decisions.md) ([中文](docs/decisions.md)) | Engineering defaults and rationale |
| [Formal Release](docs/en/formal-release.md) ([中文](docs/formal-release.md)) | Eight RC gates for v1.0 release |
| [Development Plan](docs/en/development-plan.md) ([中文](docs/development-plan.md)) | Phased development plan |

License: [Apache-2.0](LICENSE). Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Hidden packs and generated database artifacts are not public distribution artifacts; `data/trusted` in the source repository only covers `C360_0001–0020`.
