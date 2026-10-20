"""v1.4 DSL extensions: HAVING clause post-aggregation filtering."""

from __future__ import annotations

import duckdb
import pytest

from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import HavingCondition, SemanticSpec
from customer360.errors import QueryRejected
from customer360.evaluator.compare import ComparisonPolicy, compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices


def test_having_condition_contract_validation():
    # Valid having condition
    cond = HavingCondition(operator="gte", value=10)
    assert cond.operator == "gte"
    assert cond.value == 10

    # Reject NaN / infinite float
    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        HavingCondition(operator="gt", value=float("nan"))

    # Valid spec with having on group_by
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=5),),
    )
    assert len(spec.having) == 1
    assert spec.having[0].value == 5

    # Reject having on scalar queries without group_by
    with pytest.raises(
        ValueError, match="having conditions are only valid on multi-row group_by queries"
    ):
        SemanticSpec(
            metric="active_customer_count",
            having=(HavingCondition(operator="gt", value=10),),
        )

    # Reject having metric mismatch
    with pytest.raises(ValueError, match="does not match query metric"):
        SemanticSpec(
            metric="active_customer_count",
            group_by=("region",),
            having=(HavingCondition(metric="total_asset", operator="gt", value=100),),
        )


def test_compiler_generates_having_sql():
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=2),),
    )
    compiled = compile_semantic(spec, repo)
    assert 'GROUP BY "region"' in compiled.sql
    assert 'HAVING COUNT(DISTINCT "customer_id") >= 2' in compiled.sql
    assert compiled.columns == (
        Column(name="region", kind="string"),
        Column(name="active_customer_count", kind="integer"),
    )


def test_sql_guard_admits_valid_having_and_topk():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="dim_customer", columns=("region", "customer_id")),),
    )
    limits = SqlLimits()

    # Valid grouped query with HAVING and ORDER BY + LIMIT
    sql = (
        'SELECT "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        'HAVING COUNT(DISTINCT "customer_id") >= 2 '
        'ORDER BY "cnt" DESC, "region" ASC '
        "LIMIT 3"
    )
    guarded = validate_sql(sql, repo.catalog, policy, limits)
    assert guarded.table == "dim_customer"
    assert guarded.output_names == ("region", "cnt")


def test_sql_guard_rejects_unsafe_having():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="dim_customer", columns=("region", "customer_id")),),
    )
    limits = SqlLimits()

    # 1. Reject HAVING on scalar query without GROUP BY
    bad_scalar = (
        'SELECT COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'HAVING COUNT(DISTINCT "customer_id") >= 2'
    )
    with pytest.raises(Exception, match="HAVING clause is only supported on grouped queries"):
        validate_sql(bad_scalar, repo.catalog, policy, limits)

    # 2. Reject HAVING with raw column predicate (e.g. region = '华东' in having)
    bad_having = (
        'SELECT "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        "HAVING \"region\" = '华东'"
    )
    with pytest.raises(Exception, match="HAVING"):
        validate_sql(bad_having, repo.catalog, policy, limits)


def test_independent_oracle_and_duckdb_having_match(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=2),),
    )

    compiled = compile_semantic(spec, repo)
    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = QueryResult(columns=compiled.columns, rows=tuple(duck_res))
    assert len(duck_result.rows) == len(oracle_res.rows)
    assert duck_result.columns == oracle_res.columns

    # Verify every row satisfies having condition >= 2
    for row in oracle_res.rows:
        assert row[1] >= 2

    assert compare_results(duck_result, oracle_res) is True


def test_having_combined_with_topk_and_tie_breaker(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=2),),
        order_direction="desc",
        limit=2,
    )

    compiled = compile_semantic(spec, repo)
    assert 'HAVING COUNT(DISTINCT "customer_id") >= 2' in compiled.sql
    assert "LIMIT 2" in compiled.sql

    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)

    duck_result = QueryResult(columns=compiled.columns, rows=tuple(duck_res))
    assert len(oracle_res.rows) <= 2
    assert len(duck_result.rows) == len(oracle_res.rows)
    for row in oracle_res.rows:
        assert row[1] >= 2

    policy = ComparisonPolicy(ordered=True)
    assert compare_results(duck_result, oracle_res, policy=policy) is True


def test_having_operators_coverage(baseline):
    repo = MetadataRepository()
    db_path = str(baseline / "dataset.duckdb")
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)

    # Test gt, lt, lte, eq, ne
    for op, val in [("gt", 2), ("lt", 5), ("lte", 3), ("eq", 2), ("ne", 2)]:
        spec = SemanticSpec(
            metric="distinct_customer_count",
            group_by=("customer_level",),
            having=(HavingCondition(operator=op, value=val),),  # type: ignore[arg-type]
        )
        compiled = compile_semantic(spec, repo)
        conn = duckdb.connect(db_path, read_only=True)
        duck_res = conn.execute(compiled.sql).fetchall()
        conn.close()

        oracle_res = compute_independent(spec, repo, slices)
        duck_result = QueryResult(columns=compiled.columns, rows=tuple(duck_res))
        assert compare_results(duck_result, oracle_res) is True


def test_having_compound_and_conditions(baseline):
    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(
            HavingCondition(operator="gte", value=2),
            HavingCondition(operator="lte", value=10),
        ),
    )
    compiled = compile_semantic(spec, repo)
    expected_having = (
        'HAVING COUNT(DISTINCT "customer_id") >= 2 AND COUNT(DISTINCT "customer_id") <= 10'
    )
    assert expected_having in compiled.sql

    db_path = str(baseline / "dataset.duckdb")
    conn = duckdb.connect(db_path, read_only=True)
    duck_res = conn.execute(compiled.sql).fetchall()
    conn.close()

    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)
    oracle_res = compute_independent(spec, repo, slices)
    duck_result = QueryResult(columns=compiled.columns, rows=tuple(duck_res))
    assert compare_results(duck_result, oracle_res) is True


def test_sql_guard_having_adversarial_rejections():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="dim_customer", columns=("region", "customer_id")),),
    )
    limits = SqlLimits()

    # 1. Reject OR inside HAVING (Fail-Closed: only AND is supported)
    bad_or = (
        'SELECT "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        'HAVING COUNT(DISTINCT "customer_id") >= 2 OR COUNT(DISTINCT "customer_id") < 1'
    )
    with pytest.raises(Exception, match="HAVING condition must use comparison predicates"):
        validate_sql(bad_or, repo.catalog, policy, limits)

    # 2. Reject string literal comparison in HAVING
    bad_str = (
        'SELECT "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        "HAVING COUNT(DISTINCT \"customer_id\") = 'two'"
    )
    with pytest.raises(Exception, match="HAVING condition value must be numeric"):
        validate_sql(bad_str, repo.catalog, policy, limits)

    # 3. Reject unknown aggregate expression in HAVING
    bad_agg = (
        'SELECT "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        'HAVING MAX("customer_id") >= 2'
    )
    with pytest.raises(QueryRejected):
        validate_sql(bad_agg, repo.catalog, policy, limits)


def test_transpile_having_sql_to_postgres():
    from customer360.runtime.dialects import transpile_sql

    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="active_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=5),),
        order_direction="desc",
        limit=3,
    )
    compiled = compile_semantic(spec, repo)
    res = transpile_sql(compiled.sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "HAVING COUNT(DISTINCT" in res.transpiled_sql
    assert "LIMIT 3" in res.transpiled_sql


def test_check_having_rewrites():
    from customer360.tasks.pack_rewrites import check_generated_rewrite

    repo = MetadataRepository()
    spec = SemanticSpec(
        metric="distinct_customer_count",
        group_by=("region",),
        having=(HavingCondition(operator="gte", value=10),),
    )

    class MockCase:
        case_id = "C360_1999"
        expected_action = "answer"
        category = "grouping"
        material_status = "compilable_answer"
        metric = "distinct_customer_count"
        filters = ()
        time_window = None
        join = None
        group_by = ("region",)
        having = spec.having
        limit = None
        missing_slots = ()
        slot_replies = ()
        accepted_reason_codes = ()

    mock_case = MockCase()

    # 1. Valid rewrite
    valid_text = "按地区统计客户数不少于10人的各地区及客户数量。"
    issues = check_generated_rewrite(mock_case, valid_text, repo)
    assert len(issues) == 0

    # 2. Dropping threshold 10
    bad_thresh = "按地区统计客户数较多的各地区客户数量。"
    issues = check_generated_rewrite(mock_case, bad_thresh, repo)
    assert any("having rewrite drops threshold 10" in i.detail for i in issues)

    # 3. Dropping comparison direction
    bad_dir = "按地区统计客户数为10人的各地区及客户数量。"
    issues = check_generated_rewrite(mock_case, bad_dir, repo)
    assert any("having rewrite drops greater-than comparison direction" in i.detail for i in issues)


def test_sql_guard_rejects_grouping_column_in_having():
    repo = MetadataRepository()
    policy = AccessPolicy(
        role="analyst",
        customer_ids=(),
        grants=(TableGrant(table="dim_customer", columns=("region", "customer_id")),),
    )
    limits = SqlLimits()

    # Reject grouping column in HAVING (region is not the aggregated metric alias)
    bad_group_having = (
        'SELECT "region" AS "region", COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" '
        'GROUP BY "region" '
        'HAVING "region" > 1'
    )
    match_msg = "HAVING column 'region' must reference the aggregated metric alias"
    with pytest.raises(QueryRejected, match=match_msg):
        validate_sql(bad_group_having, repo.catalog, policy, limits)


def test_generate_task_pack_with_having(tmp_path):
    import yaml

    from customer360.tasks.generator import generate_task_pack, write_generated_pack

    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)

    # Verify that having drafts exist in the pack
    having_cases = [c for c in pack.cases if getattr(c, "having", ())]
    assert len(having_cases) >= 1
    for c in having_cases:
        assert c.category == "grouping"
        assert c.group_by
        assert c.having[0].operator in {"gte", "gt"}

    # Write pack and verify public cases do NOT leak having
    out_dir = tmp_path / "task_pack_having"
    write_generated_pack(out_dir, pack)

    public_yaml = yaml.safe_load((out_dir / "public_cases.yaml").read_text(encoding="utf-8"))
    for case in public_yaml["cases"]:
        assert "having" not in case
        assert "expected_action" not in case

    # Verify trusted oracles contain having
    trusted_yaml = yaml.safe_load((out_dir / "generated_oracles.yaml").read_text(encoding="utf-8"))
    trusted_having = [c for c in trusted_yaml["cases"] if c.get("having")]
    assert len(trusted_having) >= 1
    for c in trusted_having:
        assert len(c["having"]) >= 1
        assert "operator" in c["having"][0]
        assert "value" in c["having"][0]
