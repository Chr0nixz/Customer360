# Security Policy / 安全政策

[English](#english) | [中文](#chinese)

---

<a name="english"></a>
## English

Customer360 Agent Benchmark ships a SQL execution gateway, authorization checks, and result filters. Safety is enabled by default.

### What to report privately

Use **GitHub Security Advisories** (or another private channel published by maintainers) for:

- SQL Guard bypasses (writes, filesystem/network reads, extension loading, system table access, side-effect functions)
- Authorization bypasses (role, table, column, or row-scope)
- Result leaks of sensitive fields, hidden-pack contents, Gold SQL, or private evaluator traces
- Ways to disable or skip the gateway while still receiving a successful evaluation

Do **not** open a public issue for these. Do **not** attach hidden packs, `hidden_oracles.yaml`, Gold SQL, private JSONL, or real personal data.

### What is not a vulnerability

- An Agent producing wrong SQL that the evaluator marks as failed
- `POLICY_INCOMPATIBLE` / `INPUT_LIMIT` / timeout on oversized queries
- Official Baseline scoring below a diagnostic target
- Missing PostgreSQL, FastAPI, or network model adapters (out of v1.0 scope)

### Public tree rules

- Wheels, sdists, and Docker images must not contain `data/trusted`, `data/hidden`, `outputs/`, or generated Gold.
- `data/trusted/human_oracles.yaml` in this source repository covers only the 20 public human cases (`C360_0001–0020`). It is not the hidden set.
- Generated hidden packs stay in gitignored `outputs/` on the maintainer machine.

### Supported versions

Only the current `main` branch and signed `v1.x` tags published by maintainers. Unsigned local snapshots are not a supported distribution.

### After a report

Maintainers will reproduce on Tiny, keep hidden artifacts off the public tree, and treat scoring-rule or whitelist changes as protocol changes (updating versions and documentation). Never "fix" a leak by rewriting Gold or turning off a safety gate.

---

<a name="chinese"></a>
## 中文

Customer360 Agent Benchmark 自带 SQL 执行网关、权限检查与结果脱敏过滤。安全机制默认开启。

### 需私下报告的问题

请通过 **GitHub Security Advisories**（或维护者发布的私下渠道）报告以下问题：

- SQL Guard 绕过（写入、文件系统/网络读取、加载扩展、访问系统表、副作用函数）
- 权限绕过（角色、表、列或客户行级范围）
- 敏感字段、隐藏题包内容、Gold SQL 或私有评测痕迹泄漏
- 能够在绕过或关闭执行网关的情况下仍获得评测通过的方法

请**不要**为此类问题创建公开 Issue。请**不要**在报告中附加隐藏集、`hidden_oracles.yaml`、Gold SQL、私有 JSONL 或真实个人数据。

### 不属于安全漏洞的情况

- Agent 生成了错误 SQL，且评测器正常将其标记为失败
- 超限查询导致的 `POLICY_INCOMPATIBLE` / `INPUT_LIMIT` / 超时
- 官方 Baseline 未达到某个诊断目标分数
- 暂未实现的 PostgreSQL、FastAPI 或网络模型适配器（这些不属于 v1.0 范围）

### 公开树规则

- Wheel、sdist 和 Docker 镜像严禁包含 `data/trusted`、`data/hidden`、`outputs/` 或生成的 Gold。
- 源码仓库中的 `data/trusted/human_oracles.yaml` 仅覆盖 20 道公开 human case（`C360_0001–0020`），绝非隐藏集。
- 生成的隐藏题包必须保存在本地 gitignore 的 `outputs/` 目录中。

### 支持版本

仅支持当前的 `main` 分支以及维护者发布的已签署 `v1.x` 标签。未签署的本地快照不在官方支持范围内。

### 收到漏洞报告后

维护者应在 Tiny 数据集上复现，确保隐藏制品不进入公开树，并将评分规则或白名单的修改视为协议变更（同步更新版本与文档）。严禁通过修改 Gold 或关闭安全门来“修复”泄漏。
