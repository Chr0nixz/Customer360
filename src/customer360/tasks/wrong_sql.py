"""Trusted distinguishing wrong SQL for generated/hidden intended failure classes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from customer360.contracts.execution import SqlLimits
from customer360.contracts.semantic import (
    Filter,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository, load_catalog
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.compiler import CompiledQuery, compile_semantic
from customer360.tasks.independent import TableSlice, compute_independent
from customer360.tasks.trusted_data import normalize_sql_result
from customer360.tasks.variant import tiny_eval_policy

PERMISSION_SQL = 'SELECT COUNT("customer_name") AS "customer_count" FROM "dim_customer"'
METRIC_SWAPS = {
    "failed_transaction_amount": "successful_transaction_amount",
    "successful_transaction_amount": "failed_transaction_amount",
    "failed_transaction_count": "successful_transaction_count",
    "successful_transaction_count": "failed_transaction_count",
    "cancelled_transaction_count": "successful_transaction_count",
    "cancelled_transaction_amount": "successful_transaction_amount",
    "snapshot_total_asset": "snapshot_net_asset",
    "snapshot_net_asset": "snapshot_total_asset",
    "snapshot_cash_asset": "snapshot_investment_asset",
    "snapshot_investment_asset": "snapshot_cash_asset",
    "latest_total_asset": "snapshot_total_asset",
    "distinct_customer_count": "active_customer_count",
    "active_customer_count": "distinct_customer_count",
    "closed_customer_count": "dormant_customer_count",
    "dormant_customer_count": "closed_customer_count",
    "current_service_relation_count": "current_primary_service_relation_count",
    "current_primary_service_relation_count": "current_service_relation_count",
    "successful_cash_inflow": "successful_cash_outflow",
    "successful_cash_outflow": "successful_cash_inflow",
    "successful_net_cash_flow": "successful_cash_inflow",
    "high_risk_customer_count": "distinct_customer_count",
}


@dataclass(frozen=True)
class WrongSqlContrast:
    distinguished: bool
    mode: str | None
    sql: str | None = None
    guard_code: str | None = None


def _compile_or_none(spec: SemanticSpec, repository: MetadataRepository) -> CompiledQuery | None:
    try:
        return compile_semantic(spec, repository)
    except C360Error:
        return None


def _mismatch(
    database,
    gold: CompiledQuery,
    wrong: CompiledQuery,
    independent,
) -> bool:
    if wrong.sql == gold.sql:
        return False
    try:
        observed = normalize_sql_result(database, wrong)
    except Exception:
        return False
    return not compare_results(observed, independent)


def _rolling_alts(window: RollingWindow) -> tuple[RollingWindow, ...]:
    days = [item for item in (30, 90, 180) if item != window.days]
    return tuple(RollingWindow(days=item, anchor_date=window.anchor_date) for item in days)


def _pit_alts(window: PointInTime) -> tuple[PointInTime, ...]:
    candidates = (
        date(2024, 12, 31),
        date(2025, 1, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        window.snapshot_date - timedelta(days=31),
    )
    unique = []
    for item in candidates:
        if item != window.snapshot_date and item not in unique:
            unique.append(item)
    return tuple(PointInTime(snapshot_date=item) for item in unique)


def _guard_code(sql: str) -> str | None:
    try:
        validate_sql(sql, load_catalog(), tiny_eval_policy(), SqlLimits())
    except QueryRejected as exc:
        return exc.code
    return None


def _drop_null_predicate(sql: str) -> str | None:
    for token in (' AND "end_date" IS NULL', ' WHERE "end_date" IS NULL'):
        if token in sql:
            if token.startswith(" WHERE"):
                return sql.replace(token, "", 1)
            return sql.replace(token, "", 1)
    for token in (' AND "occupation" IS NULL', ' WHERE "occupation" IS NULL'):
        if token in sql:
            if token.startswith(" WHERE"):
                return sql.replace(token, "", 1)
            return sql.replace(token, "", 1)
    return None


def _swap_metric(spec: SemanticSpec, repository: MetadataRepository) -> SemanticSpec | None:
    target = METRIC_SWAPS.get(spec.metric)
    if target is None:
        return None
    metric = repository.get_metric_definition(target)
    filters = tuple(item for item in spec.filters if item.field in metric.allowed_filter_columns)
    window = spec.time_window
    if metric.time_semantics == "none":
        window = None
    elif metric.time_semantics == "point_in_time_required" and isinstance(
        spec.time_window, LatestSnapshot
    ):
        window = PointInTime(snapshot_date=spec.time_window.anchor_date)
    elif metric.time_semantics == "rolling_required" and not isinstance(window, RollingWindow):
        return None
    group_by = spec.group_by if metric.allowed_group_dimensions else ()
    return SemanticSpec(
        metric=target,
        filters=filters,
        time_window=window,
        join=None,
        group_by=group_by,
    )


def distinguish_wrong_sql(
    *,
    intended: str,
    spec: SemanticSpec | None,
    gold: CompiledQuery | None,
    independent,
    database,
    repository: MetadataRepository,
    slices: dict[str, TableSlice],
) -> WrongSqlContrast:
    if intended == "PERMISSION_ERROR":
        code = _guard_code(PERMISSION_SQL)
        ok = code in {"PERMISSION_DENIED", "UNSAFE_SQL"}
        return WrongSqlContrast(ok, "guard_rejected" if ok else None, PERMISSION_SQL, code)
    if intended == "CLARIFICATION_FAILURE":
        if spec is None or spec.time_window is None:
            return WrongSqlContrast(False, None)
        completed = spec
        if not isinstance(completed.time_window, RollingWindow):
            return WrongSqlContrast(False, None)
        wrong_spec = SemanticSpec(
            metric=completed.metric,
            filters=completed.filters,
            time_window=_rolling_alts(completed.time_window)[0],
            join=completed.join,
            group_by=completed.group_by,
        )
        gold_query = gold or _compile_or_none(completed, repository)
        wrong = _compile_or_none(wrong_spec, repository)
        truth = independent
        if truth is None and gold_query is not None:
            truth = compute_independent(completed, repository, slices)
        if gold_query is None or wrong is None or truth is None:
            return WrongSqlContrast(False, None)
        if _mismatch(database, gold_query, wrong, truth):
            return WrongSqlContrast(True, "mismatch", wrong.sql)
        return WrongSqlContrast(False, None, wrong.sql)
    if spec is None or gold is None or independent is None:
        return WrongSqlContrast(False, None)

    def try_spec(mutated: SemanticSpec) -> WrongSqlContrast | None:
        compiled = _compile_or_none(mutated, repository)
        if compiled is None:
            return None
        if _mismatch(database, gold, compiled, independent):
            return WrongSqlContrast(True, "mismatch", compiled.sql)
        return None

    if intended == "TIME_RANGE_ERROR":
        window = spec.time_window
        if isinstance(window, RollingWindow):
            for alt in _rolling_alts(window):
                hit = try_spec(spec.model_copy(update={"time_window": alt}))
                if hit is not None:
                    return hit
        if isinstance(window, PointInTime):
            for alt in _pit_alts(window):
                hit = try_spec(spec.model_copy(update={"time_window": alt}))
                if hit is not None:
                    return hit
        if isinstance(window, LatestSnapshot):
            earlier = LatestSnapshot(anchor_date=window.anchor_date - timedelta(days=181))
            hit = try_spec(spec.model_copy(update={"time_window": earlier}))
            if hit is not None:
                return hit
            pit = SemanticSpec(
                metric="snapshot_total_asset",
                time_window=PointInTime(snapshot_date=window.anchor_date),
            )
            hit = try_spec(pit)
            if hit is not None:
                return hit
        return WrongSqlContrast(False, None)
    if intended == "JOIN_ERROR" and spec.join is not None:
        hit = try_spec(spec.model_copy(update={"join": None}))
        if hit is not None:
            return hit
        return WrongSqlContrast(False, None)
    if intended == "DUPLICATE_COUNT_ERROR" and "COUNT(DISTINCT" in gold.sql:
        if 'COUNT(DISTINCT "c"."customer_id")' in gold.sql:
            mutated_sql = gold.sql.replace('COUNT(DISTINCT "c"."customer_id")', "COUNT(*)", 1)
        else:
            mutated_sql = gold.sql.replace("COUNT(DISTINCT ", "COUNT(", 1)
        mutated = CompiledQuery(sql=mutated_sql, columns=gold.columns)
        if _mismatch(database, gold, mutated, independent):
            return WrongSqlContrast(True, "mismatch", mutated.sql)
        return WrongSqlContrast(False, None, mutated.sql)
    if intended == "NULL_HANDLING_ERROR":
        if spec.filters and any(item.operator == "is_null" for item in spec.filters):
            dropped = tuple(item for item in spec.filters if item.operator != "is_null")
            hit = try_spec(spec.model_copy(update={"filters": dropped}))
            if hit is not None:
                return hit
            filled = tuple(
                Filter(field=item.field, operator="is_not_null")
                if item.operator == "is_null"
                else item
                for item in spec.filters
            )
            hit = try_spec(spec.model_copy(update={"filters": filled}))
            if hit is not None:
                return hit
        stripped = _drop_null_predicate(gold.sql)
        if stripped is not None:
            mutated = CompiledQuery(sql=stripped, columns=gold.columns)
            if _mismatch(database, gold, mutated, independent):
                return WrongSqlContrast(True, "mismatch", mutated.sql)
        return WrongSqlContrast(False, None)
    if intended == "FILTER_ERROR" and spec.filters:
        hit = try_spec(spec.model_copy(update={"filters": ()}))
        if hit is not None:
            return hit
        return WrongSqlContrast(False, None)
    if intended == "METRIC_ERROR":
        swapped = _swap_metric(spec, repository)
        if swapped is not None:
            hit = try_spec(swapped)
            if hit is not None:
                return hit
        return WrongSqlContrast(False, None)
    if intended == "AGGREGATION_ERROR" and spec.group_by:
        mutated = CompiledQuery(
            sql=gold.sql.replace("COUNT(DISTINCT ", "COUNT(", 1),
            columns=gold.columns,
        )
        if _mismatch(database, gold, mutated, independent):
            return WrongSqlContrast(True, "mismatch", mutated.sql)
        return WrongSqlContrast(False, None)
    return WrongSqlContrast(False, None)
