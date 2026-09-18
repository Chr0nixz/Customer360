"""Semantic family identity and split isolation. Trusted-side only."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text

RESERVED_HUMAN_CASE_IDS = tuple(f"C360_{index:04d}" for index in range(1, 21))
FORBIDDEN_SPLITS = frozenset({"test", "private", "hidden", "challenge"})
ALLOWED_GENERATED_SPLITS = frozenset({"train", "dev"})
ALLOWED_HIDDEN_SPLITS = frozenset({"private"})
PUBLIC_GENERATED_ID_MIN = 1001
PUBLIC_GENERATED_ID_MAX = 3999
HIDDEN_CASE_ID_MIN = 4001
HIDDEN_DEFAULT_COUNT = 30
M6_PUBLIC_COUNT = 300
FORBIDDEN_HIDDEN_DATA_SEEDS = frozenset({42, 43})
DEFAULT_HIDDEN_DATA_SEED = 1042
ERROR_CLASSES_REQUIRED = frozenset(
    {
        "TIME_RANGE_ERROR",
        "JOIN_ERROR",
        "DUPLICATE_COUNT_ERROR",
        "NULL_HANDLING_ERROR",
        "FILTER_ERROR",
        "METRIC_ERROR",
        "PERMISSION_ERROR",
        "CLARIFICATION_FAILURE",
    }
)


class FamilyFingerprint(Contract):
    template_id: Identifier
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    metric: Identifier | None = None
    join_path: Identifier | None = None
    time_kind: Literal["none", "rolling", "point_in_time", "latest_snapshot"]
    rolling_days: int | None = None
    time_point: Text = "-"
    filter_signature: Text
    group_by: tuple[Identifier, ...] = ()
    canonical: Text
    family_id: Text

    @model_validator(mode="after")
    def family_matches_canonical(self) -> "FamilyFingerprint":
        if self.time_kind != "rolling" and self.rolling_days is not None:
            raise ValueError("rolling_days is only valid for rolling windows")
        if self.time_kind == "rolling" and self.rolling_days is None:
            raise ValueError("rolling family needs rolling_days")
        if not self.family_id.startswith("fam_"):
            raise ValueError("family_id must use the fam_ prefix")
        return self


class IsolationIssue(Contract):
    code: Identifier
    detail: Text
    case_id: Text | None = None
    family_id: Text | None = None


class IsolationReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["split_isolation"] = "split_isolation"
    passed: bool
    scoring_applied: Literal[False] = False
    human_pack_untouched: bool
    generated_case_count: int = Field(default=0, ge=0)
    hidden_case_count: int = Field(default=0, ge=0)
    family_count: int = Field(default=0, ge=0)
    error_classes: tuple[Text, ...] = ()
    issues: tuple[IsolationIssue, ...] = ()
