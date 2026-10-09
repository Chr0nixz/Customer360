from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from customer360.contracts.public import Column
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error
from customer360.metadata.metrics import MetadataRepository, MetricDef


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    columns: tuple[Column, ...]


def _quote(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, (date, str)):
        return "'" + str(value).replace("'", "''") + "'"
    raise C360Error("UNSUPPORTED_QUERY", "unsupported literal")


def _fixed_predicates(metric: MetricDef) -> list[str]:
    predicates = [f'"{key}" = {_quote(value)}' for key, value in metric.fixed_filters.items()]
    predicates.extend(f'"{column}" IS NULL' for column in metric.fixed_null_columns)
    return predicates


def _time_filters(metric: MetricDef, spec: SemanticSpec) -> list[Filter]:
    if metric.time_semantics == "rolling_required":
        if not isinstance(spec.time_window, RollingWindow):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a rolling time window")
        assert metric.time_column is not None
        return [
            Filter(
                field=metric.time_column,
                operator="gte",
                values=(spec.time_window.start_date.isoformat(),),
            ),
            Filter(
                field=metric.time_column,
                operator="lte",
                values=(spec.time_window.anchor_date.isoformat(),),
            ),
        ]
    if metric.time_semantics == "point_in_time_required":
        if not isinstance(spec.time_window, PointInTime):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a point-in-time snapshot_date")
        assert metric.time_column is not None
        return [
            Filter(
                field=metric.time_column,
                operator="eq",
                values=(spec.time_window.snapshot_date.isoformat(),),
            )
        ]
    if metric.time_semantics == "latest_snapshot_required":
        if not isinstance(spec.time_window, LatestSnapshot):
            raise C360Error("TIME_RANGE_ERROR", "metric requires a latest-snapshot anchor_date")
        return []
    if spec.time_window is not None:
        raise C360Error("TIME_RANGE_ERROR", "metric does not accept a time window")
    return []


JOIN_PATH_SPECS = {
    "customer_transactions": {
        "right_table": "fact_transaction",
        "alias": "t",
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
        "alias": "cf",
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
        "alias": "h",
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
        "alias": "a",
        "allowed_columns": {
            "customer_id",
            "snapshot_date",
        },
        "time_column": "snapshot_date",
        "window_kind": "pit",
    },
    "customer_service_relations": {
        "right_table": "fact_service_relation",
        "alias": "sr",
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


def _validate_join_filters(
    join: JoinSpec, repository: MetadataRepository
) -> tuple[list[str], str, str]:
    if join.path not in JOIN_PATH_SPECS:
        raise C360Error("JOIN_ERROR", "join path is not supported")
    path_def = JOIN_PATH_SPECS[join.path]
    table = repository.catalog.table(path_def["right_table"])
    allowed = path_def["allowed_columns"]
    alias = path_def["alias"]
    predicates = []
    filters = list(join.filters)

    if path_def["window_kind"] == "rolling":
        if join.time_window is None or not isinstance(join.time_window, RollingWindow):
            msg = f"joined {join.path} query requires a rolling window"
            raise C360Error("TIME_RANGE_ERROR", msg)
        time_col = path_def["time_column"]
        filters.extend(
            [
                Filter(
                    field=time_col,
                    operator="gte",
                    values=(join.time_window.start_date.isoformat(),),
                ),
                Filter(
                    field=time_col,
                    operator="lte",
                    values=(join.time_window.anchor_date.isoformat(),),
                ),
            ]
        )
    elif path_def["window_kind"] == "pit":
        if join.time_window is not None:
            time_col = path_def["time_column"]
            if isinstance(join.time_window, PointInTime):
                filters.append(
                    Filter(
                        field=time_col,
                        operator="eq",
                        values=(join.time_window.snapshot_date.isoformat(),),
                    )
                )
            elif isinstance(join.time_window, LatestSnapshot):
                filters.append(
                    Filter(
                        field=time_col,
                        operator="lte",
                        values=(join.time_window.anchor_date.isoformat(),),
                    )
                )

    for item in filters:
        if item.field not in allowed or item.field == "customer_id":
            raise C360Error("JOIN_ERROR", f"join filter is not allowed: {item.field}")
        kind = table.column(item.field).kind
        for value in item.values:
            if kind == "string" and type(value) is not str:
                raise C360Error("JOIN_ERROR", "join filter value does not match column type")
            if kind == "boolean" and type(value) is not bool:
                raise C360Error("JOIN_ERROR", "join filter value does not match column type")
            if kind == "date":
                try:
                    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except ValueError as exc:
                    raise C360Error("JOIN_ERROR", "join date is not canonical") from exc
        predicates.append(_predicate(item, prefix=alias))
    return predicates, path_def["right_table"], alias


def _predicate(item: Filter, prefix: str | None = None) -> str:
    field = f'"{prefix}"."{item.field}"' if prefix else f'"{item.field}"'
    if item.operator == "is_null":
        return f"{field} IS NULL"
    if item.operator == "is_not_null":
        return f"{field} IS NOT NULL"
    if item.operator == "in":
        return f"{field} IN (" + ", ".join(_quote(v) for v in item.values) + ")"
    operator = {"eq": "=", "ne": "<>", "gte": ">=", "lte": "<="}[item.operator]
    return f"{field} {operator} {_quote(item.values[0])}"


def compile_semantic(spec: SemanticSpec, repository: MetadataRepository) -> CompiledQuery:
    try:
        metric = repository.get_metric_definition(spec.metric)
    except KeyError as exc:
        raise C360Error("UNKNOWN_METRIC", "metric is not defined") from exc
    if spec.join is not None:
        if metric.metric_name != "distinct_customer_count":
            raise C360Error("JOIN_ERROR", "only customer count supports the v0.1 join")
        if metric.source_table != "dim_customer":
            raise C360Error("JOIN_ERROR", "join metric source is not the customer table")
        if spec.group_by:
            raise C360Error("JOIN_ERROR", "joined queries cannot group")
    if spec.group_by:
        allowed_groups = set(metric.allowed_group_dimensions)
        if any(name not in allowed_groups for name in spec.group_by):
            raise C360Error("AGGREGATION_ERROR", "group dimension is not allowed")
    table = repository.catalog.table(metric.source_table)
    filters = list(spec.filters) + _time_filters(metric, spec)
    allowed = set(metric.allowed_filter_columns)
    fixed = set(metric.fixed_filters) | set(metric.fixed_null_columns)
    predicates = _fixed_predicates(metric)
    for item in filters:
        if item.field not in allowed or item.field in fixed:
            raise C360Error("METRIC_ERROR", f"filter is not allowed: {item.field}")
        if item.field not in {c.column_name for c in table.columns}:
            raise C360Error("SCHEMA_ERROR", f"unknown filter field: {item.field}")
        kind = table.column(item.field).kind
        for value in item.values:
            valid = True
            if kind == "string":
                valid = type(value) is str
            elif kind == "date":
                try:
                    valid = type(value) is str and date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
            elif kind == "integer":
                valid = type(value) is int
            elif kind == "boolean":
                valid = type(value) is bool
            elif kind == "decimal":
                try:
                    valid = type(value) in {int, str} and Decimal(value).is_finite()
                except InvalidOperation:
                    valid = False
            if not valid:
                raise C360Error("METRIC_ERROR", "filter value does not match column type")
        predicates.append(_predicate(item))
    where = (" WHERE " + " AND ".join(predicates)) if predicates else ""
    if metric.operation == "count_distinct":
        expression, alias, kind = (
            f'COUNT(DISTINCT "{metric.measure_column}")',
            metric.output_column,
            "integer",
        )
    elif metric.operation == "count":
        expression, alias, kind = (
            f'COUNT("{metric.measure_column}")',
            metric.output_column,
            "integer",
        )
    else:
        expression, alias, kind = f'SUM("{metric.measure_column}")', metric.output_column, "decimal"
    if spec.join is not None:
        join_predicates, right_table, right_alias = _validate_join_filters(spec.join, repository)
        customer_predicates = [_predicate(item, prefix="c") for item in filters]
        joined_where = customer_predicates + join_predicates
        where = " WHERE " + " AND ".join(joined_where) if joined_where else ""
        join_clause = (
            f'JOIN "{right_table}" AS "{right_alias}" '
            f'ON "c"."customer_id" = "{right_alias}"."customer_id"'
        )
        sql = (
            f'SELECT COUNT(DISTINCT "c"."customer_id") AS "{alias}" '
            f'FROM "dim_customer" AS "c" {join_clause}{where}'
        )
        return CompiledQuery(sql, (Column(name=alias, kind=kind),))
    if metric.time_semantics == "latest_snapshot_required":
        if spec.filters or spec.group_by:
            raise C360Error("METRIC_ERROR", "latest-snapshot does not accept extra filters")
        assert isinstance(spec.time_window, LatestSnapshot)
        assert metric.time_column is not None
        anchor = _quote(spec.time_window.anchor_date.isoformat())
        sql = (
            f'SELECT SUM("s"."{metric.measure_column}") AS "{alias}" '
            f'FROM "{metric.source_table}" AS "s" '
            "JOIN ("
            f'SELECT "customer_id", MAX("{metric.time_column}") AS "{metric.time_column}" '
            f'FROM "{metric.source_table}" '
            f'WHERE "{metric.time_column}" <= {anchor} '
            'GROUP BY "customer_id"'
            ') AS "latest" '
            'ON "s"."customer_id" = "latest"."customer_id" '
            f'AND "s"."{metric.time_column}" = "latest"."{metric.time_column}"'
        )
        return CompiledQuery(sql, (Column(name=alias, kind=kind),))
    if spec.group_by:
        key_select = ", ".join(f'"{name}" AS "{name}"' for name in spec.group_by)
        group_clause = " GROUP BY " + ", ".join(f'"{name}"' for name in spec.group_by)
        sql = (
            f'SELECT {key_select}, {expression} AS "{alias}" '
            f'FROM "{metric.source_table}"{where}{group_clause}'
        )
        key_columns = tuple(
            Column(name=name, kind=table.column(name).kind) for name in spec.group_by
        )
        return CompiledQuery(sql, (*key_columns, Column(name=alias, kind=kind)))
    sql = f'SELECT {expression} AS "{alias}" FROM "{metric.source_table}"{where}'
    return CompiledQuery(sql, (Column(name=alias, kind=kind),))
