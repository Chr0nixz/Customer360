"""Independent hidden task pack. Never relabels C360_0001-0020 or public train/dev."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.coverage import CaseCategory, MaterialStatus, validate_case_material
from customer360.contracts.family import (
    ALLOWED_HIDDEN_SPLITS,
    ERROR_CLASSES_REQUIRED,
    HIDDEN_CASE_ID_MIN,
    FamilyFingerprint,
)
from customer360.contracts.oracle import SlotReply
from customer360.contracts.public import RefusalCode
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)

HIDDEN_PACK_ID = "hidden-m6-0.1"
HIDDEN_TASK_VERSION = "hidden-0.1"
PUBLIC_HIDDEN_FIELDS = frozenset(
    {"case_id", "pack_id", "task_version", "split", "question", "rewrites"}
)
PUBLIC_HIDDEN_FORBIDDEN = frozenset(
    {
        "semantic_spec",
        "missing_slots",
        "slot_replies",
        "candidate_sql",
        "sql",
        "gold",
        "expected_action",
        "question",
        "rewrites",
        "seed",
        "hidden_seed",
        "family_id",
        "family",
        "metric",
        "filters",
        "time_window",
        "join",
        "independent_result",
        "completed_spec",
    }
)


def _hidden_case_id(case_id: str) -> bool:
    return (
        case_id.startswith("C360_")
        and case_id[5:].isdigit()
        and len(case_id) == 9
        and int(case_id[5:]) >= HIDDEN_CASE_ID_MIN
    )


class PublicHiddenCase(Contract):
    case_id: Text
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    task_version: Literal["hidden-0.1"] = HIDDEN_TASK_VERSION
    split: Literal["private"] = "private"
    question: Text
    rewrites: tuple[Text, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def public_hidden_only(self) -> PublicHiddenCase:
        if not _hidden_case_id(self.case_id):
            raise ValueError("hidden case_id must look like C360_4001 or higher")
        if len(set(self.rewrites)) != len(self.rewrites):
            raise ValueError("case rewrites must be unique")
        if self.question in self.rewrites:
            raise ValueError("case rewrite must differ from the canonical question")
        return self


class PublicHiddenCatalog(Contract):
    catalog_version: Literal["0.5"] = "0.5"
    artifact_kind: Literal["agent_hidden_cases"] = "agent_hidden_cases"
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    cases: tuple[PublicHiddenCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_hidden_ids(self) -> PublicHiddenCatalog:
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hidden case_id")
        return self


class TrustedHiddenOracle(Contract):
    case_id: Text
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    task_version: Literal["hidden-0.1"] = HIDDEN_TASK_VERSION
    split: Literal["private"] = "private"
    family: FamilyFingerprint
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    category: CaseCategory
    material_status: MaterialStatus
    intended_failure_class: Text
    metric: Identifier | None = None
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[Identifier, ...] = ()
    missing_slots: tuple[Identifier, ...] = ()
    slot_replies: tuple[SlotReply, ...] = ()
    accepted_reason_codes: tuple[RefusalCode, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> TrustedHiddenOracle:
        if not _hidden_case_id(self.case_id):
            raise ValueError("hidden case_id must look like C360_4001 or higher")
        if self.split not in ALLOWED_HIDDEN_SPLITS:
            raise ValueError("hidden pack cases must use split=private")
        validate_case_material(
            expected_action=self.expected_action,
            category=self.category,
            material_status=self.material_status,
            metric=self.metric,
            filters=self.filters,
            time_window=self.time_window,
            join=self.join,
            unsupported_reason=None,
            missing_slots=self.missing_slots,
            slot_replies=self.slot_replies,
            accepted_reason_codes=self.accepted_reason_codes,
            group_by=self.group_by,
        )
        if self.family.expected_action != self.expected_action:
            raise ValueError("family action must match oracle action")
        if self.family.metric != self.metric:
            raise ValueError("family metric must match oracle metric")
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


class HiddenCaseBlueprint(Contract):
    case_id: Text
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    task_version: Literal["hidden-0.1"] = HIDDEN_TASK_VERSION
    split: Literal["private"] = "private"
    family: FamilyFingerprint
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
    missing_slots: tuple[Identifier, ...] = ()
    slot_replies: tuple[SlotReply, ...] = ()
    accepted_reason_codes: tuple[RefusalCode, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> HiddenCaseBlueprint:
        if not _hidden_case_id(self.case_id):
            raise ValueError("hidden case_id must look like C360_4001 or higher")
        validate_case_material(
            expected_action=self.expected_action,
            category=self.category,
            material_status=self.material_status,
            metric=self.metric,
            filters=self.filters,
            time_window=self.time_window,
            join=self.join,
            unsupported_reason=None,
            missing_slots=self.missing_slots,
            slot_replies=self.slot_replies,
            accepted_reason_codes=self.accepted_reason_codes,
            group_by=self.group_by,
        )
        if self.family.expected_action != self.expected_action:
            raise ValueError("family action must match hidden case action")
        if self.family.metric != self.metric:
            raise ValueError("family metric must match hidden case metric")
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


class HiddenTaskPack(Contract):
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    pack_kind: Literal["hidden_task_pack"] = "hidden_task_pack"
    task_version: Literal["hidden-0.1"] = HIDDEN_TASK_VERSION
    catalog_version: Literal["0.5"] = "0.5"
    seed: int = Field(ge=0)
    case_count: int = Field(ge=1)
    scoring_applied: Literal[False] = False
    hidden: Literal[True] = True
    public_pack_id: Literal["generated-m3-0.1"] = "generated-m3-0.1"
    metrics_version: Text
    join_paths_version: Text
    cases: tuple[HiddenCaseBlueprint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def pack_matches_cases(self) -> HiddenTaskPack:
        if len(self.cases) != self.case_count:
            raise ValueError("case_count must equal the number of cases")
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hidden case_id")
        families = [item.family.family_id for item in self.cases]
        if len(set(families)) != len(families):
            raise ValueError("duplicate family_id; rewrites are not extra cases")
        if any(item.split != "private" for item in self.cases):
            raise ValueError("hidden pack cases must use split=private")
        if any(not _hidden_case_id(item.case_id) for item in self.cases):
            raise ValueError("hidden pack reused a public or human case_id")
        error_classes = {item.intended_failure_class for item in self.cases}
        if missing := ERROR_CLASSES_REQUIRED - error_classes:
            raise ValueError("hidden pack is missing error classes: " + ",".join(sorted(missing)))
        return self


class HiddenDataProfile(Contract):
    artifact_kind: Literal["hidden_tiny_profile"] = "hidden_tiny_profile"
    hidden: Literal[True] = True
    scoring_applied: Literal[False] = False
    scale: Literal["tiny"] = "tiny"
    seed: int = Field(ge=0)
    snapshot_version: Literal["tiny-v1"] = "tiny-v1"
    generator_version: Literal["0.1.0"] = "0.1.0"

    @model_validator(mode="after")
    def seed_is_isolated(self) -> HiddenDataProfile:
        if self.seed in {42, 43}:
            raise ValueError("hidden Tiny cannot reuse public seeds 42 or 43")
        return self


class HiddenEvalRecord(Contract):
    case_id: Text
    split: Literal["private"] = "private"
    outcome: Literal["pass", "fail", "error"]
    reason_code: Text | None = None
    material_status: MaterialStatus
    agent_status: Text | None = None
    agent_policy_violation: bool = False
    variant_replays: tuple[HiddenVariantReplay, ...] = ()

    @model_validator(mode="after")
    def hidden_case_id(self) -> HiddenEvalRecord:
        if not _hidden_case_id(self.case_id):
            raise ValueError("hidden evaluation records must use C360_4001 or higher")
        return self


class HiddenVariantReplay(Contract):
    """Private same-SQL replay outcome for one hidden data snapshot."""

    variant_id: Text
    applicable: Literal["applicable", "policy_incompatible", "not_applicable"]
    outcome: Literal["pass", "fail", "error", "skipped"]
    reason_code: Text | None = None
    sql_replayed: bool = False
    independent_match: bool | None = None
    differs_from_baseline: bool | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def consistent_replay(self) -> HiddenVariantReplay:
        if self.applicable == "policy_incompatible":
            if self.outcome != "skipped" or self.reason_code != "POLICY_INCOMPATIBLE":
                raise ValueError("policy-incompatible replay must be skipped with its code")
            if self.sql_replayed:
                raise ValueError("policy-incompatible replay cannot execute SQL")
        if self.applicable == "not_applicable":
            if self.outcome != "skipped" or self.sql_replayed:
                raise ValueError("not-applicable replay cannot execute SQL")
        if self.truncated and self.outcome == "pass":
            raise ValueError("truncated hidden replay cannot pass")
        return self


class HiddenEvalReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["hidden_evaluation"] = "hidden_evaluation"
    scoring_applied: Literal[False] = False
    hidden: Literal[True] = True
    agent_id: Identifier
    pack_id: Literal["hidden-m6-0.1"] = HIDDEN_PACK_ID
    case_count: int = Field(ge=1)
    compilable_answers: int = Field(ge=0)
    integrity_passed: bool
    data_seed: int = Field(ge=0)
    limitations: tuple[Text, ...]
    variant_ids: tuple[Text, ...] = ()
    formal_replay: bool = False
    cases: tuple[HiddenEvalRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def report_matches_cases(self) -> HiddenEvalReport:
        if len(self.cases) != self.case_count:
            raise ValueError("case_count must equal the number of hidden evaluation records")
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hidden evaluation case_id")
        if any(item.split != "private" for item in self.cases):
            raise ValueError("hidden evaluation records must use split=private")
        executable = sum(item.material_status == "compilable_answer" for item in self.cases)
        if executable != self.compilable_answers:
            raise ValueError("compilable_answers does not match case records")
        if self.formal_replay and self.variant_ids != (
            "hidden_distribution",
            "hidden_duplicate_fanout",
            "hidden_null_empty_groups",
            "hidden_date_boundary",
        ):
            raise ValueError("formal hidden replay requires the four frozen variants")
        if any(
            tuple(row.variant_id for row in item.variant_replays) != self.variant_ids
            for item in self.cases
        ):
            raise ValueError("hidden replay rows must use the report variant order")
        return self


class PublicHiddenSummary(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["public_hidden_summary"] = "public_hidden_summary"
    scoring_applied: Literal[False] = False
    hidden: Literal[True] = True
    agent_id: Identifier
    case_count: int = Field(ge=1)
    compilable_answers: int = Field(ge=0)
    integrity_passed: bool
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def public_only(self) -> PublicHiddenSummary:
        payload = self.model_dump(mode="json")
        leaked = set(payload) & {
            "question",
            "rewrites",
            "seed",
            "hidden_seed",
            "data_seed",
            "sql",
            "gold",
            "family_id",
            "metric",
            "cases",
        }
        if leaked:
            raise ValueError(f"public hidden summary leaked {sorted(leaked)[0]}")
        return self
