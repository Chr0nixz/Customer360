"""Evaluate an independent hidden pack on isolated Tiny data. No official score."""

from datetime import date
from pathlib import Path

from customer360.agent.protocol import Agent
from customer360.artifacts import digest, write_json_new, write_jsonl_new
from customer360.contracts.generation import DatasetManifest
from customer360.contracts.hidden import (
    PUBLIC_HIDDEN_FORBIDDEN,
    HiddenEvalRecord,
    HiddenEvalReport,
    HiddenVariantReplay,
    PublicHiddenSummary,
)
from customer360.contracts.hidden_variant import HIDDEN_VARIANT_IDS, HiddenVariantManifest
from customer360.contracts.oracle import (
    AnswerOracle,
    ClarificationOracle,
    PrivateCase,
    RefusalOracle,
)
from customer360.contracts.public import AgentRequest
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import benchmark_eval_policy, customer_ids_from_database
from customer360.tasks.hidden import load_hidden_dataset, load_hidden_pack
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset

ANCHOR = date(2025, 6, 30)
LIMITATIONS = (
    "Hidden evaluation is not an official score; ROADMAP section 8 weights are not applied",
    "Hidden cases are independent of C360_0001-0020 and public train/dev families",
    "Public summary omits questions, Gold, specs, candidate SQL and the hidden seed",
    "Docker and external model network remain deferred",
)


def _oracle(item) -> AnswerOracle | ClarificationOracle | RefusalOracle:
    if item.expected_action == "answer":
        return AnswerOracle(semantic_spec=item.semantic_spec())
    if item.expected_action == "clarification_needed":
        return ClarificationOracle(replies=item.slot_replies, completed_spec=item.semantic_spec())
    return RefusalOracle(accepted_reason_codes=item.accepted_reason_codes)


def _candidate_sql(evaluation) -> tuple[str | None, bool, object | None]:
    for audit in reversed(evaluation.rounds):
        if audit.receipts:
            receipt = audit.receipts[-1]
            return receipt.sql, receipt.truncated, receipt.result
        for call in reversed(audit.tool_calls):
            if call.tool == "execute_sql" and call.rejection_code == "UNSAFE_SQL":
                return None, False, None
    return None, False, None


def _load_variant_dirs(
    variant_dirs: tuple[Path, ...], parent_manifest: DatasetManifest
) -> tuple[tuple[str, Path, DatasetManifest], ...]:
    if len(variant_dirs) != len(HIDDEN_VARIANT_IDS):
        raise ValueError("formal hidden evaluation requires exactly four --variant paths")
    expected_parent = digest(parent_manifest.model_dump(mode="json"))
    loaded: list[tuple[str, Path, DatasetManifest]] = []
    for expected_id, path in zip(HIDDEN_VARIANT_IDS, variant_dirs, strict=True):
        private_path = path / "hidden_variant_manifest.json"
        if not private_path.is_file():
            raise ValueError(f"hidden variant is missing hidden_variant_manifest.json: {path}")
        private = HiddenVariantManifest.model_validate_json(
            private_path.read_text(encoding="utf-8")
        )
        if private.variant_id != expected_id:
            raise ValueError("hidden variants must be supplied in frozen order")
        if private.parent_manifest_hash != expected_parent:
            raise ValueError("hidden variant parent manifest does not match baseline")
        database, manifest = load_verified_dataset(path)
        if not isinstance(manifest, DatasetManifest):
            raise ValueError("hidden variants must use generated Tiny manifests")
        if manifest.catalog_hash != parent_manifest.catalog_hash:
            raise ValueError("hidden variant catalog hash does not match baseline")
        if manifest.content_hashes["dim_date"] != parent_manifest.content_hashes["dim_date"]:
            raise ValueError("hidden variant date dimension must match baseline")
        if private.manifest_hash != digest(manifest.model_dump(mode="json")):
            raise ValueError("hidden variant manifest digest mismatch")
        loaded.append((expected_id, database, manifest))
    return tuple(loaded)


def _replay_variant(
    variant_id: str,
    gateway: ExecutionGateway,
    sql: str | None,
    independent,
    baseline_result,
) -> HiddenVariantReplay:
    if not sql:
        return HiddenVariantReplay(
            variant_id=variant_id,
            applicable="not_applicable",
            outcome="skipped",
            reason_code="NO_CANDIDATE_SQL",
        )
    try:
        receipt = gateway.execute(sql)
    except QueryRejected as exc:
        if exc.code == "AGGREGATION_TOO_SMALL":
            return HiddenVariantReplay(
                variant_id=variant_id,
                applicable="policy_incompatible",
                outcome="skipped",
                reason_code="POLICY_INCOMPATIBLE",
            )
        return HiddenVariantReplay(
            variant_id=variant_id,
            applicable="applicable",
            outcome="fail",
            reason_code=exc.code,
            sql_replayed=True,
            independent_match=False,
        )
    except ExecutionFailure as exc:
        code = (
            exc.code
            if exc.code in {"TIMEOUT", "WORKER_CRASH", "EXECUTION_ERROR"}
            else "EXECUTION_ERROR"
        )
        return HiddenVariantReplay(
            variant_id=variant_id,
            applicable="applicable",
            outcome="fail",
            reason_code=code,
            sql_replayed=True,
            independent_match=False,
        )
    if receipt.result.truncated:
        return HiddenVariantReplay(
            variant_id=variant_id,
            applicable="applicable",
            outcome="fail",
            reason_code="UNVERIFIED_RESULT",
            sql_replayed=True,
            truncated=True,
            independent_match=False,
        )
    matched = independent is not None and compare_results(receipt.result, independent)
    differs = baseline_result is not None and not compare_results(receipt.result, baseline_result)
    return HiddenVariantReplay(
        variant_id=variant_id,
        applicable="applicable",
        outcome="pass" if matched else "fail",
        reason_code="OK" if matched else "RESULT_MISMATCH",
        sql_replayed=True,
        independent_match=matched,
        differs_from_baseline=differs,
    )


def evaluate_hidden_pack(
    dataset_dir: Path,
    pack_dir: Path,
    agent: Agent,
    *,
    agent_id: str,
    variant_dirs: tuple[Path, ...] = (),
) -> tuple[HiddenEvalReport, list[dict]]:
    pack = load_hidden_pack(pack_dir)
    _database, manifest, profile = load_hidden_dataset(dataset_dir)
    repository = MetadataRepository()
    if (
        pack.metrics_version != repository.metrics.metrics_version
        or pack.join_paths_version != repository.join_paths.join_paths_version
    ):
        raise ValueError("hidden pack metadata version does not match the repository")
    policy = benchmark_eval_policy(manifest, customer_ids_from_database(_database))
    gateway = ExecutionGateway(_database, policy)
    variants = _load_variant_dirs(variant_dirs, manifest) if variant_dirs else ()
    variant_gateways = {
        variant_id: ExecutionGateway(
            database,
            benchmark_eval_policy(child_manifest, customer_ids_from_database(database)),
        )
        for variant_id, database, child_manifest in variants
    }
    slices = {"baseline": load_table_slices(_database, repository.catalog)}
    slices.update(
        {
            variant_id: load_table_slices(database, repository.catalog)
            for variant_id, database, _manifest in variants
        }
    )
    records: list[HiddenEvalRecord] = []
    private_records = []
    compilable = 0
    for item in pack.cases:
        if item.material_status == "compilable_answer":
            compilable += 1
        case = PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.question,
                anchor_date=ANCHOR,
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=_oracle(item),
            task_version="hidden-0.1",
        )
        evaluation = evaluate_case(case, agent, gateway, repository)
        candidate_sql, truncated, baseline_result = _candidate_sql(evaluation)
        replays: tuple[HiddenVariantReplay, ...] = ()
        if variants:
            replays = tuple(
                _replay_variant(
                    variant_id,
                    variant_gateways[variant_id],
                    candidate_sql,
                    compute_independent(item.semantic_spec(), repository, slices[variant_id])
                    if item.material_status == "compilable_answer"
                    else None,
                    baseline_result,
                )
                for variant_id, _database, _manifest in variants
            )
        private_payload = evaluation.model_dump(mode="json")
        private_payload["candidate_sql"] = candidate_sql
        private_payload["candidate_truncated"] = truncated
        private_payload["variant_replays"] = [row.model_dump(mode="json") for row in replays]
        private_records.append(private_payload)
        records.append(
            HiddenEvalRecord(
                case_id=item.case_id,
                outcome=evaluation.outcome,
                reason_code=evaluation.reason_code,
                material_status=item.material_status,
                agent_status=evaluation.agent_status,
                agent_policy_violation=evaluation.agent_policy_violation,
                variant_replays=replays,
            )
        )
    integrity = (
        pack.hidden is True
        and pack.scoring_applied is False
        and profile.seed == manifest.seed
        and all(item.split == "private" for item in pack.cases)
        and all(int(item.case_id[5:]) >= 4001 for item in pack.cases)
    )
    report = HiddenEvalReport(
        agent_id=agent_id,
        case_count=len(records),
        compilable_answers=compilable,
        integrity_passed=integrity,
        data_seed=profile.seed,
        limitations=LIMITATIONS,
        cases=tuple(records),
        variant_ids=tuple(item[0] for item in variants),
        formal_replay=bool(variants),
    )
    return report, private_records


def public_hidden_summary(report: HiddenEvalReport) -> PublicHiddenSummary:
    return PublicHiddenSummary(
        agent_id=report.agent_id,
        case_count=report.case_count,
        compilable_answers=report.compilable_answers,
        integrity_passed=report.integrity_passed,
        limitations=report.limitations,
    )


def write_hidden_run(
    output_dir: Path, report: HiddenEvalReport, private_records: list[dict]
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    private_dir = output_dir / "private"
    public_dir = output_dir / "public"
    private_dir.mkdir()
    public_dir.mkdir()
    summary = public_hidden_summary(report)
    write_json_new(private_dir / "hidden.json", report.model_dump(mode="json"))
    write_jsonl_new(private_dir / "records.jsonl", private_records)
    write_json_new(public_dir / "summary.json", summary.model_dump(mode="json"))
    public_text = (public_dir / "summary.json").read_text(encoding="utf-8")
    for field in PUBLIC_HIDDEN_FORBIDDEN:
        if f'"{field}"' in public_text:
            raise ValueError(f"public hidden artifacts leaked {field}")
    if str(report.data_seed) in public_text:
        raise ValueError("public hidden artifacts leaked the hidden seed")
    return {
        "integrity_passed": report.integrity_passed,
        "scoring_applied": report.scoring_applied,
        "hidden": True,
        "case_count": report.case_count,
        "agent_id": report.agent_id,
    }
