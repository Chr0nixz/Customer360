"""End-to-end evaluation and diagnostics tests for v1.4 benchmark pipeline.

The pinned tests read maintainer-frozen artifacts under outputs/, which are
gitignored and absent on fresh CI checkouts; each test skips with a clear
reason instead of failing the fast gate (same pattern as the PostgreSQL live
skips).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.agent.local_server import LocalInferenceServer
from customer360.cli import app

PUBLIC_FORMAL = Path("outputs/eval-public-baseline/private/formal_input.json")
HIDDEN_FORMAL_D076 = Path("outputs/eval-hidden-d076/private/formal_input.json")
BENCHMARK_BASELINE = Path("outputs/benchmark_env/baseline")
BENCHMARK_VARIANTS = (
    Path("outputs/benchmark_env/variants/distribution"),
    Path("outputs/benchmark_env/variants/fanout"),
    Path("outputs/benchmark_env/variants/null"),
    Path("outputs/benchmark_env/variants/date"),
)
D076_PUBLIC_FORMAL = Path("outputs/eval-public-d076/private/formal_input.json")


def test_diagnostics_on_public_formal_run(tmp_path: Path):
    if not PUBLIC_FORMAL.is_file():
        pytest.skip("maintainer artifact outputs/eval-public-baseline is not present")
    runner = CliRunner()
    diag_out = tmp_path / "test-diag-public"

    res = runner.invoke(
        app,
        [
            "diagnose",
            "--input",
            "outputs/eval-public-baseline",
            "--pack",
            "outputs/tasks-300-v14",
            "--output",
            str(diag_out),
        ],
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["total_cases"] == 120
    # D076: the 12 baseline policy-inapplicable cases in this historical run are
    # excluded as structural instead of counted as agent failures (82/108 eligible).
    assert data["passed_cases"] == 82
    assert data["failed_cases"] == 26
    assert data["excluded_cases"] == 12
    assert (diag_out / "diagnostics.md").is_file()
    assert (diag_out / "diagnostics.json").is_file()
    assert (diag_out / "diagnostics.html").is_file()


def test_diagnostics_on_hidden_run(tmp_path: Path):
    if not HIDDEN_FORMAL_D076.is_file():
        pytest.skip("maintainer artifact outputs/eval-hidden-d076 is not present")
    runner = CliRunner()
    diag_out = tmp_path / "test-diag-hidden"

    res = runner.invoke(
        app,
        [
            "diagnose",
            "--input",
            "outputs/eval-hidden-d076",
            "--pack",
            "outputs/hidden-pack-v14",
            "--output",
            str(diag_out),
        ],
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["total_cases"] == 100
    # Re-pinned after the maintainer acceptance run under evaluator 0.7
    # (outputs/eval-hidden-d076): 10 baseline policy-inapplicable cases are
    # excluded as structural; 4 agent failures remain.
    assert data["passed_cases"] == 86
    assert data["failed_cases"] == 4
    assert data["excluded_cases"] == 10
    assert (diag_out / "diagnostics.md").is_file()
    assert (diag_out / "diagnostics.json").is_file()
    assert (diag_out / "diagnostics.html").is_file()


def test_local_model_end_to_end_human_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if not BENCHMARK_BASELINE.is_dir() or not all(path.is_dir() for path in BENCHMARK_VARIANTS):
        pytest.skip("maintainer artifact outputs/benchmark_env is not present")
    server = LocalInferenceServer(host="127.0.0.1", port=0, model="c360-qwen-local", quiet=True)
    with server:
        monkeypatch.setenv("C360_LOCAL_MODEL_URL", server.endpoint_url)
        monkeypatch.setenv("C360_LOCAL_MODEL_NAME", server.model)

        runner = CliRunner()
        eval_out = tmp_path / "eval_out"
        diag_out = tmp_path / "diag_out"

        res_eval = runner.invoke(
            app,
            [
                "evaluate",
                "--dataset",
                str(BENCHMARK_BASELINE),
                "--distribution-variant",
                str(BENCHMARK_VARIANTS[0]),
                "--duplicate-variant",
                str(BENCHMARK_VARIANTS[1]),
                "--null-variant",
                str(BENCHMARK_VARIANTS[2]),
                "--date-variant",
                str(BENCHMARK_VARIANTS[3]),
                "--agent",
                "local-model",
                "--output",
                str(eval_out),
            ],
        )
        assert res_eval.exit_code == 0

        res_diag = runner.invoke(
            app,
            [
                "diagnose",
                "--input",
                str(eval_out),
                "--output",
                str(diag_out),
            ],
        )
        assert res_diag.exit_code == 0
        diag_data = json.loads(res_diag.stdout)
        assert diag_data["total_cases"] == 20
        # D075: the deterministic planner behind LocalInferenceServer now resolves
        # the active-customer-count and metric/time-slot clarification patterns,
        # so the local-model loop improved from 15/20 to 17/20.
        assert diag_data["passed_cases"] == 17
        assert diag_data["failed_cases"] == 3
        assert (diag_out / "diagnostics.md").is_file()
        assert (diag_out / "diagnostics.html").is_file()


@pytest.mark.slow
def test_d076_public_formal_probe_semantics():
    """Pin the D076 formal semantics on the frozen eval-public-d076 evidence.

    The variant Gold probe must have flipped C360_1284 to passing through an
    inapplicable seed43 snapshot, with exactly 12 baseline-structural cases and
    no agent-attributable failure left.
    """
    if not D076_PUBLIC_FORMAL.is_file():
        pytest.skip("D076 evidence outputs/eval-public-d076 is not present")

    from customer360.contracts.formal import FormalEvaluationReport

    report = FormalEvaluationReport.model_validate_json(
        D076_PUBLIC_FORMAL.read_text(encoding="utf-8")
    )
    assert report.evaluator_version == "0.7"
    structural = [
        case for case in report.cases if case.snapshots and not case.snapshots[0].applicable
    ]
    assert len(structural) == 12
    case = next(item for item in report.cases if item.case_id == "C360_1284")
    assert case.evaluation.outcome == "pass"
    seed43 = next(row for row in case.snapshots if row.snapshot_id == "tiny_seed_43_distribution")
    assert seed43.applicable is False
    assert seed43.policy_code == "AGGREGATION_TOO_SMALL"
    assert all(
        item.evaluation.outcome == "pass"
        for item in report.cases
        if item.snapshots and item.snapshots[0].applicable
    )
