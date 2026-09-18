"""M4-02 复盘加固: mode-mix and seed-swap fail closed."""

import shutil
from datetime import date

import duckdb
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.public import Column, Success
from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.contracts.variant import REPORT_KIND_FOR_MODE, VariantReplayReport
from customer360.evaluator.compare import compare_results
from customer360.tasks.compiler import CompiledQuery, compile_semantic
from customer360.tasks.coverage import load_human_cases
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import normalize_sql_result
from customer360.tasks.variant import build_variant_replay

ANCHOR = date(2025, 6, 30)
runner = CliRunner()


def test_hardening_mutation_variant_cannot_be_baseline(baseline, duplicate_variant):
    with pytest.raises((ValueError, ValidationError)):
        build_variant_replay(duplicate_variant, baseline)


def test_hardening_swapping_distribution_seeds_still_fails(baseline, variant):
    with pytest.raises(ValueError, match="expected Tiny seed 42"):
        build_variant_replay(variant, baseline)


def test_hardening_same_sql_report_cannot_claim_agent_rerun(baseline, variant):
    report = build_variant_replay(baseline, variant)
    payload = report.model_dump(mode="json")
    payload["replay_mode"] = "agent_rerun"
    payload["report_kind"] = REPORT_KIND_FOR_MODE["agent_rerun"]
    with pytest.raises(ValidationError, match="agent_rerun must invoke the Agent"):
        VariantReplayReport.model_validate(payload)


def test_hardening_scoring_report_cannot_set_scoring_applied(baseline, variant):
    report = build_variant_replay(baseline, variant)
    payload = report.model_dump(mode="json")
    payload["replay_mode"] = "scoring"
    payload["report_kind"] = REPORT_KIND_FOR_MODE["scoring"]
    payload["scoring_applied"] = True
    payload["passed"] = False
    with pytest.raises(ValidationError):
        VariantReplayReport.model_validate(payload)


def _tamper(source, dest, sql: str) -> None:
    shutil.copytree(source, dest)
    connection = duckdb.connect(str(dest / "dataset.duckdb"))
    connection.execute(sql)
    connection.execute("CHECKPOINT")
    connection.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE dim_date SET is_month_end = NOT is_month_end "
        "WHERE calendar_date = DATE '2025-06-30'",
        "UPDATE dim_customer SET region = '西北' WHERE customer_id = 'C001'",
        "INSERT INTO dim_date VALUES ('D9999', DATE '2099-01-01', 2099, 1, 1, 1, FALSE, FALSE)",
    ],
)
def test_hardening_tampered_contents_fail_closed(baseline, variant, tmp_path, sql):
    tampered = tmp_path / "tampered"
    _tamper(baseline, tampered, sql)
    with pytest.raises(ValueError, match="mismatch"):
        build_variant_replay(tampered, variant)
    tampered_variant = tmp_path / "tampered-variant"
    _tamper(variant, tampered_variant, sql)
    with pytest.raises(ValueError, match="mismatch"):
        build_variant_replay(baseline, tampered_variant)


def test_hardening_cli_agent_rerun_without_agent_fails(baseline, variant, tmp_path):
    result = runner.invoke(
        app,
        [
            "replay-variant",
            "--baseline",
            str(baseline),
            "--variant",
            str(variant),
            "--output",
            str(tmp_path / "agent-rerun"),
            "--mode",
            "agent_rerun",
        ],
    )
    assert result.exit_code == 2
    assert "injected Agent" in result.output


class _WrongAnswerAgent:
    def __init__(self):
        self.requests = []
        self.calls = 0

    def respond(self, request, tools):
        self.requests.append(request)
        self.calls += 1
        tools.search_metrics(request.question)
        return Success(answer="0", sql="SELECT 1 AS n", query_id="forged", confidence=1)


class _PublicToolAgent:
    def __init__(self, sql_by_case: dict[str, str]):
        self.sql_by_case = sql_by_case
        self.requests = []
        self.calls = 0

    def respond(self, request, tools):
        dumped = request.model_dump()
        assert "semantic_spec" not in dumped
        assert "oracle" not in dumped
        self.requests.append(request)
        self.calls += 1
        tools.search_metrics(request.question)
        sql = self.sql_by_case[request.case_id]
        receipt = tools.execute_sql(sql)
        return Success(answer="完成", sql=sql, query_id=receipt.query_id, confidence=1)


def test_hardening_wrong_agent_fails_and_never_sees_gold(baseline, variant, repository):
    agent = _WrongAnswerAgent()
    report = build_variant_replay(baseline, variant, replay_mode="agent_rerun", agent=agent)
    assert report.replay_mode == "agent_rerun"
    assert report.agent_invoked is True
    assert report.passed is False
    assert agent.calls >= 1
    assert "C360_0012" not in {item.case_id for item in agent.requests}
    blocked = next(item for item in report.cases if item.case_id == "C360_0012")
    assert blocked.applicability == "policy_incompatible"
    assert blocked.policy_block_code == "AGGREGATION_TOO_SMALL"
    assert blocked.agent_outcome is None
    failed = [item for item in report.cases if item.agent_outcome == "fail"]
    assert failed
    assert all(item.agent_reason_code == "UNVERIFIED_RESULT" for item in failed)
    for request in agent.requests:
        assert request.question
        assert "semantic_spec" not in request.model_dump()


def test_hardening_public_tool_agent_rerun(baseline, variant, repository):
    catalog = load_human_cases()
    sql_by_case = {
        item.case_id: compile_semantic(item.semantic_spec(), repository).sql
        for item in catalog.cases
        if item.material_status == "compilable_answer"
    }
    agent = _PublicToolAgent(sql_by_case)
    report = build_variant_replay(baseline, variant, replay_mode="agent_rerun", agent=agent)
    assert report.passed is True
    assert report.agent_invoked is True
    assert report.scoring_applied is False
    assert agent.calls == sum(
        1
        for item in report.cases
        if item.material_status == "compilable_answer" and item.applicability == "applicable"
    )
    assert {item.case_id for item in agent.requests} == {
        item.case_id for item in report.cases if item.applicability == "applicable"
    }
    blocked = next(item for item in report.cases if item.case_id == "C360_0012")
    assert blocked.applicability == "policy_incompatible"


def test_hardening_same_sql_rejects_injected_agent(baseline, variant):
    with pytest.raises(ValueError, match="same_sql replay cannot invoke the Agent"):
        build_variant_replay(baseline, variant, agent=_WrongAnswerAgent())


def test_duplicate_variant_detects_transaction_count(duplicate_variant, repository):
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0016")
    spec = case.semantic_spec()
    slices = load_table_slices(duplicate_variant / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    wrong = CompiledQuery(
        sql=(
            'SELECT COUNT(*) AS "customer_count" FROM "fact_transaction" '
            "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
            "AND \"transaction_date\" <= '2025-06-30'"
        ),
        columns=(Column(name="customer_count", kind="integer"),),
    )
    observed = normalize_sql_result(duplicate_variant / "dataset.duckdb", wrong)
    assert not compare_results(observed, independent)


def test_null_variant_detects_not_null_occupation(null_variant, repository):
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0013")
    spec = case.semantic_spec()
    slices = load_table_slices(null_variant / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    wrong = compile_semantic(
        SemanticSpec(
            metric=spec.metric,
            filters=(Filter(field="occupation", operator="is_not_null"),),
        ),
        repository,
    )
    observed = normalize_sql_result(null_variant / "dataset.duckdb", wrong)
    assert not compare_results(observed, independent)


def test_date_variant_detects_outside_window_endpoint(date_variant, repository):
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0003")
    spec = case.semantic_spec()
    slices = load_table_slices(date_variant / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    wrong = compile_semantic(
        SemanticSpec(
            metric=spec.metric,
            time_window=RollingWindow(days=91, anchor_date=ANCHOR),
        ),
        repository,
    )
    observed = normalize_sql_result(date_variant / "dataset.duckdb", wrong)
    assert not compare_results(observed, independent)
