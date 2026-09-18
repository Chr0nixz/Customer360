"""Trusted-side rewrite semantic-consistency contracts.

Natural-language paraphrases are not Gold. These records only describe whether
a rewrite still encodes the canonical date, metric, filter and Join slots.
"""

from typing import Literal

from pydantic import Field

from customer360.contracts.base import Contract, Text

RewriteIssueCode = Literal[
    "TIME_RANGE_ERROR",
    "METRIC_ERROR",
    "FILTER_ERROR",
    "JOIN_ERROR",
    "CLARIFICATION_FAILURE",
    "SCHEMA_ERROR",
    "AGGREGATION_ERROR",
]


class RewriteIssue(Contract):
    case_id: Text
    rewrite: Text
    code: RewriteIssueCode
    detail: Text


class RewriteCaseResult(Contract):
    case_id: Text
    passed: bool
    rewrite_count: int = Field(ge=3, le=5)
    issues: tuple[RewriteIssue, ...] = ()


class RewriteReport(Contract):
    protocol_version: Literal["0.1"] = "0.1"
    report_kind: Literal["rewrite_semantic_consistency"] = "rewrite_semantic_consistency"
    catalog_version: Literal["0.3"] = "0.3"
    passed: bool
    case_count: Literal[20] = 20
    rewrite_count: int = Field(ge=60, le=100)
    issue_count: int = Field(ge=0)
    cases: tuple[RewriteCaseResult, ...] = Field(min_length=20, max_length=20)
