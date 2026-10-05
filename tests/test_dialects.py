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
