"""Contracts for controlled query plan validation.

Exposes validation without executing SQL or revealing private data.
"""

from typing import Literal

from pydantic import Field

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.public import Cell

PlanOperator = Literal["eq", "ne", "gte", "lte", "in", "is_null", "is_not_null"]
PlanOperation = Literal["count_distinct", "count", "sum"]

ValidationIssueCode = Literal[
    "UNKNOWN_SOURCE_TABLE",
    "UNSUPPORTED_OPERATION",
    "INVALID_MEASURE_COLUMN",
    "DISALLOWED_FILTER_COLUMN",
    "INVALID_PREDICATE_LITERAL",
    "UNSUPPORTED_JOIN_PATH",
    "INVALID_JOIN_PREDICATES",
    "INVALID_GROUP_DIMENSION",
]


class PlanPredicate(Contract):
    """A logical predicate filter in a candidate query plan."""

    field: Identifier
    operator: PlanOperator
    values: tuple[Cell, ...] = Field(default_factory=tuple)
    alias: str | None = None


class QueryPlanValidationRequest(Contract):
    """Candidate query plan submitted for controlled validation."""

    source_table: Identifier
    operation: PlanOperation
    measure_column: Identifier
    output_column: Identifier
    predicates: tuple[PlanPredicate, ...] = Field(default_factory=tuple)
    join_path: str | None = None
    group_by: tuple[Identifier, ...] = Field(default_factory=tuple)
    time_column: Identifier | None = None


class QueryPlanIssue(Contract):
    """A specific validation failure code and explanation."""

    code: ValidationIssueCode
    field: str | None = None
    message: Text


class QueryPlanValidationResponse(Contract):
    """Validation result: is_valid is True only when issues is empty."""

    is_valid: bool
    issues: tuple[QueryPlanIssue, ...] = Field(default_factory=tuple)
