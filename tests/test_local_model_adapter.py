"""Tests for local offline model adapter."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from customer360.agent.baseline import BaselineAgent
from customer360.agent.local_model import (
    LocalModelAdapter,
    assert_local_endpoint,
    create_local_model_agent,
)
from customer360.contracts.public import (
    AgentRequest,
    Clarification,
    Refusal,
    Success,
)
from customer360.evaluator.matrix import resolve_eval_agent
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.runtime.tools import ToolSession


class MockAgentTools:
    """Mock tools providing necessary read-only metadata methods for non-execution tests."""

    def search_metrics(self, q: str):
        return ()

    def search_columns(self, q: str):
        return ()

    def search_tables(self, q: str):
        return ()

    def get_join_paths(self, q: str):
        return ()

    def get_business_glossary(self, term: str):
        return ()

    def get_metric_definition(self, name: str):
        return {}

    def get_table_schema(self, table: str):
        return ()

    def validate_query_plan(self, plan: dict):
        return {"is_valid": True, "issues": []}

    def execute_sql(self, sql: str):
        raise NotImplementedError("Execution not supported in mock tools")


def test_assert_local_endpoint_blocks_external_addresses():
    # Permitted local loopback endpoints
    assert_local_endpoint("http://127.0.0.1:11434/v1")
    assert_local_endpoint("http://localhost:8000/v1")
    assert_local_endpoint("http://0.0.0.0:8080/v1")
    assert_local_endpoint("http://[::1]:11434/v1")

    # Prohibited external hosts
    for bad_url in (
        "https://api.openai.com/v1",
        "https://api.anthropic.com/v1",
        "http://192.168.1.50:8000/v1",
        "http://10.0.0.1:11434/v1",
        "https://example.com/api",
    ):
        with pytest.raises(ValueError, match="External network connection prohibited"):
            assert_local_endpoint(bad_url)


def test_local_model_adapter_answer_end_to_end(baseline):
    # Mock model output for an answerable query
    model_json = json.dumps(
        {
            "action": "answer",
            "metric_name": "successful_transaction_count",
            "time_kind": "rolling",
            "days": 90,
            "filters": [],
        }
    )
    mock_response = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": f"```json\n{model_json}\n```",
                    }
                }
            ]
        }
    )

    def mock_poster(url: str, body: dict[str, Any], timeout: float) -> str:
        return mock_response

    agent = create_local_model_agent(http_poster=mock_poster)

    repo = MetadataRepository()
    db_path = baseline / "dataset.duckdb"
    gateway = ExecutionGateway(db_path, tiny_eval_policy())
    tools = ToolSession(gateway, repo)
    request = AgentRequest(
        case_id="C360_TEST_001",
        question="近90天有多少笔成功交易？",
        anchor_date=date(2025, 6, 30),
        metadata_version=repo.metrics.metrics_version,
    )

    response = agent.respond(request, tools)
    assert isinstance(response, Success)
    assert response.status == "success"
    assert response.query_id
    assert "fact_transaction" in response.sql
    assert "\"status\" = 'success'" in response.sql
    assert any("local_model" in ev for ev in response.evidence)


def test_local_model_adapter_clarify():
    model_json = json.dumps(
        {
            "action": "clarify",
            "metric_name": "successful_transaction_count",
            "missing_slots": ["time_window"],
            "questions": ["请问您想统计哪个时间窗口的成功交易笔数？"],
        }
    )
    mock_response = json.dumps({"choices": [{"message": {"content": model_json}}]})

    agent = create_local_model_agent(http_poster=lambda url, body, timeout: mock_response)
    repo = MetadataRepository()
    request = AgentRequest(
        case_id="C360_TEST_002",
        question="成功交易笔数是多少？",
        anchor_date=date(2025, 6, 30),
        metadata_version=repo.metrics.metrics_version,
    )

    response = agent.respond(request, MockAgentTools())
    assert isinstance(response, Clarification)
    assert response.status == "clarification_needed"
    assert "time_window" in response.requested_slots
    assert "时间窗口" in response.questions[0]


def test_local_model_adapter_refuse():
    model_json = json.dumps(
        {
            "action": "refuse",
            "reason_code": "UNKNOWN_FIELD",
            "reason": "客户手机号不属于已授权的查询字段。",
            "alternative": "请改用已声明的客户等级或地区属性进行查询。",
        }
    )
    mock_response = json.dumps({"choices": [{"message": {"content": model_json}}]})

    agent = create_local_model_agent(http_poster=lambda url, body, timeout: mock_response)
    repo = MetadataRepository()
    request = AgentRequest(
        case_id="C360_TEST_003",
        question="帮我查下客户手机号",
        anchor_date=date(2025, 6, 30),
        metadata_version=repo.metrics.metrics_version,
    )

    response = agent.respond(request, MockAgentTools())
    assert isinstance(response, Refusal)
    assert response.status == "refused"
    assert response.reason_code == "UNKNOWN_FIELD"


def test_local_model_adapter_network_failure_fallback():
    # If the local inference server fails, the adapter degrades gracefully into a refusal
    def broken_poster(url: str, body: dict[str, Any], timeout: float) -> str:
        raise OSError("Connection refused by local server")

    agent = create_local_model_agent(http_poster=broken_poster)
    repo = MetadataRepository()
    request = AgentRequest(
        case_id="C360_TEST_004",
        question="近30天交易笔数",
        anchor_date=date(2025, 6, 30),
        metadata_version=repo.metrics.metrics_version,
    )

    response = agent.respond(request, MockAgentTools())
    assert isinstance(response, Refusal)
    assert response.status == "refused"
    assert response.reason_code == "UNSUPPORTED_QUERY"
    assert "本地模型推理失败" in response.reason


def test_resolve_eval_agent_local_model(monkeypatch):
    monkeypatch.setenv("C360_LOCAL_MODEL_URL", "http://127.0.0.1:11434/v1")
    agent = resolve_eval_agent("local-model")
    assert isinstance(agent, BaselineAgent)
    assert isinstance(agent.adapter, LocalModelAdapter)
    assert agent.adapter.config.endpoint == "http://127.0.0.1:11434/v1"

    # External commercial models remain fail-closed
    with pytest.raises(ValueError, match="external model network is not permitted"):
        resolve_eval_agent("openai")
