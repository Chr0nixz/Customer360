# v1.0 本地正式发布

日常安装、评测和打分见 [使用说明](user-guide.md)。把源码公开到 GitHub 见 [GitHub 发布清单](github-publish.md)。本文只列出维护者签署八个 RC 门、准备 v1.0.0 的命令。

## 冻结边界

- package 1.0.0、formal evaluator 0.6、score protocol 1.0、pack verify 0.2。
- 只发布本地可复现 benchmark；Public Dev 与 Private Hidden 分开报告，永久 `ranking_enabled=false`。
- Apache-2.0；hidden 数据、trusted Gold、私有报告不进入公开 tar、wheel、sdist 或 Docker image。源码 Git 可含 `data/trusted`（仅 C360_0001–0020），但不得含隐藏 pack 或 `outputs/`。
- 超时、worker crash、执行错误、非法/缺失响应计入失败；policy-incompatible 单独记录。
- Token/扫描量 unavailable，不报 0。
- 八个 RC evidence gates 必须校验证据内容。空文件、历史 0.5 报告、`sha256:abc123` 一律失败。文件存在不等于通过。
- 未签署的 `docker_runtime` 不得携带 digest，不得打 `v1.0.0`。

## 隐藏重放

`generate-hidden-variants` 从 hidden Tiny baseline 生成四个私有变体。每个变体记录 parent/child manifest hash、catalog hash、内容摘要和私有 seed。`evaluate-hidden --formal` 通过四个重复 `--variant` 参数按 distribution、duplicate、NULL、date 顺序加载；Agent 只在 baseline 调用，候选 SQL 在变体上重放。缺失、重复/乱序、catalog/date 不一致均 fail-closed。

## 维护者 RC 命令（独占新目录，不覆盖）

```text
c360 generate-data --scale tiny --seed 42 --output outputs/rc-tiny-seed42
c360 generate-variant --variant-id tiny_seed_43_distribution --output outputs/rc-v-distribution
c360 generate-variant --variant-id tiny_duplicate_fanout --output outputs/rc-v-duplicate
c360 generate-variant --variant-id tiny_null_empty_groups --output outputs/rc-v-null
c360 generate-variant --variant-id tiny_date_boundary --output outputs/rc-v-date
c360 generate-tasks --count 300 --seed 42 --output outputs/rc-public-300
c360 verify-pack --dataset outputs/rc-tiny-seed42 --pack outputs/rc-public-300 --variant outputs/rc-v-distribution --variant outputs/rc-v-duplicate --variant outputs/rc-v-null --variant outputs/rc-v-date --output outputs/rc-verify-pack
c360 generate-hidden --public-pack outputs/rc-public-300 --count 30 --output outputs/rc-hidden-pack
c360 generate-hidden-data --seed 1042 --output outputs/rc-hidden-tiny
c360 generate-hidden-variants --dataset outputs/rc-hidden-tiny --output outputs/rc-hidden-variants
c360 verify-hidden --dataset outputs/rc-hidden-tiny --pack outputs/rc-hidden-pack --output outputs/rc-verify-hidden
c360 bind-rc-evidence --gate semantic_acceptance --public-verify outputs/rc-verify-pack --hidden-verify outputs/rc-verify-hidden --output outputs/rc-evidence-semantic.json
c360 evaluate-public --dataset outputs/rc-tiny-seed42 --pack outputs/rc-public-300 --variant outputs/rc-v-distribution --variant outputs/rc-v-duplicate --variant outputs/rc-v-null --variant outputs/rc-v-date --agent baseline --output outputs/rc-eval-public
c360 evaluate-hidden --dataset outputs/rc-hidden-tiny --pack outputs/rc-hidden-pack --formal --variant outputs/rc-hidden-variants/hidden_distribution --variant outputs/rc-hidden-variants/hidden_duplicate_fanout --variant outputs/rc-hidden-variants/hidden_null_empty_groups --variant outputs/rc-hidden-variants/hidden_date_boundary --agent baseline --output outputs/rc-eval-hidden
c360 evaluate-public --dataset outputs/rc-tiny-seed42 --pack outputs/rc-public-300 --variant outputs/rc-v-distribution --variant outputs/rc-v-duplicate --variant outputs/rc-v-null --variant outputs/rc-v-date --agent wrong --output outputs/rc-eval-wrong
c360 score --public-report outputs/rc-eval-public --hidden-report outputs/rc-eval-hidden --agent baseline --output outputs/rc-score
uv build --out-dir outputs/rc-dist-1
uv build --out-dir outputs/rc-dist-2
c360 bind-rc-evidence --gate reproducible_build --first-dist outputs/rc-dist-1 --second-dist outputs/rc-dist-2 --output outputs/rc-evidence-build.json
c360 prepare-formal-release --public-pack outputs/rc-public-300 --score-dir outputs/rc-score --semantic-report outputs/rc-evidence-semantic.json --conformance-report outputs/rc-eval-public --negative-control-report outputs/rc-eval-wrong --reproducible-build-report outputs/rc-evidence-build.json --output outputs/rc-formal-release
c360 check-formal-release --input outputs/rc-formal-release
```

Linux/CI 另补 Docker 证据（本机未安装 Docker 时不要伪造）：

```text
docker build -t c360:rc .
docker run --rm --read-only --network=none --user 10001 c360:rc doctor
python3 .github/scripts/record_docker_runtime.py --image c360:rc --output outputs/rc-docker-runtime.json
# 用真实 image Id（sha256: + 64 hex）再 prepare-formal-release --docker-smoke-report ...
# RepoDigests 只有 push 到 registry 之后才有；不要填 sha256:abc123
```

历史 `prepare-release/check-release` 继续产出候选 no-score 格式，不会静默升级。Docker 以非 root 用户运行，验收运行时使用 `--read-only --network=none`；私有目录只通过显式只读 mount 注入。

## 验证记录

本轮把 RC 门从“文件存在”改为内容校验，并补充评分分母/P0/空证据回归。`prepare-formal-release` 在 `docker_runtime` 未签署时仍可写出 manifest，但 `check-formal-release` 必须失败。完整 pytest/RC 与远程 CI 的最终结果应作为发布门证据保存；不凭文档声明打标签。只有所有正式门通过才可打 `v1.0.0`，没有在线排名。
