"""Generated M3 task pack. Independent of the frozen 20-case human catalog."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.coverage import CaseCategory, MaterialStatus, validate_case_material
from customer360.contracts.family import (
    M6_PUBLIC_COUNT,
    PUBLIC_GENERATED_ID_MAX,
    PUBLIC_GENERATED_ID_MIN,
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

GENERATED_PACK_ID = "generated-m3-0.1"
GENERATED_TASK_VERSION = "generated-0.1"
PUBLIC_GENERATED_FIELDS = frozenset(
    {"case_id", "pack_id", "task_version", "split", "question", "rewrites"}
)


def _generated_case_id(case_id: str) -> bool:
    return (
        case_id.startswith("C360_")
        and case_id[5:].isdigit()
        and len(case_id) == 9
        and PUBLIC_GENERATED_ID_MIN <= int(case_id[5:]) <= PUBLIC_GENERATED_ID_MAX
    )


class PublicGeneratedCase(Contract):
    case_id: Text
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    task_version: Literal["generated-0.1"] = GENERATED_TASK_VERSION
    split: Literal["train", "dev"]
    question: Text
    rewrites: tuple[Text, ...] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def public_generated_only(self) -> "PublicGeneratedCase":
        if not _generated_case_id(self.case_id):
            raise ValueError("generated case_id must be within C360_1001 through C360_3999")
        if len(set(self.rewrites)) != len(self.rewrites):
            raise ValueError("case rewrites must be unique")
        if self.question in self.rewrites:
            raise ValueError("case rewrite must differ from the canonical question")
        return self


class PublicGeneratedCatalog(Contract):
    catalog_version: Literal["0.4"] = "0.4"
    artifact_kind: Literal["public_generated_cases"] = "public_generated_cases"
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    cases: tuple[PublicGeneratedCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_public_ids(self) -> "PublicGeneratedCatalog":
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate generated case_id")
        questions = [item.question for item in self.cases]
        if len(set(questions)) != len(questions):
            raise ValueError("duplicate canonical question")
        return self


class TrustedGeneratedOracle(Contract):
    case_id: Text
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    task_version: Literal["generated-0.1"] = GENERATED_TASK_VERSION
    split: Literal["train", "dev"]
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
    def consistent(self) -> "TrustedGeneratedOracle":
        if not _generated_case_id(self.case_id):
            raise ValueError("generated case_id must be within C360_1001 through C360_3999")
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


class TrustedGeneratedCatalog(Contract):
    catalog_version: Literal["0.4"] = "0.4"
    artifact_kind: Literal["trusted_generated_oracles"] = "trusted_generated_oracles"
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    cases: tuple[TrustedGeneratedOracle, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_trusted_ids(self) -> "TrustedGeneratedCatalog":
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate generated case_id")
        families = [item.family.family_id for item in self.cases]
        if len(set(families)) != len(families):
            raise ValueError("duplicate family_id; rewrites are not extra cases")
        return self


class GeneratedCaseBlueprint(Contract):
    case_id: Text
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    task_version: Literal["generated-0.1"] = GENERATED_TASK_VERSION
    split: Literal["train", "dev"]
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
    def consistent(self) -> "GeneratedCaseBlueprint":
        if not _generated_case_id(self.case_id):
            raise ValueError("generated case_id must be within C360_1001 through C360_3999")
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
            raise ValueError("family action must match generated case action")
        if self.family.metric != self.metric:
            raise ValueError("family metric must match generated case metric")
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


class GeneratedTaskPack(Contract):
    pack_id: Literal["generated-m3-0.1"] = GENERATED_PACK_ID
    pack_kind: Literal["generated_task_pack"] = "generated_task_pack"
    task_version: Literal["generated-0.1"] = GENERATED_TASK_VERSION
    catalog_version: Literal["0.4"] = "0.4"
    seed: int = Field(ge=0)
    case_count: int = Field(ge=1)
    scoring_applied: Literal[False] = False
    m3_complete: bool
    m6_structure: bool = False
    metrics_version: Text
    join_paths_version: Text
    cases: tuple[GeneratedCaseBlueprint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def pack_matches_cases(self) -> "GeneratedTaskPack":
        if len(self.cases) != self.case_count:
            raise ValueError("case_count must equal the number of cases")
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate generated case_id")
        families = [item.family.family_id for item in self.cases]
        if len(set(families)) != len(families):
            raise ValueError("duplicate family_id; rewrites are not extra cases")
        if any(not _generated_case_id(item.case_id) for item in self.cases):
            raise ValueError("generated case_id must be within C360_1001 through C360_3999")
        if any(item.split in {"test", "private", "hidden", "challenge"} for item in self.cases):
            raise ValueError("generated pack cannot use hidden splits")
        if self.m6_structure:
            if not self.m3_complete or self.case_count != M6_PUBLIC_COUNT:
                raise ValueError("m6_structure requires a complete 300-case pack")
            if sum(item.split == "train" for item in self.cases) != 180:
                raise ValueError("m6_structure requires 180 train cases")
            if sum(item.split == "dev" for item in self.cases) != 120:
                raise ValueError("m6_structure requires 120 dev cases")
        return self
