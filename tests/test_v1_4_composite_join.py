"""v1.4 Composite Join tests: multi-table joins, SQL guard defenses, and oracle parity."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from customer360.contracts.execution import SqlLimits
from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import Filter, JoinSpec, RollingWindow, SemanticSpec
from customer360.errors import C360Error, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices


def test_compile_composite_join_sql():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        join=JoinSpec(
            path="customer_transactions_and_holdings",
            time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            filters=(
                Filter(field="status", operator="eq", values=("success",)),
                Filter(field="holding_status", operator="eq", values=("active",)),
            ),
        ),
    )
    compiled = compile_semantic(spec, repo)
    assert 'FROM "dim_customer" AS "c"' in compiled.sql
    assert 'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id"' in compiled.sql
    assert 'JOIN "fact_holding" AS "h" ON "c"."customer_id" = "h"."customer_id"' in compiled.sql
    assert '"t"."transaction_date" >=' in compiled.sql
    assert '"t"."transaction_date" <=' in compiled.sql
    assert '"t"."status" = \'success\'' in compiled.sql
    assert '"h"."holding_status" = \'active\'' in compiled.sql
    assert '"c"."customer_level" = \'VIP\'' in compiled.sql
    assert compiled.columns == (Column(name="customer_count", kind="integer"),)


def test_composite_join_requires_rolling_window():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        join=JoinSpec(
            path="customer_transactions_and_holdings",
            time_window=None,
        ),
    )
    with pytest.raises(C360Error, match="requires a rolling window"):
        compile_semantic(spec, repo)


def test_composite_join_rejects_customer_id_filter():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        join=JoinSpec(
            path="customer_transactions_and_holdings",
            time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            filters=(Filter(field="customer_id", operator="eq", values=("CUST_001",)),),
        ),
    )
    with pytest.raises(C360Error, match="join filter is not allowed: customer_id"):
        compile_semantic(spec, repo)


def test_sql_guard_validates_composite_join(repository: MetadataRepository):
    policy = tiny_eval_policy()
    sql = (
        'SELECT COUNT(DISTINCT "c"."customer_id") AS "customer_count" '
        'FROM "dim_customer" AS "c" '
        'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
        'JOIN "fact_holding" AS "h" ON "c"."customer_id" = "h"."customer_id" '
        'WHERE "c"."customer_level" = \'VIP\' '
        'AND "t"."status" = \'success\' '
        'AND "t"."transaction_date" >= \'2025-04-02\' '
        'AND "t"."transaction_date" <= \'2025-06-30\' '
        'AND "h"."holding_status" = \'active\''
    )
    guarded = validate_sql(sql, repository.catalog, policy, SqlLimits())
    assert guarded.table == "dim_customer"
    assert guarded.output_names == ("customer_count",)
    assert "dim_customer.customer_id" in guarded.referenced_columns
    assert "fact_transaction.customer_id" in guarded.referenced_columns
    assert "fact_holding.customer_id" in guarded.referenced_columns


def test_sql_guard_rejects_cartesian_join(repository: MetadataRepository):
    policy = tiny_eval_policy()
    # Missing ON condition (Cartesian product)
    bad_sql = (
        'SELECT COUNT(DISTINCT "c"."customer_id") AS "customer_count" '
        'FROM "dim_customer" AS "c" '
        'CROSS JOIN "fact_transaction" AS "t"'
    )
    with pytest.raises(QueryRejected):
        validate_sql(bad_sql, repository.catalog, policy, SqlLimits())


def test_sql_guard_rejects_duplicate_table_join(repository: MetadataRepository):
    policy = tiny_eval_policy()
    # Joining fact_transaction twice
    dup_sql = (
        'SELECT COUNT(DISTINCT "c"."customer_id") AS "customer_count" '
        'FROM "dim_customer" AS "c" '
        'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
        'JOIN "fact_transaction" AS "t2" ON "c"."customer_id" = "t2"."customer_id"'
    )
    with pytest.raises(QueryRejected):
        validate_sql(dup_sql, repository.catalog, policy, SqlLimits())


def test_composite_join_duckdb_matches_independent_oracle(baseline: Path):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        join=JoinSpec(
            path="customer_transactions_and_holdings",
            time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            filters=(
                Filter(field="status", operator="eq", values=("success",)),
                Filter(field="holding_status", operator="eq", values=("active",)),
            ),
        ),
    )
    compiled = compile_semantic(spec, repo)

    # Execute compiled SQL on DuckDB
    conn = duckdb.connect(str(baseline / "dataset.duckdb"), read_only=True)
    cur = conn.execute(compiled.sql)
    sql_rows = tuple(cur.fetchall())
    conn.close()
    sql_result = QueryResult(columns=compiled.columns, rows=sql_rows)

    # Compute with independent in-memory Oracle
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_result = compute_independent(spec, repo, slices)

    # Exact match verification
    assert sql_result.columns == oracle_result.columns
    assert sql_result.rows == oracle_result.rows
    assert compare_results(sql_result, oracle_result) is True


def test_composite_join_gateway_execution(baseline: Path):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        join=JoinSpec(
            path="customer_transactions_and_holdings",
            time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            filters=(
                Filter(field="status", operator="eq", values=("success",)),
                Filter(field="holding_status", operator="eq", values=("active",)),
            ),
        ),
    )
    compiled = compile_semantic(spec, repo)

    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    receipt = gateway.execute(compiled.sql)
    assert receipt.result is not None
    assert receipt.result.columns == (Column(name="customer_count", kind="integer"),)
    assert len(receipt.result.rows) == 1
    # Distinct customer count should be >= 0
    cnt = int(receipt.result.rows[0][0])
    assert cnt >= 0
