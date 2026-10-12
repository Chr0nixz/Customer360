import sqlglot
from sqlglot import exp

from customer360.runtime.dialects import get_dialect_capabilities, transpile_sql


def test_dialect_capabilities():
    duck = get_dialect_capabilities("duckdb")
    assert duck.dialect == "duckdb"
    assert duck.capability_only is False

    pg = get_dialect_capabilities("postgres")
    assert pg.dialect == "postgres"
    assert pg.decimal_type_name == "NUMERIC"
    assert pg.capability_only is True


def test_transpile_basic_aggregation():
    duck_sql = (
        'SELECT COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" WHERE "status" = \'active\''
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "count" in res.transpiled_sql.lower()
    assert '"dim_customer"' in res.transpiled_sql

    # Verify target SQL is valid PostgreSQL AST
    pg_ast = sqlglot.parse_one(res.transpiled_sql, read="postgres")
    assert isinstance(pg_ast, exp.Select)


def test_transpile_interval_syntax():
    duck_sql = (
        'SELECT "transaction_id" FROM "fact_transaction" '
        "WHERE \"transaction_date\" >= DATE '2025-06-30' - INTERVAL 89 DAY"
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "interval_syntax_converted" in res.differences

    # Verify target parseable in postgres
    pg_ast = sqlglot.parse_one(res.transpiled_sql, read="postgres")
    assert pg_ast is not None


def test_transpile_nulls_ordering_stabilization():
    duck_sql = (
        'SELECT "region", COUNT(*) AS "cnt" FROM "dim_customer" '
        'GROUP BY "region" ORDER BY "cnt" DESC'
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "nulls_ordering_stabilized" in res.differences

    # Check NULLS LAST presence in the generated SQL
    assert "NULLS LAST" in res.transpiled_sql


def test_transpile_join_query_equivalence():
    duck_sql = (
        'SELECT COUNT(DISTINCT "c"."customer_id") AS "vip_transactors" '
        'FROM "dim_customer" AS "c" '
        'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
        'WHERE "c"."customer_level" = \'VIP\' AND "t"."status" = \'success\''
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert '"c"' in res.transpiled_sql
    assert '"t"' in res.transpiled_sql
    assert "JOIN" in res.transpiled_sql

    pg_ast = sqlglot.parse_one(res.transpiled_sql, read="postgres")
    assert len(list(pg_ast.find_all(exp.Join))) == 1


def test_transpile_hardening_invalid_inputs_and_unsupported_dialects():
    import pytest

    # 1. Empty SQL query must be rejected
    with pytest.raises(ValueError, match="SQL query cannot be empty"):
        transpile_sql("   ")

    # 2. Unsupported source dialect
    with pytest.raises(ValueError, match="unsupported source dialect"):
        transpile_sql("SELECT 1", source_dialect="mysql")  # type: ignore[arg-type]

    # 3. Unsupported target dialect
    with pytest.raises(ValueError, match="unsupported target dialect"):
        transpile_sql("SELECT 1", target_dialect="oracle")  # type: ignore[arg-type]

    # 4. Parse error on malformed SQL
    with pytest.raises(ValueError, match="SQL parsing failed"):
        transpile_sql("SELECT FROM WHERE", source_dialect="duckdb")

    # 5. Multi-statement injection attempt must be blocked
    with pytest.raises(ValueError, match="multi-statement queries are forbidden"):
        transpile_sql(
            'SELECT 1; DROP TABLE "dim_customer"',
            source_dialect="duckdb",
            target_dialect="postgres",
        )

    # 6. Non-read-only DDL/DML must be blocked
    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('DROP TABLE "dim_customer"', source_dialect="duckdb")

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql(
            "INSERT INTO \"dim_customer\" VALUES (1, 'VIP')",
            source_dialect="duckdb",
        )


def test_transpile_cte_query_equivalence():
    duck_sql = (
        "WITH active_cust AS ("
        '  SELECT "customer_id" FROM "dim_customer" WHERE "status" = \'active\''
        ") "
        'SELECT COUNT(*) AS "active_cnt" FROM active_cust'
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert "WITH" in res.transpiled_sql
    assert '"active_cust"' in res.transpiled_sql

    pg_ast = sqlglot.parse_one(res.transpiled_sql, read="postgres")
    assert isinstance(pg_ast, exp.Select)
    assert pg_ast.find(exp.With) is not None


def test_postgresql_gateway_fail_closed_without_uri():
    import pytest

    from customer360.errors import QueryRejected
    from customer360.runtime.gateway import PostgreSQLExecutionGateway
    from customer360.tasks.variant import tiny_eval_policy

    policy = tiny_eval_policy()
    gateway = PostgreSQLExecutionGateway(connection_uri=None, policy=policy)
    assert gateway.engine_name == "postgres"

    with pytest.raises(QueryRejected) as exc_info:
        gateway.execute("SELECT 1")
    assert exc_info.value.code == "ENGINE_UNAVAILABLE"


def test_transpile_hardening_comments_non_ascii_and_subqueries():
    import pytest

    # 1. SQL comments (both single-line and multi-line) must be safely stripped/parsed
    duck_sql = (
        "-- Single line comment\n"
        "/* Multi-line block\n"
        "   comment */\n"
        'SELECT COUNT(*) AS "cnt" FROM "dim_customer" WHERE "region" = \'华东\''
    )
    res = transpile_sql(duck_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res.ast_valid is True
    assert '"dim_customer"' in res.transpiled_sql
    assert "'华东'" in res.transpiled_sql

    # 2. Chinese column alias and table identifiers
    duck_chinese = 'SELECT "customer_id", "region" AS "客户地区" FROM "dim_customer"'
    res_chinese = transpile_sql(duck_chinese, source_dialect="duckdb", target_dialect="postgres")
    assert res_chinese.ast_valid is True
    assert '"客户地区"' in res_chinese.transpiled_sql

    # 3. Injection attempt masked inside or after comments must still be blocked
    with pytest.raises(ValueError, match="multi-statement queries are forbidden"):
        transpile_sql(
            'SELECT 1 -- safe comment\n; DROP TABLE "dim_customer"',
            source_dialect="duckdb",
            target_dialect="postgres",
        )

    # 4. Expressions with COALESCE, NULL checks and CASE WHEN
    duck_expr = (
        'SELECT COALESCE("occupation", \'未知\') AS "occ", '
        'CASE WHEN "status" = \'active\' THEN 1 ELSE 0 END AS "is_act" '
        'FROM "dim_customer" WHERE "customer_level" IS NOT NULL'
    )
    res_expr = transpile_sql(duck_expr, source_dialect="duckdb", target_dialect="postgres")
    assert res_expr.ast_valid is True
    assert "COALESCE" in res_expr.transpiled_sql
    assert "CASE" in res_expr.transpiled_sql
    has_not_null = (
        'NOT "customer_level" IS NULL' in res_expr.transpiled_sql
        or "IS NOT NULL" in res_expr.transpiled_sql
    )
    assert has_not_null is True
