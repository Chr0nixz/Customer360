"""Trusted evaluator records. No official score fields."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.public import AgentRequest, AgentResponse, QueryResult

EVALUATOR_VERSION: Literal["0.5"] = "0.5"
FORMAL_EVALUATOR_VERSION: Literal["0.6"] = "0.6"

FROZEN_OUTCOMES = ("pass", "fail", "error")
FROZEN_PASS_REASON_CODES = frozenset({"OK", "CLARIFICATION_OK", "REFUSAL_OK"})
FROZEN_FAIL_REASON_CODES = frozenset(
    {
        "CLARIFICATION_FAILURE",
        "RESULT_MISMATCH",
        "UNSAFE_SQL",
        "REFUSAL_FAILURE",
        "AGENT_ERROR",
        "INVALID_AGENT_RESPONSE",
        "UNVERIFIED_RESULT",
        "SQL_RECEIPT_MISMATCH",
        "UNEXPECTED_ACTION",
        "PERMISSION_DENIED",
        "UNKNOWN_METRIC",
        "UNKNOWN_FIELD",
        "UNSUPPORTED_QUERY",
        "AGGREGATION_TOO_SMALL",
        "JOIN_ERROR",
        "TIMEOUT",
        "WORKER_CRASH",
        "EXECUTION_ERROR",
        "INPUT_LIMIT",
    }
)
FROZEN_ERROR_REASON_CODES = frozenset(
    {
        "ORACLE_EXECUTION_ERROR",
        "METADATA_VERSION_MISMATCH",
        "ORACLE_ANCHOR_MISMATCH",
        "POLICY_INCOMPATIBLE",
    }
)
FROZEN_REASON_CODES = (
    FROZEN_PASS_REASON_CODES | FROZEN_FAIL_REASON_CODES | FROZEN_ERROR_REASON_CODES
)
FROZEN_FAILURE_CLASSES = frozenset(
    {
        "CLARIFICATION_FAILURE",
        "RESULT_MISMATCH",
        "UNSAFE_SQL",
        "REFUSAL_FAILURE",
        "AGENT_ERROR",
        "ORACLE_EXECUTION_ERROR",
        "TIMEOUT",
        "WORKER_CRASH",
        "EXECUTION_ERROR",
        "INPUT_LIMIT",
        "POLICY_INCOMPATIBLE",
    }
)
EvaluationMode = Literal[
    "single_snapshot_smoke",
    "scripted_clarification",
    "scripted_multi_round",
    "single_snapshot_refusal",
]


class ToolCallAudit(Contract):
    tool: Identifier
    arguments_json: Text
    rejected: bool = False
    rejection_code: Text | None = None
    execution_code: Text | None = None
    failure_kind: Literal["policy", "execution"] | None = None
    query_id: Text | None = None


class ReceiptAudit(Contract):
    query_id: Text
    sql: Text
    truncated: bool = False
    row_count: int = Field(ge=0)
    result: QueryResult | None = None


class RoundAudit(Contract):
    """One Agent.respond() turn. Trusted-side only; not an official score."""

    round_index: int = Field(ge=0)
    request: AgentRequest
    response_status: Text | None = None
    response: AgentResponse | None = None
    requested_slots: tuple[Identifier, ...] = ()
    questions: tuple[Text, ...] = ()
    tool_calls: tuple[ToolCallAudit, ...] = ()
    receipts: tuple[ReceiptAudit, ...] = ()
    policy_violation: bool = False
    policy_codes: tuple[Text, ...] = ()


class EvaluationRecord(Contract):
    case_id: Text
    evaluator_version: Literal["0.5", "0.6"] = EVALUATOR_VERSION
    outcome: Literal["pass", "fail", "error"]
    reason_code: Text
    agent_status: Text | None = None
    agent_policy_violation: bool = False
    clarification_rounds: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(ge=0)
    mode: EvaluationMode = "single_snapshot_smoke"
    rounds: tuple[RoundAudit, ...] = ()
    task_version: Text | None = None
    metadata_version: Text | None = None
    policy_role: Text | None = None

    @model_validator(mode="after")
    def frozen_status_and_no_score(self) -> "EvaluationRecord":
        if self.reason_code not in FROZEN_REASON_CODES:
            raise ValueError(f"unknown evaluator reason code: {self.reason_code}")
        if self.outcome == "pass" and self.reason_code not in FROZEN_PASS_REASON_CODES:
            raise ValueError("pass requires a frozen pass reason code")
        if self.outcome == "fail" and self.reason_code not in FROZEN_FAIL_REASON_CODES:
            raise ValueError("fail requires a frozen fail reason code")
        if self.outcome == "error" and self.reason_code not in FROZEN_ERROR_REASON_CODES:
            raise ValueError("error requires a frozen error reason code")
        return self
