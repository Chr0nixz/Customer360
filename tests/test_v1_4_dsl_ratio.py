"""v1.4 DSL extensions: Derived compound ratios and compound measures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import duckdb
import pytest

from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import (
    HavingCondition,
    RatioSpec,
    RollingWindow,
    SemanticSpec,
)
from customer360.errors import C360Error, QueryRejected
from customer360.evaluator.compare import ComparisonPolicy, compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices

ANCHOR = date(2025, 6, 30)
ROLLING = RollingWindow(days=90, anchor_date=ANCHOR)


def test_ratio_spec_contract_validation():
    # Valid ratio spec
    ratio = RatioSpec(
        numerator_metric="successful_transaction_amount",
        denominator_metric="successful_transaction_count",
        precision=2,
    )
    assert ratio.precision == 2
    assert ratio.output_alias == "ratio"

    # Reject identical numerator and denominator
    with pytest.raises(ValueError, match="numerator and denominator cannot be the same metric"):
        RatioSpec(
            numerator_metric="distinct_customer_count",
            denominator_metric="distinct_customer_count",
        )

    # Valid SemanticSpec with ratio
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        ratio=ratio,
    )
    assert spec.ratio is not None

    # Reject primary metric mismatch
    with pytest.raises(ValueError, match="must match ratio numerator"):
        SemanticSpec(
            metric="active_customer_count",
            ratio=ratio,
        )


def test_compiler_generates_ratio_sql():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        time_window=ROLLING,
        ratio=RatioSpec(
            numerator_metric="successful_transaction_amount",
            denominator_metric="successful_transaction_count",
            precision=2,
            output_alias="avg_tx_amount",
        ),
    )
    compiled = compile_semantic(spec, repo)
    assert "NULLIF(" in compiled.sql
    assert "ROUND(" in compiled.sql
    assert 'AS "avg_tx_amount"' in compiled.sql
    assert compiled.columns == (Column(name="avg_tx_amount", kind="decimal"),)


def test_compiler_rejects_cross_table_ratio():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        time_window=ROLLING,
        ratio=RatioSpec(
            numerator_metric="successful_transaction_amount",  # fact_transaction
            denominator_metric="distinct_customer_count",  # dim_customer
        ),
    )
    with pytest.raises(C360Error, match="must share the same source table"):
        compile_semantic(spec, repo)


def _to_query_result(rows: list[tuple[object, ...]], columns: tuple[Column, ...]) -> QueryResult:
    formatted_rows = []
    for r in rows:
        formatted_row = []
        for cell in r:
            if isinstance(cell, float):
                formatted_row.append(str(cell))
            else:
                formatted_row.append(cell)
        formatted_rows.append(tuple(formatted_row))
    return QueryResult(columns=columns, rows=tuple(formatted_rows))


def test_independent_oracle_and_duckdb_ratio_scalar(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        time_window=ROLLING,
        ratio=RatioSpec(
            numerator_metric="successful_transaction_amount",
            denominator_metric="successful_transaction_count",
            precision=2,
            output_alias="avg_ticket",
        ),
    )
    compiled = compile_semantic(spec, repo)
    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = _to_query_result(duck_res, compiled.columns)
    assert duck_result.columns == oracle_res.columns
    assert compare_results(duck_result, oracle_res) is True


def test_independent_oracle_and_duckdb_ratio_grouped(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        ratio=RatioSpec(
            numerator_metric="active_customer_count",
            denominator_metric="distinct_customer_count",
            precision=4,
            output_alias="active_rate",
        ),
    )
    compiled = compile_semantic(spec, repo)
    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = _to_query_result(duck_res, compiled.columns)
    assert len(duck_result.rows) == len(oracle_res.rows)
    assert compare_results(duck_result, oracle_res) is True


def test_ratio_combined_with_topk_and_ordering(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        ratio=RatioSpec(
            numerator_metric="active_customer_count",
            denominator_metric="distinct_customer_count",
            precision=4,
            output_alias="active_rate",
        ),
        order_by=("active_rate",),
        order_direction="desc",
        limit=2,
    )
    compiled = compile_semantic(spec, repo)
    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = _to_query_result(duck_res, compiled.columns)
    assert len(oracle_res.rows) <= 2
    policy = ComparisonPolicy(ordered=True)
    assert compare_results(duck_result, oracle_res, policy=policy) is True


def test_sql_guard_admits_valid_ratio_query():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="fact_transaction", columns=("amount", "status", "customer_id")),),
    )
    limits = SqlLimits()

    sql = (
        'SELECT ROUND(CAST(SUM("amount") AS DECIMAL(18, 2)) / '
        'NULLIF(COUNT("customer_id"), 0), 2) AS "avg_ticket" '
        'FROM "fact_transaction"'
    )
    guarded = validate_sql(sql, repo.catalog, policy, limits)
    assert guarded.table == "fact_transaction"
    assert guarded.output_names == ("avg_ticket",)


def test_transpile_ratio_sql_to_postgres():
    from customer360.runtime.dialects import transpile_sql

    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        time_window=ROLLING,
        ratio=RatioSpec(
            numerator_metric="successful_transaction_amount",
            denominator_metric="successful_transaction_count",
            precision=2,
            output_alias="avg_tx_amount",
        ),
    )
    compiled = compile_semantic(spec, repo)
    res = transpile_sql(compiled.sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "ROUND(" in res.transpiled_sql
    assert "NULLIF(" in res.transpiled_sql


def test_ratio_combined_with_having(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        ratio=RatioSpec(
            numerator_metric="active_customer_count",
            denominator_metric="distinct_customer_count",
            precision=4,
            output_alias="active_rate",
        ),
        having=(HavingCondition(metric="active_rate", operator="gte", value=Decimal("0.85")),),
    )
    compiled = compile_semantic(spec, repo)
    assert "HAVING ROUND(" in compiled.sql
    assert ">= 0.85" in compiled.sql

    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = _to_query_result(duck_res, compiled.columns)
    for row in oracle_res.rows:
        assert Decimal(str(row[1])) >= Decimal("0.85")
    assert compare_results(duck_result, oracle_res) is True


def test_sql_guard_rejects_unsafe_ratios():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="fact_transaction", columns=("amount", "status", "customer_id")),),
    )
    limits = SqlLimits()

    # 1. Reject division without NULLIF (vulnerable to division by zero)
    bad_div = (
        'SELECT ROUND(CAST(SUM("amount") AS DECIMAL(18, 2)) / '
        'COUNT("customer_id"), 2) AS "avg_ticket" '
        'FROM "fact_transaction"'
    )
    with pytest.raises(QueryRejected, match="ratio denominator must be protected with NULLIF"):
        validate_sql(bad_div, repo.catalog, policy, limits)

    # 2. Reject ratio referencing denied column (e.g. product_id not in policy grants)
    denied_col_div = (
        'SELECT ROUND(CAST(SUM("amount") AS DECIMAL(18, 2)) / '
        'NULLIF(COUNT("product_id"), 0), 2) AS "avg_ticket" '
        'FROM "fact_transaction"'
    )
    with pytest.raises(QueryRejected, match="query references a denied column"):
        validate_sql(denied_col_div, repo.catalog, policy, limits)


def test_generate_task_pack_with_ratio(tmp_path):
    import yaml

    from customer360.tasks.generator import generate_task_pack, write_generated_pack

    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)

    ratio_cases = [c for c in pack.cases if getattr(c, "ratio", None) is not None]
    assert len(ratio_cases) >= 1
    for c in ratio_cases:
        assert c.ratio.precision in {2, 4}

    out_dir = tmp_path / "task_pack_ratio"
    write_generated_pack(out_dir, pack)

    public_yaml = yaml.safe_load((out_dir / "public_cases.yaml").read_text(encoding="utf-8"))
    for case in public_yaml["cases"]:
        assert "ratio" not in case
        assert "expected_action" not in case

    trusted_yaml = yaml.safe_load((out_dir / "generated_oracles.yaml").read_text(encoding="utf-8"))
    trusted_ratios = [c for c in trusted_yaml["cases"] if c.get("ratio") is not None]
    assert len(trusted_ratios) >= 1


def test_sql_guard_admits_ratio_in_having():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="dim_customer", columns=("region", "customer_id")),),
    )
    limits = SqlLimits()

    sql = (
        'SELECT "region" AS "region", '
        'ROUND(CAST(COUNT(DISTINCT "customer_id") AS DECIMAL(18, 4)) / '
        'NULLIF(COUNT(DISTINCT "customer_id"), 0), 4) AS "active_rate" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        'HAVING ROUND(CAST(COUNT(DISTINCT "customer_id") AS DECIMAL(18, 4)) / '
        'NULLIF(COUNT(DISTINCT "customer_id"), 0), 4) >= 0.85'
    )
    guarded = validate_sql(sql, repo.catalog, policy, limits)
    assert guarded.table == "dim_customer"
    assert guarded.output_names == ("region", "active_rate")


def test_sql_guard_rejects_unsafe_precision_and_cast():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="fact_transaction", columns=("amount", "customer_id")),),
    )
    limits = SqlLimits()

    # 1. Reject excessive precision (e.g. 99)
    bad_prec = (
        'SELECT ROUND(CAST(SUM("amount") AS DECIMAL(18, 2)) / '
        'NULLIF(COUNT("customer_id"), 0), 99) AS "avg_ticket" '
        'FROM "fact_transaction"'
    )
    with pytest.raises(QueryRejected, match="ROUND precision 99 is outside allowed range"):
        validate_sql(bad_prec, repo.catalog, policy, limits)

    # 2. Reject non-numeric CAST (e.g. CAST to VARCHAR)
    bad_cast = (
        'SELECT ROUND(CAST(SUM("amount") AS VARCHAR) / '
        'NULLIF(COUNT("customer_id"), 0), 2) AS "avg_ticket" '
        'FROM "fact_transaction"'
    )
    with pytest.raises(QueryRejected, match="CAST target must be a numeric type"):
        validate_sql(bad_cast, repo.catalog, policy, limits)
