import os
from decimal import Decimal

import pytest

from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.evaluator.compare import compare_results
from customer360.runtime.gateway import (
    DuckDBExecutionGateway,
    PostgreSQLExecutionGateway,
    _get_pg_driver,
)

PG_URI = os.environ.get("C360_TEST_PG_URI")
HAS_PG_ENV = bool(PG_URI and _get_pg_driver() is not None)


def _policy() -> AccessPolicy:
    return AccessPolicy(
        role="analyst",
        customer_ids=tuple(f"C{i:03d}" for i in range(1, 101)),
        grants=(
            TableGrant(
                table="dim_customer",
                columns=("customer_id", "customer_level", "region", "status"),
            ),
            TableGrant(
                table="fact_transaction",
                columns=("transaction_id", "customer_id", "amount", "status", "transaction_date"),
            ),
            TableGrant(
                table="fact_asset_snapshot",
                columns=("customer_id", "total_asset", "snapshot_date"),
            ),
        ),
    )


def test_postgresql_gateway_driver_and_env_diagnostics(monkeypatch):
    from customer360.errors import QueryRejected

    policy = _policy()
    # 1. Default (admitted=False) must fail-closed with ENGINE_UNAVAILABLE
    gateway_default = PostgreSQLExecutionGateway(
        connection_uri="postgresql://fake:5432/fake", policy=policy
    )
    with pytest.raises(QueryRejected) as exc_info:
        gateway_default.execute('SELECT COUNT("customer_id") FROM "dim_customer"')
    assert exc_info.value.code == "ENGINE_UNAVAILABLE"
    assert "not formally admitted" in exc_info.value.message

    # 2. Admitted but unset URI must reject with ENGINE_UNAVAILABLE
    gateway_no_uri = PostgreSQLExecutionGateway(connection_uri=None, policy=policy, admitted=True)
    with pytest.raises(QueryRejected) as exc_info:
        gateway_no_uri.execute('SELECT COUNT("customer_id") FROM "dim_customer"')
    assert exc_info.value.code == "ENGINE_UNAVAILABLE"
    assert "not configured" in exc_info.value.message

    # 3. Admitted with URI but driver missing must reject with ENGINE_UNAVAILABLE
    import customer360.runtime.gateway as gw_module

    monkeypatch.setattr(gw_module, "_get_pg_driver", lambda: None)
    gateway_no_driver = PostgreSQLExecutionGateway(
        connection_uri="postgresql://fake:5432/fake",
        policy=policy,
        admitted=True,
    )
    with pytest.raises(QueryRejected) as exc_info:
        gateway_no_driver.execute('SELECT COUNT("customer_id") FROM "dim_customer"')
    assert exc_info.value.code == "ENGINE_UNAVAILABLE"
    assert "driver" in exc_info.value.message

    # 4. Admitted gateway with simulated driver enforces SQL Guard before execution
    class DummyDriver:
        @staticmethod
        def connect(*args, **kwargs):
            raise AssertionError("Should not attempt DB connection when SQL Guard rejects query")

    monkeypatch.setattr(gw_module, "_get_pg_driver", lambda: DummyDriver)
    gateway_admitted = PostgreSQLExecutionGateway(
        connection_uri="postgresql://fake:5432/fake",
        policy=policy,
        admitted=True,
    )
    # Dangerous SQL (DROP) rejected by SQL Guard before DB connection
    with pytest.raises(QueryRejected) as exc_info:
        gateway_admitted.execute('DROP TABLE "dim_customer"')
    assert exc_info.value.code == "UNSAFE_SQL"

    # Single-customer grouping (customer_id as group dimension) rejected before DB connection
    group_sql = 'SELECT "customer_id", COUNT("status") FROM "dim_customer" GROUP BY "customer_id"'
    with pytest.raises(QueryRejected) as exc_info:
        gateway_admitted.execute(group_sql)
    assert exc_info.value.code == "UNSAFE_SQL"


@pytest.mark.skipif(not HAS_PG_ENV, reason="PostgreSQL live environment is not configured")
class TestPostgresLiveIntegration:
    @pytest.fixture(scope="class", autouse=True)
    def setup_postgres_schema_and_data(self, baseline):
        """Seed PostgreSQL with fixture data from the Tiny baseline DuckDB instance."""
        import duckdb

        driver = _get_pg_driver()
        with (
            driver.connect(PG_URI) as pg_conn,
            duckdb.connect(str(baseline / "dataset.duckdb"), read_only=True) as duck_conn,
        ):
            with pg_conn.cursor() as cur:
                # DDL Setup
                cur.execute('DROP TABLE IF EXISTS "fact_asset_snapshot" CASCADE;')
                cur.execute('DROP TABLE IF EXISTS "fact_transaction" CASCADE;')
                cur.execute('DROP TABLE IF EXISTS "dim_customer" CASCADE;')

                cur.execute(
                    'CREATE TABLE "dim_customer" ('
                    '  "customer_id" VARCHAR PRIMARY KEY,'
                    '  "customer_level" VARCHAR,'
                    '  "region" VARCHAR,'
                    '  "status" VARCHAR'
                    ");"
                )
                cur.execute(
                    'CREATE TABLE "fact_transaction" ('
                    '  "transaction_id" VARCHAR PRIMARY KEY,'
                    '  "customer_id" VARCHAR REFERENCES "dim_customer"("customer_id"),'
                    '  "amount" NUMERIC(18, 2),'
                    '  "status" VARCHAR,'
                    '  "transaction_date" DATE'
                    ");"
                )
                cur.execute(
                    'CREATE TABLE "fact_asset_snapshot" ('
                    '  "customer_id" VARCHAR REFERENCES "dim_customer"("customer_id"),'
                    '  "total_asset" NUMERIC(18, 2),'
                    '  "snapshot_date" DATE,'
                    '  PRIMARY KEY ("customer_id", "snapshot_date")'
                    ");"
                )

                # Seed dim_customer
                cust_rows = duck_conn.execute(
                    'SELECT "customer_id", "customer_level", "region", "status" FROM "dim_customer"'
                ).fetchall()
                for r in cust_rows:
                    cur.execute(
                        'INSERT INTO "dim_customer" VALUES (%s, %s, %s, %s);',
                        r,
                    )

                # Seed fact_transaction
                txn_sql = (
                    'SELECT "transaction_id", "customer_id", "amount", '
                    '"status", "transaction_date" FROM "fact_transaction"'
                )
                txn_rows = duck_conn.execute(txn_sql).fetchall()
                for r in txn_rows:
                    cur.execute(
                        'INSERT INTO "fact_transaction" VALUES (%s, %s, %s, %s, %s);',
                        r,
                    )

                # Seed fact_asset_snapshot
                asset_sql = (
                    'SELECT "customer_id", "total_asset", "snapshot_date" '
                    'FROM "fact_asset_snapshot"'
                )
                asset_rows = duck_conn.execute(asset_sql).fetchall()
                for r in asset_rows:
                    cur.execute(
                        'INSERT INTO "fact_asset_snapshot" VALUES (%s, %s, %s);',
                        r,
                    )
            pg_conn.commit()

    @pytest.mark.parametrize(
        "query_sql",
        [
            # 1. Single table count distinct
            (
                'SELECT COUNT(DISTINCT "customer_id") AS "cnt" '
                'FROM "dim_customer" WHERE "status" = \'active\''
            ),
            # 2. Time window sum amount
            (
                'SELECT SUM("amount") AS "total_amount" FROM "fact_transaction" '
                "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
                "AND \"transaction_date\" <= '2025-06-30'"
            ),
            # 3. Two-table join distinct count
            (
                'SELECT COUNT(DISTINCT "c"."customer_id") AS "vip_transactors" '
                'FROM "dim_customer" AS "c" '
                'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
                'WHERE "c"."customer_level" = \'VIP\' AND "t"."status" = \'success\''
            ),
            # 4. Group by dimension
            (
                'SELECT "region" AS "region", COUNT("customer_id") AS "cnt" '
                'FROM "dim_customer" GROUP BY "region"'
            ),
            # 5. Asset snapshot sum
            (
                'SELECT SUM("total_asset") AS "total_asset" FROM "fact_asset_snapshot" '
                "WHERE \"snapshot_date\" = '2025-06-30'"
            ),
        ],
    )
    def test_duckdb_and_postgres_semantic_equivalence(self, baseline, query_sql):
        policy = _policy()
        limits = SqlLimits(timeout_seconds=5)
        duck_gw = DuckDBExecutionGateway(baseline / "dataset.duckdb", policy, limits)
        pg_gw = PostgreSQLExecutionGateway(PG_URI, policy, limits, admitted=True)

        duck_receipt = duck_gw.execute(query_sql)
        pg_receipt = pg_gw.execute(query_sql)

        assert duck_receipt.result.truncated == pg_receipt.result.truncated
        # Compare columns count
        assert len(duck_receipt.result.columns) == len(pg_receipt.result.columns)
        # Compare numerical & row-level content with tolerance
        assert compare_results(duck_receipt.result, pg_receipt.result, tolerance=Decimal("0.01")), (
            f"Mismatch between DuckDB and PostgreSQL for query: {query_sql}"
        )
