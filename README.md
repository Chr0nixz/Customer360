# Customer360 Agent Benchmark

[![CI](https://github.com/Chr0nixz/Customer360/actions/workflows/ci.yml/badge.svg)](https://github.com/Chr0nixz/Customer360/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

本地、离线、默认可安全执行的 Agent benchmark：合成九表客户数据、结构化任务、受控 SQL 网关、官方 Baseline，以及分开的 public_dev / private_hidden 分数。不是在线问数服务，也不是排行榜。

**怎么用：** 请读 [使用说明](docs/user-guide.md)。  
**怎么改代码：** 请读 [AGENTS.md](AGENTS.md)、[CONTRIBUTING.md](CONTRIBUTING.md) 和 [HANDOFF.md](HANDOFF.md)。  
**怎么公开到 GitHub：** 请读 [GitHub 发布清单](docs/github-publish.md)。

当前协议：package `1.0.0`，formal evaluator `0.6`，score protocol `1.0`。八个 RC 门按证据内容签署；`docker_runtime` 未签过就不能打 `v1.0.0`。`ranking_enabled` 永久为 false。

## 最短验证

需要 Python 3.11 和 [uv](https://docs.astral.sh/uv/)。在仓库根目录执行：

```bash
uv sync --locked
uv run c360 doctor
uv run pytest -q
uv run c360 generate-data --scale tiny --seed 42 --output outputs/tiny-local
uv run c360 smoke --output outputs/smoke-local
```

输出目录必须还不存在。请用 `uv run`，不要用系统里其它 Python。`smoke` 是 3 条正确 SQL + 1 条错误 SQL + 1 条危险 SQL 的架构检查，不是正式成绩。

日常开发、300 题包、隐藏集、正式打分、Docker 和常见错误见 [使用说明](docs/user-guide.md)。

## 你会用到的命令

| 目的 | 命令 |
|---|---|
| 自检 | `c360 doctor`、`c360 smoke` |
| 生成 Tiny/Standard/Large | `c360 generate-data` |
| 20 道 human case | `c360 run-case`、`c360 evaluate`、`c360 coverage-report` |
| 公开 120/300 题 | `c360 generate-tasks`、`c360 verify-pack` |
| 隐藏集 | `c360 generate-hidden`、`c360 evaluate-hidden` |
| 正式本地分数 | `c360 evaluate-public`、`c360 score` |
| 性能（非分数） | `c360 perf-baseline` |
| 发布门 | `c360 prepare-formal-release`、`c360 check-formal-release` |

完整参数：`uv run c360 --help` 或 `uv run c360 <命令> --help`。未实现的命令会报错，不会假装成功。外部模型 agent 标识会 fail-closed。

## 不要做的事

- 把 `C360_0001–0020` 改标为 hidden
- 把 TemplateAgent 当成官方 Baseline（官方是 `--agent baseline`）
- 把 hidden pack 或 `data/trusted` 打进 wheel / 镜像
- 用 LLM 当 Gold 或最终裁判
- 关闭 SQL Guard、权限检查或行数上限
- 把 Token/扫描量报成 0
- 把 `outputs/`、hidden pack 或 `*.duckdb` 推进 GitHub

## 构建

```bash
uv build
```

wheel 只含运行代码和公开资源。sdist 用白名单，排除 `outputs`、`.venv`、`.private`、`.env`、`data/hidden`、`data/trusted`。克隆源码仓库会带上 `data/trusted`（仅 20 道公开 human case），但不要提交 `outputs/`、隐藏 pack 或 `*.duckdb`。

## 文档

| 文档 | 内容 |
|---|---|
| [使用说明](docs/user-guide.md) | 安装、命令、评测路径、常见错误 |
| [开发协作约定](AGENTS.md) | 安全默认、模块边界 |
| [贡献指南](CONTRIBUTING.md) | PR 与公开树范围 |
| [安全披露](SECURITY.md) | 漏洞私下报告 |
| [GitHub 发布清单](docs/github-publish.md) | 开源前检查项 |
| [交接与下一步](HANDOFF.md) | 已完成范围 |
| [路线图](ROADMAP.md) | 里程碑与评分协议 |
| [架构](docs/architecture.md) | 信任边界 |
| [数据字典](docs/data_dictionary.md) | 九表口径 |
| [任务格式](docs/task_format.md) | 公开/私有契约 |
| [决策记录](docs/decisions.md) | 工程默认值 |
| [正式发布](docs/formal-release.md) | v1.0 RC 八个门 |
| [后续开发计划](docs/development-plan.md) | 阶段计划 |

许可证：[Apache-2.0](LICENSE)。行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。隐藏 pack 和生成库不是 GitHub 公开制品；源码树中的 `data/trusted` 只覆盖 C360_0001–0020。
