"""M2-05/M4-02: replay compiled Gold SQL on frozen Tiny variants."""

import json
import shutil
from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.semantic import RollingWindow, SemanticSpec
from customer360.contracts.variant import REPORT_KIND_FOR_MODE, VariantReplayReport
from customer360.evaluator.compare import compare_results
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.coverage import load_human_cases
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.variant import _sql_result, build_variant_replay

ANCHOR = date(2025, 6, 30)
runner = CliRunner()


def test_same_sql_replay_matches_independent_oracle_on_variant(baseline, variant):
    report = build_variant_replay(baseline, variant)
    assert TypeAdapter(VariantReplayReport).validate_json(report.model_dump_json()) == report
    assert report.passed is True
    assert report.m2_complete is False
    assert report.scoring_applied is False
    assert report.replay_mode == "same_sql"
    assert report.variant_id == "tiny_seed_43_distribution"
    assert report.baseline_seed == 42
    assert report.variant_seed == 43
    assert report.compilable_answers == 18
    assert report.independent_oracle_matches == 18
    assert report.results_differ_from_baseline >= 1
    assert report.date_dimension_unchanged is True
    executable = [item for item in report.cases if item.material_status == "compilable_answer"]
    assert all(item.sql_unchanged is True for item in executable)
    assert len({item.sql for item in executable}) == 18
    skipped = [item for item in report.cases if item.material_status != "compilable_answer"]
    assert len(skipped) == 2
    assert all(item.sql is None for item in skipped)


def test_wrong_window_sql_still_fails_on_variant(variant, repository):
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0003")
    spec = case.semantic_spec()
    compiled = compile_semantic(spec, repository)
    wrong = compile_semantic(
        SemanticSpec(
            metric=spec.metric,
            time_window=RollingWindow(days=30, anchor_date=ANCHOR),
        ),
        repository,
    )
    assert compiled.sql != wrong.sql
    slices = load_table_slices(variant / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    observed = _sql_result(variant / "dataset.duckdb", wrong)
    assert not compare_results(observed, independent)


def test_replay_rejects_swapped_or_identical_seeds(baseline, variant, tmp_path):
    with pytest.raises(ValueError, match="expected Tiny seed 42"):
        build_variant_replay(variant, baseline)
    with pytest.raises(ValueError, match="expected Tiny seed 43"):
        build_variant_replay(baseline, baseline)
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    shutil.copyfile(baseline / "dataset.duckdb", fixture_dir / "dataset.duckdb")
    (fixture_dir / "manifest.json").write_text(
        '{"artifact_kind":"public_fixture_not_tiny"}', encoding="utf-8"
    )
    with pytest.raises((ValidationError, ValueError)):
        build_variant_replay(baseline, fixture_dir)


def test_replay_cli_writes_report_and_refuses_overwrite(baseline, variant, tmp_path):
    output = tmp_path / "replay"
    result = runner.invoke(
        app,
        [
            "replay-variant",
            "--baseline",
            str(baseline),
            "--variant",
            str(variant),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["passed"] is True
    assert summary["m2_complete"] is False
    assert summary["scoring_applied"] is False
    assert summary["independent_oracle_matches"] == 18
    assert (output / "replay.json").is_file()
    markdown = (output / "replay.md").read_text(encoding="utf-8")
    assert "m2_complete: `False`" in markdown
    assert "scoring_applied: `False`" in markdown
    second = runner.invoke(
        app,
        [
            "replay-variant",
            "--baseline",
            str(baseline),
            "--variant",
            str(variant),
            "--output",
            str(output),
        ],
    )
    assert second.exit_code == 2


def _assert_same_sql_variant(report: VariantReplayReport, variant_id: str) -> None:
    assert TypeAdapter(VariantReplayReport).validate_json(report.model_dump_json()) == report
    assert report.passed is True
    assert report.m2_complete is False
    assert report.scoring_applied is False
    assert report.replay_mode == "same_sql"
    assert report.agent_invoked is False
    assert report.variant_id == variant_id
    assert report.compilable_answers == 18
    assert report.independent_oracle_matches == 18
    assert report.results_differ_from_baseline >= 1
    assert report.date_dimension_unchanged is True
    executable = [item for item in report.cases if item.material_status == "compilable_answer"]
    assert all(item.sql_unchanged is True for item in executable)
    skipped = [item for item in report.cases if item.material_status != "compilable_answer"]
    assert len(skipped) == 2


def _wrong_window_still_mismatches(dataset_dir, repository) -> None:
    catalog = load_human_cases()
    case = next(item for item in catalog.cases if item.case_id == "C360_0003")
    spec = case.semantic_spec()
    compiled = compile_semantic(spec, repository)
    wrong = compile_semantic(
        SemanticSpec(
            metric=spec.metric,
            time_window=RollingWindow(days=30, anchor_date=ANCHOR),
        ),
        repository,
    )
    assert compiled.sql != wrong.sql
    slices = load_table_slices(dataset_dir / "dataset.duckdb", repository.catalog)
    independent = compute_independent(spec, repository, slices)
    observed = _sql_result(dataset_dir / "dataset.duckdb", wrong)
    assert not compare_results(observed, independent)


def test_duplicate_fanout_same_sql_and_wrong_sql(baseline, duplicate_variant, repository):
    report = build_variant_replay(baseline, duplicate_variant)
    _assert_same_sql_variant(report, "tiny_duplicate_fanout")
    _wrong_window_still_mismatches(duplicate_variant, repository)


def test_null_empty_groups_same_sql_and_wrong_sql(baseline, null_variant, repository):
    report = build_variant_replay(baseline, null_variant)
    _assert_same_sql_variant(report, "tiny_null_empty_groups")
    _wrong_window_still_mismatches(null_variant, repository)


def test_date_boundary_same_sql_and_wrong_sql(baseline, date_variant, repository):
    report = build_variant_replay(baseline, date_variant)
    _assert_same_sql_variant(report, "tiny_date_boundary")
    _wrong_window_still_mismatches(date_variant, repository)


def test_agent_rerun_without_agent_is_rejected(baseline, variant):
    with pytest.raises(ValueError, match="injected Agent"):
        build_variant_replay(baseline, variant, replay_mode="agent_rerun")
    report = build_variant_replay(baseline, variant)
    payload = report.model_dump(mode="json")
    payload["replay_mode"] = "same_sql"
    payload["report_kind"] = REPORT_KIND_FOR_MODE["same_sql"]
    payload["agent_invoked"] = True
    with pytest.raises(ValidationError, match="same_sql replay cannot invoke the Agent"):
        VariantReplayReport.model_validate(payload)


@pytest.mark.parametrize(
    "dataset,variant_id",
    [
        ("duplicate_variant", "tiny_duplicate_fanout"),
        ("null_variant", "tiny_null_empty_groups"),
        ("date_variant", "tiny_date_boundary"),
    ],
)
def test_replay_cli_on_mutation_variants(baseline, dataset, variant_id, tmp_path, request):
    variant_dir = request.getfixturevalue(dataset)
    output = tmp_path / variant_id
    result = runner.invoke(
        app,
        [
            "replay-variant",
            "--baseline",
            str(baseline),
            "--variant",
            str(variant_dir),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["passed"] is True
    assert summary["replay_mode"] == "same_sql"
    assert summary["variant_id"] == variant_id
    assert summary["scoring_applied"] is False
    assert summary["m2_complete"] is False
    assert summary["independent_oracle_matches"] == 18


def test_scoring_mode_cannot_apply_weights(baseline, variant):
    with pytest.raises(ValueError, match="scoring is not enabled"):
        build_variant_replay(baseline, variant, replay_mode="scoring")
    with pytest.raises(ValidationError):
        VariantReplayReport.model_validate(
            {
                "report_kind": "tiny_scoring_variant",
                "replay_mode": "scoring",
                "scoring_applied": True,
                "passed": False,
                "baseline_manifest_hash": "a" * 64,
                "variant_manifest_hash": "b" * 64,
                "date_dimension_unchanged": True,
                "limitations": ("x",),
                "cases": [],
            }
        )
