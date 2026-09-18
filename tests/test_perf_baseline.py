"""Stage G performance baseline CLI and reports. Not an official score."""

import json
from pathlib import Path

from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.perf import PUBLIC_PERF_FORBIDDEN, UNAVAILABLE
from customer360.evaluator.perf import (
    collect_evaluate,
    collect_gold_execute,
    public_perf_summary,
    write_perf_run,
)

runner = CliRunner()
ROOT = Path(__file__).parents[1]


def test_help_lists_perf_baseline():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "perf-baseline" in result.output


def test_perf_baseline_rejects_scoring_workload(tmp_path, baseline):
    result = runner.invoke(
        app,
        [
            "perf-baseline",
            "--workload",
            "scoring",
            "--dataset",
            str(baseline),
            "--output",
            str(tmp_path / "perf"),
        ],
    )
    assert result.exit_code == 2
    assert "scoring_applied remains false" in result.output
    assert not (tmp_path / "perf").exists()


def test_perf_baseline_generate_requires_scale(tmp_path):
    result = runner.invoke(
        app,
        [
            "perf-baseline",
            "--workload",
            "generate",
            "--dataset",
            str(tmp_path / "data"),
            "--output",
            str(tmp_path / "perf"),
        ],
    )
    assert result.exit_code == 2
    assert "requires --scale" in result.output


def test_perf_baseline_rejects_network_agent(tmp_path, baseline):
    result = runner.invoke(
        app,
        [
            "perf-baseline",
            "--workload",
            "evaluate",
            "--agent",
            "openai",
            "--dataset",
            str(baseline),
            "--output",
            str(tmp_path / "perf"),
        ],
    )
    assert result.exit_code == 2
    assert "not permitted" in result.output


def test_perf_baseline_rejects_hidden_dataset(tmp_path):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "hidden_profile.json").write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "perf-baseline",
            "--workload",
            "gold-execute",
            "--dataset",
            str(hidden),
            "--output",
            str(tmp_path / "perf"),
        ],
    )
    assert result.exit_code == 2
    assert "hidden Tiny" in result.output


def test_gold_execute_tiny_public_summary_hides_gold_and_scan(tmp_path, baseline):
    report, private_records = collect_gold_execute(baseline)
    assert report.budget_profile == "tiny"
    assert report.scoring_applied is False
    assert report.scan_count_status == UNAVAILABLE
    assert report.token_status == UNAVAILABLE
    assert report.peak_rss_status == UNAVAILABLE
    assert report.success_count == 17
    assert report.skipped_count == 3
    assert report.failure_count == 0
    assert report.integrity_passed is True
    policy = next(item for item in report.queries if item.case_id == "C360_0012")
    assert policy.status == "skipped"
    assert policy.reason_code == "POLICY_INCOMPATIBLE"
    assert report.p95_ms is not None
    summary = write_perf_run(tmp_path / "perf", report, private_records)
    public = json.loads((tmp_path / "perf" / "public" / "summary.json").read_text(encoding="utf-8"))
    assert public["scan_count_status"] == "unavailable"
    assert public["token_status"] == "unavailable"
    assert "scan_count" not in public
    assert "queries" not in public
    assert "dataset_manifest_hash" not in public
    dumped = json.dumps(public)
    for field in PUBLIC_PERF_FORBIDDEN:
        assert f'"{field}"' not in dumped
    assert '"sql"' not in dumped
    assert private_records
    assert any("sql" in item for item in private_records)
    assert summary["scoring_applied"] is False
    payload = public_perf_summary(report).model_dump(mode="json")
    assert payload["concurrency"] == 1
    assert payload["hardware"]["memory_total_status"] in {"available", "unavailable"}
    assert "python" in payload["versions"]

    before = (tmp_path / "perf" / "public" / "summary.json").read_bytes()
    again = runner.invoke(
        app,
        [
            "perf-baseline",
            "--workload",
            "gold-execute",
            "--dataset",
            str(baseline),
            "--output",
            str(tmp_path / "perf"),
        ],
    )
    assert again.exit_code == 2
    assert (tmp_path / "perf" / "public" / "summary.json").read_bytes() == before


def test_evaluate_rejects_scoring_agent_id(baseline):
    try:
        collect_evaluate(baseline, agent_id="scoring")
    except ValueError as exc:
        assert "scoring_applied remains false" in str(exc)
    else:
        raise AssertionError("expected scoring to fail closed")
