"""Private, versioned input to formal scoring; legacy reports are never upgraded."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.evaluation import EvaluationRecord
from customer360.contracts.hidden_variant import HIDDEN_VARIANT_IDS
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS


class FormalSnapshot(Contract):
    snapshot_id: Text
    applicable: bool
    policy_code: Literal["AGGREGATION_TOO_SMALL"] | None = None
    execution_code: Text | None = None
    independent_match: bool = False
    differs: bool | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def policy_is_explicit(self):
        if not self.applicable and self.policy_code is None:
            raise ValueError("inapplicability requires the explicit Gold policy code")
        if self.applicable and self.policy_code is not None:
            raise ValueError("applicable snapshot cannot carry a policy code")
        if self.independent_match and (
            not self.applicable or self.execution_code or self.truncated
        ):
            raise ValueError("failed, inapplicable or truncated snapshots cannot match")
        return self


class FormalCase(Contract):
    case_id: Text
    expected_action: Literal["answer", "clarification_needed", "refuse"]
    evaluation: EvaluationRecord | None = None
    snapshots: tuple[FormalSnapshot, ...] = ()
    format_passed: bool = False
    evidence_passed: bool = False
    interaction_passed: bool = False

    @model_validator(mode="after")
    def bind_record(self):
        if self.evaluation is None:
            if self.format_passed or self.evidence_passed or self.interaction_passed:
                raise ValueError("missing response cannot earn response credit")
        elif self.evaluation.case_id != self.case_id:
            raise ValueError("evaluation case identity mismatch")
        elif self.evaluation.evaluator_version != "0.6":
            raise ValueError("historical evaluator records cannot become formal inputs")
        if self.expected_action == "refuse" and self.snapshots:
            raise ValueError("refusal has no executable Gold")
        return self


class FormalEvaluationReport(Contract):
    report_kind: Literal["formal_evaluation_input"] = "formal_evaluation_input"
    score_protocol_version: Literal["1.0"] = "1.0"
    evaluator_version: Literal["0.6"] = "0.6"
    protocol_version: Literal["0.1"] = "0.1"
    scoring_applied: Literal[False] = False
    replay_mode: Literal["same_sql"] = "same_sql"
    split: Literal["public_dev", "private_hidden"]
    agent_id: Identifier
    agent_version: Text
    case_count: int = Field(ge=1)
    case_ids: tuple[Text, ...]
    snapshot_ids: tuple[Text, ...]
    integrity_passed: bool
    data_version: Text
    task_version: Text
    metadata_version: Text
    input_digests: dict[str, Text]
    environment: dict
    efficiency_profile: Literal["local-tiny-v1"] = "local-tiny-v1"
    cases: tuple[FormalCase, ...]

    @model_validator(mode="after")
    def frozen_roster(self):
        expected = (
            HIDDEN_VARIANT_IDS if self.split == "private_hidden" else SEMANTIC_VERIFY_VARIANT_IDS
        )
        if self.snapshot_ids != ("baseline", *expected):
            raise ValueError("formal input requires baseline plus four ordered snapshots")
        if self.case_count != len(self.case_ids) or len(set(self.case_ids)) != self.case_count:
            raise ValueError("formal input roster must be complete and unique")
        if tuple(item.case_id for item in self.cases) != self.case_ids:
            raise ValueError("missing records need explicit roster entries, not dropped cases")
        if self.split == "public_dev":
            if self.case_count != 120 or any(
                not case_id.startswith("C360_") or not 1001 <= int(case_id[5:]) <= 3999
                for case_id in self.case_ids
            ):
                raise ValueError("public_dev requires 120 generated-dev cases; no human/train")
        elif any(
            not case_id.startswith("C360_") or int(case_id[5:]) < 4001 for case_id in self.case_ids
        ):
            raise ValueError("hidden case roster contains public cases")
        for case in self.cases:
            if (
                case.expected_action != "refuse"
                and tuple(row.snapshot_id for row in case.snapshots) != self.snapshot_ids
            ):
                raise ValueError("every answer/clarification needs five snapshot records")
        if not self.input_digests or not self.environment:
            raise ValueError("formal input requires data/task/environment provenance")
        return self
