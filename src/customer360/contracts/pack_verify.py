"""Trusted semantic-acceptance reports for generated and hidden packs.

Not an official score. Public summaries omit Gold, specs, SQL, questions and seeds.
"""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text
from customer360.contracts.coverage import MaterialStatus
from customer360.contracts.family import ERROR_CLASSES_REQUIRED
from customer360.contracts.public import QueryResult
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS, NamedVariantId

PUBLIC_VERIFY_FIELDS = frozenset(
    {
        "protocol_version",
        "report_kind",
        "scoring_applied",
        "hidden",
        "pack_id",
        "m6_structure",
        "semantic_passed",
        "case_count",
        "compilable_answers",
        "independent_oracle_matches",
        "unscored_oracles",
        "policy_incompatible_count",
        "wrong_sql_classes",
        "rewrite_passed",
        "variant_count",
        "replay_mode",
        "limitations",
    }
)
PUBLIC_VERIFY_FORBIDDEN = frozenset(
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
        "family",
        "family_id",
        "metric",
        "filters",
        "time_window",
        "join",
        "independent_result",
        "wrong_sql",
        "candidate_sql",
        "missing_slots",
        "slot_replies",
        "completed_spec",
    }
)


class PackPolicyProbe(Contract):
    """Tiny Agent policy diagnostics, independent of trusted Gold correctness."""

    policy_incompatible: bool = False
    policy_block_code: Literal["AGGREGATION_TOO_SMALL", "PERMISSION_DENIED"] | None = None

    @model_validator(mode="after")
    def policy_status_is_explicit(self) -> "PackPolicyProbe":
        if self.policy_incompatible != (self.policy_block_code == "AGGREGATION_TOO_SMALL"):
            raise ValueError("policy_incompatible must match the explicit gateway rejection")
        return self


class PackVariantResult(PackPolicyProbe):
    variant_id: NamedVariantId
    independent_match: bool
    results_differ_from_baseline: bool


class PackVerifyCase(PackPolicyProbe):
    case_id: Text
    split: Literal["train", "dev", "private"]
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    material_status: MaterialStatus
    intended_failure_class: Text
    independent_match: bool | None = None
    rewrite_passed: bool
    wrong_sql_distinguished: bool | None = None
    wrong_sql_mode: Literal["mismatch", "guard_rejected", "unscored"] | None = None
    compiled_sql: Text | None = None
    independent_result: QueryResult | None = None
    variants: tuple[PackVariantResult, ...] = ()
    failure: Text | None = None


class PackVerifyReport(Contract):
    protocol_version: Literal["0.2"] = "0.2"
    report_kind: Literal["pack_semantic_verify"] = "pack_semantic_verify"
    scoring_applied: Literal[False] = False
    hidden: bool = False
    pack_id: Text
    m6_structure: bool = False
    semantic_passed: bool
    case_count: int = Field(ge=1)
    compilable_answers: int = Field(ge=0)
    independent_oracle_matches: int = Field(ge=0)
    unscored_oracles: int = Field(ge=0)
    policy_incompatible_count: int = Field(ge=0)
    wrong_sql_classes: tuple[Text, ...] = ()
    rewrite_passed: bool
    variant_count: int = Field(ge=0)
    replay_mode: Literal["same_sql", "none"] = "none"
    dataset_seed: int = Field(ge=0)
    limitations: tuple[Text, ...]
    cases: tuple[PackVerifyCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def counts_match_cases(self) -> "PackVerifyReport":
        if len(self.cases) != self.case_count:
            raise ValueError("case_count must equal the number of verify records")
        ids = tuple(item.case_id for item in self.cases)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate verify case_id")
        compilable = sum(item.material_status == "compilable_answer" for item in self.cases)
        if compilable != self.compilable_answers:
            raise ValueError("compilable_answers does not match case records")
        unscored = sum(item.material_status == "unscored_oracle" for item in self.cases)
        if unscored != self.unscored_oracles:
            raise ValueError("unscored_oracles does not match case records")
        if self.independent_oracle_matches != sum(
            item.independent_match is True for item in self.cases
        ):
            raise ValueError("independent_oracle_matches does not match case records")
        if self.policy_incompatible_count != sum(item.policy_incompatible for item in self.cases):
            raise ValueError("policy_incompatible_count does not match case records")
        if self.rewrite_passed != all(item.rewrite_passed for item in self.cases):
            raise ValueError("rewrite_passed does not match case records")
        classes = {
            item.intended_failure_class for item in self.cases if item.wrong_sql_distinguished
        }
        if self.wrong_sql_classes != tuple(sorted(classes)):
            raise ValueError("wrong_sql_classes does not match case records")
        if self.scoring_applied:
            raise ValueError("pack semantic verify cannot apply official scores")
        if self.replay_mode == "same_sql" and self.variant_count < 1:
            raise ValueError("same_sql verify requires at least one variant")
        if self.replay_mode == "none" and self.variant_count != 0:
            raise ValueError("baseline-only verify cannot record variants")
        if self.hidden and self.variant_count != 0:
            raise ValueError("hidden pack verify does not accept public Tiny variants")
        requires_four = not self.hidden and (self.m6_structure or self.case_count >= 300)
        if requires_four:
            if self.replay_mode != "same_sql" or self.variant_count != len(
                SEMANTIC_VERIFY_VARIANT_IDS
            ):
                raise ValueError("300-case semantic verify requires the four frozen Tiny variants")
        expected_ids = None
        for case in self.cases:
            if self.hidden != (case.split == "private"):
                raise ValueError("case split does not match hidden report status")
            if case.material_status != "compilable_answer":
                if case.variants or case.independent_match is not None or case.policy_block_code:
                    raise ValueError("non-answer verify cannot carry execution evidence")
                continue
            if case.independent_match is None:
                raise ValueError("compilable answer requires independent oracle evidence")
            ids = tuple(row.variant_id for row in case.variants)
            if len(ids) != self.variant_count or len(set(ids)) != len(ids):
                raise ValueError("case variants must match variant_count without duplicates")
            if requires_four and ids != SEMANTIC_VERIFY_VARIANT_IDS:
                raise ValueError("300-case verify records must contain four frozen variants")
            if expected_ids is not None and ids != expected_ids:
                raise ValueError("all cases must replay the same ordered variants")
            expected_ids = ids
        variant_rows = tuple(row for case in self.cases for row in case.variants)
        variant_ok = not self.variant_count or (
            all(row.independent_match for row in variant_rows)
            and any(row.results_differ_from_baseline for row in variant_rows)
        )
        expected_passed = (
            compilable > 0
            and self.independent_oracle_matches == compilable
            and self.rewrite_passed
            and ERROR_CLASSES_REQUIRED <= classes
            and variant_ok
        )
        if self.semantic_passed != expected_passed:
            raise ValueError("semantic_passed does not match verify evidence")
        return self


class PublicPackVerifySummary(Contract):
    protocol_version: Literal["0.2"] = "0.2"
    report_kind: Literal["public_pack_verify_summary"] = "public_pack_verify_summary"
    scoring_applied: Literal[False] = False
    hidden: bool = False
    pack_id: Text
    m6_structure: bool = False
    semantic_passed: bool
    case_count: int = Field(ge=1)
    compilable_answers: int = Field(ge=0)
    independent_oracle_matches: int = Field(ge=0)
    unscored_oracles: int = Field(ge=0)
    policy_incompatible_count: int = Field(ge=0)
    wrong_sql_classes: tuple[Text, ...] = ()
    rewrite_passed: bool
    variant_count: int = Field(ge=0)
    replay_mode: Literal["same_sql", "none"] = "none"
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def public_only(self) -> "PublicPackVerifySummary":
        payload = self.model_dump(mode="json")
        leaked = PUBLIC_VERIFY_FORBIDDEN & set(payload)
        if leaked:
            raise ValueError("public pack verify summary leaked " + ",".join(sorted(leaked)))
        if self.scoring_applied:
            raise ValueError("public pack verify summary cannot apply official scores")
        return self


REQUIRED_WRONG_SQL_CLASSES = ERROR_CLASSES_REQUIRED
