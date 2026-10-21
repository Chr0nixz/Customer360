"""Generate candidate SQL from a local query plan. Independent of Gold compiler."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PlanFilter:
    field: str
    operator: str
    values: tuple[object, ...] = ()
    alias: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    source_table: str
    operation: str
    measure_column: str
    output_column: str
    predicates: tuple[PlanFilter, ...] = ()
    time_column: str | None = None
    latest_anchor: date | None = None
    join_path: str | None = None
    group_by: tuple[str, ...] = ()
    limit: int | None = None
    order_by: tuple[str, ...] = ()
    order_direction: str = "desc"
    having_operator: str | None = None
    having_threshold: float | int | None = None
    ratio_alias: str | None = None


_UNSAFE = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "attach",
    "copy",
    "install",
    "load",
    "pragma",
    "call ",
    "create",
    "replace",
    "vacuum",
    "export",
    "import",
    "checkpoint",
    "grant",
    "revoke",
)


def sql_is_unsafe(sql: str) -> bool:
    folded = " ".join(sql.lower().split())
    if ";" in folded.rstrip(";"):
        return True
    return any(token in folded for token in _UNSAFE)


def _literal(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and type(value) is int:
        return str(value)
    if isinstance(value, date):
        value = value.isoformat()
    return "'" + str(value).replace("'", "''") + "'"


def _field(item: PlanFilter) -> str:
    if item.alias:
        return f'"{item.alias}"."{item.field}"'
    return f'"{item.field}"'


def _predicate(item: PlanFilter) -> str:
    field = _field(item)
    if item.operator == "is_null":
        return f"{field} IS NULL"
    if item.operator == "is_not_null":
        return f"{field} IS NOT NULL"
    if item.operator == "in":
        return f"{field} IN (" + ", ".join(_literal(v) for v in item.values) + ")"
    operator = {"eq": "=", "ne": "<>", "gte": ">=", "lte": "<="}[item.operator]
    return f"{field} {operator} {_literal(item.values[0])}"


def _aggregate(plan: QueryPlan) -> str:
    if plan.ratio_alias == "avg_ticket":
        return (
            'ROUND(CAST(SUM("amount") AS DECIMAL(18, 2)) / NULLIF(COUNT("transaction_id"), 0), 2)'
        )
    if plan.ratio_alias == "active_rate":
        case_expr = 'COUNT(DISTINCT CASE WHEN "status" = \'active\' THEN "customer_id" END)'
        den = 'NULLIF(COUNT(DISTINCT "customer_id"), 0)'
        return f"ROUND(CAST({case_expr} AS DECIMAL(18, 4)) / {den}, 4)"
    if plan.operation == "count_distinct":
        return f'COUNT(DISTINCT "{plan.measure_column}")'
    if plan.operation == "count":
        return f'COUNT("{plan.measure_column}")'
    if plan.operation == "sum":
        return f'SUM("{plan.measure_column}")'
    raise ValueError(f"unsupported operation: {plan.operation}")


JOIN_TABLE_SPECS: dict[str, tuple[str, str]] = {
    "customer_transactions": ("fact_transaction", "t"),
    "customer_cash_flows": ("fact_cash_flow", "cf"),
    "customer_holdings": ("fact_holding", "h"),
    "customer_asset_snapshots": ("fact_asset_snapshot", "a"),
    "customer_service_relations": ("fact_service_relation", "sr"),
}


def render_sql(plan: QueryPlan) -> str:
    if plan.join_path and (
        plan.join_path not in JOIN_TABLE_SPECS
        and plan.join_path != "customer_transactions_and_holdings"
    ):
        raise ValueError("join path is not executable")
    if plan.latest_anchor is not None:
        if plan.predicates or plan.group_by or plan.join_path or not plan.time_column:
            raise ValueError("latest-snapshot cannot mix extra plan clauses")
        anchor = _literal(plan.latest_anchor)
        time_column = plan.time_column
        return (
            f'SELECT SUM("s"."{plan.measure_column}") AS "{plan.output_column}" '
            f'FROM "{plan.source_table}" AS "s" '
            "JOIN ("
            f'SELECT "customer_id", MAX("{time_column}") AS "{time_column}" '
            f'FROM "{plan.source_table}" WHERE "{time_column}" <= {anchor} '
            'GROUP BY "customer_id"'
            ') AS "latest" '
            'ON "s"."customer_id" = "latest"."customer_id" '
            f'AND "s"."{time_column}" = "latest"."{time_column}"'
        )
    where = ""
    if plan.predicates:
        where = " WHERE " + " AND ".join(_predicate(item) for item in plan.predicates)
    if plan.join_path == "customer_transactions_and_holdings":
        expression = f'COUNT(DISTINCT "c"."{plan.measure_column}")'
        return (
            f'SELECT {expression} AS "{plan.output_column}" '
            f'FROM "dim_customer" AS "c" '
            f'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
            f'JOIN "fact_holding" AS "h" ON "c"."customer_id" = "h"."customer_id"' + where
        )
    if plan.join_path:
        right_table, alias = JOIN_TABLE_SPECS[plan.join_path]
        expression = f'COUNT(DISTINCT "c"."{plan.measure_column}")'
        if plan.group_by:
            keys = ", ".join(f'"c"."{name}" AS "{name}"' for name in plan.group_by)
            grouped = " GROUP BY " + ", ".join(f'"c"."{name}"' for name in plan.group_by)
            return (
                f'SELECT {keys}, {expression} AS "{plan.output_column}" '
                f'FROM "dim_customer" AS "c" '
                f'JOIN "{right_table}" AS "{alias}" ON "c"."customer_id" = "{alias}"."customer_id"'
                f"{where}{grouped}"
            )
        return (
            f'SELECT {expression} AS "{plan.output_column}" '
            f'FROM "dim_customer" AS "c" '
            f'JOIN "{right_table}" AS "{alias}" ON "c"."customer_id" = "{alias}"."customer_id"'
            + where
        )
    expression = _aggregate(plan)
    if plan.group_by:
        keys = ", ".join(f'"{name}" AS "{name}"' for name in plan.group_by)
        grouped = " GROUP BY " + ", ".join(f'"{name}"' for name in plan.group_by)
        having_clause = ""
        if plan.having_operator and plan.having_threshold is not None:
            op_map = {
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
                "eq": "=",
                "ne": "<>",
                ">": ">",
                ">=": ">=",
                "<": "<",
                "<=": "<=",
                "=": "=",
                "<>": "<>",
            }
            op_str = op_map.get(plan.having_operator, ">")
            having_clause = f" HAVING {expression} {op_str} {plan.having_threshold}"
        order_clause = ""
        if plan.order_by or plan.limit is not None:
            direction = plan.order_direction.upper()
            primary = plan.order_by[0] if plan.order_by else plan.output_column
            tie_breakers = [f'"{dim}" ASC' for dim in plan.group_by if dim != primary]
            order_items = [f'"{primary}" {direction}'] + tie_breakers
            order_clause = " ORDER BY " + ", ".join(order_items)
        limit_clause = f" LIMIT {plan.limit}" if plan.limit is not None else ""
        tail = f"{where}{grouped}{having_clause}{order_clause}{limit_clause}"
        select_clause = f'SELECT {keys}, {expression} AS "{plan.output_column}"'
        return f'{select_clause} FROM "{plan.source_table}"{tail}'
    return f'SELECT {expression} AS "{plan.output_column}" FROM "{plan.source_table}"{where}'
