"""End-to-end evaluation and diagnostics tests for v1.4 benchmark pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.agent.local_server import LocalInferenceServer
from customer360.cli import app


def test_diagnostics_on_public_formal_run(tmp_path: Path):
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
    assert data["passed_cases"] == 82
    assert data["failed_cases"] == 38
    assert (diag_out / "diagnostics.md").is_file()
    assert (diag_out / "diagnostics.json").is_file()
    assert (diag_out / "diagnostics.html").is_file()


def test_diagnostics_on_hidden_run(tmp_path: Path):
    runner = CliRunner()
    diag_out = tmp_path / "test-diag-hidden"

    res = runner.invoke(
        app,
        [
            "diagnose",
            "--input",
            "outputs/eval-hidden-baseline",
            "--pack",
            "outputs/hidden-pack-v14",
            "--output",
            str(diag_out),
        ],
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["total_cases"] == 100
    assert data["passed_cases"] == 66
    assert data["failed_cases"] == 34
    assert (diag_out / "diagnostics.md").is_file()
    assert (diag_out / "diagnostics.json").is_file()
    assert (diag_out / "diagnostics.html").is_file()


def test_local_model_end_to_end_human_eval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
                "outputs/benchmark_env/baseline",
                "--distribution-variant",
                "outputs/benchmark_env/variants/distribution",
                "--duplicate-variant",
                "outputs/benchmark_env/variants/fanout",
                "--null-variant",
                "outputs/benchmark_env/variants/null",
                "--date-variant",
                "outputs/benchmark_env/variants/date",
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
        assert diag_data["passed_cases"] == 15
        assert diag_data["failed_cases"] == 5
        assert (diag_out / "diagnostics.md").is_file()
        assert (diag_out / "diagnostics.html").is_file()
