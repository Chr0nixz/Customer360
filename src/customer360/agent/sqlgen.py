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
    if plan.operation == "count_distinct":
        return f'COUNT(DISTINCT "{plan.measure_column}")'
    if plan.operation == "count":
        return f'COUNT("{plan.measure_column}")'
    if plan.operation == "sum":
        return f'SUM("{plan.measure_column}")'
    raise ValueError(f"unsupported operation: {plan.operation}")


def render_sql(plan: QueryPlan) -> str:
    if plan.join_path and plan.join_path != "customer_transactions":
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
    if plan.join_path == "customer_transactions":
        expression = f'COUNT(DISTINCT "c"."{plan.measure_column}")'
        return (
            f'SELECT {expression} AS "{plan.output_column}" '
            'FROM "dim_customer" AS "c" '
            'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id"' + where
        )
    expression = _aggregate(plan)
    if plan.group_by:
        keys = ", ".join(f'"{name}" AS "{name}"' for name in plan.group_by)
        grouped = " GROUP BY " + ", ".join(f'"{name}"' for name in plan.group_by)
        return (
            f'SELECT {keys}, {expression} AS "{plan.output_column}" '
            f'FROM "{plan.source_table}"{where}{grouped}'
        )
    return f'SELECT {expression} AS "{plan.output_column}" FROM "{plan.source_table}"{where}'
