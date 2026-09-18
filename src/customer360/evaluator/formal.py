"""Trusted formal evaluation: frozen roster, Gold applicability, same-SQL replay."""

from datetime import date
from pathlib import Path

from customer360 import __version__
from customer360.artifacts import digest, write_json_new
from customer360.contracts.budget import limits_for_manifest
from customer360.contracts.formal import FormalCase, FormalEvaluationReport, FormalSnapshot
from customer360.contracts.oracle import (
    AnswerOracle,
    ClarificationOracle,
    PrivateCase,
    RefusalOracle,
)
from customer360.contracts.public import AgentRequest, Refusal, Success
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.perf import collect_environment
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import benchmark_eval_policy, customer_ids_from_database
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.generator import load_generated_pack
from customer360.tasks.hidden import load_hidden_dataset, load_hidden_pack
from customer360.tasks.hidden_variants import load_hidden_variant_paths
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import normalize_sql_result
from customer360.tasks.variant import load_baseline_tiny, load_named_variant


def case_oracle(item):
    if item.expected_action == "answer":
        return AnswerOracle(semantic_spec=item.semantic_spec())
    if item.expected_action == "clarification_needed":
        return ClarificationOracle(replies=item.slot_replies, completed_spec=item.semantic_spec())
    return RefusalOracle(accepted_reason_codes=item.accepted_reason_codes)


def final_receipt(evaluation):
    """Only the receipt bound to the final response counts, never a tool probe."""
    final = evaluation.rounds[-1].response if evaluation.rounds else None
    if not isinstance(final, Success):
        return final, None
    for audit in evaluation.rounds:
        for receipt in audit.receipts:
            if receipt.query_id == final.query_id and receipt.sql == final.sql:
                return final, receipt
    return final, None


def _reference(snapshot_id, item, database, gateway, repository, slices, *, execute_gateway=True):
    compiled = compile_semantic(item.semantic_spec(), repository)
    independent = compute_independent(item.semantic_spec(), repository, slices)
    # Oracle correctness is checked even for a policy-incompatible snapshot.
    if not compare_results(normalize_sql_result(database, compiled), independent):
        raise ValueError("formal Gold disagrees with independent oracle")
    try:
        receipt = gateway.execute(compiled.sql) if execute_gateway else None
    except QueryRejected as exc:
        if exc.code == "AGGREGATION_TOO_SMALL":
            return independent, FormalSnapshot(
                snapshot_id=snapshot_id, applicable=False, policy_code=exc.code
            )
        raise ValueError(f"formal Gold rejected: {exc.code}") from exc
    except ExecutionFailure as exc:
        raise ValueError(f"formal Gold execution failed: {exc.code}") from exc
    if receipt is not None and (
        receipt.result.truncated or not compare_results(receipt.result, independent)
    ):
        raise ValueError("formal Gold gateway result is truncated or inconsistent")
    return independent, None


def _replay(snapshot_id, gateway, sql, independent, baseline_result):
    if sql is None:
        return FormalSnapshot(
            snapshot_id=snapshot_id, applicable=True, execution_code="MISSING_RESULT"
        )
    try:
        receipt = gateway.execute(sql)
    except (QueryRejected, ExecutionFailure) as exc:
        # Candidate rejection cannot change Gold applicability or its denominator.
        return FormalSnapshot(snapshot_id=snapshot_id, applicable=True, execution_code=exc.code)
    return FormalSnapshot(
        snapshot_id=snapshot_id,
        applicable=True,
        independent_match=not receipt.result.truncated
        and compare_results(receipt.result, independent),
        truncated=receipt.result.truncated,
        execution_code="UNVERIFIED_RESULT" if receipt.result.truncated else None,
        differs=(
            not compare_results(receipt.result, baseline_result)
            if baseline_result is not None
            else None
        ),
    )


def evaluate_formal(dataset_dir, pack_dir, variant_dirs, agent, *, agent_id, hidden=False):
    """One baseline conversation per case; variants never invoke Agent.respond."""
    repository = MetadataRepository()
    if hidden:
        database, manifest, _profile = load_hidden_dataset(dataset_dir)
        pack = load_hidden_pack(pack_dir)
        _parent, variant_set, loaded = load_hidden_variant_paths(dataset_dir, variant_dirs)
        children = tuple((name, db, child) for name, db, child, _private in loaded)
        cases = pack.cases
        split = "private_hidden"
        provenance = {"variant_set": digest(variant_set.model_dump(mode="json"))}
    else:
        database, manifest = load_baseline_tiny(dataset_dir)
        pack = load_generated_pack(pack_dir)
        cases = tuple(item for item in pack.cases if item.split == "dev")
        if not pack.m6_structure or pack.case_count != 300 or len(cases) != 120:
            raise ValueError("formal public evaluation requires generated-dev 120 of 300 cases")
        loaded = tuple(load_named_variant(path) for path in variant_dirs)
        if tuple(row[2] for row in loaded) != SEMANTIC_VERIFY_VARIANT_IDS:
            raise ValueError("formal public evaluation requires four ordered public variants")
        children = tuple((name, db, child) for db, child, name, _seed in loaded)
        split = "public_dev"
        provenance = {}
    if (
        pack.metrics_version != repository.metrics.metrics_version
        or pack.join_paths_version != repository.join_paths.join_paths_version
    ):
        raise ValueError("formal task metadata does not match bundled repository")
    snapshots = (("baseline", database, manifest), *children)
    gateways, slices = {}, {}
    for name, db, child in snapshots:
        if child.catalog_hash != manifest.catalog_hash:
            raise ValueError("formal snapshot catalog mismatch")
        if child.content_hashes["dim_date"] != manifest.content_hashes["dim_date"]:
            raise ValueError("formal snapshot date dimension mismatch")
        policy = benchmark_eval_policy(manifest, customer_ids_from_database(db))
        gateways[name] = ExecutionGateway(db, policy, limits_for_manifest(manifest))
        slices[name] = load_table_slices(db, repository.catalog)
        provenance[name] = digest(child.model_dump(mode="json"))
    records = []
    for item in cases:
        references = {}
        if item.expected_action != "refuse":
            for name, db, _ in snapshots:
                references[name] = _reference(
                    name,
                    item,
                    db,
                    gateways[name],
                    repository,
                    slices[name],
                    execute_gateway=name == "baseline",
                )
        private = PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.question,
                anchor_date=date(2025, 6, 30),
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=case_oracle(item),
            task_version=item.task_version,
        )
        evaluation = evaluate_case(private, agent, gateways["baseline"], repository).model_copy(
            update={"evaluator_version": "0.6"}
        )
        final, receipt = final_receipt(evaluation)
        sql = receipt.sql if receipt and not receipt.truncated else None
        baseline_result = receipt.result if receipt else None
        rows = []
        for name, (independent, blocked) in references.items():
            if blocked is not None:
                rows.append(blocked)
            elif name == "baseline":
                rows.append(
                    FormalSnapshot(
                        snapshot_id=name,
                        applicable=True,
                        independent_match=bool(
                            receipt
                            and not receipt.truncated
                            and receipt.result
                            and compare_results(receipt.result, independent)
                        ),
                        truncated=bool(receipt and receipt.truncated),
                        execution_code=None if sql else "MISSING_RESULT",
                    )
                )
            else:
                rows.append(_replay(name, gateways[name], sql, independent, baseline_result))
        interaction = evaluation.outcome == "pass"
        if item.expected_action == "answer":
            interaction = isinstance(final, Success)
        format_ok = isinstance(final, Refusal) if item.expected_action == "refuse" else bool(sql)
        evidence_ok = bool(
            final
            and (
                isinstance(final, Success)
                and final.evidence
                and receipt
                or isinstance(final, Refusal)
                and final.reason
                and final.alternative
            )
        )
        records.append(
            FormalCase(
                case_id=item.case_id,
                expected_action=item.expected_action,
                evaluation=evaluation,
                snapshots=tuple(rows),
                format_passed=format_ok,
                evidence_passed=evidence_ok,
                interaction_passed=interaction,
            )
        )
    provenance["task_pack"] = digest(pack.model_dump(mode="json"))
    return FormalEvaluationReport(
        split=split,
        agent_id=agent_id,
        agent_version=__version__,
        case_count=len(records),
        case_ids=tuple(item.case_id for item in records),
        snapshot_ids=tuple(item[0] for item in snapshots),
        integrity_passed=True,
        data_version=manifest.snapshot_version,
        task_version=pack.task_version,
        metadata_version=repository.metrics.metrics_version,
        input_digests=provenance,
        environment={
            **collect_environment().model_dump(mode="json"),
            "concurrency": 1,
            "cache": "disabled",
            "retries": 0,
            "model": "local/offline",
        },
        cases=tuple(records),
    )


def write_formal_input(output_dir: Path, report: FormalEvaluationReport) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "private").mkdir()
    (output_dir / "public").mkdir()
    write_json_new(output_dir / "private/formal_input.json", report.model_dump(mode="json"))
    # Explicit allowlist: no private IDs, question, SQL, rows, paths or digests.
    summary = {
        "score_protocol_version": "1.0",
        "split": report.split,
        "agent_id": report.agent_id,
        "case_count": report.case_count,
        "integrity_passed": report.integrity_passed,
        "scoring_applied": False,
        "ranking_enabled": False,
    }
    write_json_new(output_dir / "public/summary.json", summary)
    return summary
