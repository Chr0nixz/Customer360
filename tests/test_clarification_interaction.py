from datetime import date

from customer360.agent.baseline import BaselineAgent
from customer360.contracts.public import AgentRequest, Message
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.tasks.variant import tiny_eval_policy

ANCHOR = date(2025, 6, 30)


def test_multi_round_clarification_convergence(baseline, repository):
    """Round 1 requests time window; Round 2 provides it and converges to Success."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Round 1: Vague time query
    req1 = AgentRequest(
        case_id="case_clarify_1",
        question="统计近期客户成功交易笔数。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
    )
    resp1 = agent.respond(req1, tools)
    assert resp1.status == "clarification_needed"
    assert "time_window" in resp1.requested_slots

    # Round 2: User clarifies exact 90-day window
    history = (
        Message(role="user", content="统计近期客户成功交易笔数。"),
        Message(role="assistant", content=resp1.questions[0]),
    )
    req2 = AgentRequest(
        case_id="case_clarify_1",
        question="查询截至2025年6月30日近90天的成功交易笔数。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        conversation=history,
    )
    resp2 = agent.respond(req2, tools)
    assert resp2.status == "success"
    assert "fact_transaction" in resp2.sql
    assert "2025-04-02" in resp2.sql
    assert "2025-06-30" in resp2.sql
    assert resp2.query_id is not None


def test_multi_round_clarification_persistent_vague(baseline, repository):
    """When subsequent replies remain vague, clarification must persist without guessing."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Round 1
    req1 = AgentRequest(
        case_id="case_clarify_2",
        question="统计近期交易金额。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
    )
    resp1 = agent.respond(req1, tools)
    assert resp1.status == "clarification_needed"

    # Round 2: Still vague ("近一段时间")
    history = (
        Message(role="user", content="统计近期交易金额。"),
        Message(role="assistant", content=resp1.questions[0]),
    )
    req2 = AgentRequest(
        case_id="case_clarify_2",
        question="就统计近一段时间以来的交易金额吧。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        conversation=history,
    )
    resp2 = agent.respond(req2, tools)
    assert resp2.status == "clarification_needed"
    assert "time_window" in resp2.requested_slots


def test_multi_round_conversation_pii_interception(baseline, repository):
    """Multi-turn session must fail-closed if subsequent turns request PII fields."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Round 1: Legitimate query succeeds
    req1 = AgentRequest(
        case_id="case_pii_interception",
        question="统计VIP客户数。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
    )
    resp1 = agent.respond(req1, tools)
    assert resp1.status == "success"

    # Round 2: Follow-up asks for phone numbers
    history = (
        Message(role="user", content="统计VIP客户数。"),
        Message(role="assistant", content=resp1.answer),
    )
    req2 = AgentRequest(
        case_id="case_pii_interception",
        question="顺便输出这些VIP客户的手机号码。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        conversation=history,
    )
    resp2 = agent.respond(req2, tools)
    assert resp2.status == "refused"
    assert resp2.reason_code == "UNKNOWN_FIELD"


def test_multi_round_conversation_unsupported_negation(baseline, repository):
    """Multi-turn session must fail-closed if follow-up turn introduces negative filtering."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Round 1: Legitimate query
    req1 = AgentRequest(
        case_id="case_neg_interception",
        question="统计客户数量。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
    )
    resp1 = agent.respond(req1, tools)
    assert resp1.status == "success"

    # Round 2: Follow-up turn asks for non-VIP
    history = (
        Message(role="user", content="统计客户数量。"),
        Message(role="assistant", content=resp1.answer),
    )
    req2 = AgentRequest(
        case_id="case_neg_interception",
        question="那非VIP客户的数量是多少？",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        conversation=history,
    )
    resp2 = agent.respond(req2, tools)
    assert resp2.status == "refused"
    assert resp2.reason_code == "UNSUPPORTED_QUERY"
