# GitHub 公开发布清单

面向要把本仓库推到 **公开 GitHub** 的维护者。日常使用见 [user-guide.md](user-guide.md)。打 `v1.0.0` 仍须满足 [formal-release.md](formal-release.md) 的八个 RC 门。

本机可以先把文件准备好。不要伪造 Docker digest，也不要在未签署 `docker_runtime` 时打 `v1.0.0`。

## 1. 公开树 vs 永远不要上传

**会进入 GitHub 的内容（预期）：**

- `src/`、`tests/`、`configs/`、`docs/`、`.github/`
- `data/trusted/human_oracles.yaml`（仅 C360_0001–0020 的公开 human case Gold）
- Apache-2.0：`LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`
- 社区文件：`CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、`CITATION.cff`
- 锁文件：`pyproject.toml`、`uv.lock`、`.python-version`、`Dockerfile`

**不要 `git add`、不要放进 wheel/sdist/镜像：**

| 路径 | 原因 |
|---|---|
| `outputs/` | RC 评测、隐藏 Tiny、私有 JSONL |
| `tmp-formal-*`、其它 `tmp-*/` | 含 hidden pack / Gold 的本地试验目录 |
| `dist/`、`dist-ci/`、`dist-m2-final/` | 构建产物；用 CI 或 `uv build` 再生成 |
| `data/hidden/` | 隐藏数据 |
| `*.duckdb` | 生成库 |
| `.env`、密钥、真实客户数据 | 本项目不需要生产凭证 |
| `hidden_oracles.yaml`、`hidden_profile.json`、`generated_oracles.yaml` | 可信侧；生成题包留在本地 `outputs/` |

`data/trusted` 在**源码仓库**里是故意留下的，方便克隆后跑 20 道 human case 的 coverage/Gold；它**不会**进 wheel/sdist/Docker。不要把隐藏集写进这个目录。

当前工作区里的 `outputs/rc-hidden-*`、`tmp-formal-release*` 含真实 hidden case，依赖 `.gitignore` 的 `outputs/`、`tmp-*/`、`*.duckdb`。推送前必须用 `git status` 确认它们未被暂存。

## 2. 推送前本地检查

```bash
uv sync --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
uv run c360 doctor
```

Windows PowerShell 同样使用上述 `uv` 命令。不要用系统里其它 Python。

## 3. 建立 git 仓库

若工作区已有 `git init -b main` 且公开文件已暂存，跳过 init，直接审查 `git status`。否则在仓库根目录：

```bash
git init -b main
git add -A
git status
```

`git status` 里**不应**出现：`outputs/`、`tmp-formal-`、`*.duckdb`、`dist/` 下的 wheel、`.venv`、`.env`。若出现，停下来改 `.gitignore`，不要提交。

建议首条提交信息：`Initial public snapshot of Customer360 Agent Benchmark.`  
不要在第一条提交里打 `v1.0.0` 标签。

本清单不代替你填写 GitHub 上的 owner、仓库名和远程 URL。没有真实仓库地址时，不要在 `pyproject.toml` 里写虚构 Homepage。

## 4. 创建 GitHub 仓库时的推荐设置

- 可见性：Public
- 不要用 GitHub 自动添加的第二份 LICENSE/README 覆盖本仓库文件
- 启用 Issues
- 启用 **Private vulnerability reporting**
- 不要启用会把私有评测结果贴上去的 Wiki，除非有单独审阅
- 说明（About）：`Local offline Agent benchmark over synthetic Customer360 data. Not a leaderboard.`
- Topics 建议：`benchmark`、`agent`、`evaluation`、`nl2sql`、`duckdb`、`apache2`
- 默认分支：`main`
- 分支保护（建议）：`main` 必须通过 `customer360-ci`；禁止直接 push 已签署标签以外的 force-push

公开仓库：https://github.com/Chr0nixz/Customer360

```bash
git remote add origin https://github.com/Chr0nixz/Customer360.git
git branch -M main
git push -u origin main
```

`pyproject.toml` 的 `[project.urls]` 与 issue 模板 `contact_links` 已指向该仓库。之后再改这些字段会改变 sdist 元数据，需要重新 `uv build` 并重绑 `public_artifacts` / `reproducible_build`。

## 5. CI 会做什么

`.github/workflows/ci.yml`：

1. `public-tree`：拒绝已跟踪的 duckdb / hidden oracle / `outputs/` / `tmp-formal-*`
2. Linux：`uv sync --locked`、ruff、pytest、`uv build`、源码目录外 doctor/smoke
3. Windows：锁依赖、ruff、pytest、CLI smoke
4. Docker：非 root、`--read-only --network=none` 跑 `c360 doctor`，并把 **image Id** 写成 `DockerRuntimeEvidence` 工件

Docker 工件不是自动签署的 v1.0.0。维护者下载 `docker-runtime-evidence` 后，用 `prepare-formal-release --docker-smoke-report ...` 绑定。digest 必须是 `sha256:` + 64 位十六进制；不要填 `sha256:abc123`。本地 `docker inspect --format='{{.Id}}'` 即可；`RepoDigests` 只有 push 到 registry 之后才有。

## 6. 仍然不要在这一步做的事

- 打 `v1.0.0`（八个 RC 门未全部签署前禁止）
- 把 hidden pack 或 RC 私有报告推进 GitHub
- 开启官方在线排名（`ranking_enabled` 永久 false）
- 接入未在 ROADMAP 第 10 节许可的模型 API
- 把 TemplateAgent 写成官方 Baseline
- 把 README 徽章指到别的仓库

`v1.0.0` 的命令顺序仍以 [formal-release.md](formal-release.md) 为准：Linux/CI 签署 `docker_runtime` → 用含本批文档的树重新 `uv build` → `check-formal-release` 为 true → 维护者打标签。
