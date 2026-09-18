from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from customer360.contracts.base import Contract, Identifier, Text

Cell: TypeAlias = StrictStr | StrictInt | StrictBool | None
Kind: TypeAlias = Literal["string", "integer", "decimal", "date", "boolean"]


class Column(Contract):
    name: Identifier
    kind: Kind


class QueryResult(Contract):
    """Wire format: decimals and dates are strings, interpreted by typed columns."""

    columns: tuple[Column, ...] = Field(min_length=1)
    rows: tuple[tuple[Cell, ...], ...]
    truncated: bool = False

    @model_validator(mode="after")
    def validate_cells(self) -> "QueryResult":
        if len({c.name for c in self.columns}) != len(self.columns):
            raise ValueError("duplicate result column")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError("row width differs from column count")
            for col, value in zip(self.columns, row, strict=True):
                if value is None:
                    continue
                if col.kind == "integer" and type(value) is not int:
                    raise ValueError("integer cell must be an integer, not bool/string")
                if col.kind == "boolean" and type(value) is not bool:
                    raise ValueError("boolean cell must be bool")
                if col.kind in {"string", "decimal", "date"} and type(value) is not str:
                    raise ValueError(f"{col.kind} cell must be a string")
                if col.kind == "decimal":
                    try:
                        if not Decimal(value).is_finite():
                            raise ValueError("non-finite decimal")
                    except InvalidOperation as exc:
                        raise ValueError("invalid decimal") from exc
                if col.kind == "date" and date.fromisoformat(value).isoformat() != value:
                    raise ValueError("date must be canonical ISO YYYY-MM-DD")
        return self


class Message(Contract):
    role: Literal["user", "assistant"]
    content: Text


class AgentRequest(Contract):
    case_id: Text
    question: Text
    anchor_date: date
    metadata_version: Text
    protocol_version: Literal["0.1"] = "0.1"
    conversation: tuple[Message, ...] = ()


class QueryReceipt(Contract):
    query_id: Text
    result: QueryResult
    elapsed_ms: float = Field(ge=0)


class Success(Contract):
    status: Literal["success"] = "success"
    answer: Text
    sql: Text
    query_id: Text
    assumptions: tuple[Text, ...] = ()
    evidence: tuple[Text, ...] = ()
    confidence: float = Field(ge=0, le=1)


class Clarification(Contract):
    status: Literal["clarification_needed"] = "clarification_needed"
    questions: tuple[Text, ...] = Field(min_length=1)
    requested_slots: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_slots(self) -> "Clarification":
        if len(set(self.requested_slots)) != len(self.requested_slots):
            raise ValueError("duplicate requested slot")
        return self


RefusalCode = Literal[
    "PERMISSION_DENIED",
    "UNSAFE_SQL",
    "UNKNOWN_METRIC",
    "UNKNOWN_FIELD",
    "UNSUPPORTED_QUERY",
    "AGGREGATION_TOO_SMALL",
]


class Refusal(Contract):
    status: Literal["refused"] = "refused"
    reason_code: RefusalCode
    reason: Text
    alternative: Text | None = None


class AgentError(Contract):
    status: Literal["error"] = "error"
    reason_code: Literal["UNSUPPORTED_REQUEST", "TOOL_ERROR", "INTERNAL_ERROR"]
    message: Text


AgentResponse = Annotated[
    Success | Clarification | Refusal | AgentError, Field(discriminator="status")
]
