"""Python Gold oracle. Must not import the SQL compiler, DuckDB, Agent or evaluator."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import (
    Filter,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error
from customer360.metadata.metrics import MetadataRepository, MetricDef


@dataclass(frozen=True)
class TableSlice:
    table_name: str
    columns: tuple[str, ...]
    kinds: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]

    def index(self, column: str) -> int:
        return self.columns.index(column)

    def kind(self, column: str) -> str:
        return self.kinds[self.index(column)]


def _coerce(kind: str, value: object) -> object:
    if kind == "string":
        if type(value) is not str:
            raise C360Error("METRIC_ERROR", "filter value does not match column type")
        return value
    if kind == "date":
        try:
            parsed = date.fromisoformat(value) if type(value) is str else value
        except ValueError as exc:
            raise C360Error("METRIC_ERROR", "filter value does not match column type") from exc
        if not isinstance(parsed, date) or (type(value) is str and parsed.isoformat() != value):
            raise C360Error("METRIC_ERROR", "filter value does not match column type")
        return parsed
    if kind == "integer":
        if type(value) is not int:
            raise C360Error("METRIC_ERROR", "filter value does not match column type")
        return value
    if kind == "boolean":
        if type(value) is not bool:
            raise C360Error("METRIC_ERROR", "filter value does not match column type")
        return value
    if kind == "decimal":
        try:
            if type(value) not in {int, str, Decimal} or not Decimal(value).is_finite():
                raise C360Error("METRIC_ERROR", "filter value does not match column type")
        except (InvalidOperation, TypeError) as exc:
            raise C360Error("METRIC_ERROR", "filter value does not match column type") from exc
        return Decimal(value)
    raise C360Error("UNSUPPORTED_QUERY", "unsupported literal")


def _matches_filter(cell: object, item: Filter, kind: str) -> bool:
    if item.operator == "is_null":
        return cell is None
    if item.operator == "is_not_null":
        return cell is not None
    if cell is None:
        return False
    values = tuple(_coerce(kind, value) for value in item.values)
    if item.operator == "eq":
        return cell == values[0]
    if item.operator == "ne":
        return cell != values[0]
    if item.operator == "gte":
        return cell >= values[0]
    if item.operator == "lte":
        return cell <= values[0]
    return cell in values


def _in_time_window(cell: object, metric: MetricDef, spec: SemanticSpec) -> bool:
    if metric.time_semantics == "rolling_required":
        if not isinstance(spec.time_window, RollingWindow):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a rolling time window")
        return spec.time_window.start_date <= cell <= spec.time_window.anchor_date
    if metric.time_semantics == "point_in_time_required":
        if not isinstance(spec.time_window, PointInTime):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a point-in-time snapshot_date")
        return cell == spec.time_window.snapshot_date
    if metric.time_semantics == "latest_snapshot_required":
        if not isinstance(spec.time_window, LatestSnapshot):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a latest-snapshot anchor_date")
        return cell <= spec.time_window.anchor_date
    if spec.time_window is not None:
        raise C360Error("TIME_RANGE_ERROR", "metric does not accept a time window")
    return True


def compute_independent(
    spec: SemanticSpec, repository: MetadataRepository, slices: dict[str, TableSlice]
) -> QueryResult:
    """Aggregate a semantic spec over in-memory rows. No SQL is generated."""
    try:
        metric = repository.get_metric_definition(spec.metric)
    except KeyError as exc:
        raise C360Error("UNKNOWN_METRIC", "metric is not defined") from exc
    if spec.join is not None:
        if spec.group_by:
            raise C360Error("JOIN_ERROR", "joined queries cannot group")
        return _compute_customer_join(spec, repository, slices, metric)
    if spec.group_by:
        allowed_groups = set(metric.allowed_group_dimensions)
        if any(name not in allowed_groups for name in spec.group_by):
            raise C360Error("AGGREGATION_ERROR", "group dimension is not allowed")
    table = repository.catalog.table(metric.source_table)
    slice_ = slices[metric.source_table]
    allowed = set(metric.allowed_filter_columns)
    fixed = set(metric.fixed_filters) | set(metric.fixed_null_columns)
    for item in spec.filters:
        if item.field not in allowed or item.field in fixed:
            raise C360Error("METRIC_ERROR", f"filter is not allowed: {item.field}")
        if item.field not in {column.column_name for column in table.columns}:
            raise C360Error("SCHEMA_ERROR", f"unknown filter field: {item.field}")
        kind = table.column(item.field).kind
        for value in item.values:
            _coerce(kind, value)
    if metric.time_semantics in {
        "rolling_required",
        "point_in_time_required",
        "latest_snapshot_required",
    }:
        _in_time_window(date.min, metric, spec)
    elif spec.time_window is not None:
        raise C360Error("TIME_RANGE_ERROR", "metric does not accept a time window")

    matched = []
    for row in slice_.rows:
        keep = True
        for key, value in metric.fixed_filters.items():
            if row[slice_.index(key)] != value:
                keep = False
                break
        if not keep:
            continue
        if any(row[slice_.index(column)] is not None for column in metric.fixed_null_columns):
            continue
        if metric.time_column is not None and not _in_time_window(
            row[slice_.index(metric.time_column)], metric, spec
        ):
            continue
        if any(
            not _matches_filter(row[slice_.index(item.field)], item, slice_.kind(item.field))
            for item in spec.filters
        ):
            continue
        matched.append(row)

    if metric.time_semantics == "latest_snapshot_required":
        if spec.filters or spec.group_by:
            raise C360Error("METRIC_ERROR", "latest-snapshot does not accept extra filters")
        assert metric.time_column is not None
        customer_id = slice_.index("customer_id")
        snapshot_date = slice_.index(metric.time_column)
        latest: dict[object, tuple[object, ...]] = {}
        for row in matched:
            previous = latest.get(row[customer_id])
            if previous is None or row[snapshot_date] > previous[snapshot_date]:
                latest[row[customer_id]] = row
        matched = list(latest.values())

    measure = slice_.index(metric.measure_column)

    def _aggregate(rows: list[tuple[object, ...]]) -> tuple[object, str]:
        if metric.operation == "count_distinct":
            return len({row[measure] for row in rows if row[measure] is not None}), "integer"
        if metric.operation == "count":
            return sum(1 for row in rows if row[measure] is not None), "integer"
        amounts = [row[measure] for row in rows if row[measure] is not None]
        if not amounts:
            return None, "decimal"
        total = sum((Decimal(amount) for amount in amounts), Decimal("0"))
        return format(total, "f"), "decimal"

    if spec.group_by:
        groups: dict[tuple[object, ...], list[tuple[object, ...]]] = {}
        indexes = tuple(slice_.index(name) for name in spec.group_by)
        for row in matched:
            groups.setdefault(tuple(row[index] for index in indexes), []).append(row)
        result_rows = []
        kinds = tuple(slice_.kind(name) for name in spec.group_by)
        output_kind = "integer"
        for key, rows in groups.items():
            cell, output_kind = _aggregate(rows)
            result_rows.append((*key, cell))
        columns = tuple(
            Column(name=name, kind=kind) for name, kind in zip(spec.group_by, kinds, strict=True)
        ) + (Column(name=metric.output_column, kind=output_kind),)
        return QueryResult(columns=columns, rows=tuple(result_rows))
    cell, kind = _aggregate(matched)
    return QueryResult(
        columns=(Column(name=metric.output_column, kind=kind),),
        rows=((cell,),),
    )


INDEPENDENT_JOIN_SPECS = {
    "customer_transactions": {
        "right_table": "fact_transaction",
        "allowed_columns": {
            "customer_id",
            "product_id",
            "transaction_type",
            "channel",
            "transaction_date",
            "status",
        },
        "time_column": "transaction_date",
        "window_kind": "rolling",
    },
    "customer_cash_flows": {
        "right_table": "fact_cash_flow",
        "allowed_columns": {
            "customer_id",
            "channel",
            "flow_type",
            "flow_date",
            "status",
        },
        "time_column": "flow_date",
        "window_kind": "rolling",
    },
    "customer_holdings": {
        "right_table": "fact_holding",
        "allowed_columns": {
            "customer_id",
            "product_id",
            "holding_status",
            "snapshot_date",
        },
        "time_column": "snapshot_date",
        "window_kind": "pit",
    },
    "customer_asset_snapshots": {
        "right_table": "fact_asset_snapshot",
        "allowed_columns": {
            "customer_id",
            "snapshot_date",
        },
        "time_column": "snapshot_date",
        "window_kind": "pit",
    },
    "customer_service_relations": {
        "right_table": "fact_service_relation",
        "allowed_columns": {
            "customer_id",
            "manager_id",
            "is_primary",
            "start_date",
            "end_date",
        },
        "time_column": None,
        "window_kind": None,
    },
}


def _compute_customer_join(
    spec: SemanticSpec,
    repository: MetadataRepository,
    slices: dict[str, TableSlice],
    metric: MetricDef,
) -> QueryResult:
    supported = (
        spec.join.path in INDEPENDENT_JOIN_SPECS and metric.metric_name == "distinct_customer_count"
    )
    if not supported:
        raise C360Error("JOIN_ERROR", "only distinct customer count join is supported")
    path_def = INDEPENDENT_JOIN_SPECS[spec.join.path]
    right_table_name = path_def["right_table"]
    customer = slices["dim_customer"]
    right_slice = slices[right_table_name]
    customer_table = repository.catalog.table("dim_customer")
    right_table = repository.catalog.table(right_table_name)

    for item in spec.filters:
        if item.field not in metric.allowed_filter_columns:
            raise C360Error("JOIN_ERROR", f"customer filter is not allowed: {item.field}")
        kind = customer_table.column(item.field).kind
        for value in item.values:
            _coerce(kind, value)

    allowed_right_fields = path_def["allowed_columns"]
    for item in spec.join.filters:
        if item.field not in allowed_right_fields:
            raise C360Error("JOIN_ERROR", f"join filter is not allowed: {item.field}")
        kind = right_table.column(item.field).kind
        for value in item.values:
            _coerce(kind, value)

    if path_def["window_kind"] == "rolling":
        if spec.join.time_window is None or not isinstance(spec.join.time_window, RollingWindow):
            msg = f"joined {spec.join.path} query requires a rolling window"
            raise C360Error("TIME_RANGE_ERROR", msg)

    customer_id = customer.index("customer_id")
    right_customer_id = right_slice.index("customer_id")
    time_col = path_def["time_column"]
    time_idx = right_slice.index(time_col) if time_col else -1

    matched_ids = set()
    for customer_row in customer.rows:
        if any(
            not _matches_filter(
                customer_row[customer.index(item.field)], item, customer.kind(item.field)
            )
            for item in spec.filters
        ):
            continue

        for right_row in right_slice.rows:
            if right_row[right_customer_id] != customer_row[customer_id]:
                continue

            if path_def["window_kind"] == "rolling":
                row_date = right_row[time_idx]
                in_window = (
                    spec.join.time_window.start_date
                    <= row_date
                    <= spec.join.time_window.anchor_date
                )
                if not in_window:
                    continue
            elif path_def["window_kind"] == "pit" and spec.join.time_window is not None:
                row_date = right_row[time_idx]
                if isinstance(spec.join.time_window, PointInTime):
                    if row_date != spec.join.time_window.snapshot_date:
                        continue
                elif isinstance(spec.join.time_window, LatestSnapshot):
                    if row_date > spec.join.time_window.anchor_date:
                        continue

            if any(
                not _matches_filter(
                    right_row[right_slice.index(item.field)],
                    item,
                    right_slice.kind(item.field),
                )
                for item in spec.join.filters
            ):
                continue

            matched_ids.add(customer_row[customer_id])
            break

    return QueryResult(
        columns=(Column(name=metric.output_column, kind="integer"),),
        rows=((len(matched_ids),),),
    )
