import pytest

from customer360.contracts.execution import SqlLimits
from customer360.errors import QueryRejected
from customer360.safety.sql_guard import validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM dim_customer",
        "SELECT COUNT(DISTINCT customer_id) AS n FROM dim_customer WHERE customer_level = 'VIP'",
        "SELECT SUM(amount) AS n FROM fact_transaction WHERE status = 'success'",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE occupation IS NOT NULL",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE (region IN ('华东','华南'))",
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE c.customer_level='VIP' AND t.status='success'",
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.channel IN ('app','branch') AND t.status='success'",
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.product_id IS NULL AND t.status='success'",
        "SELECT region AS region, COUNT(DISTINCT customer_id) AS active_customer_count "
        "FROM dim_customer WHERE status = 'active' GROUP BY region",
        "SELECT SUM(s.total_asset) AS latest_total_asset FROM fact_asset_snapshot AS s "
        "JOIN (SELECT customer_id, MAX(snapshot_date) AS snapshot_date "
        "FROM fact_asset_snapshot WHERE snapshot_date <= '2025-06-30' "
        "GROUP BY customer_id) AS latest "
        "ON s.customer_id = latest.customer_id AND s.snapshot_date = latest.snapshot_date",
    ],
)
def test_supported_subset(sql, repository, policy):
    assert validate_sql(sql, repository.catalog, policy, SqlLimits()).table


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE dim_customer",
        "DELETE FROM dim_customer",
        "UPDATE dim_customer SET customer_level='VIP'",
        "SELECT COUNT(*) AS n FROM dim_customer; DROP TABLE dim_customer",
        "SELECT * FROM dim_customer",
        "SELECT customer_name AS n FROM dim_customer",
        "SELECT COUNT(customer_name) AS n FROM dim_customer",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE customer_name='客户甲'",
        "SELECT COUNT(*) AS n FROM duckdb_settings()",
        "SELECT COUNT(*) AS n FROM read_csv_auto('C:/secret.csv')",
        "SELECT COUNT(*) AS n FROM read_parquet('https://example.invalid/secret.parquet')",
        "SELECT COUNT(*) AS n FROM information_schema.tables",
        "SELECT COUNT(*) AS n FROM dim_customer JOIN fact_transaction USING(customer_id)",
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.region=t.customer_id",
        "WITH x AS (SELECT * FROM dim_customer) SELECT COUNT(*) AS n FROM x",
        "SELECT COUNT(*) AS n FROM dim_customer UNION SELECT 1",
        "SELECT COUNT(*) AS n FROM dim_customer "
        "WHERE customer_id IN (SELECT customer_id FROM dim_customer)",
        "SELECT COUNT(*) AS n FROM dim_customer GROUP BY region",
        "SELECT region AS region, COUNT(*) AS n FROM dim_customer GROUP BY region",
        "SELECT customer_level AS customer_level, COUNT(DISTINCT customer_id) AS n "
        "FROM dim_customer GROUP BY customer_level",
        "SELECT region AS region, COUNT(DISTINCT customer_id) AS n FROM dim_customer "
        "JOIN fact_transaction AS t ON dim_customer.customer_id=t.customer_id GROUP BY region",
        "SELECT SUM(total_asset) AS latest_total_asset FROM fact_asset_snapshot "
        "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM fact_asset_snapshot)",
        "SELECT COUNT(*) AS n FROM dim_customer LIMIT 1",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE customer_id = getenv('SECRET')",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE customer_level = TRUE",
        "SELECT SUM(amount) AS n FROM fact_transaction WHERE amount > '10.00'",
        "SELECT SUM(s.total_asset) AS latest_total_asset FROM fact_asset_snapshot AS s "
        "JOIN (SELECT customer_id, MAX(snapshot_date) AS snapshot_date "
        "FROM fact_asset_snapshot WHERE snapshot_date <= 'not-a-date' "
        "GROUP BY customer_id) AS latest "
        "ON s.customer_id = latest.customer_id AND s.snapshot_date = latest.snapshot_date",
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.status='success' HAVING EXISTS (SELECT 1 FROM duckdb_tables())",
        "WITH x AS (SELECT * FROM read_csv_auto('audit-fixture.csv')) "
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.status='success'",
        "SELECT COUNT(*) AS n FROM dim_customer c",
        "SELECT COUNT(*) AS n FROM dim_customer WHERE 1=1",
        "SELECT COUNT(*) AS n FROM missing_table",
        "SELECT SUM(unknown_measure) AS n FROM fact_transaction",
        "SELECT COUNT(*) FILTER (WHERE status='active') AS n FROM dim_customer",
        "SELECT COUNT(*) OVER () AS n FROM dim_customer",
        "-- only a comment",
        "",
        "SELECT 'unterminated",
    ],
)
def test_denied_constructs_never_reach_execution(sql, repository, policy):
    with pytest.raises(QueryRejected):
        validate_sql(sql, repository.catalog, policy, SqlLimits())


def test_join_in_filter_is_query_rejected_not_attribute_error(repository, policy):
    sql = (
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.channel IN ('app','branch') AND t.status='success'"
    )
    guarded = validate_sql(sql, repository.catalog, policy, SqlLimits())
    assert guarded.tables == ("dim_customer", "fact_transaction")
    assert "fact_transaction.channel" in guarded.referenced_columns


def test_join_embedded_system_function_is_rejected(repository, policy):
    sql = (
        "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
        "JOIN fact_transaction AS t ON c.customer_id=t.customer_id "
        "WHERE t.status='success' HAVING EXISTS (SELECT 1 FROM duckdb_tables())"
    )
    with pytest.raises(QueryRejected) as caught:
        validate_sql(sql, repository.catalog, policy, SqlLimits())
    assert caught.value.code in {"UNSUPPORTED_QUERY", "UNSAFE_SQL"}


@pytest.mark.parametrize("latest", [False, True])
@pytest.mark.parametrize("join_kind", ["INNER", "LEFT", "CROSS"])
def test_join_kind_is_checked_in_both_supported_shapes(repository, policy, latest, join_kind):
    if latest:
        sql = (
            "SELECT SUM(s.total_asset) AS n FROM fact_asset_snapshot AS s "
            f"{join_kind} JOIN (SELECT customer_id, MAX(snapshot_date) AS snapshot_date "
            "FROM fact_asset_snapshot WHERE snapshot_date <= '2025-06-30' "
            "GROUP BY customer_id) AS latest "
            "ON s.customer_id=latest.customer_id AND s.snapshot_date=latest.snapshot_date"
        )
    else:
        sql = (
            "SELECT COUNT(DISTINCT c.customer_id) AS n FROM dim_customer AS c "
            f"{join_kind} JOIN fact_transaction AS t ON c.customer_id=t.customer_id"
        )
    if join_kind == "INNER":
        assert validate_sql(sql, repository.catalog, policy, SqlLimits()).table
    else:
        with pytest.raises(QueryRejected):
            validate_sql(sql, repository.catalog, policy, SqlLimits())
