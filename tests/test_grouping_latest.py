"""Grouping and latest-snapshot semantics: compiler, oracle, Guard, Agent."""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from customer360.agent.template import TemplateAgent
from customer360.contracts.execution import SqlLimits
from customer360.contracts.oracle import PrivateCase
from customer360.contracts.public import AgentRequest, QueryResult
from customer360.contracts.semantic import (
    Filter,
    LatestSnapshot,
    PointInTime,
    SemanticSpec,
)
from customer360.errors import QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway
from customer360.safety.sql_guard import validate_sql
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import TableSlice, compute_independent
from customer360.tasks.variant import tiny_eval_policy

ROOT = Path(__file__).parents[1]
ANCHOR = date(2025, 6, 30)


def _row(day: date, customer_id: str, amount: str) -> tuple[object, ...]:
    value = Decimal(amount)
    return (day, customer_id, value, Decimal("0"), Decimal("0"), Decimal("0"), value)


def _uneven_assets() -> dict[str, TableSlice]:
    return _asset_slice(
        (
            _row(date(2025, 5, 31), "C001", "100.00"),
            _row(date(2025, 6, 30), "C001", "200.00"),
            _row(date(2025, 5, 31), "C002", "50.00"),
            _row(date(2025, 6, 30), "C003", "10.00"),
        )
    )


def _asset_slice(rows: tuple[tuple[object, ...], ...]) -> dict[str, TableSlice]:
    return {
        "fact_asset_snapshot": TableSlice(
            table_name="fact_asset_snapshot",
            columns=(
                "snapshot_date",
                "customer_id",
                "total_asset",
                "cash_asset",
                "investment_asset",
                "liability",
                "net_asset",
            ),
            kinds=("date", "string", "decimal", "decimal", "decimal", "decimal", "decimal"),
            rows=rows,
        )
    }


def test_latest_snapshot_mismatches_point_in_time_on_uneven_slice(repository):
    slices = _uneven_assets()
    latest = compute_independent(
        SemanticSpec(
            metric="latest_total_asset",
            time_window=LatestSnapshot(anchor_date=ANCHOR),
        ),
        repository,
        slices,
    )
    pit = compute_independent(
        SemanticSpec(
            metric="snapshot_total_asset",
            time_window=PointInTime(snapshot_date=ANCHOR),
        ),
        repository,
        slices,
    )
    assert latest.rows == (("260.00",),)
    assert pit.rows == (("210.00",),)
    assert not compare_results(latest, pit)


def test_global_max_date_sql_is_not_latest_snapshot(repository, policy):
    slices = _uneven_assets()
    gold = compute_independent(
        SemanticSpec(
            metric="latest_total_asset",
            time_window=LatestSnapshot(anchor_date=ANCHOR),
        ),
        repository,
        slices,
    )
    wrong = QueryResult(
        columns=gold.columns,
        rows=(("210.00",),),
    )
    assert not compare_results(gold, wrong)
    with pytest.raises(QueryRejected):
        validate_sql(
            "SELECT SUM(total_asset) AS latest_total_asset FROM fact_asset_snapshot "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM fact_asset_snapshot)",
            repository.catalog,
            policy,
            SqlLimits(),
        )


def test_grouping_omits_empty_regions_and_keeps_distinct(repository):
    customers = TableSlice(
        table_name="dim_customer",
        columns=("customer_id", "customer_level", "region", "status"),
        kinds=("string", "string", "string", "string"),
        rows=(
            ("C001", "VIP", "华东", "active"),
            ("C002", "VIP", "华东", "active"),
            ("C003", "standard", "华北", "active"),
            ("C004", "standard", "华北", "dormant"),
            ("C005", "VIP", "华南", "closed"),
        ),
    )
    result = compute_independent(
        SemanticSpec(metric="active_customer_count", group_by=("region",)),
        repository,
        {"dim_customer": customers},
    )
    observed = {row[0]: row[1] for row in result.rows}
    assert observed == {"华东": 2, "华北": 1}
    assert "华南" not in observed
    wrong = compute_independent(
        SemanticSpec(
            metric="active_customer_count",
            group_by=("region",),
            filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        ),
        repository,
        {"dim_customer": customers},
    )
    assert {row[0]: row[1] for row in wrong.rows} != observed


def test_compiled_group_and_latest_pass_guard(repository, policy, database):
    grouped = compile_semantic(
        SemanticSpec(metric="active_customer_count", group_by=("region",)),
        repository,
    )
    latest = compile_semantic(
        SemanticSpec(
            metric="latest_total_asset",
            time_window=LatestSnapshot(anchor_date=ANCHOR),
        ),
        repository,
    )
    assert "GROUP BY" in grouped.sql
    assert "ROW_NUMBER" not in latest.sql.upper()
    assert validate_sql(grouped.sql, repository.catalog, policy, SqlLimits()).output_kinds == (
        "string",
        "integer",
    )
    assert validate_sql(latest.sql, repository.catalog, policy, SqlLimits()).output_kinds == (
        "decimal",
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        grouped_rows = connection.execute(grouped.sql).fetchall()
        assert grouped_rows
        assert all(count >= 1 for _region, count in grouped_rows)


def test_template_agent_has_no_gold_imports():
    path = ROOT / "src/customer360/agent/template.py"
    denied = (
        "customer360.tasks.compiler",
        "customer360.tasks.independent",
        "customer360.tasks.catalog",
        "customer360.tasks.gold",
        "data.trusted",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(module == item or module.startswith(f"{item}.") for item in denied)


def test_template_agent_answer_clarify_refuse(baseline, repository):
    catalog = load_human_cases()
    by_id = {item.case_id: item for item in catalog.cases}
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = TemplateAgent()

    def run(case_id: str):
        item = by_id[case_id]
        return evaluate_case(
            PrivateCase(
                request=AgentRequest(
                    case_id=item.case_id,
                    question=item.question,
                    anchor_date=ANCHOR,
                    metadata_version=repository.metrics.metrics_version,
                ),
                oracle=item.oracle(),
            ),
            agent,
            gateway,
            repository,
        )

    answered = run("C360_0018")
    assert answered.outcome == "pass"
    latest = run("C360_0017")
    assert latest.outcome == "pass"
    clarified = run("C360_0019")
    assert clarified.outcome == "pass"
    assert clarified.reason_code == "CLARIFICATION_OK"
    refused = run("C360_0020")
    assert refused.outcome == "pass"
    assert refused.reason_code == "REFUSAL_OK"
