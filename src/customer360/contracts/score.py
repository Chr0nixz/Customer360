"""Formal local score protocol. Historical no-score reports remain unchanged."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text

SCORE_PROTOCOL_VERSION = "1.0"
SCORE_WEIGHTS = {
    "correctness": 0.45,
    "safety": 0.20,
    "interaction": 0.15,
    "efficiency": 0.15,
    "robustness": 0.05,
}


class ScoreDimension(Contract):
    name: Literal["correctness", "safety", "interaction", "efficiency", "robustness"]
    weight: float = Field(ge=0, le=1)
    passed: int = Field(ge=0)
    eligible: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)
    unavailable: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def counts_and_weight(self) -> "ScoreDimension":
        if self.passed > self.eligible:
            raise ValueError("score dimension passed cannot exceed eligible")
        expected = self.passed / self.eligible if self.eligible else 0.0
        if abs(self.score - expected) > 1e-9:
            raise ValueError("score dimension score does not match counts")
        if abs(self.contribution - self.score * self.weight) > 1e-9:
            raise ValueError("score dimension contribution does not match weight")
        return self


class ScoreGate(Contract):
    name: Text
    passed: bool
    reason: Text


class ScoreRunReport(Contract):
    protocol_version: Literal["1.0"] = SCORE_PROTOCOL_VERSION
    score_protocol_version: Literal["1.0"] = "1.0"
    report_kind: Literal["official_local_score"] = "official_local_score"
    scoring_applied: Literal[True] = True
    ranking_enabled: Literal[False] = False
    split: Literal["public_dev", "private_hidden"]
    agent_id: Text
    agent_version: Text
    case_count: int = Field(ge=1)
    eligible_count: int = Field(ge=0)
    weighted_score: float = Field(ge=0, le=1)
    dimensions: tuple[ScoreDimension, ...] = Field(min_length=5, max_length=5)
    hard_gates: tuple[ScoreGate, ...] = Field(min_length=1)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    coverage: dict[str, int] = Field(default_factory=dict)
    unavailable_metrics: tuple[Text, ...] = ("token_count", "scan_count")
    evaluator_version: Text
    data_version: Text
    task_version: Text
    metadata_version: Text
    environment: dict
    input_report_digests: dict[str, Text]
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def complete_score(self) -> "ScoreRunReport":
        names = tuple(item.name for item in self.dimensions)
        if set(names) != set(SCORE_WEIGHTS) or len(names) != len(set(names)):
            raise ValueError("score report must contain each weighted dimension exactly once")
        if abs(sum(item.weight for item in self.dimensions) - 1.0) > 1e-9:
            raise ValueError("score weights must sum to one")
        if any(item.weight != SCORE_WEIGHTS[item.name] for item in self.dimensions):
            raise ValueError("formal score weights are frozen")
        expected = sum(item.contribution for item in self.dimensions)
        if abs(self.weighted_score - expected) > 1e-9:
            raise ValueError("weighted score does not match dimension contributions")
        if self.eligible_count > self.case_count:
            raise ValueError("eligible_count cannot exceed case_count")
        return self


class PublicScoreSummary(Contract):
    protocol_version: Literal["1.0"] = SCORE_PROTOCOL_VERSION
    score_protocol_version: Literal["1.0"] = "1.0"
    report_kind: Literal["public_official_local_score"] = "public_official_local_score"
    scoring_applied: Literal[True] = True
    ranking_enabled: Literal[False] = False
    split: Literal["public_dev", "private_hidden"]
    agent_id: Text
    case_count: int = Field(ge=1)
    eligible_count: int = Field(ge=0)
    weighted_score: float = Field(ge=0, le=1)
    dimension_scores: dict[str, float]
    hard_gates_passed: bool
    coverage: dict[str, int]
    limitations: tuple[Text, ...]
