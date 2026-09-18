from datetime import date, timedelta
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
    """The only v0.1 join path: customer attributes to transaction facts."""

    path: Literal["customer_transactions"]
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | None = None


class SemanticSpec(Contract):
    """v0.1 is intentionally single-metric. Grouping and latest-snapshot are explicit fields."""

    semantic_version: Literal["0.1"] = "0.1"
    metric: Identifier
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def grouping_and_join_are_exclusive(self) -> "SemanticSpec":
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("duplicate group_by dimension")
        if self.group_by and self.join is not None:
            raise ValueError("join queries cannot declare group_by")
        if self.group_by and isinstance(self.time_window, LatestSnapshot):
            raise ValueError("latest-snapshot queries cannot declare group_by")
        return self
