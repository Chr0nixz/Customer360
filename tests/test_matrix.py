"""Stage D / M4 matrix evaluation: baseline + 4 variants, no official score."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.agent.template import TemplateAgent
from customer360.cli import app
from customer360.contracts.matrix import (
    MATRIX_SNAPSHOT_IDS,
    PUBLIC_MATRIX_FORBIDDEN,
    PublicMatrixSummary,
)
from customer360.contracts.semantic import RollingWindow, SemanticSpec
from customer360.errors import QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.evaluator.matrix import evaluate_matrix, resolve_eval_agent
from customer360.evaluator.report import public_summary, write_matrix_run
from customer360.runtime.gateway import ExecutionGateway
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.variant import tiny_eval_policy

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def _variant_map(variant, duplicate_variant, null_variant, date_variant):
    return {
        "tiny_seed_43_distribution": variant,
        "tiny_duplicate_fanout": duplicate_variant,
        "tiny_null_empty_groups": null_variant,
        "tiny_date_boundary": date_variant,
    }


@pytest.fixture(scope="module")
def matrix_report(baseline, variant, duplicate_variant, null_variant, date_variant):
    return evaluate_matrix(
        baseline,
        _variant_map(variant, duplicate_variant, null_variant, date_variant),
        TemplateAgent(),
        agent_id="template",
        replay_mode="same_sql",
    )


def test_resolve_agent_keeps_template_separate_from_official_baseline():
    from customer360.agent.baseline import BaselineAgent

    assert isinstance(resolve_eval_agent("template"), TemplateAgent)
    assert isinstance(resolve_eval_agent("baseline"), BaselineAgent)
    with pytest.raises(ValueError, match="external model network is not permitted"):
        resolve_eval_agent("gpt")
    with pytest.raises(ValueError, match="unknown agent"):
        resolve_eval_agent("mystery")


def test_scoring_mode_cannot_apply_weights(
    baseline, variant, duplicate_variant, null_variant, date_variant
):
    with pytest.raises(ValueError, match="scoring_applied remains false"):
        evaluate_matrix(
            baseline,
            _variant_map(variant, duplicate_variant, null_variant, date_variant),
            TemplateAgent(),
            replay_mode="scoring",
        )


def test_missing_variant_fails_closed(baseline, variant):
    with pytest.raises(ValueError, match="four frozen Tiny variants"):
        evaluate_matrix(
            baseline,
            {"tiny_seed_43_distribution": variant},
            TemplateAgent(),
        )


def test_same_sql_matrix_and_public_redaction(matrix_report, tmp_path):
    report = matrix_report
    assert report.scoring_applied is False
    assert report.m4_scored is False
    assert report.m2_complete is False
    assert report.integrity_passed is True
    assert report.replay_mode == "same_sql"
    assert report.snapshot_ids == MATRIX_SNAPSHOT_IDS
    assert report.date_dimension_unchanged is True
    assert tuple(item.case_id for item in report.cases) == tuple(
        f"C360_{index:04d}" for index in range(1, 21)
    )
    assert all(item.split == "dev" for item in report.cases)
    variants_invoked = [
        snapshot.agent_invoked
        for case in report.cases
        for snapshot in case.snapshots
        if snapshot.snapshot_id != "tiny_baseline_seed_42"
    ]
    assert any(snapshot.agent_invoked for case in report.cases for snapshot in case.snapshots)
    assert not any(variants_invoked)
    clarification = next(item for item in report.cases if item.case_id == "C360_0019")
    assert clarification.baseline_record.reason_code == "CLARIFICATION_OK"
    assert clarification.candidate_sql
    refused = next(item for item in report.cases if item.case_id == "C360_0020")
    assert refused.baseline_record.reason_code == "REFUSAL_OK"
    assert all(
        snapshot.applicable == "not_applicable"
        for snapshot in refused.snapshots
        if snapshot.snapshot_id != "tiny_baseline_seed_42"
    )
    output = tmp_path / "matrix-d"
    summary = write_matrix_run(output, report)
    assert summary["scoring_applied"] is False
    public = (output / "public" / "summary.json").read_text(encoding="utf-8")
    markdown = (output / "public" / "report.md").read_text(encoding="utf-8")
    html = (output / "public" / "report.html").read_text(encoding="utf-8")
    for field in PUBLIC_MATRIX_FORBIDDEN:
        assert f'"{field}"' not in public
        assert f'"{field}"' not in markdown
        assert f'"{field}"' not in html
    assert "SELECT" not in public
    assert "SELECT" not in markdown
    assert "SELECT" not in html
    assert "missing_slots" not in public
    loaded = PublicMatrixSummary.model_validate_json(public)
    assert loaded.scoring_applied is False
    assert public_summary(report) == loaded


def test_wrong_window_sql_is_distinguished_on_variants(variant, repository):
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0003")
    spec = case.semantic_spec()
    wrong = compile_semantic(
        SemanticSpec(
            metric=spec.metric,
            time_window=RollingWindow(days=30, anchor_date=spec.time_window.anchor_date),
        ),
        repository,
    )
    slices = load_table_slices(variant / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    gateway = ExecutionGateway(variant / "dataset.duckdb", tiny_eval_policy())
    observed = gateway.execute(wrong.sql).result
    assert not compare_results(observed, independent)


def test_unsafe_sql_stays_rejected_on_variant(variant):
    gateway = ExecutionGateway(variant / "dataset.duckdb", tiny_eval_policy())
    with pytest.raises(QueryRejected) as rejected:
        gateway.execute("DROP TABLE dim_customer")
    assert rejected.value.code == "UNSAFE_SQL"


def test_evaluate_cli_rejects_scoring_and_hidden_split(
    baseline, variant, duplicate_variant, null_variant, date_variant, tmp_path
):
    common = [
        "evaluate",
        "--dataset",
        str(baseline),
        "--distribution-variant",
        str(variant),
        "--duplicate-variant",
        str(duplicate_variant),
        "--null-variant",
        str(null_variant),
        "--date-variant",
        str(date_variant),
        "--oracles",
        str(ROOT / "data/trusted/human_oracles.yaml"),
    ]
    scored = runner.invoke(
        app, [*common, "--output", str(tmp_path / "eval-score"), "--mode", "scoring"]
    )
    assert scored.exit_code == 2, scored.output
    assert "scoring_applied remains false" in scored.output
    hidden = runner.invoke(
        app, [*common, "--output", str(tmp_path / "eval-hidden"), "--split", "private"]
    )
    assert hidden.exit_code == 2, hidden.output
    assert "split=dev" in hidden.output


def test_report_cli_stays_desensitized(matrix_report, tmp_path):
    output = tmp_path / "eval-ok"
    write_matrix_run(output, matrix_report)
    rendered = runner.invoke(app, ["report", "--input", str(output), "--format", "json"])
    assert rendered.exit_code == 0, rendered.output
    assert "candidate_sql" not in rendered.output
    assert "semantic_spec" not in rendered.output
    assert '"scoring_applied":false' in rendered.output.replace(" ", "")
