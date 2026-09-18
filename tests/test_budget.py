"""Stage G resource budgets: Tiny 10k default stays; mismatch and over-cap fail closed."""

from pathlib import Path

import duckdb
import pytest

from customer360.application import fixture_policy
from customer360.contracts.budget import (
    LARGE_MAX_INPUT_ROWS,
    STANDARD_MAX_INPUT_ROWS,
    TINY_MAX_INPUT_ROWS,
    budget_for_scale,
    limits_for_budget,
    limits_for_manifest,
    require_budget_matches_manifest,
)
from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import (
    ANALYST_GRANTS,
    customer_ids_from_database,
    eval_policy_for_dataset,
    tiny_eval_policy,
)
from customer360.synth.ids import numbered_id
from customer360.synth.schema import render_ddl, render_literal
from customer360.tasks.variant import tiny_eval_policy as variant_tiny_policy


def test_tiny_budget_matches_sql_limits_defaults():
    tiny = limits_for_budget("tiny")
    default = SqlLimits()
    assert tiny.max_input_rows == TINY_MAX_INPUT_ROWS == 10_000
    assert tiny.model_dump() == default.model_dump()
    assert tiny.timeout_seconds == 15
    assert tiny.memory_mb == 128
    assert tiny.max_rows == 100


def test_standard_and_large_budgets_are_finite_and_higher():
    standard = limits_for_budget("standard")
    large = limits_for_budget("large")
    assert standard.max_input_rows == STANDARD_MAX_INPUT_ROWS == 400_000
    assert large.max_input_rows == LARGE_MAX_INPUT_ROWS == 4_000_000
    assert standard.timeout_seconds == 60
    assert large.timeout_seconds == 180
    assert standard.memory_mb == 512
    assert large.memory_mb == 1024
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SqlLimits(max_input_rows=0)
    with pytest.raises(ValidationError):
        SqlLimits(timeout_seconds=0)


def test_budget_must_match_dataset_scale(baseline):
    from customer360.tasks.trusted_data import load_verified_dataset

    _database, manifest = load_verified_dataset(baseline)
    assert budget_for_scale(manifest.scale) == "tiny"
    require_budget_matches_manifest("tiny", manifest)
    limits_for_manifest(manifest)
    with pytest.raises(ValueError, match="does not match dataset scale"):
        require_budget_matches_manifest("standard", manifest)
    with pytest.raises(ValueError, match="does not match dataset scale"):
        require_budget_matches_manifest("large", manifest)


def test_tiny_eval_policy_stays_c001_c100():
    policy = tiny_eval_policy()
    assert policy.customer_ids[0] == "C001"
    assert policy.customer_ids[-1] == "C100"
    assert len(policy.customer_ids) == 100
    assert policy.grants == ANALYST_GRANTS
    assert variant_tiny_policy().model_dump() == policy.model_dump()


def test_eval_policy_reads_verified_customer_ids(baseline):
    from customer360.tasks.trusted_data import load_verified_dataset

    database, manifest = load_verified_dataset(baseline)
    ids = customer_ids_from_database(database)
    policy = eval_policy_for_dataset(manifest, ids)
    assert policy.customer_ids == tiny_eval_policy().customer_ids
    assert policy.role == "tiny_eval_analyst"
    with pytest.raises(ValueError, match="row count"):
        eval_policy_for_dataset(manifest, ids[:-1])


def test_standard_customer_ids_use_five_digits():
    assert numbered_id("C", 1, 10_000) == "C00001"
    assert numbered_id("C", 10_000, 10_000) == "C10000"
    assert numbered_id("C", 1, 100) == "C001"


def test_standard_copy_insert_matches_tiny_values_path(database):
    tiny = ExecutionGateway(database, fixture_policy(), SqlLimits())
    standard = ExecutionGateway(
        database, fixture_policy(), SqlLimits(max_input_rows=20_000, timeout_seconds=15)
    )
    count_sql = "SELECT COUNT(*) AS n FROM dim_customer"
    assert tiny.execute(count_sql).result.rows == standard.execute(count_sql).result.rows
    amount_sql = (
        "SELECT SUM(amount) AS transaction_amount FROM fact_transaction "
        "WHERE status = 'success' AND transaction_date >= '2025-04-02' "
        "AND transaction_date <= '2025-06-30'"
    )
    assert tiny.execute(amount_sql).result.rows == standard.execute(amount_sql).result.rows
    null_sql = "SELECT COUNT(*) AS n FROM dim_customer WHERE occupation IS NULL"
    assert tiny.execute(null_sql).result.rows == standard.execute(null_sql).result.rows


def test_input_limit_is_inclusive_of_max_input_rows(database):
    five = fixture_policy(tuple(f"C00{i}" for i in range(1, 6)))
    gateway = ExecutionGateway(database, five, SqlLimits(max_input_rows=5))
    result = gateway.execute("SELECT COUNT(*) AS n FROM dim_customer").result
    assert result.rows == ((5,),)
    six = fixture_policy()
    limited = ExecutionGateway(database, six, SqlLimits(max_input_rows=5))
    with pytest.raises(ExecutionFailure) as caught:
        limited.execute("SELECT COUNT(*) AS n FROM dim_customer")
    assert caught.value.code == "INPUT_LIMIT"


def test_tiny_default_cap_trips_at_10001_rows(tmp_path):
    path = tmp_path / "oversize.duckdb"
    _write_customers(path, 10_001)
    ids = tuple(f"X{index:05d}" for index in range(1, 10_002))
    policy = AccessPolicy(
        role="oversize_analyst",
        customer_ids=ids,
        grants=(
            TableGrant(
                table="dim_customer",
                columns=("customer_id", "customer_level", "status"),
            ),
        ),
    )
    gateway = ExecutionGateway(
        path, policy, SqlLimits(timeout_seconds=60, max_input_rows=TINY_MAX_INPUT_ROWS)
    )
    with pytest.raises(ExecutionFailure) as caught:
        gateway.execute("SELECT COUNT(*) AS n FROM dim_customer")
    assert caught.value.code == "INPUT_LIMIT"


def test_scope_still_applied_before_aggregation(database):
    gateway = ExecutionGateway(database, fixture_policy(("C001",)))
    result = gateway.execute("SELECT COUNT(*) AS n FROM dim_customer").result
    assert result.rows == ((1,),)


def test_empty_scope_is_not_all_customers(database):
    gateway = ExecutionGateway(database, fixture_policy(()))
    with pytest.raises(QueryRejected) as caught:
        gateway.execute("SELECT COUNT(*) AS n FROM dim_customer")
    assert caught.value.code == "AGGREGATION_TOO_SMALL"


def test_restricted_columns_still_cannot_be_granted(database):
    policy = fixture_policy().model_copy(
        update={
            "grants": (TableGrant(table="dim_customer", columns=("customer_id", "customer_name")),)
        }
    )
    with pytest.raises(QueryRejected):
        ExecutionGateway(database, policy)


def _write_customers(path: Path, count: int) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(render_ddl())
        for start in range(0, count, 250):
            chunk = []
            for index in range(start + 1, min(start + 250, count) + 1):
                customer_id = f"X{index:05d}"
                chunk.append(
                    "("
                    + ", ".join(
                        [
                            render_literal(customer_id),
                            render_literal("n"),
                            render_literal("M"),
                            "DATE '1990-01-01'",
                            render_literal("normal"),
                            render_literal("R2"),
                            render_literal("east"),
                            render_literal("city"),
                            "NULL",
                            "DATE '2024-07-01'",
                            render_literal("active"),
                        ]
                    )
                    + ")"
                )
            connection.execute(
                "INSERT INTO dim_customer ("
                "customer_id, customer_name, gender, birth_date, customer_level, "
                "risk_level, region, city, occupation, registration_date, status"
                ") VALUES " + ", ".join(chunk)
            )
    finally:
        connection.close()
