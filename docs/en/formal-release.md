# v1.0 Formal Local Release

[English](formal-release.md) | [简体中文](../formal-release.md)

For day-to-day installation, evaluation, and scoring, see the [User Guide](user-guide.md). To publish the source repository to GitHub, see the [GitHub Publishing Checklist](github-publish.md). This document details maintainer commands for signing all eight RC gates and preparing the v1.0.0 release.

## Frozen Boundaries

- Package 1.0.0, formal evaluator 0.6, score protocol 1.0, pack verification 0.2.
- Only reproducible local benchmarks are published; Public Dev and Private Hidden are reported separately, with `ranking_enabled=false` permanently.
- Apache-2.0 license. Hidden data, trusted Gold, and private traces must never enter public tarballs, wheels, sdists, or Docker images. The source Git tree may retain `data/trusted` (covering only `C360_0001–0020`), but never hidden packs or `outputs/`.
- Timeouts, worker crashes, execution errors, and invalid/missing responses count as failures; policy-incompatible cases are audited separately.
- Token consumption and scan volume are marked `unavailable`, never reported as 0.
- All eight RC evidence gates strictly validate evidence content. Empty files, legacy evaluator 0.5 reports, or placeholder digests (e.g., `sha256:abc123`) fail immediately. File presence does not imply gate satisfaction.
- An unsigned `docker_runtime` gate must not carry a dummy digest, and `v1.0.0` cannot be tagged until it is signed with valid evidence.

## Hidden Set Replay

`generate-hidden-variants` creates four private variants from the hidden Tiny baseline. Each variant records parent/child manifest hashes, catalog hash, content digests, and a private seed. `evaluate-hidden --formal` loads these variants in the exact order: distribution, duplicate, NULL, date, via four `--variant` arguments. The Agent is invoked only once on the baseline; the candidate SQL is replayed across variants. Missing variants, reordering, or catalog/date inconsistencies fail-closed.

## Maintainer RC Commands (Exclusive Fresh Directories)

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

Docker runtime verification on Linux/CI (do not forge evidence if Docker is absent locally):

```text
docker build -t c360:rc .
docker run --rm --read-only --network=none --user 10001 c360:rc doctor
python3 .github/scripts/record_docker_runtime.py --image c360:rc --output outputs/rc-docker-runtime.json
# Bind real image Id (sha256: + 64 hex) using prepare-formal-release --docker-smoke-report ...
# RepoDigests exist only after registry push; do not enter sha256:abc123
```

Legacy `prepare-release` / `check-release` commands continue to produce the candidate no-score format without silent upgrades. Docker runs under a non-root user (`c360`, UID 10001) with `--read-only --network=none`.

## Verification Notes

All eight RC gates require cryptographic/content evidence validation. `prepare-formal-release` may write the manifest while `docker_runtime` is still unsigned, but `check-formal-release` will fail until all eight gates pass. Only when every formal gate passes can `v1.0.0` be officially tagged.
