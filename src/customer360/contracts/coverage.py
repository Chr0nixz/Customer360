"""Trusted human-case contracts, probes and Tiny coverage report.

These objects never go to an Agent. The catalog is a small, versioned formal
task package; coverage is still a boundary report rather than a benchmark score.
"""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.oracle import (
    AnswerOracle,
    CaseOracle,
    ClarificationOracle,
    RefusalOracle,
    SlotReply,
)
from customer360.contracts.public import QueryResult, RefusalCode
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)

CASE_ID_PREFIX = "C360_"
FAILURE_CLASSES = frozenset(
    {
        "SCHEMA_ERROR",
        "METRIC_ERROR",
        "FILTER_ERROR",
        "TIME_RANGE_ERROR",
        "JOIN_ERROR",
        "DUPLICATE_COUNT_ERROR",
        "AGGREGATION_ERROR",
        "NULL_HANDLING_ERROR",
        "PERMISSION_ERROR",
        "UNSAFE_SQL",
        "CLARIFICATION_FAILURE",
        "TIMEOUT",
    }
)
CaseCategory = Literal[
    "single_table",
    "aggregation",
    "time_window",
    "time_window_boundary",
    "point_in_time",
    "customer_filter",
    "null_handling",
    "join",
    "grouping",
    "latest_snapshot",
    "clarification",
    "refuse",
]
MaterialStatus = Literal["compilable_answer", "unsupported_capability", "unscored_oracle"]
PUBLIC_CASE_FIELDS = frozenset({"case_id", "task_version", "split", "question", "rewrites"})
PRIVATE_ORACLE_FIELDS = frozenset(
    {
        "expected_action",
        "category",
        "material_status",
        "intended_failure_class",
        "metric",
        "filters",
        "time_window",
        "join",
        "group_by",
        "unsupported_reason",
        "missing_slots",
        "slot_replies",
        "accepted_reason_codes",
        "required_probes",
        "semantic_spec",
        "completed_spec",
    }
)
REQUIRED_CATEGORIES = frozenset(
    {
        "single_table",
        "join",
        "time_window",
        "aggregation",
        "customer_filter",
        "clarification",
        "refuse",
        "grouping",
        "latest_snapshot",
        "null_handling",
        "point_in_time",
        "time_window_boundary",
    }
)


def _valid_case_id(case_id: str) -> bool:
    return (
        case_id.startswith(CASE_ID_PREFIX)
        and case_id[len(CASE_ID_PREFIX) :].isdigit()
        and len(case_id) == 9
    )


def validate_case_material(
    *,
    expected_action: str,
    category: str,
    material_status: str,
    metric: str | None,
    filters,
    time_window,
    join,
    unsupported_reason: str | None,
    missing_slots,
    slot_replies,
    accepted_reason_codes,
    group_by=(),
) -> None:
    """Shared action/material constraints for public overlay and trusted blueprint."""

    if join is not None and category != "join":
        raise ValueError("join semantic specs must use the join category")
    if category == "join" and join is None and material_status == "compilable_answer":
        raise ValueError("compilable join case needs a join spec")
    if group_by and category != "grouping":
        raise ValueError("group_by requires the grouping category")
    if category == "grouping" and material_status == "compilable_answer" and not group_by:
        raise ValueError("compilable grouping case needs group_by")
    if category == "latest_snapshot" and material_status == "compilable_answer":
        if metric != "latest_total_asset" or not isinstance(time_window, LatestSnapshot):
            raise ValueError("compilable latest-snapshot needs latest_total_asset and anchor")
    if material_status == "compilable_answer":
        if expected_action != "answer" or metric is None:
            raise ValueError("compilable answer needs a metric")
        if unsupported_reason or missing_slots or accepted_reason_codes:
            raise ValueError("compilable answer cannot carry unsupported oracle fields")
    elif material_status == "unsupported_capability":
        if expected_action != "answer" or metric is not None:
            raise ValueError("unsupported capability must not compile a spec")
        if unsupported_reason is None:
            raise ValueError("unsupported capability needs a reason")
        if filters or time_window or slot_replies or group_by:
            raise ValueError("unsupported capability cannot carry executable filters")
    else:
        if expected_action == "answer" or unsupported_reason:
            raise ValueError("unscored oracle is clarification or refuse only")
        if expected_action == "clarification_needed":
            if not missing_slots or not slot_replies or metric is None:
                raise ValueError("clarification material needs slots, replies and completed spec")
            if {item.slot for item in slot_replies} != set(missing_slots):
                raise ValueError("clarification replies must cover missing slots")
        elif not accepted_reason_codes or metric is not None:
            raise ValueError("refuse material needs reason codes and no Gold spec")


class PublicCase(Contract):
    """Wheel-safe case input. No Gold, slots, reason codes or expected action."""

    case_id: Text
    task_version: Literal["human-0.1"] = "human-0.1"
    split: Literal["dev"] = "dev"
    question: Text
    rewrites: tuple[Text, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def public_only(self) -> "PublicCase":
        if not _valid_case_id(self.case_id):
            raise ValueError("case_id must look like C360_0001")
        if len(set(self.rewrites)) != len(self.rewrites):
            raise ValueError("case rewrites must be unique")
        if self.question in self.rewrites:
            raise ValueError("case rewrite must differ from the canonical question")
        return self


class PublicCaseCatalog(Contract):
    catalog_version: Literal["0.3"] = "0.3"
    artifact_kind: Literal["public_human_cases"] = "public_human_cases"
    cases: tuple[PublicCase, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def complete_public_catalog(self) -> "PublicCaseCatalog":
        ids = tuple(item.case_id for item in self.cases)
        expected = tuple(f"C360_{index:04d}" for index in range(1, 21))
        if ids != expected:
            raise ValueError("catalog must be C360_0001 through C360_0020 in order")
        questions = [item.question for item in self.cases]
        if len(set(questions)) != len(questions):
            raise ValueError("duplicate canonical question")
        if any(item.task_version != "human-0.1" or item.split != "dev" for item in self.cases):
            raise ValueError("formal catalog requires task_version human-0.1 and split dev")
        return self


class TrustedCaseOracle(Contract):
    """Trusted-side overlay. Never packaged in the wheel."""

    case_id: Text
    task_version: Literal["human-0.1"] = "human-0.1"
    split: Literal["dev"] = "dev"
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    category: CaseCategory
    material_status: MaterialStatus
    intended_failure_class: Text
    metric: Identifier | None = None
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[Identifier, ...] = ()
    unsupported_reason: Text | None = None
    missing_slots: tuple[Identifier, ...] = ()
    slot_replies: tuple[SlotReply, ...] = ()
    accepted_reason_codes: tuple[RefusalCode, ...] = ()
    required_probes: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> "TrustedCaseOracle":
        if not _valid_case_id(self.case_id):
            raise ValueError("case_id must look like C360_0001")
        if self.intended_failure_class not in FAILURE_CLASSES:
            raise ValueError("unknown intended failure class")
        validate_case_material(
            expected_action=self.expected_action,
            category=self.category,
            material_status=self.material_status,
            metric=self.metric,
            filters=self.filters,
            time_window=self.time_window,
            join=self.join,
            unsupported_reason=self.unsupported_reason,
            missing_slots=self.missing_slots,
            slot_replies=self.slot_replies,
            accepted_reason_codes=self.accepted_reason_codes,
            group_by=self.group_by,
        )
        return self


class TrustedOracleCatalog(Contract):
    catalog_version: Literal["0.3"] = "0.3"
    artifact_kind: Literal["trusted_human_oracles"] = "trusted_human_oracles"
    cases: tuple[TrustedCaseOracle, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def complete_trusted_catalog(self) -> "TrustedOracleCatalog":
        ids = tuple(item.case_id for item in self.cases)
        expected = tuple(f"C360_{index:04d}" for index in range(1, 21))
        if ids != expected:
            raise ValueError("catalog must be C360_0001 through C360_0020 in order")
        if any(item.task_version != "human-0.1" or item.split != "dev" for item in self.cases):
            raise ValueError("formal catalog requires task_version human-0.1 and split dev")
        missing = REQUIRED_CATEGORIES - {item.category for item in self.cases}
        if missing:
            raise ValueError(f"catalog missing categories: {sorted(missing)}")
        return self


class HumanCaseBlueprint(Contract):
    case_id: Text
    task_version: Literal["human-0.1"] = "human-0.1"
    split: Literal["dev"] = "dev"
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    category: CaseCategory
    material_status: MaterialStatus
    intended_failure_class: Text
    question: Text
    rewrites: tuple[Text, ...] = Field(min_length=3, max_length=5)
    metric: Identifier | None = None
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[Identifier, ...] = ()
    unsupported_reason: Text | None = None
    missing_slots: tuple[Identifier, ...] = ()
    slot_replies: tuple[SlotReply, ...] = ()
    accepted_reason_codes: tuple[RefusalCode, ...] = ()
    required_probes: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> "HumanCaseBlueprint":
        if not _valid_case_id(self.case_id):
            raise ValueError("case_id must look like C360_0001")
        if self.intended_failure_class not in FAILURE_CLASSES:
            raise ValueError("unknown intended failure class")
        if len(set(self.rewrites)) != len(self.rewrites):
            raise ValueError("case rewrites must be unique")
        if self.question in self.rewrites:
            raise ValueError("case rewrite must differ from the canonical question")
        validate_case_material(
            expected_action=self.expected_action,
            category=self.category,
            material_status=self.material_status,
            metric=self.metric,
            filters=self.filters,
            time_window=self.time_window,
            join=self.join,
            unsupported_reason=self.unsupported_reason,
            missing_slots=self.missing_slots,
            slot_replies=self.slot_replies,
            accepted_reason_codes=self.accepted_reason_codes,
            group_by=self.group_by,
        )
        return self

    def semantic_spec(self) -> SemanticSpec:
        if self.metric is None:
            raise ValueError("case has no semantic spec")
        return SemanticSpec(
            metric=self.metric,
            filters=self.filters,
            time_window=self.time_window,
            join=self.join,
            group_by=self.group_by,
        )

    def oracle(self) -> CaseOracle:
        if self.material_status == "compilable_answer":
            return AnswerOracle(semantic_spec=self.semantic_spec())
        if self.expected_action == "clarification_needed":
            return ClarificationOracle(
                replies=self.slot_replies, completed_spec=self.semantic_spec()
            )
        if self.expected_action == "refuse":
            return RefusalOracle(accepted_reason_codes=self.accepted_reason_codes)
        raise ValueError("unsupported capability has no executable oracle")


class HumanCaseCatalog(Contract):
    catalog_version: Literal["0.3"] = "0.3"
    cases: tuple[HumanCaseBlueprint, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def complete_catalog(self) -> "HumanCaseCatalog":
        ids = tuple(item.case_id for item in self.cases)
        expected = tuple(f"C360_{index:04d}" for index in range(1, 21))
        if ids != expected:
            raise ValueError("catalog must be C360_0001 through C360_0020 in order")
        questions = [item.question for item in self.cases]
        if len(set(questions)) != len(questions):
            raise ValueError("duplicate canonical question")
        if any(item.task_version != "human-0.1" or item.split != "dev" for item in self.cases):
            raise ValueError("formal catalog requires task_version human-0.1 and split dev")
        missing = REQUIRED_CATEGORIES - {item.category for item in self.cases}
        if missing:
            raise ValueError(f"catalog missing categories: {sorted(missing)}")
        return self


class ProbeResult(Contract):
    probe_id: Identifier
    passed: bool
    observed: object
    detail: Text


class CaseCoverage(Contract):
    case_id: Text
    task_version: Literal["human-0.1"] = "human-0.1"
    split: Literal["dev"] = "dev"
    expected_action: Text
    category: CaseCategory
    material_status: MaterialStatus
    intended_failure_class: Text
    question: Text
    rewrites: tuple[Text, ...] = Field(min_length=3, max_length=5)
    compiled_match: bool | None = None
    independent_result: QueryResult | None = None
    compiled_sql: Text | None = None
    unsupported_reason: Text | None = None
    required_probes: tuple[Identifier, ...] = ()


class CoverageReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["tiny_boundary_coverage"] = "tiny_boundary_coverage"
    m2_complete: Literal[False] = False
    coverage_passed: bool
    case_count: Literal[20] = 20
    compilable_answers: int = Field(ge=0, le=20)
    unsupported_capabilities: int = Field(ge=0, le=20)
    unscored_oracles: int = Field(ge=0, le=20)
    independent_oracle_matches: int = Field(ge=0, le=20)
    probes_passed: bool
    dataset_manifest_hash: Text
    limitations: tuple[Text, ...]
    probes: tuple[ProbeResult, ...]
    cases: tuple[CaseCoverage, ...]
