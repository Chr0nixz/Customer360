"""v1.4 DSL extensions: Top-K, deterministic tie-breakers, and ordering semantics."""

from __future__ import annotations

import duckdb
import pytest

from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import Filter, SemanticSpec
from customer360.evaluator.compare import ComparisonPolicy, compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices


def test_topk_semantic_spec_contract_validation():
    # Valid Top-K spec
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        limit=3,
        order_direction="desc",
    )
    assert spec.limit == 3
    assert spec.order_direction == "desc"

    # Reject duplicate order_by
    with pytest.raises(ValueError, match="duplicate order_by"):
        SemanticSpec(
            metric="active_customer_count",
            group_by=("region",),
            order_by=("region", "region"),
        )

    # Reject limit without group_by or order_by
    with pytest.raises(ValueError, match="limit queries require explicit order_by or group_by"):
        SemanticSpec(
            metric="active_customer_count",
            limit=5,
        )


def test_compile_topk_sql_with_deterministic_tie_breaker():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        limit=3,
        order_direction="desc",
    )
    compiled = compile_semantic(spec, repo)
    assert 'GROUP BY "region"' in compiled.sql
    assert 'ORDER BY "active_customer_count" DESC, "region" ASC' in compiled.sql
    assert "LIMIT 3" in compiled.sql
    assert compiled.columns == (
        Column(name="region", kind="string"),
        Column(name="active_customer_count", kind="integer"),
    )


def test_topk_independent_oracle_matches_compiled_duckdb(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        limit=3,
        order_direction="desc",
    )
    compiled = compile_semantic(spec, repo)

    # Execute compiled SQL on real DuckDB database
    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    cur = conn.execute(compiled.sql)
    sql_rows = tuple(cur.fetchall())
    conn.close()

    sql_result = QueryResult(columns=compiled.columns, rows=sql_rows)

    # Compute independent Oracle directly from slices
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    independent_result = compute_independent(spec, repo, slices)

    # Both results must match in length and exact ordered rows
    assert len(sql_result.rows) <= 3
    assert len(sql_result.rows) == len(independent_result.rows)
    assert sql_result.columns == independent_result.columns

    # Verify strict ordered equality
    policy = ComparisonPolicy(ordered=True)
    assert compare_results(sql_result, independent_result, policy=policy) is True


def test_topk_filters_and_order_direction(baseline):
    repo = MetadataRepository()
    # Filter for active customers in specific status, order by customer_level ASC, Limit 2
    spec = SemanticSpec(
        metric="distinct_customer_count",
        group_by=("customer_level",),
        filters=(Filter(field="status", operator="eq", values=("active",)),),
        limit=2,
        order_direction="asc",
    )
    compiled = compile_semantic(spec, repo)
    assert 'ORDER BY "customer_count" ASC, "customer_level" ASC' in compiled.sql
    assert "LIMIT 2" in compiled.sql

    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    cur = conn.execute(compiled.sql)
    sql_rows = tuple(cur.fetchall())
    conn.close()

    sql_result = QueryResult(columns=compiled.columns, rows=sql_rows)
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    independent_result = compute_independent(spec, repo, slices)

    assert len(sql_result.rows) == 2
    policy = ComparisonPolicy(ordered=True)
    assert compare_results(sql_result, independent_result, policy=policy) is True


def test_topk_deterministic_tie_breaker_parity(baseline):
    repo = MetadataRepository()
    # Query all regions with Limit 5 (all regions), checking tie-breaker order consistency
    spec = SemanticSpec(
        metric="distinct_customer_count",
        group_by=("region",),
        limit=5,
        order_direction="desc",
    )
    compiled = compile_semantic(spec, repo)
    assert 'ORDER BY "customer_count" DESC, "region" ASC' in compiled.sql

    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    cur = conn.execute(compiled.sql)
    sql_rows = tuple(cur.fetchall())
    conn.close()

    sql_result = QueryResult(columns=compiled.columns, rows=sql_rows)
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    independent_result = compute_independent(spec, repo, slices)

    # Ordered check must strictly match
    policy = ComparisonPolicy(ordered=True)
    assert compare_results(sql_result, independent_result, policy=policy) is True
