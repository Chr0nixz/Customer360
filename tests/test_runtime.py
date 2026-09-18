import multiprocessing
from datetime import date

import pytest

from customer360.application import fixture_policy
from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.contracts.semantic import Filter, JoinSpec, RollingWindow, SemanticSpec
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.tasks.compiler import compile_semantic

pytestmark = pytest.mark.integration


def test_scope_is_applied_before_aggregation(database):
    gateway = ExecutionGateway(database, fixture_policy(("C001",)))
    result = gateway.execute("SELECT COUNT(*) AS n FROM dim_customer").result
    assert result.rows == ((1,),)


def test_customer_transaction_join_executes_in_scoped_worker(database, repository):
    spec = SemanticSpec(
        metric="distinct_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        join=JoinSpec(
            path="customer_transactions",
            filters=(Filter(field="status", operator="eq", values=("success",)),),
            time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
        ),
    )
    query = compile_semantic(spec, repository)
    result = ExecutionGateway(database, fixture_policy()).execute(query.sql).result
    assert result.rows == ((2,),)


def test_empty_scope_does_not_mean_all(database):
    gateway = ExecutionGateway(database, fixture_policy(()))
    with pytest.raises(QueryRejected) as caught:
        gateway.execute("SELECT COUNT(*) AS n FROM dim_customer")
    assert caught.value.code == "AGGREGATION_TOO_SMALL"


def test_minimum_aggregation_size(database):
    policy = fixture_policy(("C001",)).model_copy(update={"min_group_size": 2})
    gateway = ExecutionGateway(database, policy)
    with pytest.raises(QueryRejected):
        gateway.execute("SELECT COUNT(*) AS n FROM dim_customer")


def test_sensitive_grant_is_rejected(database):
    policy = fixture_policy().model_copy(
        update={
            "grants": (TableGrant(table="dim_customer", columns=("customer_id", "customer_name")),)
        }
    )
    with pytest.raises(QueryRejected):
        ExecutionGateway(database, policy)


def test_timeout_kills_worker(database):
    before = {p.pid for p in multiprocessing.active_children()}
    gateway = ExecutionGateway(database, fixture_policy(), SqlLimits(timeout_seconds=0.001))
    with pytest.raises(ExecutionFailure) as caught:
        gateway.execute("SELECT COUNT(*) AS n FROM dim_customer")
    assert caught.value.code == "TIMEOUT"
    assert {p.pid for p in multiprocessing.active_children()} <= before


def test_metadata_tools_only_expose_granted_columns(database, policy, repository):
    session = ToolSession(ExecutionGateway(database, policy), repository)
    columns = session.get_table_schema("dim_customer")
    assert "customer_name" not in {c["column_name"] for c in columns}
    with pytest.raises(QueryRejected):
        session.get_table_schema("dim_product")
    assert {item["metric_name"] for item in session.search_metrics("")} == {
        "distinct_customer_count",
        "active_customer_count",
        "closed_customer_count",
        "dormant_customer_count",
        "high_risk_customer_count",
        "successful_transaction_count",
        "successful_transaction_amount",
        "failed_transaction_count",
        "cancelled_transaction_count",
        "cancelled_transaction_amount",
        "failed_transaction_amount",
        "successful_buy_transaction_count",
        "successful_app_transaction_count",
        "snapshot_total_asset",
        "snapshot_net_asset",
        "latest_total_asset",
        "snapshot_cash_asset",
        "snapshot_investment_asset",
        "snapshot_liability",
    }
    assert {table["table_name"] for table in session.search_tables("")} == {
        "dim_customer",
        "fact_transaction",
        "fact_asset_snapshot",
    }
    assert "columns" not in session.search_tables("dim_customer")[0]
    assert session.search_columns("客户名称") == ()
    assert session.search_columns("customer_name") == ()
    assert "customer_name" not in {
        entry["column_name"] for entry in session.get_business_glossary("客户名称")
    }
    assert {hit["column_name"] for hit in session.search_columns("customer_level")} == {
        "customer_level"
    }
    assert session.get_metric_definition("distinct_customer_count")["metric_name"] == (
        "distinct_customer_count"
    )


def test_metadata_tools_hide_ungranted_metrics_and_tables(database, repository):
    policy = AccessPolicy(
        role="limited_analyst",
        customer_ids=("C001",),
        grants=(
            TableGrant(
                table="dim_customer",
                columns=("customer_id", "customer_level", "status"),
            ),
        ),
    )
    session = ToolSession(ExecutionGateway(database, policy), repository)
    assert {item["metric_name"] for item in session.search_metrics("")} == {
        "distinct_customer_count",
        "active_customer_count",
        "closed_customer_count",
        "dormant_customer_count",
    }
    assert session.search_tables("")[0]["table_name"] == "dim_customer"
    assert session.search_columns("amount") == ()
    with pytest.raises(QueryRejected) as denied:
        session.get_metric_definition("successful_transaction_count")
    assert denied.value.code == "PERMISSION_DENIED"
    with pytest.raises(QueryRejected) as ungranted:
        session.get_metric_definition("latest_total_asset")
    assert ungranted.value.code == "PERMISSION_DENIED"
    with pytest.raises(QueryRejected) as missing:
        session.get_metric_definition("windowed_asset")
    assert missing.value.code == "UNKNOWN_METRIC"
    glossary = session.get_business_glossary("")
    assert {entry["table_name"] for entry in glossary if entry["kind"] == "table"} == {
        "dim_customer"
    }
    assert {entry["metric_name"] for entry in glossary if entry["kind"] == "metric"} == {
        "distinct_customer_count",
        "active_customer_count",
        "closed_customer_count",
        "dormant_customer_count",
    }


def test_join_path_requires_both_authorized_tables(database, repository):
    session = ToolSession(ExecutionGateway(database, fixture_policy()), repository)
    assert {item["path_name"] for item in session.get_join_paths("")} == {
        "customer_transactions",
        "customer_asset_snapshots",
        "latest_customer_asset_snapshot",
    }
    assert [
        item["path_name"]
        for item in session.get_join_paths("")
        if item["compile_status"] == "executable"
    ] == ["customer_transactions"]
    base = fixture_policy()
    restricted = base.model_copy(update={"grants": (base.grants[0],)})
    limited = ToolSession(ExecutionGateway(database, restricted), repository)
    assert limited.get_join_paths("") == ()


def test_rejection_is_auditable_even_when_caught(database, policy, repository):
    session = ToolSession(ExecutionGateway(database, policy), repository)
    with pytest.raises(QueryRejected):
        session.execute_sql("DROP TABLE dim_customer")
    assert session.rejections == ["UNSAFE_SQL"]
