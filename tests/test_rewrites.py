"""M2-04: structured rewrite checks for date, metric, filter and Join slots."""

import ast
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.rewrites import RewriteReport
from customer360.tasks.coverage import load_human_cases
from customer360.tasks.rewrites import check_rewrite, validate_catalog_rewrites

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_rewrite_module_has_no_compiler_or_engine():
    path = ROOT / "src/customer360/tasks/rewrites.py"
    denied = (
        "customer360.tasks.compiler",
        "customer360.evaluator",
        "customer360.agent",
        "customer360.runtime",
        "customer360.synth",
        "duckdb",
        "sqlglot",
        "subprocess",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(module == item or module.startswith(f"{item}.") for item in denied)
        if isinstance(node, ast.Import):
            assert all(
                not any(alias.name == item or alias.name.startswith(f"{item}.") for item in denied)
                for alias in node.names
            )


def test_catalog_rewrites_match_canonical_slots():
    catalog = load_human_cases(check_rewrites=False)
    report = validate_catalog_rewrites(catalog)
    assert TypeAdapter(RewriteReport).validate_json(report.model_dump_json()) == report
    assert report.passed is True
    assert report.report_kind == "rewrite_semantic_consistency"
    assert report.catalog_version == "0.3"
    assert report.case_count == 20
    assert report.rewrite_count == 60
    assert report.issue_count == 0
    assert all(item.passed and item.rewrite_count == 3 for item in report.cases)


def test_packaged_catalog_loads_only_after_rewrite_gate():
    catalog = load_human_cases()
    assert catalog.catalog_version == "0.3"
    assert all(len(item.rewrites) == 3 for item in catalog.cases)


def test_load_human_cases_fail_closes_when_rewrites_drift(monkeypatch):
    catalog = load_human_cases(check_rewrites=False)
    payload = validate_catalog_rewrites(catalog).model_dump(mode="json")
    payload["passed"] = False
    payload["issue_count"] = 1
    monkeypatch.setattr(
        "customer360.tasks.catalog.validate_catalog_rewrites",
        lambda _catalog: RewriteReport.model_validate(payload),
    )
    with pytest.raises(ValueError, match="rewrite semantic consistency failed"):
        load_human_cases()


@pytest.mark.parametrize(
    ("case_id", "rewrite", "code"),
    [
        ("C360_0003", "截至2025年6月30日最近三个月成功交易有几笔？", "TIME_RANGE_ERROR"),
        ("C360_0003", "截至2025年6月30日近30天成功交易有几笔？", "TIME_RANGE_ERROR"),
        ("C360_0003", "截至2025年6月30日近90天成功交易金额是多少？", "METRIC_ERROR"),
        ("C360_0004", "截至2025年6月30日近90天成功交易有几笔？", "METRIC_ERROR"),
        ("C360_0005", "截至2025年6月30日近90天成功交易有多少笔？", "METRIC_ERROR"),
        ("C360_0001", "现有客户一共有多少人？", "FILTER_ERROR"),
        ("C360_0001", "统计非VIP客户数。", "FILTER_ERROR"),
        ("C360_0003", "截至2025年6月30日近90天不成功交易有几笔？", "METRIC_ERROR"),
        ("C360_0001", "华东的VIP客户一共有多少人？", "FILTER_ERROR"),
        ("C360_0001", "近90天有成功交易的VIP客户一共有多少人？", "JOIN_ERROR"),
        ("C360_0014", "VIP客户一共有多少？", "FILTER_ERROR"),
        ("C360_0013", "职业为工程师的客户有多少？", "FILTER_ERROR"),
        ("C360_0009", "2024年12月31日估值日的总资产是多少？", "TIME_RANGE_ERROR"),
        ("C360_0009", "2025年6月30日估值日的净资产是多少？", "METRIC_ERROR"),
        ("C360_0009", "统计截至2025年6月30日近90天总资产合计。", "TIME_RANGE_ERROR"),
        ("C360_0015", "2025年6月30日估值日净资产总额是多少？", "TIME_RANGE_ERROR"),
        ("C360_0016", "近90天VIP客户有多少？", "JOIN_ERROR"),
        ("C360_0016", "近90天成功交易有几笔？", "JOIN_ERROR"),
        ("C360_0018", "请汇总活跃客户数量。", "AGGREGATION_ERROR"),
        ("C360_0019", "截至2025年6月30日近90天交易多不多？", "CLARIFICATION_FAILURE"),
        ("C360_0020", "统计客户姓名数量。", "SCHEMA_ERROR"),
        ("C360_0017", "统计2025年6月30日估值日的总资产合计。", "TIME_RANGE_ERROR"),
    ],
)
def test_rewrite_negatives_keep_slot_codes(case_id, rewrite, code):
    catalog = load_human_cases(check_rewrites=False)
    case = next(item for item in catalog.cases if item.case_id == case_id)
    issues = check_rewrite(case, rewrite)
    assert issues, f"{case_id} accepted drifted rewrite: {rewrite}"
    assert any(item.code == code for item in issues), (code, issues)


def test_canonical_questions_pass_the_same_checker():
    catalog = load_human_cases(check_rewrites=False)
    for case in catalog.cases:
        assert not check_rewrite(case, case.question), case.case_id


def test_check_rewrites_cli_passes_catalog():
    result = runner.invoke(app, ["check-rewrites"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["issue_count"] == 0
    assert payload["rewrite_count"] == 60
    assert payload["report_kind"] == "rewrite_semantic_consistency"
    assert "m2_complete" not in payload
