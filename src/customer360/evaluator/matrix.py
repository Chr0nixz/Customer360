"""Run one Agent on Tiny baseline, then replay across the frozen variant matrix."""

from datetime import date
from pathlib import Path

from customer360.agent.baseline import BaselineAgent
from customer360.agent.protocol import Agent
from customer360.agent.template import TemplateAgent
from customer360.artifacts import digest
from customer360.contracts.evaluation import FROZEN_FAILURE_CLASSES, EvaluationRecord
from customer360.contracts.matrix import (
    BASELINE_SNAPSHOT_ID,
    MATRIX_SNAPSHOT_IDS,
    CaseMatrixRecord,
    MatrixRunReport,
    SnapshotOutcome,
)
from customer360.contracts.oracle import PrivateCase
from customer360.contracts.public import AgentRequest, QueryResult
from customer360.contracts.variant import ReplayMode
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.variant import load_baseline_tiny, load_named_variant, tiny_eval_policy

ANCHOR = date(2025, 6, 30)
LIMITATIONS = (
    "Not an official score or five-variant grade; ROADMAP section 8 weights are not applied",
    "same_sql replays the Agent candidate SQL; it does not treat Gold SQL as an Agent score",
    "agent_rerun is recorded separately and cannot share a robustness score",
    "scoring_applied and m4_scored remain false until denominators are confirmed",
    "policy_incompatible snapshots do not invoke the Agent and are not Agent misses",
    "Truncated, timed-out or crashed executions cannot pass as empty results",
    "TemplateAgent is a protocol driver; --agent baseline is the official local baseline",
)
NETWORK_AGENT_IDS = frozenset({"gpt", "openai", "anthropic", "network", "llm"})


def resolve_eval_agent(agent_id: str) -> Agent:
    if agent_id == "wrong":
        from customer360.agent.wrong import WrongAgent

        return WrongAgent()
    if agent_id == "template":
        return TemplateAgent()
    if agent_id == "baseline":
        return BaselineAgent()
    if agent_id in NETWORK_AGENT_IDS:
        raise ValueError("external model network is not permitted")
    raise ValueError(f"unknown agent: {agent_id}")


def _private_case(item, repository: MetadataRepository) -> PrivateCase:
    return PrivateCase(
        request=AgentRequest(
            case_id=item.case_id,
            question=item.question,
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        oracle=item.oracle(),
        task_version=item.task_version,
    )


def _candidate_sql(record: EvaluationRecord) -> tuple[str | None, bool]:
    for audit in reversed(record.rounds):
        if audit.receipts:
            receipt = audit.receipts[-1]
            return receipt.sql, receipt.truncated
        for call in reversed(audit.tool_calls):
            if call.tool == "execute_sql" and call.rejection_code == "UNSAFE_SQL":
                return None, False
    return None, False


def _failure_class(outcome: str, reason: str | None) -> str | None:
    if outcome in {"fail", "error"} and reason:
        return reason if reason in FROZEN_FAILURE_CLASSES else reason
    return None


def _replay_candidate(
    snapshot_id: str,
    gateway: ExecutionGateway,
    sql: str,
    independent: QueryResult | None,
    baseline_result: QueryResult | None,
) -> SnapshotOutcome:
    try:
        receipt = gateway.execute(sql)
    except QueryRejected as exc:
        if exc.code == "AGGREGATION_TOO_SMALL":
            return SnapshotOutcome(
                snapshot_id=snapshot_id,
                applicable="policy_incompatible",
                stage="same_sql_replay",
                outcome="skipped",
                reason_code="POLICY_INCOMPATIBLE",
                failure_class="POLICY_INCOMPATIBLE",
            )
        outcome = "fail"
        return SnapshotOutcome(
            snapshot_id=snapshot_id,
            applicable="applicable",
            stage="same_sql_replay",
            outcome=outcome,
            reason_code=exc.code,
            failure_class=_failure_class(outcome, exc.code),
            sql_replayed=True,
            independent_match=False,
        )
    except ExecutionFailure as exc:
        code = (
            exc.code
            if exc.code in {"TIMEOUT", "WORKER_CRASH", "EXECUTION_ERROR", "INPUT_LIMIT"}
            else "EXECUTION_ERROR"
        )
        return SnapshotOutcome(
            snapshot_id=snapshot_id,
            applicable="applicable",
            stage="same_sql_replay",
            outcome="fail",
            reason_code=code,
            failure_class=code,
            sql_replayed=True,
            independent_match=False,
        )
    if receipt.result.truncated:
        return SnapshotOutcome(
            snapshot_id=snapshot_id,
            applicable="applicable",
            stage="same_sql_replay",
            outcome="fail",
            reason_code="UNVERIFIED_RESULT",
            failure_class="RESULT_MISMATCH",
            sql_replayed=True,
            truncated=True,
            independent_match=False,
        )
    matched = independent is not None and compare_results(receipt.result, independent)
    differs = baseline_result is not None and not compare_results(receipt.result, baseline_result)
    outcome = "pass" if matched else "fail"
    reason = "OK" if matched else "RESULT_MISMATCH"
    return SnapshotOutcome(
        snapshot_id=snapshot_id,
        applicable="applicable",
        stage="same_sql_replay",
        outcome=outcome,
        reason_code=reason,
        failure_class=_failure_class(outcome, reason),
        sql_replayed=True,
        differs_from_baseline=differs,
        independent_match=matched,
    )


def _reference_blocked(gateway: ExecutionGateway, sql: str) -> bool:
    try:
        gateway.execute(sql)
    except QueryRejected as exc:
        return exc.code == "AGGREGATION_TOO_SMALL"
    return False


def evaluate_matrix(
    baseline_dir: Path,
    variant_dirs: dict[str, Path],
    agent: Agent,
    *,
    agent_id: str = "template",
    replay_mode: ReplayMode = "same_sql",
    repository: MetadataRepository | None = None,
    oracles: Path | None = None,
) -> MatrixRunReport:
    if replay_mode == "scoring":
        raise ValueError("robustness scoring is not enabled; scoring_applied remains false")
    if replay_mode not in {"same_sql", "agent_rerun"}:
        raise ValueError(f"unknown replay mode: {replay_mode}")
    expected = set(MATRIX_SNAPSHOT_IDS[1:])
    if set(variant_dirs) != expected:
        raise ValueError("matrix requires the four frozen Tiny variants")
    repository = repository or MetadataRepository()
    catalog = load_human_cases(oracles=oracles)
    if any(item.split != "dev" for item in catalog.cases):
        raise ValueError("human pack split relabel is forbidden")
    baseline_db, baseline_manifest = load_baseline_tiny(baseline_dir)
    snapshots: dict[str, tuple] = {BASELINE_SNAPSHOT_ID: (baseline_db, baseline_manifest)}
    variant_hashes: dict[str, str] = {}
    date_hash = baseline_manifest.content_hashes["dim_date"]
    date_unchanged = True
    for snapshot_id in MATRIX_SNAPSHOT_IDS[1:]:
        database, manifest, loaded_id, _seed = load_named_variant(variant_dirs[snapshot_id])
        if loaded_id != snapshot_id:
            raise ValueError(f"variant directory is {loaded_id}, expected {snapshot_id}")
        if manifest.catalog_hash != baseline_manifest.catalog_hash:
            raise ValueError("baseline and variant must share the same catalog hash")
        date_unchanged = date_unchanged and manifest.content_hashes["dim_date"] == date_hash
        snapshots[snapshot_id] = (database, manifest)
        variant_hashes[snapshot_id] = digest(manifest.model_dump(mode="json"))
    policy = tiny_eval_policy()
    gateways = {
        snapshot_id: ExecutionGateway(database, policy)
        for snapshot_id, (database, _manifest) in snapshots.items()
    }
    slices = {
        snapshot_id: load_table_slices(database, repository.catalog)
        for snapshot_id, (database, _manifest) in snapshots.items()
    }
    records: list[CaseMatrixRecord] = []
    agent_invoked = False
    independent_matches = 0
    compilable = 0
    for item in catalog.cases:
        private = _private_case(item, repository)
        baseline_gateway = gateways[BASELINE_SNAPSHOT_ID]
        baseline_eval = evaluate_case(private, agent, baseline_gateway, repository)
        agent_invoked = True
        candidate_sql, truncated = _candidate_sql(baseline_eval)
        gold_sql = None
        independents: dict[str, QueryResult | None] = dict.fromkeys(MATRIX_SNAPSHOT_IDS)
        if item.material_status == "compilable_answer":
            compilable += 1
            spec = item.semantic_spec()
            gold_sql = compile_semantic(spec, repository).sql
            for snapshot_id, slice_map in slices.items():
                independents[snapshot_id] = compute_independent(spec, repository, slice_map)
        baseline_result = None
        if baseline_eval.rounds:
            receipts = baseline_eval.rounds[-1].receipts
            if receipts:
                baseline_result = receipts[-1].result
        rows: list[SnapshotOutcome] = []
        for snapshot_id in MATRIX_SNAPSHOT_IDS:
            gateway = gateways[snapshot_id]
            independent = independents[snapshot_id]
            if replay_mode == "agent_rerun":
                if (
                    gold_sql
                    and snapshot_id != BASELINE_SNAPSHOT_ID
                    and _reference_blocked(gateway, gold_sql)
                ):
                    rows.append(
                        SnapshotOutcome(
                            snapshot_id=snapshot_id,
                            applicable="policy_incompatible",
                            stage="agent_rerun",
                            outcome="skipped",
                            reason_code="POLICY_INCOMPATIBLE",
                            failure_class="POLICY_INCOMPATIBLE",
                        )
                    )
                    continue
                record = (
                    baseline_eval
                    if snapshot_id == BASELINE_SNAPSHOT_ID
                    else evaluate_case(private, agent, gateway, repository)
                )
                agent_invoked = True
                sql, snap_truncated = _candidate_sql(record)
                result = None
                if record.rounds and record.rounds[-1].receipts:
                    result = record.rounds[-1].receipts[-1].result
                matched = (
                    independent is not None
                    and result is not None
                    and not snap_truncated
                    and compare_results(result, independent)
                )
                rows.append(
                    SnapshotOutcome(
                        snapshot_id=snapshot_id,
                        applicable="applicable",
                        stage="agent_rerun",
                        outcome=record.outcome,  # type: ignore[arg-type]
                        reason_code=record.reason_code,
                        failure_class=_failure_class(record.outcome, record.reason_code),
                        sql_replayed=sql is not None,
                        agent_invoked=True,
                        truncated=snap_truncated,
                        independent_match=matched if sql else None,
                    )
                )
                if matched:
                    independent_matches += 1
                continue
            if snapshot_id == BASELINE_SNAPSHOT_ID:
                matched = (
                    independent is not None
                    and baseline_result is not None
                    and not truncated
                    and compare_results(baseline_result, independent)
                )
                if truncated:
                    outcome = "fail"
                    reason = "UNVERIFIED_RESULT"
                else:
                    outcome = baseline_eval.outcome
                    reason = baseline_eval.reason_code
                rows.append(
                    SnapshotOutcome(
                        snapshot_id=snapshot_id,
                        applicable="applicable",
                        stage="agent_submit",
                        outcome=outcome,  # type: ignore[arg-type]
                        reason_code=reason,
                        failure_class=_failure_class(outcome, reason),
                        sql_replayed=candidate_sql is not None,
                        agent_invoked=True,
                        truncated=truncated,
                        independent_match=matched if candidate_sql else None,
                    )
                )
                if matched:
                    independent_matches += 1
                continue
            if not candidate_sql:
                rows.append(
                    SnapshotOutcome(
                        snapshot_id=snapshot_id,
                        applicable="not_applicable",
                        stage="same_sql_replay",
                        outcome="skipped",
                        reason_code="NO_CANDIDATE_SQL",
                    )
                )
                continue
            replayed = _replay_candidate(
                snapshot_id, gateway, candidate_sql, independent, baseline_result
            )
            rows.append(replayed)
            if replayed.independent_match:
                independent_matches += 1
        records.append(
            CaseMatrixRecord(
                case_id=item.case_id,
                split="dev",
                task_version=item.task_version,
                material_status=item.material_status,
                baseline_record=baseline_eval,
                candidate_sql=candidate_sql,
                snapshots=tuple(rows),
                applicable_snapshots=tuple(
                    row.snapshot_id for row in rows if row.applicable == "applicable"
                ),
            )
        )
    integrity = date_unchanged and all(item.split == "dev" for item in records)
    return MatrixRunReport(
        replay_mode=replay_mode,
        agent_id=agent_id,
        integrity_passed=integrity,
        agent_invoked=agent_invoked,
        date_dimension_unchanged=date_unchanged,
        baseline_manifest_hash=digest(baseline_manifest.model_dump(mode="json")),
        variant_manifest_hashes=variant_hashes,
        compilable_answers=compilable,
        independent_oracle_matches=independent_matches,
        limitations=LIMITATIONS,
        cases=tuple(records),
    )
