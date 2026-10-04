"""Diagnostics contracts: fine-grained failure attribution and dimensional aggregations.

Public and desensitized; does not expose private gold queries or seeds.
"""

from typing import Literal

from pydantic import Field

from customer360.contracts.base import Contract, Text


class DiagnosticQuadruple(Contract):
    """The four core business facets of a query task."""

    metric_name: Text | None = None
    filter_dimensions: tuple[Text, ...] = Field(default_factory=tuple)
    time_kind: Text | None = None
    join_path: Text | None = None


class CaseFailureAttribution(Contract):
    """Fine-grained attribution for a failed test case."""

    case_id: Text
    split: Text = "dev"
    stage: Literal["plan", "sql_guard", "execution", "comparison", "interaction"]
    primary_failure_code: Text
    quadruple: DiagnosticQuadruple
    diff_summary: Text | None = None


class DimensionFailureAggregation(Contract):
    """Failure statistics aggregated along a single business facet."""

    dimension_type: Literal["metric", "filter", "time", "join"]
    dimension_value: Text
    total_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    failure_rate: float = Field(ge=0.0, le=1.0)
    top_failure_codes: tuple[tuple[Text, int], ...] = Field(default_factory=tuple)


class DiagnosticSummary(Contract):
    """Complete diagnostic report for an evaluation run."""

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    attributions: tuple[CaseFailureAttribution, ...] = Field(default_factory=tuple)
    aggregations: tuple[DimensionFailureAggregation, ...] = Field(default_factory=tuple)
    limitations: tuple[Text, ...] = Field(default_factory=tuple)
