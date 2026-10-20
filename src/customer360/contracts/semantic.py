import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier
from customer360.contracts.public import Cell


class RollingWindow(Contract):
    type: Literal["rolling"] = "rolling"
    days: int = Field(ge=1, le=3660)
    anchor_date: date

    @property
    def start_date(self) -> date:
        return self.anchor_date - timedelta(days=self.days - 1)


class PointInTime(Contract):
    type: Literal["point_in_time"] = "point_in_time"
    snapshot_date: date


class LatestSnapshot(Contract):
    """Per-customer max snapshot_date on or before anchor; not a named valuation day."""

    type: Literal["latest_snapshot"] = "latest_snapshot"
    anchor_date: date


class Filter(Contract):
    field: Identifier
    operator: Literal["eq", "ne", "gte", "lte", "in", "is_null", "is_not_null"]
    values: tuple[Cell, ...] = ()

    @model_validator(mode="after")
    def arity(self) -> "Filter":
        expected = 0 if self.operator in {"is_null", "is_not_null"} else 1
        if self.operator == "in":
            if not self.values:
                raise ValueError("IN requires non-empty values")
        elif len(self.values) != expected:
            raise ValueError("wrong filter arity")
        if any(v is None for v in self.values):
            raise ValueError("use is_null/is_not_null, not NULL comparison")
        return self


class JoinSpec(Contract):
    """Supported join paths connecting customer attributes to fact tables."""

    path: Literal[
        "customer_transactions",
        "customer_holdings",
        "customer_asset_snapshots",
        "customer_cash_flows",
        "customer_service_relations",
        "customer_transactions_and_holdings",
    ]
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None


class HavingCondition(Contract):
    """Post-aggregation filter condition on the aggregated metric value."""

    metric: Identifier | None = None
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    value: Decimal | int | float

    @model_validator(mode="after")
    def validate_value(self) -> "HavingCondition":
        if isinstance(self.value, float) and (math.isnan(self.value) or math.isinf(self.value)):
            raise ValueError("having value cannot be NaN or infinite")
        return self


class SemanticSpec(Contract):
    """v0.1 is intentionally single-metric. Grouping, ordering, and latest-snapshot are explicit."""

    semantic_version: Literal["0.1"] = "0.1"
    metric: Identifier
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[Identifier, ...] = ()
    limit: int | None = Field(default=None, ge=1, le=1000)
    order_by: tuple[Identifier, ...] = ()
    order_direction: Literal["asc", "desc"] = "desc"
    having: tuple[HavingCondition, ...] = ()

    @model_validator(mode="after")
    def grouping_and_join_are_exclusive(self) -> "SemanticSpec":
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("duplicate group_by dimension")
        if self.group_by and self.join is not None:
            raise ValueError("join queries cannot declare group_by")
        if self.group_by and isinstance(self.time_window, LatestSnapshot):
            raise ValueError("latest-snapshot queries cannot declare group_by")
        if len(set(self.order_by)) != len(self.order_by):
            raise ValueError("duplicate order_by dimension")
        if (self.limit is not None or self.order_by) and not self.group_by:
            raise ValueError("ordering and limit are only valid on multi-row group_by queries")
        if self.having and not self.group_by:
            raise ValueError("having conditions are only valid on multi-row group_by queries")
        for cond in self.having:
            if cond.metric is not None and cond.metric != self.metric:
                raise ValueError(
                    f"having metric '{cond.metric}' does not match query metric '{self.metric}'"
                )
        return self
