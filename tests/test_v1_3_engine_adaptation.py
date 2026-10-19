"""v1.3 Cross-engine dialect transpilation, gateway abstraction, and perf tests."""

from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.dialects import TranspiledQuery
from customer360.contracts.execution import AccessPolicy, TableGrant
from customer360.contracts.perf import PhasePercentileSummary
from customer360.errors import QueryRejected
from customer360.evaluator.perf import _compute_phase_summary
from customer360.runtime.dialects import (
    get_dialect_capabilities,
    transpile_sql,
)
from customer360.runtime.gateway import (
    DuckDBExecutionGateway,
    PostgreSQLExecutionGateway,
)
from customer360.tasks.variant import tiny_eval_policy


def _mock_policy() -> AccessPolicy:
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
        ),
    )


def test_v1_3_dialect_capabilities_matrix() -> None:
    """Verify engine capability matrix declarations."""
    duck = get_dialect_capabilities("duckdb")
    assert duck.dialect == "duckdb"
    assert duck.supports_read_only_pragma is True
    assert duck.capability_only is False

    pg = get_dialect_capabilities("postgres")
    assert pg.dialect == "postgres"
    assert pg.decimal_type_name == "NUMERIC"
    assert pg.capability_only is True

    ansi = get_dialect_capabilities("ansi")
    assert ansi.dialect == "ansi"
    assert ansi.capability_only is True

    with pytest.raises(ValueError, match="unsupported dialect"):
        get_dialect_capabilities("sqlite")


def test_v1_3_transpile_interval_and_nulls_ordering() -> None:
    """Date intervals and NULLS ordering must be cross-engine stabilized."""
    duck_sql = (
        'SELECT "c"."region", COUNT("t"."transaction_id") AS "tx_cnt" '
        'FROM "dim_customer" AS "c" '
        'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
        'WHERE "t"."transaction_date" >= DATE \'2025-06-30\' - INTERVAL 89 DAY '
        'GROUP BY "c"."region" '
        'ORDER BY "tx_cnt" DESC'
    )
    res: TranspiledQuery = transpile_sql(
        duck_sql, source_dialect="duckdb", target_dialect="postgres"
    )
    assert res.ast_valid is True
    assert "interval_syntax_converted" in res.differences
    assert "nulls_ordering_stabilized" in res.differences
    assert "NULLS LAST" in res.transpiled_sql

    # Validate target AST can be parsed by sqlglot with postgres dialect
    pg_ast = sqlglot.parse_one(res.transpiled_sql, read="postgres")
    assert isinstance(pg_ast, exp.Select)
    assert len(list(pg_ast.find_all(exp.Join))) == 1


def test_v1_3_transpile_ddl_dml_and_injection_defense() -> None:
    """Transpiler must reject any non-read-only operation including ALTER and TRUNCATE."""
    # 1. Multi-statement injection
    with pytest.raises(ValueError, match="multi-statement queries are forbidden"):
        transpile_sql('SELECT 1; DROP TABLE "dim_customer"')

    # 2. DDL operations
    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('DROP TABLE "dim_customer"')

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('ALTER TABLE "dim_customer" DROP COLUMN "status"')

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('TRUNCATE TABLE "dim_customer"')

    # 3. DML operations
    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql("INSERT INTO \"dim_customer\" VALUES ('C999', 'VIP', 'East', 'active')")

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('UPDATE "dim_customer" SET "status" = \'inactive\'')

    # 4. Privilege and session control operations
    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('GRANT ALL ON "dim_customer" TO public')

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql('REVOKE ALL ON "dim_customer" FROM public')

    with pytest.raises(ValueError, match="only read-only queries can be transpiled"):
        transpile_sql("SET statement_timeout = 1000")

    # 5. Semicolon inside string literals must NOT be falsely flagged as multi-statement
    safe_semi_sql = 'SELECT \'val1;val2\' AS "tag" FROM "dim_customer"'
    res_semi = transpile_sql(safe_semi_sql, source_dialect="duckdb", target_dialect="postgres")
    assert res_semi.ast_valid is True
    assert "tag" in res_semi.transpiled_sql


def test_v1_3_gateway_fail_closed_and_pre_connection_guard(monkeypatch) -> None:
    """PostgreSQL gateway must fail closed when unadmitted and enforce SQL Guard."""
    policy = _mock_policy()

    # 1. Unadmitted (default) must raise ENGINE_UNAVAILABLE
    gw_unadmitted = PostgreSQLExecutionGateway(
        connection_uri="postgresql://user:pass@host/db", policy=policy
    )
    with pytest.raises(QueryRejected) as exc_info:
        gw_unadmitted.execute('SELECT COUNT("customer_id") FROM "dim_customer"')
    assert exc_info.value.code == "ENGINE_UNAVAILABLE"
    assert "not formally admitted" in exc_info.value.message

    # 2. Admitted with simulated driver enforces SQL Guard before any connection attempt
    class GuardShieldDriver:
        @staticmethod
        def connect(*args, **kwargs):
            raise AssertionError("Database connection should NEVER be initiated on guard rejection")

    import customer360.runtime.gateway as gw_mod

    monkeypatch.setattr(gw_mod, "_get_pg_driver", lambda: GuardShieldDriver)

    gw_admitted = PostgreSQLExecutionGateway(
        connection_uri="postgresql://user:pass@host/db",
        policy=policy,
        admitted=True,
    )

    # Harmful DROP TABLE blocked by SQL Guard
    with pytest.raises(QueryRejected) as exc_info:
        gw_admitted.execute('DROP TABLE "dim_customer"')
    assert exc_info.value.code == "UNSAFE_SQL"

    # Single-customer grouping blocked by SQL Guard
    bad_group = 'SELECT "customer_id", COUNT("status") FROM "dim_customer" GROUP BY "customer_id"'
    with pytest.raises(QueryRejected) as exc_info:
        gw_admitted.execute(bad_group)
    assert exc_info.value.code == "UNSAFE_SQL"


def test_v1_3_phase_breakdown_profiling(baseline: Path) -> None:
    """DuckDB execution gateway must produce real guard_ms and exec_ms in QueryReceipt."""
    policy = tiny_eval_policy()
    gateway = DuckDBExecutionGateway(baseline / "dataset.duckdb", policy)

    sql = (
        'SELECT COUNT(DISTINCT "customer_id") AS "cnt" '
        'FROM "dim_customer" WHERE "status" = \'active\''
    )
    receipt = gateway.execute(sql)

    assert receipt.elapsed_ms > 0
    assert receipt.guard_ms >= 0
    assert receipt.exec_ms >= 0
    assert receipt.elapsed_ms >= receipt.guard_ms

    # Check phase summary computation
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    summary: PhasePercentileSummary = _compute_phase_summary(samples)
    assert summary.p50_ms == 30.0
    assert summary.p90_ms == 46.0
    assert summary.p95_ms == 48.0
    assert summary.p99_ms == 49.6


def test_v1_3_cli_transpile_sql_command() -> None:
    """CLI c360 transpile-sql must successfully transpile valid SQL and fail on invalid SQL."""
    import json

    runner = CliRunner()

    # 1. Valid transpilation
    res = runner.invoke(
        app,
        [
            "transpile-sql",
            "--sql",
            'SELECT COUNT("customer_id") FROM "dim_customer"',
            "--source",
            "duckdb",
            "--target",
            "postgres",
        ],
    )
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["ast_valid"] is True
    assert '"dim_customer"' in payload["transpiled_sql"]
    assert "transpiled_from_duckdb_to_postgres" in payload["differences"]

    # 2. Invalid SQL syntax
    res_bad = runner.invoke(
        app,
        [
            "transpile-sql",
            "--sql",
            "SELECT FROM WHERE",
        ],
    )
    assert res_bad.exit_code == 2
    assert "SQL transpilation failed" in res_bad.output
