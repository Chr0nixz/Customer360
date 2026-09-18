from datetime import date
from decimal import Decimal

import duckdb
import pytest

from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error
from customer360.tasks.compiler import compile_semantic

ANCHOR = date(2025, 6, 30)


def test_compiler_has_required_success_and_date_filters(repository, database):
    compiled = compile_semantic(
        SemanticSpec(
            metric="successful_transaction_count",
            time_window=RollingWindow(days=90, anchor_date=ANCHOR),
        ),
        repository,
    )
    assert "2025-04-02" in compiled.sql and "'success'" in compiled.sql
    with duckdb.connect(str(database), read_only=True) as db:
        assert db.execute(compiled.sql).fetchone() == (4,)


@pytest.mark.parametrize(
    "spec,code",
    [
        (SemanticSpec(metric="missing_metric"), "UNKNOWN_METRIC"),
        (SemanticSpec(metric="successful_transaction_count"), "TIME_RANGE_ERROR"),
        (
            SemanticSpec(
                metric="successful_transaction_count",
                time_window=PointInTime(snapshot_date=ANCHOR),
            ),
            "TIME_RANGE_ERROR",
        ),
        (SemanticSpec(metric="snapshot_total_asset"), "TIME_RANGE_ERROR"),
        (
            SemanticSpec(
                metric="snapshot_total_asset",
                time_window=RollingWindow(days=90, anchor_date=ANCHOR),
            ),
            "TIME_RANGE_ERROR",
        ),
        (
            SemanticSpec(
                metric="distinct_customer_count",
                filters=(Filter(field="customer_name", operator="eq", values=("x",)),),
            ),
            "METRIC_ERROR",
        ),
        (
            SemanticSpec(
                metric="active_customer_count",
                filters=(Filter(field="status", operator="eq", values=("closed",)),),
            ),
            "METRIC_ERROR",
        ),
        (
            SemanticSpec(
                metric="latest_total_asset",
                time_window=PointInTime(snapshot_date=ANCHOR),
            ),
            "TIME_RANGE_ERROR",
        ),
        (
            SemanticSpec(metric="active_customer_count", group_by=("customer_level",)),
            "AGGREGATION_ERROR",
        ),
        (
            SemanticSpec(
                metric="snapshot_total_asset",
                time_window=LatestSnapshot(anchor_date=ANCHOR),
            ),
            "TIME_RANGE_ERROR",
        ),
    ],
)
def test_unsupported_semantics_fail_closed(repository, spec, code):
    with pytest.raises(C360Error) as caught:
        compile_semantic(spec, repository)
    assert caught.value.code == code


def test_join_in_filter_compiles_and_passes_guard(repository, policy, database):
    from customer360.contracts.execution import SqlLimits
    from customer360.runtime.gateway import ExecutionGateway
    from customer360.safety.sql_guard import validate_sql

    compiled = compile_semantic(
        SemanticSpec(
            metric="distinct_customer_count",
            join=JoinSpec(
                path="customer_transactions",
                filters=(
                    Filter(field="status", operator="eq", values=("success",)),
                    Filter(field="channel", operator="in", values=("app", "branch")),
                ),
                time_window=RollingWindow(days=90, anchor_date=ANCHOR),
            ),
        ),
        repository,
    )
    assert "IN" in compiled.sql
    guarded = validate_sql(compiled.sql, repository.catalog, policy, SqlLimits())
    assert "fact_transaction.channel" in guarded.referenced_columns
    result = ExecutionGateway(database, policy).execute(compiled.sql).result
    assert result.rows


def test_literal_injection_stays_data(repository, database):
    compiled = compile_semantic(
        SemanticSpec(
            metric="distinct_customer_count",
            filters=(Filter(field="customer_level", operator="eq", values=("VIP' OR '1'='1",)),),
        ),
        repository,
    )
    with duckdb.connect(str(database), read_only=True) as db:
        assert db.execute(compiled.sql).fetchone() == (0,)


def test_new_metrics_match_fixture_slices(repository, database):
    rolling = RollingWindow(days=90, anchor_date=ANCHOR)
    point = PointInTime(snapshot_date=ANCHOR)
    with duckdb.connect(str(database), read_only=True) as db:
        customers = db.execute("SELECT status FROM dim_customer").fetchall()
        transactions = db.execute(
            "SELECT transaction_date, status FROM fact_transaction"
        ).fetchall()
        flows = db.execute(
            "SELECT flow_date, flow_type, signed_amount, status FROM fact_cash_flow"
        ).fetchall()
        relations = db.execute("SELECT is_primary, end_date FROM fact_service_relation").fetchall()
        assets = db.execute(
            "SELECT snapshot_date, total_asset, net_asset FROM fact_asset_snapshot"
        ).fetchall()
    start = rolling.start_date
    expected = {
        "active_customer_count": sum(1 for (status,) in customers if status == "active"),
        "failed_transaction_count": sum(
            1
            for txn_date, status in transactions
            if status == "failed" and start <= txn_date <= ANCHOR
        ),
        "successful_net_cash_flow": sum(
            (
                amount
                for flow_date, _, amount, status in flows
                if status == "success" and start <= flow_date <= ANCHOR
            ),
            Decimal("0"),
        ),
        "successful_cash_inflow": sum(
            (
                amount
                for flow_date, flow_type, amount, status in flows
                if status == "success" and flow_type == "in" and start <= flow_date <= ANCHOR
            ),
            Decimal("0"),
        ),
        "current_primary_service_relation_count": sum(
            1 for primary, end in relations if primary and end is None
        ),
        "snapshot_total_asset": sum(
            (total for snapshot, total, _ in assets if snapshot == ANCHOR), Decimal("0")
        ),
        "snapshot_net_asset": sum(
            (net for snapshot, _, net in assets if snapshot == ANCHOR), Decimal("0")
        ),
    }
    assert expected["active_customer_count"] == 4
    assert expected["failed_transaction_count"] == 1
    assert expected["successful_net_cash_flow"] == Decimal("1400.00")
    assert expected["successful_cash_inflow"] == Decimal("1500.00")
    assert expected["current_primary_service_relation_count"] == 3
    cases = [
        SemanticSpec(metric="active_customer_count"),
        SemanticSpec(metric="failed_transaction_count", time_window=rolling),
        SemanticSpec(metric="successful_net_cash_flow", time_window=rolling),
        SemanticSpec(metric="successful_cash_inflow", time_window=rolling),
        SemanticSpec(metric="current_primary_service_relation_count"),
        SemanticSpec(metric="snapshot_total_asset", time_window=point),
        SemanticSpec(metric="snapshot_net_asset", time_window=point),
    ]
    with duckdb.connect(str(database), read_only=True) as db:
        for spec in cases:
            compiled = compile_semantic(spec, repository)
            assert "ROW_NUMBER" not in compiled.sql.upper()
            assert " JOIN " not in compiled.sql.upper()
            assert db.execute(compiled.sql).fetchone()[0] == expected[spec.metric]


def test_primary_relation_sql_uses_boolean_and_null(repository):
    compiled = compile_semantic(
        SemanticSpec(metric="current_primary_service_relation_count"), repository
    )
    assert "TRUE" in compiled.sql
    assert "IS NULL" in compiled.sql
    assert "end_date" in compiled.sql


def test_snapshot_sql_equals_one_valuation_date(repository):
    compiled = compile_semantic(
        SemanticSpec(
            metric="snapshot_total_asset",
            time_window=PointInTime(snapshot_date=ANCHOR),
        ),
        repository,
    )
    assert "snapshot_date" in compiled.sql
    assert "2025-06-30" in compiled.sql
    assert ">=" not in compiled.sql


def test_customer_transaction_join_compiles_and_deduplicates(repository, database):
    spec = SemanticSpec(
        metric="distinct_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        join=JoinSpec(
            path="customer_transactions",
            filters=(Filter(field="status", operator="eq", values=("success",)),),
            time_window=RollingWindow(days=90, anchor_date=ANCHOR),
        ),
    )
    compiled = compile_semantic(spec, repository)
    assert 'JOIN "fact_transaction"' in compiled.sql
    assert 'COUNT(DISTINCT "c"."customer_id")' in compiled.sql
    with duckdb.connect(str(database), read_only=True) as db:
        assert db.execute(compiled.sql).fetchone() == (2,)


def test_join_rejects_missing_window(repository):
    with pytest.raises(C360Error, match="rolling window"):
        compile_semantic(
            SemanticSpec(
                metric="distinct_customer_count",
                join=JoinSpec(path="customer_transactions"),
            ),
            repository,
        )
