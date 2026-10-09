# Contributing to Customer360 Agent Benchmark / 贡献指南

[English](#english) | [中文](#chinese)

---

<a name="english"></a>
## English

This is a **local, offline, auditable Agent benchmark**, not a ranking service and not an online NL-to-SQL demo. Please read this guide before submitting a pull request.

- **How to run commands:** [docs/en/user-guide.md](docs/en/user-guide.md) ([中文](docs/user-guide.md))
- **Agent integration guide:** [docs/en/agent-integration-guide.md](docs/en/agent-integration-guide.md) ([中文](docs/agent-integration-guide.md))
- **Agent development conventions:** [AGENTS.md](AGENTS.md)
- **Pre-publish checklist:** [docs/en/github-publish.md](docs/en/github-publish.md) ([中文](docs/github-publish.md))

### Priorities

1. Evaluation credibility & auditability
2. Precise business semantics
3. Safety enabled by default
4. Reproducibility
5. Straightforward integration and extensibility
6. Test volume, model tuning, and performance optimization last

Never disable SQL Guard, authorization checks, result masking, or row limits just to "make it run". Never use an LLM as Gold or as the final judge.

### Development Environment

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
```

Always use `uv run`. Output directories must not already exist; pick a new path when re-running. Pytest runs Tiny by default; do not put Large generation into routine CI.

### What Belongs in the Public Tree

| Allowed in Git | Never Commit |
|---|---|
| Source, tests, public catalogs/metrics, documentation | `outputs/`, `tmp-*/`, `dist/`, wheels/sdists |
| `data/trusted/human_oracles.yaml` (C360_0001–0020 only) | Hidden packs, `hidden_oracles.yaml`, `hidden_profile.json` |
| LICENSE / NOTICE / CI configurations | `*.duckdb`, `.env`, credentials, real customer data |

`data/trusted` exists solely to serve the 20 public human cases, enabling local coverage, Gold verification, and paraphrase checks. It is **not** the hidden set. Hidden cases (`C360_4001+`) must be generated locally in `outputs/` and remain gitignored.

### Pull Requests

1. Keep the scope focused on the task; do not arbitrarily alter scoring weights, Gold SQL, splits, or the SQL whitelist.
2. Synchronize DDL, metadata, tests, and documentation when adding columns, metrics, or Joins.
3. Modifying Gold requires justification and a version bump, not just changing the expected value.
4. Do not reclassify `C360_0001–0020` as hidden/private.
5. Do not label `TemplateAgent` as the official Baseline (the official baseline is `--agent baseline`).
6. Network models, FastAPI, PostgreSQL, and additional executable Joins are outside the v1.0 default scope.

PR descriptions must state: what was changed, why, and how to verify. Use `.github/PULL_REQUEST_TEMPLATE.md`.

### Security-Related Changes

The default-deny behavior of SQL Guard, permissions, result masking, and the execution gateway must not be weakened. If you discover a bypass vulnerability, do not open a public issue—follow [SECURITY.md](SECURITY.md).

### Code of Conduct

Participation is governed by the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

<a name="chinese"></a>
## 中文

本项目是一套**本地、离线、可审计的 Agent benchmark**，不是排行榜服务，也不是在线 NL-to-SQL 演示。提交 Pull Request 前请阅读本文件。

- **怎么跑命令：** [docs/user-guide.md](docs/user-guide.md) ([English](docs/en/user-guide.md))
- **Agent 接入与使用指南：** [docs/agent-integration-guide.md](docs/agent-integration-guide.md) ([English](docs/en/agent-integration-guide.md))
- **开发协作约定：** [AGENTS.md](AGENTS.md)
- **公开发布清单：** [docs/github-publish.md](docs/github-publish.md) ([English](docs/en/github-publish.md))

### 优先级

1. 评测可信
2. 业务语义明确
3. 安全默认开启
4. 结果可复现
5. 接入和扩展简单
6. 最后才是题量、模型效果和性能优化

不要为了“先跑起来”关闭 SQL Guard、权限检查、结果脱敏或行数限制，也不要用 LLM 当 Gold 或最终裁判。

### 开发环境

需要 Python 3.11 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
```

请用 `uv run`。输出目录必须还不存在；重跑请换新路径。默认 pytest 只跑 Tiny，不要把 Large 生成放进日常 CI。

### 公开树里可以有什么

| 可以提交 | 不要提交 |
|---|---|
| 源码、测试、公开 catalog/metrics、文档 | `outputs/`、`tmp-*/`、`dist/`、wheel/sdist |
| `data/trusted/human_oracles.yaml`（仅 C360_0001–0020） | 隐藏 pack、`hidden_oracles.yaml`、`hidden_profile.json` |
| LICENSE / NOTICE / CI 配置文件 | `*.duckdb`、`.env`、密钥、真实客户数据 |

`data/trusted` 只服务公开 20 道 human case，方便本地跑 coverage / Gold / 改写检查。它**不是**隐藏集。隐藏题（C360_4001+）必须由维护者在本地 `outputs/` 生成，且保持 gitignore。

### 拉取请求

1. 保持改动范围与任务一致；不要顺手改评分权重、Gold、split 或 SQL 白名单。
2. 新增字段/指标/Join 要同步 DDL、元数据、测试和文档。
3. 修改 Gold 必须说明原因并更新版本，不能只改期望值。
4. 不要把 `C360_0001–0020` 改标为 hidden/private。
5. 不要把 TemplateAgent 标成官方 Baseline（官方是 `--agent baseline`）。
6. 网络模型、FastAPI、PostgreSQL、额外可执行 Join 不在默认范围内。

PR 描述请说明：改了什么、为什么改、如何验证。模板见 `.github/PULL_REQUEST_TEMPLATE.md`。

### 安全相关改动

SQL Guard、权限、结果脱敏和执行网关的默认拒绝行为不能削弱。若发现可绕过的漏洞，不要开公开 Issue，请走 [SECURITY.md](SECURITY.md)。

### 行为准则

参与本仓库即表示同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
