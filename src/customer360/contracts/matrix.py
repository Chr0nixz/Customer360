"""Trusted matrix evaluation: one Agent submission, then snapshot replay.

Official scoring weights are not applied. same_sql and agent_rerun cannot share
a robustness score.
"""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.coverage import MaterialStatus
from customer360.contracts.evaluation import EvaluationRecord
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS, ReplayMode

BASELINE_SNAPSHOT_ID = "tiny_baseline_seed_42"
MATRIX_SNAPSHOT_IDS = (
    BASELINE_SNAPSHOT_ID,
    *SEMANTIC_VERIFY_VARIANT_IDS,
)
PUBLIC_MATRIX_FORBIDDEN = frozenset(
    {
        "semantic_spec",
        "missing_slots",
        "slot_replies",
        "candidate_sql",
        "sql",
        "independent_result",
        "baseline_result",
        "variant_result",
        "gold",
        "expected_action",
        "completed_spec",
    }
)
SnapshotApplicability = Literal["applicable", "policy_incompatible", "not_applicable"]
SnapshotStage = Literal["agent_submit", "same_sql_replay", "agent_rerun"]
SnapshotOutcomeStatus = Literal["pass", "fail", "error", "skipped"]


class SnapshotOutcome(Contract):
    snapshot_id: Text
    applicable: SnapshotApplicability
    stage: SnapshotStage
    outcome: SnapshotOutcomeStatus
    reason_code: Text | None = None
    failure_class: Text | None = None
    sql_replayed: bool = False
    agent_invoked: bool = False
    truncated: bool = False
    differs_from_baseline: bool | None = None
    independent_match: bool | None = None

    @model_validator(mode="after")
    def consistent_snapshot(self) -> "SnapshotOutcome":
        if self.applicable == "policy_incompatible":
            if self.agent_invoked:
                raise ValueError("policy-incompatible snapshot cannot invoke the Agent")
            if self.outcome != "skipped":
                raise ValueError("policy-incompatible snapshot must be skipped")
            if self.reason_code != "POLICY_INCOMPATIBLE":
                raise ValueError("policy-incompatible snapshot needs POLICY_INCOMPATIBLE")
        if self.applicable == "not_applicable":
            if self.agent_invoked or self.sql_replayed:
                raise ValueError("not-applicable snapshot cannot execute SQL or the Agent")
            if self.outcome != "skipped":
                raise ValueError("not-applicable snapshot must be skipped")
        if self.truncated and self.outcome == "pass":
            raise ValueError("truncated results cannot pass")
        return self


class CaseMatrixRecord(Contract):
    case_id: Text
    split: Literal["dev"] = "dev"
    task_version: Text
    material_status: MaterialStatus
    baseline_record: EvaluationRecord
    candidate_sql: Text | None = None
    snapshots: tuple[SnapshotOutcome, ...] = Field(min_length=5, max_length=5)
    applicable_snapshots: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def snapshots_are_the_frozen_matrix(self) -> "CaseMatrixRecord":
        ids = tuple(item.snapshot_id for item in self.snapshots)
        if ids != MATRIX_SNAPSHOT_IDS:
            raise ValueError("matrix must record baseline plus four named variants in order")
        if self.split != "dev":
            raise ValueError("human matrix cases must stay split=dev")
        expected = tuple(
            item.snapshot_id for item in self.snapshots if item.applicable == "applicable"
        )
        if expected != self.applicable_snapshots:
            raise ValueError("applicable_snapshots does not match snapshot rows")
        return self


class MatrixRunReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["tiny_matrix_evaluation"] = "tiny_matrix_evaluation"
    replay_mode: ReplayMode
    scoring_applied: Literal[False] = False
    m2_complete: Literal[False] = False
    m4_scored: Literal[False] = False
    agent_id: Identifier
    split: Literal["dev"] = "dev"
    case_count: Literal[20] = 20
    snapshot_ids: tuple[Text, ...] = MATRIX_SNAPSHOT_IDS
    integrity_passed: bool
    agent_invoked: bool
    date_dimension_unchanged: bool
    baseline_manifest_hash: Text
    variant_manifest_hashes: dict[str, Text]
    compilable_answers: int = Field(ge=0, le=20)
    independent_oracle_matches: int = Field(ge=0, le=100)
    limitations: tuple[Text, ...]
    cases: tuple[CaseMatrixRecord, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def matrix_integrity(self) -> "MatrixRunReport":
        if self.scoring_applied or self.m4_scored:
            raise ValueError("official scoring is not enabled")
        if self.replay_mode == "scoring":
            raise ValueError("scoring mode cannot produce a matrix report")
        if tuple(item.case_id for item in self.cases) != tuple(
            f"C360_{index:04d}" for index in range(1, 21)
        ):
            raise ValueError("matrix must keep C360_0001 through C360_0020 in order")
        if any(item.split != "dev" for item in self.cases):
            raise ValueError("matrix cannot relabel the human pack")
        if self.snapshot_ids != MATRIX_SNAPSHOT_IDS:
            raise ValueError("matrix snapshot set is frozen")
        if self.replay_mode == "same_sql" and any(
            snapshot.agent_invoked
            for case in self.cases
            for snapshot in case.snapshots
            if snapshot.snapshot_id != BASELINE_SNAPSHOT_ID
        ):
            raise ValueError("same_sql cannot invoke the Agent on variants")
        if self.replay_mode == "same_sql" and self.agent_invoked is False:
            raise ValueError("same_sql still submits the Agent once on baseline")
        if self.replay_mode == "agent_rerun" and not self.agent_invoked:
            raise ValueError("agent_rerun must invoke the Agent")
        matches = sum(
            snapshot.independent_match is True
            for case in self.cases
            for snapshot in case.snapshots
            if snapshot.applicable == "applicable" and snapshot.sql_replayed
        )
        if matches != self.independent_oracle_matches:
            raise ValueError("independent_oracle_matches does not match snapshot rows")
        return self


class PublicSnapshotSummary(Contract):
    snapshot_id: Text
    applicable: SnapshotApplicability
    stage: SnapshotStage
    outcome: SnapshotOutcomeStatus
    reason_code: Text | None = None
    failure_class: Text | None = None


class PublicCaseSummary(Contract):
    case_id: Text
    split: Literal["dev"] = "dev"
    snapshots: tuple[PublicSnapshotSummary, ...] = Field(min_length=5, max_length=5)


class PublicMatrixSummary(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["public_matrix_summary"] = "public_matrix_summary"
    scoring_applied: Literal[False] = False
    m2_complete: Literal[False] = False
    m4_scored: Literal[False] = False
    replay_mode: ReplayMode
    agent_id: Identifier
    case_count: Literal[20] = 20
    integrity_passed: bool
    snapshot_ids: tuple[Text, ...] = MATRIX_SNAPSHOT_IDS
    limitations: tuple[Text, ...]
    cases: tuple[PublicCaseSummary, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def public_only(self) -> "PublicMatrixSummary":
        leaked = _json_keys(self.model_dump(mode="json")) & PUBLIC_MATRIX_FORBIDDEN
        if leaked:
            raise ValueError(f"public matrix summary leaked {sorted(leaked)[0]}")
        return self


def _json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _json_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _json_keys(item)
    return keys
