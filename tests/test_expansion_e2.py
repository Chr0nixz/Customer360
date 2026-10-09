from datetime import date
from pathlib import Path

import duckdb
import pytest

from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    PointInTime,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error, QueryRejected
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import TableSlice, compute_independent

ANCHOR = date(2025, 6, 30)
ROLLING = RollingWindow(days=90, anchor_date=ANCHOR)
PIT = PointInTime(snapshot_date=ANCHOR)


def _build_test_db_and_slices(repo: MetadataRepository, db_path: Path | None = None):
    conn = duckdb.connect(str(db_path) if db_path else ":memory:")
    conn.execute(
        "CREATE TABLE dim_customer ("
        "customer_id VARCHAR, region VARCHAR, customer_level VARCHAR, status VARCHAR);"
    )
    conn.execute(
        "INSERT INTO dim_customer VALUES "
        "('C001', '华东', 'VIP', 'active'), "
        "('C002', '华北', 'standard', 'active'), "
        "('C003', '华东', 'standard', 'closed');"
    )

    conn.execute(
        "CREATE TABLE fact_transaction ("
        "customer_id VARCHAR, product_id VARCHAR, transaction_type VARCHAR, "
        "channel VARCHAR, transaction_date DATE, status VARCHAR);"
    )
    conn.execute(
        "INSERT INTO fact_transaction VALUES "
        "('C001', 'P01', 'buy', 'app', '2025-05-01', 'success'), "
        "('C002', 'P01', 'sell', 'branch', '2025-05-10', 'failed');"
    )

    conn.execute(
        "CREATE TABLE fact_cash_flow ("
        "customer_id VARCHAR, channel VARCHAR, flow_type VARCHAR, "
        "flow_date DATE, status VARCHAR);"
    )
    conn.execute(
        "INSERT INTO fact_cash_flow VALUES "
        "('C001', 'app', 'in', '2025-05-02', 'success'), "
        "('C002', 'bank', 'out', '2025-05-05', 'success');"
    )

    conn.execute(
        "CREATE TABLE fact_holding ("
        "customer_id VARCHAR, product_id VARCHAR, holding_status VARCHAR, snapshot_date DATE);"
    )
    conn.execute(
        "INSERT INTO fact_holding VALUES "
        "('C001', 'P01', 'active', '2025-06-30'), "
        "('C002', 'P02', 'active', '2025-06-30');"
    )

    conn.execute("CREATE TABLE fact_asset_snapshot (customer_id VARCHAR, snapshot_date DATE);")
    conn.execute(
        "INSERT INTO fact_asset_snapshot VALUES ('C001', '2025-06-30'), ('C003', '2025-06-30');"
    )

    conn.execute(
        "CREATE TABLE fact_service_relation ("
        "customer_id VARCHAR, manager_id VARCHAR, is_primary BOOLEAN, "
        "start_date DATE, end_date DATE);"
    )
    conn.execute(
        "INSERT INTO fact_service_relation VALUES "
        "('C001', 'M01', true, '2024-01-01', NULL), "
        "('C002', 'M02', false, '2024-01-01', '2025-01-01');"
    )

    table_configs = {
        "dim_customer": (
            ("customer_id", "region", "customer_level", "status"),
            ("string", "string", "string", "string"),
        ),
        "fact_transaction": (
            (
                "customer_id",
                "product_id",
                "transaction_type",
                "channel",
                "transaction_date",
                "status",
            ),
            ("string", "string", "string", "string", "date", "string"),
        ),
        "fact_cash_flow": (
            ("customer_id", "channel", "flow_type", "flow_date", "status"),
            ("string", "string", "string", "date", "string"),
        ),
        "fact_holding": (
            ("customer_id", "product_id", "holding_status", "snapshot_date"),
            ("string", "string", "string", "date"),
        ),
        "fact_asset_snapshot": (
            ("customer_id", "snapshot_date"),
            ("string", "date"),
        ),
        "fact_service_relation": (
            ("customer_id", "manager_id", "is_primary", "start_date", "end_date"),
            ("string", "string", "boolean", "date", "date"),
        ),
    }

    slices = {}
    for table_name, (columns, kinds) in table_configs.items():
        res = conn.execute(f"SELECT {', '.join(columns)} FROM {table_name}").fetchall()
        slices[table_name] = TableSlice(
            table_name=table_name,
            columns=columns,
            kinds=kinds,
            rows=tuple(res),
        )

    return conn, slices


def test_expansion_e2_all_five_join_paths_compile_guard_and_match_oracle(tmp_path: Path) -> None:
    repo = MetadataRepository()
    db_path = tmp_path / "test_e2.duckdb"
    conn, slices = _build_test_db_and_slices(repo, db_path)
    conn.close()

    test_cases = [
        (
            JoinSpec(
                path="customer_transactions",
                filters=(Filter(field="status", operator="eq", values=("success",)),),
                time_window=ROLLING,
            ),
            "fact_transaction",
            (
                "customer_id",
                "product_id",
                "transaction_type",
                "channel",
                "transaction_date",
                "status",
            ),
        ),
        (
            JoinSpec(
                path="customer_cash_flows",
                filters=(Filter(field="status", operator="eq", values=("success",)),),
                time_window=ROLLING,
            ),
            "fact_cash_flow",
            ("customer_id", "channel", "flow_type", "flow_date", "status"),
        ),
        (
            JoinSpec(
                path="customer_holdings",
                filters=(Filter(field="holding_status", operator="eq", values=("active",)),),
                time_window=PIT,
            ),
            "fact_holding",
            ("customer_id", "product_id", "holding_status", "snapshot_date"),
        ),
        (
            JoinSpec(
                path="customer_asset_snapshots",
                time_window=PIT,
            ),
            "fact_asset_snapshot",
            ("customer_id", "snapshot_date"),
        ),
        (
            JoinSpec(
                path="customer_service_relations",
                filters=(Filter(field="is_primary", operator="eq", values=(True,)),),
            ),
            "fact_service_relation",
            ("customer_id", "manager_id", "is_primary", "start_date", "end_date"),
        ),
    ]

    customer_cols = ("customer_id", "region", "customer_level", "status")

    for join_spec, right_table, right_cols in test_cases:
        spec = SemanticSpec(
            metric="distinct_customer_count",
            filters=(Filter(field="region", operator="eq", values=("华东",)),),
            join=join_spec,
        )

        compiled = compile_semantic(spec, repo)
        assert "JOIN" in compiled.sql
        assert right_table in compiled.sql

        policy = AccessPolicy(
            role="analyst",
            customer_ids=("C001", "C002", "C003"),
            grants=(
                TableGrant(table="dim_customer", columns=customer_cols),
                TableGrant(table=right_table, columns=right_cols),
            ),
        )
        limits = SqlLimits(max_rows=100, max_input_rows=10000, timeout_seconds=5)
        guarded = validate_sql(compiled.sql, repo.catalog, policy, limits)
        assert guarded.table == "dim_customer"
        assert right_table in guarded.tables

        oracle_res = compute_independent(spec, repo, slices)
        assert len(oracle_res.rows) == 1

        gateway = ExecutionGateway(db_path, policy, limits)
        receipt = gateway.execute(compiled.sql)
        gw_val = receipt.result.rows[0][0]
        orc_val = oracle_res.rows[0][0]
        err_msg = f"Mismatch for {join_spec.path}: gateway={gw_val}, oracle={orc_val}"
        assert gw_val == orc_val, err_msg

        # Row-level customer scope materialization check:
        # If policy only authorizes C002 (North standard), any attempt to aggregate East VIP
        # yields 0 contributors and is strictly rejected with AGGREGATION_TOO_SMALL,
        # proving row-level customer scoping precedes query aggregation.
        restricted_policy = policy.model_copy(update={"customer_ids": ("C002",)})
        restricted_gateway = ExecutionGateway(db_path, restricted_policy, limits)
        with pytest.raises(QueryRejected) as exc_scope:
            restricted_gateway.execute(compiled.sql)
        assert exc_scope.value.code == "AGGREGATION_TOO_SMALL"


def test_expansion_e2_negative_controls() -> None:
    repo = MetadataRepository()

    # 1. customer_cash_flows without rolling window should fail with TIME_RANGE_ERROR
    broken_window = SemanticSpec(
        metric="distinct_customer_count",
        join=JoinSpec(path="customer_cash_flows"),
    )
    with pytest.raises(C360Error) as exc_info:
        compile_semantic(broken_window, repo)
    assert exc_info.value.code == "TIME_RANGE_ERROR"

    # 2. Invalid filter field on right table
    broken_field = SemanticSpec(
        metric="distinct_customer_count",
        join=JoinSpec(
            path="customer_holdings",
            filters=(Filter(field="invalid_col", operator="eq", values=("val",)),),
        ),
    )
    with pytest.raises(C360Error) as exc_info:
        compile_semantic(broken_field, repo)
    assert exc_info.value.code == "JOIN_ERROR"

    # 3. SQL Guard catches non-distinct COUNT on join
    policy = AccessPolicy(
        role="analyst",
        customer_ids=("C001", "C002"),
        grants=(
            TableGrant(table="dim_customer", columns=("customer_id",)),
            TableGrant(table="fact_transaction", columns=("customer_id", "status")),
        ),
    )
    limits = SqlLimits()
    join_str = 'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id"'
    unsafe_sql = f'SELECT COUNT("c"."customer_id") AS "cnt" FROM "dim_customer" AS "c" {join_str}'
    with pytest.raises(QueryRejected) as exc_info:
        validate_sql(unsafe_sql, repo.catalog, policy, limits)
    assert exc_info.value.code == "JOIN_ERROR"
