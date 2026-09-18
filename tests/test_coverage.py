"""T3: Tiny boundary probes, independent Python oracle and coverage report."""

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from pydantic import TypeAdapter, ValidationError
from typer.testing import CliRunner

from customer360.agent.submission import SqlSubmissionAgent
from customer360.cli import app
from customer360.contracts.coverage import HumanCaseCatalog
from customer360.contracts.generation import GenerationConfig
from customer360.contracts.oracle import PrivateCase
from customer360.contracts.public import AgentRequest, QueryResult
from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.errors import C360Error
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway
from customer360.synth.generator import generate_dataset
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.coverage import load_human_cases, write_coverage_report
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices

ROOT = Path(__file__).parents[1]
ANCHOR = date(2025, 6, 30)
runner = CliRunner()


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-t3") / "data"
    manifest, _quality = generate_dataset(GenerationConfig(seed=42), output)
    return output, manifest


def _request(case) -> AgentRequest:
    return AgentRequest(
        case_id=case.case_id,
        question=case.question,
        anchor_date=ANCHOR,
        metadata_version="0.3",
    )


def test_independent_oracle_has_no_compiler_or_engine():
    path = ROOT / "src/customer360/tasks/independent.py"
    denied = (
        "customer360.tasks.compiler",
        "customer360.evaluator",
        "customer360.agent",
        "customer360.runtime",
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


def test_human_case_catalog_is_formal_twenty_case_dev_package():
    catalog = load_human_cases()
    assert catalog.catalog_version == "0.3"
    assert len(catalog.cases) == 20
    assert [item.case_id for item in catalog.cases] == [f"C360_{i:04d}" for i in range(1, 21)]
    assert TypeAdapter(HumanCaseCatalog).validate_json(catalog.model_dump_json()) == catalog
    statuses = {item.material_status for item in catalog.cases}
    assert statuses == {"compilable_answer", "unscored_oracle"}
    assert sum(item.material_status == "compilable_answer" for item in catalog.cases) == 18
    assert sum(item.material_status == "unsupported_capability" for item in catalog.cases) == 0
    assert sum(item.material_status == "unscored_oracle" for item in catalog.cases) == 2
    assert all(item.task_version == "human-0.1" for item in catalog.cases)
    assert all(item.split == "dev" for item in catalog.cases)
    assert all(3 <= len(item.rewrites) <= 5 for item in catalog.cases)
    assert all(item.question not in item.rewrites for item in catalog.cases)


def test_unknown_dsl_fields_still_fail_closed():
    with pytest.raises(ValidationError):
        SemanticSpec.model_validate(
            {
                "metric": "snapshot_total_asset",
                "time_window": {"type": "latest_snapshot", "snapshot_date": "2025-06-30"},
            }
        )
    with pytest.raises(ValidationError):
        SemanticSpec.model_validate(
            {"metric": "distinct_customer_count", "join_path": ["dim_customer", "fact_transaction"]}
        )
    spec = SemanticSpec.model_validate({"metric": "active_customer_count", "group_by": ["region"]})
    assert spec.group_by == ("region",)


def test_independent_matches_compiler_on_public_fixture(repository, database):
    slices = load_table_slices(database, repository.catalog)
    rolling = RollingWindow(days=90, anchor_date=ANCHOR)
    specs = [
        SemanticSpec(
            metric="distinct_customer_count",
            filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        ),
        SemanticSpec(metric="active_customer_count"),
        SemanticSpec(metric="successful_transaction_count", time_window=rolling),
        SemanticSpec(metric="successful_transaction_amount", time_window=rolling),
        SemanticSpec(
            metric="distinct_customer_count",
            filters=(Filter(field="occupation", operator="is_null"),),
        ),
    ]
    with duckdb.connect(str(database), read_only=True) as connection:
        for spec in specs:
            independent = compute_independent(spec, repository, slices)
            compiled = compile_semantic(spec, repository)
            row = connection.execute(compiled.sql).fetchone()
            expected = independent.rows[0][0]
            if independent.columns[0].kind == "decimal":
                assert Decimal(str(row[0])) == Decimal(expected)
            else:
                assert row[0] == expected
    null_occupation = compute_independent(specs[-1], repository, slices)
    assert null_occupation.rows[0][0] == 2


def test_empty_sum_is_sql_null_not_zero(repository, database):
    slices = load_table_slices(database, repository.catalog)
    spec = SemanticSpec(
        metric="successful_transaction_amount",
        filters=(Filter(field="transaction_date", operator="eq", values=("2020-01-01",)),),
        time_window=RollingWindow(days=90, anchor_date=ANCHOR),
    )
    independent = compute_independent(spec, repository, slices)
    compiled = compile_semantic(spec, repository)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(compiled.sql).fetchone() == (None,)
    assert independent.rows[0][0] is None
    assert independent.columns[0].kind == "decimal"


def test_independent_rejects_window_mismatch(repository, database):
    slices = load_table_slices(database, repository.catalog)
    with pytest.raises(C360Error) as caught:
        compute_independent(
            SemanticSpec(
                metric="snapshot_total_asset",
                time_window=RollingWindow(days=90, anchor_date=ANCHOR),
            ),
            repository,
            slices,
        )
    assert caught.value.code == "TIME_RANGE_ERROR"


def test_clarification_and_refuse_are_not_falsely_passed(database, policy, repository):
    catalog = load_human_cases()
    gateway = ExecutionGateway(database, policy)
    for case_id in ("C360_0019", "C360_0020"):
        item = next(case for case in catalog.cases if case.case_id == case_id)
        record = evaluate_case(
            PrivateCase(request=_request(item), oracle=item.oracle()),
            SqlSubmissionAgent("SELECT 1 AS n FROM dim_customer"),
            gateway,
            repository,
        )
        assert record.outcome == "fail"
        assert record.reason_code in {
            "CLARIFICATION_FAILURE",
            "REFUSAL_FAILURE",
            "UNSUPPORTED_QUERY",
        }


def test_tiny_coverage_cross_checks_twenty_cases(tiny, repository):
    output, manifest = tiny
    report = write_coverage_report(output, output.parent / "coverage")
    assert report["coverage_passed"] is True
    assert report["m2_complete"] is False
    assert report["case_count"] == 20
    assert report["compilable_answers"] == 18
    assert report["independent_oracle_matches"] == 18
    assert report["unsupported_capabilities"] == 0
    assert report["unscored_oracles"] == 2
    assert report["probes_passed"] is True
    assert report["dataset_manifest_hash"]
    by_id = {item["case_id"]: item for item in report["cases"]}
    assert by_id["C360_0011"]["independent_result"]["rows"][0][0] >= 1
    assert by_id["C360_0012"]["independent_result"]["rows"][0][0] == 0
    assert by_id["C360_0013"]["independent_result"]["rows"][0][0] == 3
    assert "2025-06-30" in by_id["C360_0009"]["compiled_sql"]
    assert "2024-12-31" in by_id["C360_0015"]["compiled_sql"]
    assert ">=" not in by_id["C360_0015"]["compiled_sql"]
    assert (
        by_id["C360_0010"]["independent_result"]["rows"][0][0]
        != by_id["C360_0015"]["independent_result"]["rows"][0][0]
    )
    assert by_id["C360_0014"]["independent_result"]["rows"][0][0] >= 1
    assert by_id["C360_0016"]["compiled_match"] is True
    assert by_id["C360_0016"]["task_version"] == "human-0.1"
    assert by_id["C360_0016"]["split"] == "dev"
    assert len(by_id["C360_0016"]["rewrites"]) == 3
    assert "JOIN" in (by_id["C360_0016"]["compiled_sql"] or "").upper()
    assert "JOIN" not in (by_id["C360_0003"]["compiled_sql"] or "").upper()
    assert by_id["C360_0017"]["compiled_match"] is True
    assert "MAX(" in (by_id["C360_0017"]["compiled_sql"] or "").upper()
    assert "ROW_NUMBER" not in (by_id["C360_0017"]["compiled_sql"] or "").upper()
    assert by_id["C360_0018"]["compiled_match"] is True
    assert "GROUP BY" in (by_id["C360_0018"]["compiled_sql"] or "").upper()
    markdown = (output.parent / "coverage" / "coverage.md").read_text(encoding="utf-8")
    assert "m2_complete: `False`" in markdown
    slices = load_table_slices(output / "dataset.duckdb", repository.catalog)
    for item in load_human_cases().cases:
        if item.material_status != "compilable_answer":
            continue
        independent = compute_independent(item.semantic_spec(), repository, slices)
        dumped = QueryResult.model_validate(by_id[item.case_id]["independent_result"])
        assert compare_results(independent, dumped)


def test_coverage_cli_and_fail_closed_inputs(tiny, tmp_path, database):
    dataset, _manifest = tiny
    output = tmp_path / "cli-coverage"
    result = runner.invoke(
        app, ["coverage-report", "--dataset", str(dataset), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["coverage_passed"] is True
    assert payload["m2_complete"] is False
    second = runner.invoke(
        app, ["coverage-report", "--dataset", str(dataset), "--output", str(output)]
    )
    assert second.exit_code == 2
    fixture_dir = tmp_path / "fixture-dir"
    fixture_dir.mkdir()
    (fixture_dir / "dataset.duckdb").write_bytes(database.read_bytes())
    (fixture_dir / "manifest.json").write_text(
        json.dumps({"artifact_kind": "public_fixture_not_tiny"}), encoding="utf-8"
    )
    refused = runner.invoke(
        app,
        ["coverage-report", "--dataset", str(fixture_dir), "--output", str(tmp_path / "from-fix")],
    )
    assert refused.exit_code == 2
    assert "dataset" in refused.output.lower()
