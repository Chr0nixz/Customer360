"""End-to-end benchmark test for local offline model adapter and live loopback server."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import pytest

from customer360.agent.local_model import create_local_model_agent
from customer360.agent.local_server import LocalInferenceServer
from customer360.cli import app
from customer360.contracts.public import Success
from customer360.evaluator.matrix import evaluate_matrix, resolve_eval_agent
from customer360.evaluator.report import (
    load_private_matrix,
    public_summary,
    render_html,
    render_markdown,
)
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.runtime.tools import ToolSession


@pytest.fixture
def mock_server():
    """Start an ephemeral loopback mock inference server."""
    server = LocalInferenceServer(host="127.0.0.1", port=0, model="qwen2.5-coder-7b", quiet=True)
    with server:
        yield server


def test_local_server_endpoints(mock_server: LocalInferenceServer):
    # Test /health
    health_url = f"http://127.0.0.1:{mock_server.bound_port}/health"
    with urlopen(health_url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"

    # Test /v1/models
    models_url = f"{mock_server.endpoint_url}/models"
    with urlopen(models_url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["object"] == "list"
        assert data["data"][0]["id"] == "qwen2.5-coder-7b"


def test_local_model_agent_live_loopback_query(mock_server: LocalInferenceServer, baseline: Path):
    agent = create_local_model_agent(
        endpoint=mock_server.endpoint_url,
        model=mock_server.model,
    )
    repo = MetadataRepository()
    db_path = baseline / "dataset.duckdb"
    gateway = ExecutionGateway(db_path, tiny_eval_policy())
    tools = ToolSession(gateway, repo)

    from datetime import date

    from customer360.contracts.public import AgentRequest

    request = AgentRequest(
        case_id="C360_0001",
        question="统计截至2025年6月30日近90天成功交易金额。",
        anchor_date=date(2025, 6, 30),
        metadata_version=repo.metrics.metrics_version,
    )

    response = agent.respond(request, tools)
    assert isinstance(response, Success)
    assert "fact_transaction" in response.sql
    assert response.query_id
    assert response.confidence == 1.0


@pytest.mark.slow
def test_local_model_matrix_evaluation_and_reports(
    mock_server: LocalInferenceServer,
    baseline: Path,
    variant: Path,
    duplicate_variant: Path,
    null_variant: Path,
    date_variant: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("C360_LOCAL_MODEL_URL", mock_server.endpoint_url)
    monkeypatch.setenv("C360_LOCAL_MODEL_NAME", mock_server.model)

    agent = resolve_eval_agent("local-model")
    matrix_dir = tmp_path / "matrix_eval_local_model"

    variants = {
        "tiny_seed_43_distribution": variant,
        "tiny_duplicate_fanout": duplicate_variant,
        "tiny_null_empty_groups": null_variant,
        "tiny_date_boundary": date_variant,
    }

    report = evaluate_matrix(
        baseline,
        variants,
        agent,
        agent_id="local-model",
        replay_mode="same_sql",
    )

    from customer360.evaluator.report import write_matrix_run

    summary = write_matrix_run(matrix_dir, report)
    assert summary["integrity_passed"] is True
    assert summary["case_count"] == 20
    assert summary["agent_id"] == "local_model"

    # Verify written matrix artifact
    matrix = load_private_matrix(matrix_dir)
    assert matrix.agent_id == "local_model"
    pub_sum = public_summary(matrix)
    assert pub_sum.case_count == 20
    assert pub_sum.integrity_passed is True
    assert len(pub_sum.cases) == 20

    # Test report rendering
    md_report = render_markdown(pub_sum)
    assert "local_model" in md_report
    assert "case_count: `20`" in md_report

    html_report = render_html(pub_sum)
    assert "local_model" in html_report
    assert "<li>agent_id: local_model</li>" in html_report


def test_local_model_run_case_cli(
    mock_server: LocalInferenceServer,
    baseline: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from typer.testing import CliRunner

    runner = CliRunner()
    monkeypatch.setenv("C360_LOCAL_MODEL_URL", mock_server.endpoint_url)
    monkeypatch.setenv("C360_LOCAL_MODEL_NAME", mock_server.model)

    out_dir = tmp_path / "case_out"
    result = runner.invoke(
        app,
        [
            "run-case",
            "--case-id",
            "C360_0001",
            "--dataset",
            str(baseline),
            "--output",
            str(out_dir),
            "--agent",
            "local-model",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["outcome"] == "pass"
    assert data["case_id"] == "C360_0001"


def test_local_model_error_fallback(baseline: Path):
    # Server in forced-error mode
    server = LocalInferenceServer(host="127.0.0.1", port=0, force_error=True)
    with server:
        agent = create_local_model_agent(endpoint=server.endpoint_url, model=server.model)
        repo = MetadataRepository()
        gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
        tools = ToolSession(gateway, repo)

        from datetime import date

        from customer360.contracts.public import AgentRequest, Refusal

        req = AgentRequest(
            case_id="C360_ERR",
            question="统计活跃客户数",
            anchor_date=date(2025, 6, 30),
            metadata_version=repo.metrics.metrics_version,
        )
        resp = agent.respond(req, tools)
        assert isinstance(resp, Refusal)
        assert resp.reason_code == "UNSUPPORTED_QUERY"
