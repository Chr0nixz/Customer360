"""Trusted-side Tiny variant replay contracts.

same_sql, agent_rerun and scoring are distinct modes and cannot share a report.
Scoring weights are not applied.
"""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text
from customer360.contracts.coverage import MaterialStatus
from customer360.contracts.manifest import Hash, NineTableDigests
from customer360.contracts.public import QueryResult

BASELINE_SEED = 42
VARIANT_SEED = 43
VARIANT_ID = "tiny_seed_43_distribution"
ReplayMode = Literal["same_sql", "agent_rerun", "scoring"]
NamedVariantId = Literal[
    "tiny_seed_43_distribution",
    "tiny_duplicate_fanout",
    "tiny_null_empty_groups",
    "tiny_date_boundary",
]
MUTATION_VARIANT_IDS = (
    "tiny_duplicate_fanout",
    "tiny_null_empty_groups",
    "tiny_date_boundary",
)
# The semantic pack verifier and the agent matrix must use the same frozen
# public Tiny variant set.  Keep this tuple ordered so reports are deterministic.
SEMANTIC_VERIFY_VARIANT_IDS = (VARIANT_ID, *MUTATION_VARIANT_IDS)
REPORT_KIND_FOR_MODE = {
    "same_sql": "tiny_sql_replay_variant",
    "agent_rerun": "tiny_agent_rerun_variant",
    "scoring": "tiny_scoring_variant",
}


class VariantDatasetManifest(NineTableDigests):
    """Mutated Tiny snapshot. Not the canonical seed-42 Tiny dataset."""

    artifact_kind: Literal["tiny_variant_dataset"] = "tiny_variant_dataset"
    variant_id: Literal[
        "tiny_duplicate_fanout",
        "tiny_null_empty_groups",
        "tiny_date_boundary",
    ]
    variant_version: Literal["0.1"] = "0.1"
    generator_version: Literal["0.1.0"] = "0.1.0"
    snapshot_version: Literal["tiny-v1"] = "tiny-v1"
    schema_version: Literal["0.1"] = "0.1"
    metadata_version: Literal["0.1"] = "0.1"
    scale: Literal["tiny"] = "tiny"
    parent_seed: Literal[42] = BASELINE_SEED
    seed: int = Field(ge=0)
    anchor_date: date
    config_hash: Hash
    environment: dict[str, Text]


class VariantCaseReplay(Contract):
    case_id: Text
    task_version: Literal["human-0.1"] = "human-0.1"
    split: Literal["dev"] = "dev"
    material_status: MaterialStatus
    sql: Text | None = None
    sql_unchanged: bool | None = None
    independent_match: bool | None = None
    differs_from_baseline: bool | None = None
    baseline_result: QueryResult | None = None
    variant_result: QueryResult | None = None
    independent_result: QueryResult | None = None
    agent_outcome: Text | None = None
    agent_reason_code: Text | None = None
    applicability: Literal["applicable", "policy_incompatible"] | None = None
    policy_block_code: Text | None = None

    @model_validator(mode="after")
    def replay_fields_match_status(self) -> "VariantCaseReplay":
        executable = self.material_status == "compilable_answer"
        if executable:
            if (
                self.sql is None
                or self.independent_match is None
                or self.differs_from_baseline is None
                or self.baseline_result is None
                or self.variant_result is None
                or self.independent_result is None
            ):
                raise ValueError("compilable replay needs SQL and both dataset results")
        elif any(
            value is not None
            for value in (
                self.sql,
                self.sql_unchanged,
                self.independent_match,
                self.differs_from_baseline,
                self.baseline_result,
                self.variant_result,
                self.independent_result,
                self.agent_outcome,
                self.agent_reason_code,
                self.applicability,
                self.policy_block_code,
            )
        ):
            raise ValueError("non-answer replay cannot carry executable results")
        if self.applicability == "policy_incompatible" and self.policy_block_code is None:
            raise ValueError("policy-incompatible replay needs a policy block code")
        return self


class VariantReplayReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal[
        "tiny_sql_replay_variant",
        "tiny_agent_rerun_variant",
        "tiny_scoring_variant",
    ] = "tiny_sql_replay_variant"
    replay_mode: ReplayMode = "same_sql"
    variant_id: NamedVariantId = VARIANT_ID
    variant_version: Literal["0.1"] = "0.1"
    m2_complete: Literal[False] = False
    scoring_applied: Literal[False] = False
    agent_invoked: bool = False
    passed: bool
    baseline_seed: Literal[42] = BASELINE_SEED
    variant_seed: int = Field(default=VARIANT_SEED, ge=0)
    baseline_manifest_hash: Text
    variant_manifest_hash: Text
    generator_version: Literal["0.1.0"] = "0.1.0"
    snapshot_version: Literal["tiny-v1"] = "tiny-v1"
    compilable_answers: int = Field(ge=0, le=20)
    independent_oracle_matches: int = Field(ge=0, le=20)
    results_differ_from_baseline: int = Field(ge=0, le=20)
    date_dimension_unchanged: bool
    limitations: tuple[Text, ...]
    cases: tuple[VariantCaseReplay, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def consistent_replay(self) -> "VariantReplayReport":
        if self.report_kind != REPORT_KIND_FOR_MODE[self.replay_mode]:
            raise ValueError("report_kind does not match replay_mode")
        if self.replay_mode == "same_sql" and self.agent_invoked:
            raise ValueError("same_sql replay cannot invoke the Agent")
        if self.replay_mode == "agent_rerun" and not self.agent_invoked:
            raise ValueError("agent_rerun must invoke the Agent")
        if self.replay_mode == "scoring" and self.scoring_applied:
            raise ValueError("scoring weights are not applied")
        if self.variant_id == VARIANT_ID and self.variant_seed != VARIANT_SEED:
            raise ValueError("distribution variant seed must be 43")
        if self.baseline_manifest_hash == self.variant_manifest_hash:
            raise ValueError("variant manifest must differ from the baseline")
        executable = tuple(
            item for item in self.cases if item.material_status == "compilable_answer"
        )
        if len(executable) != self.compilable_answers:
            raise ValueError("compilable_answers does not match case records")
        matches = sum(bool(item.independent_match) for item in executable)
        differed = sum(bool(item.differs_from_baseline) for item in executable)
        if matches != self.independent_oracle_matches:
            raise ValueError("independent_oracle_matches does not match case records")
        if differed != self.results_differ_from_baseline:
            raise ValueError("results_differ_from_baseline does not match case records")
        if self.replay_mode == "same_sql":
            sql_ok = all(item.sql_unchanged is True for item in executable)
            expected = (
                matches == self.compilable_answers
                and differed >= 1
                and self.date_dimension_unchanged
                and sql_ok
            )
        elif self.replay_mode == "agent_rerun":
            applicable = tuple(
                item for item in executable if item.applicability != "policy_incompatible"
            )
            blocked = tuple(
                item for item in executable if item.applicability == "policy_incompatible"
            )
            agent_ok = bool(applicable) and all(item.agent_outcome == "pass" for item in applicable)
            blocked_ok = all(
                item.agent_outcome is None and item.policy_block_code for item in blocked
            )
            expected = (
                matches == self.compilable_answers
                and differed >= 1
                and self.date_dimension_unchanged
                and agent_ok
                and blocked_ok
            )
        else:
            expected = False
        if self.passed != expected:
            raise ValueError("passed does not match replay evidence")
        return self
