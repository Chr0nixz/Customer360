"""Replay compiled Gold SQL on frozen Tiny variants.

Trusted-side only. same_sql does not invoke the Agent. agent_rerun requires an
injected Agent that only sees the public request. Scoring weights are not
applied. Seed 42 is the baseline Tiny snapshot.
"""

from datetime import date
from pathlib import Path

from customer360.agent.protocol import Agent
from customer360.artifacts import digest, write_json_new
from customer360.contracts.generation import DatasetManifest
from customer360.contracts.oracle import AnswerOracle, PrivateCase
from customer360.contracts.public import AgentRequest
from customer360.contracts.variant import (
    BASELINE_SEED,
    REPORT_KIND_FOR_MODE,
    VARIANT_ID,
    ReplayMode,
    VariantCaseReplay,
    VariantDatasetManifest,
    VariantReplayReport,
)
from customer360.errors import QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.coverage import load_human_cases
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset, normalize_sql_result

LIMITATIONS = (
    "Not an official robustness score, five-variant suite or model baseline",
    "same_sql, agent_rerun and scoring are distinct modes and cannot share a report",
    "Scoring weights are not applied; scoring_applied remains false",
    "agent_rerun requires an injected Agent; Gold SQL submission is not a rerun",
    "Empty aggregation under min_group_size is policy_incompatible, not an Agent miss",
    "Coverage reports remain unscored; this replay does not complete M2",
)

_sql_result = normalize_sql_result


def load_baseline_tiny(dataset_dir: Path) -> tuple[Path, DatasetManifest]:
    database, manifest = load_verified_dataset(dataset_dir)
    if not isinstance(manifest, DatasetManifest) or manifest.artifact_kind != "tiny_dataset":
        raise ValueError("baseline must be the canonical Tiny dataset, not a public fixture")
    if manifest.seed != BASELINE_SEED:
        raise ValueError(
            f"expected Tiny seed {BASELINE_SEED} for this replay role, got {manifest.seed}"
        )
    if manifest.generator_version != "0.1.0" or manifest.snapshot_version != "tiny-v1":
        raise ValueError("variant replay requires generator_version 0.1.0 and snapshot tiny-v1")
    return database, manifest


def load_named_variant(
    dataset_dir: Path,
) -> tuple[Path, DatasetManifest | VariantDatasetManifest, str, int]:
    database, manifest = load_verified_dataset(dataset_dir)
    if isinstance(manifest, DatasetManifest):
        if manifest.artifact_kind != "tiny_dataset":
            raise ValueError("variant replay requires a Tiny dataset, not a public fixture")
        if manifest.seed != 43:
            raise ValueError(f"expected Tiny seed 43 for this replay role, got {manifest.seed}")
        if manifest.generator_version != "0.1.0" or manifest.snapshot_version != "tiny-v1":
            raise ValueError("variant replay requires generator_version 0.1.0 and snapshot tiny-v1")
        return database, manifest, VARIANT_ID, manifest.seed
    return database, manifest, manifest.variant_id, manifest.seed


def build_variant_replay(
    baseline_dir: Path,
    variant_dir: Path,
    repository: MetadataRepository | None = None,
    oracles: Path | None = None,
    replay_mode: ReplayMode = "same_sql",
    agent: Agent | None = None,
) -> VariantReplayReport:
    if replay_mode == "scoring":
        raise ValueError("robustness scoring is not enabled; scoring_applied remains false")
    if replay_mode not in {"same_sql", "agent_rerun"}:
        raise ValueError(f"unknown replay mode: {replay_mode}")
    if replay_mode == "same_sql" and agent is not None:
        raise ValueError("same_sql replay cannot invoke the Agent")
    if replay_mode == "agent_rerun" and agent is None:
        raise ValueError(
            "agent_rerun requires an injected Agent; Gold SQL submission is not a rerun"
        )
    baseline_db, baseline_manifest = load_baseline_tiny(baseline_dir)
    variant_db, variant_manifest, variant_id, variant_seed = load_named_variant(variant_dir)
    if baseline_manifest.catalog_hash != variant_manifest.catalog_hash:
        raise ValueError("baseline and variant must share the same catalog hash")
    date_unchanged = (
        baseline_manifest.content_hashes["dim_date"] == variant_manifest.content_hashes["dim_date"]
    )
    catalog = load_human_cases(oracles=oracles)
    repository = repository or MetadataRepository()
    baseline_slices = load_table_slices(baseline_db, repository.catalog)
    variant_slices = load_table_slices(variant_db, repository.catalog)
    gateway = None
    policy = tiny_eval_policy()
    if replay_mode == "agent_rerun":
        gateway = ExecutionGateway(variant_db, policy)
    cases: list[VariantCaseReplay] = []
    matches = 0
    differed = 0
    agent_called = False
    for item in catalog.cases:
        if item.material_status != "compilable_answer":
            cases.append(
                VariantCaseReplay(
                    case_id=item.case_id,
                    task_version=item.task_version,
                    split=item.split,
                    material_status=item.material_status,
                )
            )
            continue
        spec = item.semantic_spec()
        compiled = compile_semantic(spec, repository)
        baseline_result = _sql_result(baseline_db, compiled)
        variant_result = _sql_result(variant_db, compiled)
        independent = compute_independent(spec, repository, variant_slices)
        baseline_independent = compute_independent(spec, repository, baseline_slices)
        if not compare_results(baseline_independent, baseline_result):
            raise ValueError(f"baseline independent oracle mismatch for {item.case_id}")
        matched = compare_results(independent, variant_result)
        changed = not compare_results(baseline_result, variant_result)
        matches += int(matched)
        differed += int(changed)
        agent_outcome = None
        agent_reason = None
        applicability = None
        policy_block = None
        if gateway is not None:
            applicability = "applicable"
            try:
                gateway.execute(compiled.sql)
            except QueryRejected as exc:
                if exc.code != "AGGREGATION_TOO_SMALL":
                    raise
                applicability = "policy_incompatible"
                policy_block = exc.code
                agent_reason = "POLICY_INCOMPATIBLE"
            if applicability == "applicable":
                assert agent is not None
                request = AgentRequest(
                    case_id=item.case_id,
                    question=item.question,
                    anchor_date=date(2025, 6, 30),
                    metadata_version=repository.metrics.metrics_version,
                )
                record = evaluate_case(
                    PrivateCase(request=request, oracle=AnswerOracle(semantic_spec=spec)),
                    agent,
                    gateway,
                    repository,
                )
                agent_called = True
                agent_outcome = record.outcome
                agent_reason = record.reason_code
        cases.append(
            VariantCaseReplay(
                case_id=item.case_id,
                task_version=item.task_version,
                split=item.split,
                material_status=item.material_status,
                sql=compiled.sql,
                sql_unchanged=True if replay_mode == "same_sql" else None,
                independent_match=matched,
                differs_from_baseline=changed,
                baseline_result=baseline_result,
                variant_result=variant_result,
                independent_result=independent,
                agent_outcome=agent_outcome,
                agent_reason_code=agent_reason,
                applicability=applicability,
                policy_block_code=policy_block,
            )
        )
    compilable = sum(item.material_status == "compilable_answer" for item in catalog.cases)
    if replay_mode == "same_sql":
        passed = matches == compilable and differed >= 1 and date_unchanged
    else:
        applicable = [
            item
            for item in cases
            if item.material_status == "compilable_answer"
            and item.applicability != "policy_incompatible"
        ]
        blocked = [
            item
            for item in cases
            if item.material_status == "compilable_answer"
            and item.applicability == "policy_incompatible"
        ]
        agent_ok = bool(applicable) and all(item.agent_outcome == "pass" for item in applicable)
        blocked_ok = all(item.agent_outcome is None and item.policy_block_code for item in blocked)
        passed = (
            matches == compilable and differed >= 1 and date_unchanged and agent_ok and blocked_ok
        )
    return VariantReplayReport(
        report_kind=REPORT_KIND_FOR_MODE[replay_mode],  # type: ignore[arg-type]
        replay_mode=replay_mode,
        variant_id=variant_id,  # type: ignore[arg-type]
        agent_invoked=agent_called,
        passed=passed,
        variant_seed=variant_seed,
        baseline_manifest_hash=digest(baseline_manifest.model_dump(mode="json")),
        variant_manifest_hash=digest(variant_manifest.model_dump(mode="json")),
        compilable_answers=compilable,
        independent_oracle_matches=matches,
        results_differ_from_baseline=differed,
        date_dimension_unchanged=date_unchanged,
        limitations=LIMITATIONS,
        cases=tuple(cases),
    )


def _markdown(report: VariantReplayReport) -> str:
    lines = [
        "# Tiny variant replay",
        "",
        "Trusted-side replay. Not an official score.",
        "",
        f"- passed: `{report.passed}`",
        f"- replay_mode: `{report.replay_mode}`",
        f"- variant_id: `{report.variant_id}`",
        f"- independent_oracle_matches: `{report.independent_oracle_matches}`",
        f"- results_differ_from_baseline: `{report.results_differ_from_baseline}`",
        f"- date_dimension_unchanged: `{report.date_dimension_unchanged}`",
        f"- agent_invoked: `{report.agent_invoked}`",
        f"- m2_complete: `{report.m2_complete}`",
        f"- scoring_applied: `{report.scoring_applied}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case | status | independent | differs |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in report.cases:
        match = "" if case.independent_match is None else str(case.independent_match)
        differs = "" if case.differs_from_baseline is None else str(case.differs_from_baseline)
        lines.append(f"| {case.case_id} | {case.material_status} | `{match}` | `{differs}` |")
    lines.append("")
    return "\n".join(lines)


def write_variant_replay(
    baseline_dir: Path,
    variant_dir: Path,
    output_dir: Path,
    oracles: Path | None = None,
    replay_mode: ReplayMode = "same_sql",
    agent: Agent | None = None,
) -> dict:
    report = build_variant_replay(
        baseline_dir,
        variant_dir,
        oracles=oracles,
        replay_mode=replay_mode,
        agent=agent,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = report.model_dump(mode="json")
    write_json_new(output_dir / "replay.json", payload)
    with (output_dir / "replay.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_markdown(report))
    return payload
