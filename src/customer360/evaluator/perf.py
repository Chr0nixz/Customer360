"""Collect Standard/Large (and Tiny control) performance baselines. Not a score."""

from __future__ import annotations

import math
import os
import platform
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from customer360.artifacts import digest, write_json_new, write_jsonl_new
from customer360.contracts.budget import (
    BudgetName,
    budget_for_scale,
    limits_for_manifest,
    require_budget_matches_manifest,
)
from customer360.contracts.generation import DatasetManifest, Scale
from customer360.contracts.oracle import PrivateCase
from customer360.contracts.perf import (
    PUBLIC_PERF_FORBIDDEN,
    ROADMAP_TARGET_MS,
    UNAVAILABLE,
    PerfBaselineReport,
    PerfEnvironment,
    PerfQueryRecord,
    PublicPerfSummary,
)
from customer360.contracts.public import AgentRequest
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.evaluator.matrix import resolve_eval_agent
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import (
    customer_ids_from_database,
    eval_policy_for_dataset,
)
from customer360.synth.generator import generate_dataset, load_generation_config
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.trusted_data import load_verified_dataset

LIMITATIONS = (
    "Not an official score; ROADMAP section 8 weights are not applied",
    "P50/P95 are diagnostics against ROADMAP latency targets, not a grade",
    "Scan count is unavailable and must not be reported as 0",
    "Local baseline has no tokenizer; token_status stays unavailable",
    "Tiny default materialization cap remains 10000 rows",
    "Zero-contributor Gold is POLICY_INCOMPATIBLE, not a resource miss",
    "Same semantic spec on Standard/Large changes business totals; not a Tiny regression",
    "Default pytest stays Tiny-only; Large is an explicit command",
    "Public summary omits questions, Gold, specs, SQL and dataset seeds",
)

HIDDEN_PROFILE = "hidden_profile.json"


def _percentile(samples: tuple[float, ...], pct: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _total_memory_mb() -> tuple[int | None, str]:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page / (1024 * 1024)), "available"
    except (AttributeError, OSError, ValueError):
        return None, UNAVAILABLE


def collect_environment() -> PerfEnvironment:
    memory_mb, memory_status = _total_memory_mb()
    return PerfEnvironment(
        python=platform.python_version(),
        platform=platform.platform(),
        machine=platform.machine() or "unknown",
        cpu_count=os.cpu_count(),
        memory_total_mb=memory_mb,
        memory_total_status=memory_status,  # type: ignore[arg-type]
        duckdb=version("duckdb"),
        pydantic=version("pydantic"),
        sqlglot=version("sqlglot"),
    )


def _targets(p95: float | None) -> dict[str, bool | None]:
    if p95 is None:
        return {
            "p95_vs_simple_target": None,
            "p95_vs_medium_target": None,
            "p95_vs_complex_target": None,
        }
    return {
        "p95_vs_simple_target": p95 <= ROADMAP_TARGET_MS["simple_p95_ms"],
        "p95_vs_medium_target": p95 <= ROADMAP_TARGET_MS["medium_p95_ms"],
        "p95_vs_complex_target": p95 <= ROADMAP_TARGET_MS["complex_p95_ms"],
    }


def _load_generated(dataset_dir: Path) -> tuple[Path, DatasetManifest]:
    if (dataset_dir / HIDDEN_PROFILE).is_file():
        raise ValueError("perf-baseline does not run on hidden Tiny")
    database, manifest = load_verified_dataset(dataset_dir)
    if not isinstance(manifest, DatasetManifest):
        raise ValueError("perf-baseline requires a generated dataset, not a variant")
    return database, manifest


def _status_for_execution(code: str) -> str:
    mapping = {
        "TIMEOUT": "timeout",
        "INPUT_LIMIT": "input_limit",
        "WORKER_CRASH": "execution_error",
        "EXECUTION_ERROR": "execution_error",
    }
    return mapping.get(code, "rejected")


def collect_generate(
    *,
    scale: Scale,
    seed: int,
    dataset_dir: Path,
    config: Path,
) -> tuple[PerfBaselineReport, list[dict]]:
    started = perf_counter()
    generation = load_generation_config(config, scale=scale, seed=seed)
    manifest, quality = generate_dataset(generation, dataset_dir)
    elapsed_ms = (perf_counter() - started) * 1000
    parsed = DatasetManifest.model_validate(manifest)
    require_budget_matches_manifest(budget_for_scale(parsed.scale), parsed)
    report = PerfBaselineReport(
        workload="generate",
        budget_profile=parsed.scale,
        dataset_scale=parsed.scale,
        dataset_manifest_hash=digest(parsed.model_dump(mode="json")),
        query_count=0,
        success_count=0,
        failure_count=0,
        skipped_count=0,
        elapsed_ms=elapsed_ms,
        integrity_passed=quality["all_passed"] is True,
        all_passed=quality["all_passed"],
        row_counts=parsed.row_counts,
        environment=collect_environment(),
        limitations=LIMITATIONS,
        **_targets(None),
    )
    private = [
        {
            "workload": "generate",
            "elapsed_ms": elapsed_ms,
            "all_passed": quality["all_passed"],
            "row_counts": parsed.row_counts,
            "budget_profile": parsed.scale,
        }
    ]
    return report, private


def collect_gold_execute(
    dataset_dir: Path, *, oracles: Path | None = None
) -> tuple[PerfBaselineReport, list[dict]]:
    database, manifest = _load_generated(dataset_dir)
    budget: BudgetName = budget_for_scale(manifest.scale)
    require_budget_matches_manifest(budget, manifest)
    limits = limits_for_manifest(manifest)
    policy = eval_policy_for_dataset(manifest, customer_ids_from_database(database))
    gateway = ExecutionGateway(database, policy, limits)
    repository = MetadataRepository()
    catalog = load_human_cases(oracles=oracles)
    queries: list[PerfQueryRecord] = []
    private: list[dict] = []
    started = perf_counter()
    for case in catalog.cases:
        if case.material_status != "compilable_answer":
            queries.append(
                PerfQueryRecord(
                    case_id=case.case_id, status="skipped", elapsed_ms=0, reason_code=None
                )
            )
            private.append({"case_id": case.case_id, "status": "skipped"})
            continue
        spec = case.semantic_spec()
        compiled = compile_semantic(spec, repository)
        query_started = perf_counter()
        try:
            receipt = gateway.execute(compiled.sql)
            elapsed = (perf_counter() - query_started) * 1000
            status = "ok"
            reason = None
            if receipt.result.truncated:
                status = "execution_error"
                reason = "TRUNCATED"
            record = PerfQueryRecord(
                case_id=case.case_id,
                status=status,  # type: ignore[arg-type]
                reason_code=reason,
                elapsed_ms=elapsed,
                truncated=receipt.result.truncated,
                row_count=len(receipt.result.rows),
            )
            private.append(
                {
                    "case_id": case.case_id,
                    "status": status,
                    "elapsed_ms": elapsed,
                    "truncated": receipt.result.truncated,
                    "sql": compiled.sql,
                    "query_id": receipt.query_id,
                }
            )
        except ExecutionFailure as exc:
            elapsed = (perf_counter() - query_started) * 1000
            record = PerfQueryRecord(
                case_id=case.case_id,
                status=_status_for_execution(exc.code),  # type: ignore[arg-type]
                reason_code=exc.code,
                elapsed_ms=elapsed,
            )
            private.append(
                {
                    "case_id": case.case_id,
                    "status": record.status,
                    "reason_code": exc.code,
                    "elapsed_ms": elapsed,
                    "sql": compiled.sql,
                }
            )
        except QueryRejected as exc:
            elapsed = (perf_counter() - query_started) * 1000
            if exc.code == "AGGREGATION_TOO_SMALL":
                status = "skipped"
                reason = "POLICY_INCOMPATIBLE"
            else:
                status = "rejected"
                reason = exc.code
            record = PerfQueryRecord(
                case_id=case.case_id,
                status=status,  # type: ignore[arg-type]
                reason_code=reason,
                elapsed_ms=elapsed,
            )
            private.append(
                {
                    "case_id": case.case_id,
                    "status": status,
                    "reason_code": reason,
                    "elapsed_ms": elapsed,
                    "sql": compiled.sql,
                }
            )
        queries.append(record)
    elapsed_ms = (perf_counter() - started) * 1000
    timed = tuple(item.elapsed_ms for item in queries if item.status != "skipped")
    p50 = _percentile(timed, 50)
    p95 = _percentile(timed, 95)
    success = sum(item.status == "ok" for item in queries)
    skipped = sum(item.status == "skipped" for item in queries)
    failure = len(queries) - success - skipped
    reasons = tuple(item.reason_code for item in queries if item.reason_code is not None)
    report = PerfBaselineReport(
        workload="gold_execute",
        budget_profile=budget,
        dataset_scale=manifest.scale,
        dataset_manifest_hash=digest(manifest.model_dump(mode="json")),
        query_count=len(queries),
        success_count=success,
        failure_count=failure,
        skipped_count=skipped,
        elapsed_ms=elapsed_ms,
        p50_ms=p50,
        p95_ms=p95,
        integrity_passed=failure == 0,
        reason_codes=reasons,
        environment=collect_environment(),
        limitations=LIMITATIONS,
        queries=tuple(queries),
        **_targets(p95),
    )
    return report, private


def collect_evaluate(
    dataset_dir: Path, *, agent_id: str, oracles: Path | None = None
) -> tuple[PerfBaselineReport, list[dict]]:
    if agent_id == "scoring":
        raise ValueError("robustness scoring is not enabled; scoring_applied remains false")
    agent = resolve_eval_agent(agent_id)
    database, manifest = _load_generated(dataset_dir)
    budget: BudgetName = budget_for_scale(manifest.scale)
    require_budget_matches_manifest(budget, manifest)
    limits = limits_for_manifest(manifest)
    policy = eval_policy_for_dataset(manifest, customer_ids_from_database(database))
    gateway = ExecutionGateway(database, policy, limits)
    repository = MetadataRepository()
    catalog = load_human_cases(oracles=oracles)
    queries: list[PerfQueryRecord] = []
    private: list[dict] = []
    started = perf_counter()
    for item in catalog.cases:
        case = PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.question,
                anchor_date=manifest.anchor_date,
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=item.oracle(),
            task_version=item.task_version,
        )
        evaluation = evaluate_case(case, agent, gateway, repository)
        status = "ok" if evaluation.outcome == "pass" else "execution_error"
        if evaluation.reason_code == "TIMEOUT":
            status = "timeout"
        elif evaluation.reason_code == "INPUT_LIMIT":
            status = "input_limit"
        elif evaluation.outcome == "error":
            status = "execution_error"
        elif evaluation.outcome == "fail":
            status = "rejected"
        truncated = any(
            receipt.truncated
            for round_audit in evaluation.rounds
            for receipt in round_audit.receipts
        )
        if truncated:
            status = "execution_error"
        record = PerfQueryRecord(
            case_id=item.case_id,
            status=status,  # type: ignore[arg-type]
            reason_code=evaluation.reason_code,
            elapsed_ms=evaluation.elapsed_ms,
            truncated=truncated,
        )
        queries.append(record)
        dumped = evaluation.model_dump(mode="json")
        dumped["budget_profile"] = budget
        private.append(dumped)
    elapsed_ms = (perf_counter() - started) * 1000
    timed = tuple(item.elapsed_ms for item in queries)
    p50 = _percentile(timed, 50)
    p95 = _percentile(timed, 95)
    success = sum(item.status == "ok" for item in queries)
    failure = len(queries) - success
    reasons = tuple(item.reason_code for item in queries if item.reason_code is not None)
    report = PerfBaselineReport(
        workload="evaluate",
        budget_profile=budget,
        dataset_scale=manifest.scale,
        dataset_manifest_hash=digest(manifest.model_dump(mode="json")),
        agent_id=agent_id,
        query_count=len(queries),
        success_count=success,
        failure_count=failure,
        skipped_count=0,
        elapsed_ms=elapsed_ms,
        p50_ms=p50,
        p95_ms=p95,
        integrity_passed=failure == 0,
        reason_codes=reasons,
        environment=collect_environment(),
        limitations=LIMITATIONS,
        queries=tuple(queries),
        **_targets(p95),
    )
    return report, private


def public_perf_summary(report: PerfBaselineReport) -> PublicPerfSummary:
    env = report.environment
    return PublicPerfSummary(
        workload=report.workload,
        budget_profile=report.budget_profile,
        dataset_scale=report.dataset_scale,
        query_count=report.query_count,
        success_count=report.success_count,
        failure_count=report.failure_count,
        elapsed_ms=report.elapsed_ms,
        p50_ms=report.p50_ms,
        p95_ms=report.p95_ms,
        integrity_passed=report.integrity_passed,
        all_passed=report.all_passed,
        row_counts=report.row_counts,
        reason_codes=report.reason_codes,
        roadmap_targets_ms=report.roadmap_targets_ms,
        p95_vs_simple_target=report.p95_vs_simple_target,
        p95_vs_medium_target=report.p95_vs_medium_target,
        p95_vs_complex_target=report.p95_vs_complex_target,
        agent_id=report.agent_id,
        hardware={
            "platform": env.platform,
            "machine": env.machine,
            "cpu_count": env.cpu_count,
            "memory_total_mb": env.memory_total_mb,
            "memory_total_status": env.memory_total_status,
        },
        versions={
            "python": env.python,
            "duckdb": env.duckdb,
            "pydantic": env.pydantic,
            "sqlglot": env.sqlglot,
        },
        limitations=report.limitations,
    )


def _markdown(summary: PublicPerfSummary) -> str:
    lines = [
        "# Customer360 performance baseline",
        "",
        "Desensitized public summary. Not an official score.",
        "",
        f"- integrity_passed: `{summary.integrity_passed}`",
        f"- workload: `{summary.workload}`",
        f"- budget_profile: `{summary.budget_profile}`",
        f"- dataset_scale: `{summary.dataset_scale}`",
        f"- scoring_applied: `{summary.scoring_applied}`",
        f"- query_count: `{summary.query_count}`",
        f"- success_count: `{summary.success_count}`",
        f"- failure_count: `{summary.failure_count}`",
        f"- p50_ms: `{summary.p50_ms}`",
        f"- p95_ms: `{summary.p95_ms}`",
        f"- scan_count_status: `{summary.scan_count_status}`",
        f"- token_status: `{summary.token_status}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in summary.limitations)
    lines.append("")
    return "\n".join(lines)


def write_perf_run(
    output_dir: Path, report: PerfBaselineReport, private_records: list[dict]
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    private_dir = output_dir / "private"
    public_dir = output_dir / "public"
    private_dir.mkdir()
    public_dir.mkdir()
    summary = public_perf_summary(report)
    write_json_new(private_dir / "perf.json", report.model_dump(mode="json"))
    write_jsonl_new(private_dir / "records.jsonl", private_records)
    write_json_new(public_dir / "summary.json", summary.model_dump(mode="json"))
    (public_dir / "summary.md").write_text(_markdown(summary), encoding="utf-8", newline="\n")
    public_text = (public_dir / "summary.json").read_text(encoding="utf-8")
    for field in PUBLIC_PERF_FORBIDDEN:
        if f'"{field}"' in public_text:
            raise ValueError(f"public performance artifacts leaked {field}")
    if '"scan_count"' in public_text:
        raise ValueError("public performance artifacts must not invent a scan_count")
    return {
        "integrity_passed": report.integrity_passed,
        "scoring_applied": report.scoring_applied,
        "workload": report.workload,
        "budget_profile": report.budget_profile,
        "dataset_scale": report.dataset_scale,
        "query_count": report.query_count,
        "success_count": report.success_count,
        "failure_count": report.failure_count,
        "p50_ms": report.p50_ms,
        "p95_ms": report.p95_ms,
        "scan_count_status": report.scan_count_status,
        "token_status": report.token_status,
    }
