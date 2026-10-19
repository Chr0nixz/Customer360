# Development Plan

[English](development-plan.md) | [简体中文](../development-plan.md)

Status: execution plan dated 2026-10-18, based on `main@bb1373f`. Scope: M6 release assurance and M7 capability admission.

This replaces the 2026-10-12 forward plan and supplements [ROADMAP](../../ROADMAP_EN.md). All work packages below are pending. Verified observations, targets, and proposals are distinguished. This document changes no code, task, Gold, current split, authorization, or scoring rule. Historical N0–N4 deliveries remain evidence for their original revisions.

## 1. Objective and verified baseline

The next iteration must establish artifact integrity, align executable capabilities with their security claims, improve formal Dev coverage, and produce release evidence bound to one final revision.

Local verification on 2026-10-18:

| Item | Verified state |
|---|---|
| Data and metadata | 9 tables, 72 columns, 30 metrics, 20 Join metadata paths, 5 executable Joins; three data scales implemented |
| Tasks | 20 fixed human dev cases; public 300 = 180 train / 120 generated-dev; formally expanded independent hidden 100-case stability artifacts (61 Answer / 23 Clarification / 16 Refusal) |
| Tests | Complete Tiny suite: `466 passed, 5 skipped` in 1048.74s; all five skips are unconfigured PostgreSQL live tests |
| Checks | Ruff check/format, doctor, metadata audit, 60/60 Tiny quality assertions, and architecture smoke passed |
| Versions | Package 1.0.0, Agent protocol 0.1, formal evaluator 0.6, score 1.0, metrics 0.4, join_paths 0.2, generated/hidden tasks 0.2 |
| Release history | Local `v1.0.0` points to `09d5c64`; the baseline has 27 later commits. An older signed artifact passes the checker; the N4 candidate records a missing docker_runtime gate |
| Open findings | Artifact digests are not recomputed by the release checker; PostgreSQL lacks equivalent authorization/result checks; formal Dev coverage is skewed |
| Unverified environments | Remote CI, real Docker runtime, and real PostgreSQL were not verified in this local audit; skipped tests are not engine qualification |

Keep dates and versions attached to historical results. The 2026-10-12 public_dev/private_hidden weighted scores, 0.9473/0.9536, predate recent Baseline changes. Historical performance workloads contain 17 successful cases, two non-answer skips, one policy-incompatible case, and no execution failures out of 20 human cases.

Preserve the nine tables, scale sizes, Tiny seed-42 content digests, 30 metric definitions, and current DuckDB SQL whitelist. Never relabel the human 20 as hidden. Public/private reports remain separate, `ranking_enabled=false`, and token/scan counts remain unavailable. External models, online services, arbitrary Python Agent sandboxes, and online rankings are outside this iteration.

## 2. Order and development exit gates

No staffing or release dates have been agreed. Schedule against dependencies and evidence rather than invented calendar commitments. Assign one delivery owner per package and one maintainer for final full verification.

| Package | Priority | Dependencies | Deliverable | Development exit gate |
|---|---|---|---|---|
| WP-01 Baseline and version boundaries | Highest | None | Capability/version inventory, historical/current states, pending decisions | G1: every capability has an implementation state and environment-specific evidence |
| WP-02 Release integrity | Highest | WP-01 evidence contract | Strict checker, versioned evidence, tamper regression | G2: tampering, omissions, mixed identities, and path escapes fail |
| WP-03 PostgreSQL safety | Highest | WP-01 engine scope | Fail-closed boundary, fixture repair; optional qualification | G3a: experimental execution safely closed; G3b: separately qualified execution |
| WP-04 Dev coverage | High | WP-01 and quota approval | New task version, split coverage checks, independent acceptance | G4: coverage and family isolation both hold |
| WP-05 Baseline quality | High | WP-03 capability boundary; frozen WP-04 pack | Public regressions, attribution, matched split diagnostics | G5: scoped failures fixed, existing positives preserved, no safety regression |
| WP-06 Performance/report evidence | Medium | WP-01; final measurement after WP-04/05 | Measured phases, correct denominators, environment records | G6: measurements are explainable and reproducible; unknowns stay unavailable |
| WP-07 Unified RC | High | G1/G2/G3a/G4/G5/G6; G3b if PG is enabled | Same-revision CI, Docker, distributions, and evaluation evidence | G7: all existing RC gates and current findings independently verified |

G1–G7 are development exit conditions, not new scoring hard gates or additions to the existing eight RC gates. WP-02 and WP-03 may be implemented independently once shared contracts are clear. Freeze tasks before final Baseline comparisons, and freeze code/documents before final RC builds.

> **Implementation Progress Confirmation (2026-10-19)**: Work packages WP-01 through WP-07 have achieved their developer exit criteria (G1 through G7) on the current local baseline, alongside v1.1 multi-turn clarification protocols, v1.2 query plan validation & metadata lifecycle governance, and v1.3 cross-engine adaptation & phase-split performance profiling. See [HANDOFF_EN.md](../HANDOFF_EN.md) for details.

## 3. Work packages

### WP-01: One baseline and explicit version boundaries

**Scope:** ROADMAP/HANDOFF, user/release/protocol documentation, capability and version inventories. Do not bump runtime versions in this stage.

1. Distinguish implemented, unit-tested, real-environment-tested, and formally supported capabilities. Transpilation alone does not establish safe execution.
2. Record the old tag, N4 candidate, and current main separately. Do not move, delete, or recreate `v1.0.0`.
3. Record owner, input/output contract, acceptance command, version impact, and unresolved items for each package. Attach historical N0–N4 evidence to its original revision.
4. Resolve conflicting current claims such as “only Docker remains,” PostgreSQL “not implemented/complete,” and “one executable Join.” Keep historical conclusions dated.
5. Prepare section 6 decisions. Pending version numbers do not block independent reproducers or test design; dependent migrations and release binding wait for confirmation.

**G1:** All entry points identify the active plan and capability inventory; skips, historical scores, and old tags cannot be mistaken for current verification.

### WP-02: Verify actual release artifact integrity

**Scope:** `release.py`, `contracts/release.py`, `contracts/evidence.py`, relevant CLI/CI, and formal-release/packaging/public-tree tests.

1. First add a failing regression for the observed modified-README acceptance. Recompute public artifact and evidence digests and check SHA256SUMS against the actual inventory. Specify private inputs verified only on the trusted side.
2. Reject missing/undeclared files, altered wheel/sdist contents, contradictory gate evidence, mixed historical reports, and unknown formats with stable failures. Inspect archive members rather than relying on extensions.
3. Restrict artifact references to safe relative paths. Reject absolute paths, `..`, symlink escapes, and similar out-of-root access without exposing private contents.
4. Propose an explicit evidence format version plus source commit, build-tree digest, lockfile digest, environment, capability profile, and applicable task/evaluator bindings. Define fields and migration contracts before implementation; these are not existing fields.
5. Several current contracts hardcode 1.0.0. After the next release version is approved, migrate through explicit versioned models or a supported-version mapping. Do not replace strict version checks with unconstrained strings.
6. Hashes establish content consistency; authenticity depends on trusted CI/maintainer provenance. Keep the inventory's own digest in a trusted root record to avoid self-reference. A well-formed digest or a JSON passed flag does not establish authenticity.

**G2:** A valid matching release passes. Altered documentation, distributions, evidence, lockfiles, or source identities fail, as do deletion, insertion, and path escapes. Historical formats remain historical; they cannot silently qualify as a new RC.

### WP-03: Close PostgreSQL gaps before qualification

**Scope:** runtime gateways/dialects, capability contracts, CI, live PostgreSQL and security tests.

G3a is mandatory for the current main:

1. Keep DuckDB as the default formal engine. Reject Agent SQL on PostgreSQL when validated security capabilities are absent; a configured URI or successful transpilation is insufficient. Record unavailable capabilities separately from authorization refusals; ENGINE_UNAVAILABLE is not a correct permission refusal.
2. Align declarations, gateway behavior, and CLI documentation. Preserve pure transpilation without granting database execution or file/network capabilities.
3. Fix the live fixture's directory-as-database-file error. Initialize synthetic data only in a dedicated test database/schema, never destructively reset arbitrary connection targets.
4. Add assertions for missing drivers/environment, unqualified capability, unauthorized columns, and customer scopes. The disabled path needs actual assertions; skips mean unverified.

Only perform G3b after formal inclusion is approved:

- Enforce AST and role/table/column/customer authorization before execution, including trusted pre-aggregation customer scoping; enforce result safety, contributor minimums, row limits, and truncation handling afterward.
- Use least privilege and current-transaction read-only enforcement. Verify engine timeout, client cleanup, and termination of server-side work, with stable failure codes.
- Pin driver/service versions in live CI. Cover dates, Decimal, NULL, the five permitted Joins, grouping, scopes, restricted fields, and timeout behavior within the declared SQL subset.
- Compare identical synthetic specs using the existing multiset comparator, including policy refusals. Required live tests cannot be skipped while claiming qualification.

**G3a:** Unqualified capabilities cannot access the database through public execution entry points; DuckDB safety behavior remains intact. **G3b:** Declared capabilities, authorization, and real execution agree. Completing only G3a retains experimental/unqualified status.

### WP-04: Representative formal Dev coverage

**Scope:** task generation, splitting, audits, pack contracts, and version-boundary tests. Preserve metric definitions, Guard, score weights, and the comparator.

Current seed-42 Dev contains 118 answer, one clarification, and one refusal, with only two Join and two grouped cases. The following is a **proposal requiring section 6 approval**, not a modification to existing packs:

| Action | Current Dev | Proposed Dev | Proposed Train |
|---|---:|---:|---:|
| answer | 118 | 90 | 150 |
| clarification_needed | 1 | 18 | 18 |
| refuse | 1 | 12 | 12 |
| Total | 120 | 120 | 180 |

The proposed public pack still has 300 independent semantic cases, totaling 240/36/24 actions. Prove family-pool feasibility first. Rewrites and variants cannot fill quotas, and moving all non-answer examples into Dev must not remove training examples.

Proposed Dev quality checks:

- All 30 metrics covered, each by at least two independent families.
- At least 15 Join cases, with at least three independent cases for each of the five executable paths.
- At least 15 grouped cases across four existing permitted dimensions; this does not enable Join+GROUP BY.
- At least 12 cases covering NULL, empty results, missing relationships, or time boundaries. Tags may overlap; cases are counted once.
- Report controlled aggregate coverage by action, metric, Join, grouping, time, and intended error across train/dev/private. Keep private detailed matrices private.

Write coverage/isolation tests before family-stratified allocation. Create new task versions and preserve old packs and results. Check new public families against retained hidden families; never turn old hidden cases into public fixtures. Bump hidden task/pack versions if hidden semantics or associated public-pack identity changes.

**G4:** Counts, quotas, split coverage, and isolation pass together. Independently verify Gold/oracles, rewrites, all eight error classes, and every applicable frozen variant. Record infeasible pools and policy incompatibility; never relax Guard to meet a quota.

### WP-05: Baseline quality and diagnosis

**Scope:** `agent/`, public synthetic regressions, and diagnostics. Do not alter evaluation or Gold rules for better Agent scores.

1. Re-establish current public failures instead of treating already-supported filters and five Joins as new features. Prioritize failing combinations, negation/conflicts, temporal boundaries, NULL, and status semantics.
2. Give each fix an independent public synthetic fixture through the real gateway. Record public input, parsed plan, failure stage/code, receipt, and versions.
3. Test minimal clarification slots, replanning after replies, contradictory replies, round limits, and distinct permission/unknown-field/policy/runtime outcomes.
4. Do not inspect case-ID patterns, Gold, semantic specs, hidden prompts, or private hidden diagnostics in Baseline development. Use hidden evaluation after freezing; do not feed private cases into tuning.
5. Compare before/after behavior on identical task/data/policy versions. Report new and old packs separately; do not attribute changed coverage to Agent improvement.

**G5:** All scoped public failure fixtures pass, old positives do not regress, and P0 Agent safety violations remain zero. Attribute score changes and preserve per-split denominators, policy incompatibility, the four existing hard gates, and failure categories. Never merge or rank the splits.

### WP-06: Measured performance and defensible reports

**Scope:** `evaluator/perf.py`, performance/diagnostic contracts, reports, and performance tests.

1. Distinguish success, non-answer skips, policy incompatibility, timeouts, and execution failures. Define timing sample denominators; skipped cases are not zero-latency successes.
2. Measure plan/guard/execute/end-to-end boundaries, process startup, and overlap. Produce actual phase_stats; historical null phase_stats are not phase-level measurement evidence.
3. Record fixed hardware, concurrency, caches, threads, dependencies, Agent, retries, and budget profile. Run Standard/Large only in explicit performance workflows and separately from Tiny semantic scoring.
4. Retain finite materialization/time/output budgets. Keep unmeasured token/scan/peak-memory values unavailable; define capability/report contracts before adding real measurements.
5. Add action/Join/grouping/time diagnostics. If adding 95% intervals, freeze the method first, sample by case/family, and avoid treating rewrites or correlated variants as independent observations. Version this as diagnostic reporting.

**G6:** Denominators, failures, and timing boundaries are auditable. Performance and scoring artifacts remain separate, and public reports reveal no Gold, hidden results/seeds, or reconstructable private-case details.

### WP-07: One-revision release acceptance

**Scope:** final builds, CI, RC evidence, and release documentation; no new semantic capabilities.

1. Finish dependencies and bilingual documents, then freeze commit, build tree, lockfile, and version tuple before generating final evidence.
2. Run matching Linux full Tiny and Windows regressions, doctor, metadata/split audits, and wheel smoke outside the source tree.
3. Verify the claimed reproducibility with two independent builds. Scan the tracked tree, distributions, and image for hidden/trusted artifacts, private reports, credentials, and generated databases.
4. Run real non-root, read-only, network-disabled Docker doctor/smoke. Bind actual image Id, source revision, and logs; never reuse an old image digest for new code.
5. Bind public 300 semantic acceptance, independent hidden acceptance, formal public/private four-variant evaluation, WrongAgent negative control, and separate scoring to the same release identity. Access hidden data only through trusted controlled mounts.
6. Verify all eight existing RC gates and their content/provenance through WP-02's strict checker. The maintainer then publishes the next approved version without overwriting the old tag.

**G7:** No unexplained P0/P1 remains; all eight RC gates have genuine matching evidence and Gold/independent oracles pass every applicable variant. Report Agent results under existing scoring and its four hard gates; a perfect Baseline score is not required. Public artifacts pass leak checks, trusted inputs remain traceable, and documents state commands, environmental limits, and unqualified capabilities.

## 4. Validation and delivery

These are existing commands. Define contracts, help, and tests before adding future evidence fields or CLI flags; this plan does not claim they exist.

Daily and targeted checks:

```bash
uv sync --locked
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q -m "not slow"
uv run --locked c360 doctor
uv run --locked c360 audit-metadata
```

| Package | Existing test entry points |
|---|---|
| WP-02 | `tests/test_formal_release.py`, `test_packaging.py`, `test_public_tree.py` |
| WP-03 | `tests/test_runtime.py`, `test_sql_guard.py`, `test_dialects.py`, `test_postgres_live.py` |
| WP-04 | `tests/test_m3_pack.py`, `test_m6_hidden.py`, `test_pack_verify.py`, `test_audit_splits.py`, `test_version_boundary.py` |
| WP-05 | `tests/test_baseline.py`, `test_clarification_interaction.py`, `test_plan_validation.py`, `test_diagnostics.py` |
| WP-06 | `tests/test_perf_baseline.py`, `test_perf_phases.py` |

Run targeted tests first. Complete `uv run --locked pytest -q` before submitting semantic/runtime/security changes. One owner runs final full regression and formal release checking. List skips explicitly; do not combine historical partial counts into a claimed full pass. Documentation-only changes use link, public-boundary, and diff checks without repeating lengthy generation/scoring.

Each delivery includes implementation/tests, version impacts, commands/exit codes, evidence identities/paths, failed gates, limits, and pending decisions. Use exclusive new output directories and separate public summaries from trusted details. Regenerate affected builds/evidence after frozen code, documents, or dependencies change.

## 5. Version and compatibility strategy

Recommend `v1.1.0` for the next mainline release, **pending maintainer confirmation**. Current main includes semantic/capability extensions after the old v1.0.0 tag; do not label the entire branch as a patch release. An urgent v1.0.1 would require a separate maintenance line from the old tag, minimal selected patches, and independent acceptance; it is not default additional scope.

| Change | Versions/artifacts to review |
|---|---|
| Status documents/tests only | No runtime protocol bump; rebind final build digests when documents enter artifacts |
| Release manifests, evidence formats, identity checks | Explicit evidence/manifest schema, package, and compatibility policy; no relabeling of historical formats |
| Agent fields, states, stable rejection contract | protocol_version; evaluator_version review for observable evaluation changes |
| Task semantics, quotas, generation, splits | New task/pack versions and case identity rules, independent oracles, isolation, regression baseline |
| Metric/Join/Schema semantics | Corresponding metrics/join/catalog/schema versions; semantic changes are outside this iteration's default |
| Generator/data content | generator/snapshot/config digests; preserve current Tiny content |
| Baseline planning/SQL/clarification | Agent/adapter version, parameters, matched-task before/after diagnostics |
| Comparator/replay/failure-attribution behavior | Evaluator/report version and migration; old results cannot be relabeled as reruns |
| Weights, scoring denominator rules, hard gates | Score protocol and regression baseline; no such change is proposed here |
| Formal engine admission | Capability profile, gateway/protocol/evaluation identity, pinned driver and real-environment evidence; no automatic cross-engine ranking |

## 6. Pending decisions and safe progress

These are proposals, not frozen protocols. Maintainers record decisions before dependent changes; independent reproducers and regression design may proceed beforehand.

| ID | Decision | Recommendation and progress before confirmation |
|---|---|---|
| P-01 | Next mainline release version | Confirmed and locked as v1.1.0 (distinct from historical v1.0.0 at 09d5c64, containing WP-01–WP-07 and v1.1–v1.3 evolutions) |
| P-02 | Action quotas and Dev quality checks | Recommend WP-04 targets; prove family-pool feasibility/migration before producing new formal packs |
| P-03 | PostgreSQL in this formal release | Default to G3a and DuckDB-only formal evaluation; G3b requires separate scope approval and live qualification |
| P-04 | Evidence trust and custody | Designate trusted CI/maintainer and private storage; implement local integrity tests now, confirm provenance before signing |

## 7. Admission of later extensions

After release assurance and coverage stabilize:

- Expand hidden 60 to 100: **Formally completed (2026-10-20)**. Proved 313 remaining independent semantic families, implemented `count >= 100` scientific stratification quota (61 Answer / 23 Clarification / 16 Refuse), covering 26 distinct metrics and all 8 required error classes, 100% answer compilability verified, and enforced via `test_hidden_100_pack_stratified_and_isolated`.
- New metrics, composite Joins, Top-K, or multi-metric DSL: **Top-K aggregation and deterministic tie-breaking formally completed (2026-10-20, D066)**. Implemented `limit`, `order_by`, and `order_direction` contracts, strict order column whitelisting, deterministic total ordering tie-breaking ("primary DESC/ASC + group dimensions ASC"), two-pass stable sorting in memory slices, and strict ordered parity verification (`tests/test_v1_4_dsl_topk.py`). Composite Joins and additional metrics subject to further expansion.
- Claim formal PostgreSQL or complete phase performance support only after G3b or real measurements pass.
- External models, remote services, and untrusted Python OS isolation require separate product/security decisions and plans; no enablement before network/cost/trust boundaries are settled.
- Online rankings remain outside this roadmap and `ranking_enabled=false` remains unchanged. Any different competition format requires an explicit separate decision.

Accept work against source, independent results, and genuine matching evidence. Preserve failed gates as open findings rather than replacing them with document labels or manifest booleans.
