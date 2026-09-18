"""Performance baseline reports. Not an official score and not a scan statistic."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.budget import BudgetName
from customer360.contracts.generation import Scale

PerfWorkload = Literal["generate", "gold_execute", "evaluate"]
UNAVAILABLE = "unavailable"

PUBLIC_PERF_FIELDS = frozenset(
    {
        "protocol_version",
        "report_kind",
        "scoring_applied",
        "workload",
        "budget_profile",
        "dataset_scale",
        "query_count",
        "success_count",
        "failure_count",
        "p50_ms",
        "p95_ms",
        "elapsed_ms",
        "scan_count_status",
        "token_status",
        "peak_rss_status",
        "concurrency",
        "limitations",
        "roadmap_targets_ms",
        "p95_vs_simple_target",
        "p95_vs_medium_target",
        "p95_vs_complex_target",
        "integrity_passed",
        "all_passed",
        "row_counts",
        "reason_codes",
        "agent_id",
        "hardware",
        "versions",
    }
)
PUBLIC_PERF_FORBIDDEN = frozenset(
    {
        "question",
        "rewrites",
        "semantic_spec",
        "sql",
        "compiled_sql",
        "gold",
        "expected_action",
        "seed",
        "hidden_seed",
        "dataset_seed",
        "candidate_sql",
        "missing_slots",
        "slot_replies",
        "completed_spec",
        "independent_result",
        "family",
        "family_id",
        "metric",
        "filters",
        "time_window",
        "join",
    }
)

ROADMAP_TARGET_MS = {
    "simple_p95_ms": 30_000,
    "medium_p95_ms": 90_000,
    "complex_p95_ms": 180_000,
}


class PerfQueryRecord(Contract):
    case_id: Text
    status: Literal["ok", "timeout", "input_limit", "execution_error", "rejected", "skipped"]
    reason_code: Text | None = None
    elapsed_ms: float = Field(ge=0)
    truncated: bool = False
    row_count: int | None = Field(default=None, ge=0)


class PerfEnvironment(Contract):
    python: Text
    platform: Text
    machine: Text
    cpu_count: int | None = None
    memory_total_mb: int | None = None
    memory_total_status: Literal["available", "unavailable"] = UNAVAILABLE
    duckdb: Text
    pydantic: Text
    sqlglot: Text
    concurrency: Literal[1] = 1
    cache: Literal["duckdb_default"] = "duckdb_default"


class PerfBaselineReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["perf_baseline"] = "perf_baseline"
    scoring_applied: Literal[False] = False
    workload: PerfWorkload
    budget_profile: BudgetName
    dataset_scale: Scale | None = None
    dataset_manifest_hash: Text | None = None
    agent_id: Identifier | None = None
    query_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None
    scan_count_status: Literal["unavailable"] = UNAVAILABLE
    token_status: Literal["unavailable"] = UNAVAILABLE
    peak_rss_status: Literal["unavailable"] = UNAVAILABLE
    integrity_passed: bool
    all_passed: bool | None = None
    row_counts: dict[str, int] | None = None
    reason_codes: tuple[Text, ...] = ()
    roadmap_targets_ms: dict[str, int] = Field(default_factory=lambda: dict(ROADMAP_TARGET_MS))
    p95_vs_simple_target: bool | None = None
    p95_vs_medium_target: bool | None = None
    p95_vs_complex_target: bool | None = None
    environment: PerfEnvironment
    limitations: tuple[Text, ...]
    queries: tuple[PerfQueryRecord, ...] = ()

    @model_validator(mode="after")
    def no_official_score_or_fake_scan(self) -> "PerfBaselineReport":
        if self.scoring_applied:
            raise ValueError("performance baseline cannot apply official scores")
        if self.scan_count_status != UNAVAILABLE or self.token_status != UNAVAILABLE:
            raise ValueError("scan count and tokens must stay unavailable")
        if self.success_count + self.failure_count + self.skipped_count != self.query_count:
            raise ValueError("query counts must sum to query_count")
        if self.truncated_pass():
            raise ValueError("truncated results cannot pass")
        return self

    def truncated_pass(self) -> bool:
        return any(item.truncated and item.status == "ok" for item in self.queries)


class PublicPerfSummary(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["perf_baseline"] = "perf_baseline"
    scoring_applied: Literal[False] = False
    workload: PerfWorkload
    budget_profile: BudgetName
    dataset_scale: Scale | None = None
    query_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None
    scan_count_status: Literal["unavailable"] = UNAVAILABLE
    token_status: Literal["unavailable"] = UNAVAILABLE
    peak_rss_status: Literal["unavailable"] = UNAVAILABLE
    concurrency: Literal[1] = 1
    integrity_passed: bool
    all_passed: bool | None = None
    row_counts: dict[str, int] | None = None
    reason_codes: tuple[Text, ...] = ()
    roadmap_targets_ms: dict[str, int] = Field(default_factory=lambda: dict(ROADMAP_TARGET_MS))
    p95_vs_simple_target: bool | None = None
    p95_vs_medium_target: bool | None = None
    p95_vs_complex_target: bool | None = None
    agent_id: Identifier | None = None
    hardware: dict[str, Text | int | None]
    versions: dict[str, Text]
    limitations: tuple[Text, ...]
