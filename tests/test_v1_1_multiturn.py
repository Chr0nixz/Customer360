"""v1.1 Multi-turn clarification, distractor resistance, and over-clarification tests."""

from datetime import date
from pathlib import Path

from customer360.agent.baseline import BaselineAgent
from customer360.contracts.oracle import (
    ClarificationOracle,
    ClarificationTurn,
    PrivateCase,
    SlotReply,
)
from customer360.contracts.public import AgentRequest, Clarification, Message, Success
from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.tasks.variant import tiny_eval_policy

ANCHOR = date(2025, 6, 30)


def test_baseline_counterfactual_distractor_resistance(baseline: Path, repository) -> None:
    """User provides the required slot value along with irrelevant distractor."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Turn 1: Vague query
    req1 = AgentRequest(
        case_id="case_v1_1_distractor",
        question="统计近期交易金额。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        protocol_version="1.1",
    )
    resp1 = agent.respond(req1, tools)
    assert resp1.status == "clarification_needed"
    assert "time_window" in resp1.requested_slots

    # Turn 2: User reply contains target slot ("近90天") AND distracting narrative
    history = (
        Message(role="user", content="统计近期交易金额。", turn=1),
        Message(role="assistant", content=resp1.questions[0], turn=1),
    )
    req2 = AgentRequest(
        case_id="case_v1_1_distractor",
        question="请统计近90天的交易金额，顺便说明一下我们下周准备搬迁办公室，另外假定系统有500万海外账户。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        protocol_version="1.1",
        conversation=history,
    )
    resp2 = agent.respond(req2, tools)
    assert resp2.status == "success"
    assert "2025-04-02" in resp2.sql
    assert "2025-06-30" in resp2.sql
    assert "fact_transaction" in resp2.sql


def test_evaluator_scripted_turn_with_distractor(baseline: Path, repository) -> None:
    """The trusted multi-round evaluator correctly replays turns with distractor attachments."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    replies = (
        SlotReply(
            slot="time_window",
            reply="截至2025-06-30的近90个自然日",
            distractor="另外顺便提一句今天天气真不错，部门刚刚开完例会",
            distractor_role="noise",
        ),
    )
    case = PrivateCase(
        request=AgentRequest(
            case_id="case_eval_distractor",
            question="统计近期成功交易金额。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
            protocol_version="1.1",
        ),
        oracle=ClarificationOracle(
            replies=replies,
            completed_spec=SemanticSpec(
                metric="successful_transaction_amount",
                time_window=RollingWindow(days=90, anchor_date=ANCHOR),
            ),
        ),
    )
    agent = BaselineAgent()
    record = evaluate_case(case, agent, gateway, repository)
    assert record.outcome == "pass"
    assert record.reason_code == "CLARIFICATION_OK"
    assert record.clarification_rounds == 1
    # Check that the user message in round 1 captured the distractor
    user_msgs = [m for m in record.rounds[1].request.conversation if m.role == "user"]
    assert any("部门刚刚开完例会" in m.content for m in user_msgs)


def test_evaluator_detects_over_clarification(baseline: Path, repository) -> None:
    """Agent that persistently asks for already provided slots must fail."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())

    class OverClarifyingAgent:
        def respond(self, request: AgentRequest, tools: ToolSession):
            # Always ask for time_window regardless of whether it's already provided
            return Clarification(
                questions=("请确认时间窗口？",),
                requested_slots=("time_window",),
            )

    replies = (SlotReply(slot="time_window", reply="截至2025-06-30的近90个自然日"),)
    case = PrivateCase(
        request=AgentRequest(
            case_id="case_over_clarify",
            question="统计近期成功交易金额。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        oracle=ClarificationOracle(
            replies=replies,
            completed_spec=SemanticSpec(
                metric="successful_transaction_amount",
                time_window=RollingWindow(days=90, anchor_date=ANCHOR),
            ),
        ),
    )
    record = evaluate_case(case, OverClarifyingAgent(), gateway, repository)
    assert record.outcome == "fail"
    assert record.reason_code == "CLARIFICATION_FAILURE"
    assert record.agent_status == "clarification_needed"


def test_multi_round_stepwise_convergence(baseline: Path, repository) -> None:
    """Step-by-step 2-turn scripted clarification with BaselineAgent."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())

    class TwoTurnClarifier:
        """Driver that asks customer_level first, then region, then executes."""

        def respond(self, request: AgentRequest, tools: ToolSession):
            seen = " ".join(m.content for m in request.conversation)
            if "VIP" not in seen:
                return Clarification(
                    questions=("请提供客户等级。",),
                    requested_slots=("customer_level",),
                )
            if "华东" not in seen:
                return Clarification(
                    questions=("请提供客户所在区域。",),
                    requested_slots=("region",),
                )
            sql = (
                'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
                'FROM "dim_customer" WHERE "customer_level" = \'VIP\' AND "region" = \'华东\''
            )
            receipt = tools.execute_sql(sql)
            return Success(
                answer="统计完成",
                sql=sql,
                query_id=receipt.query_id,
                confidence=1.0,
            )

    replies = (
        SlotReply(slot="customer_level", reply="VIP"),
        SlotReply(
            slot="region",
            reply="华东",
            distractor="（包括上海、杭州等城市）",
            distractor_role="noise",
        ),
    )
    case = PrivateCase(
        request=AgentRequest(
            case_id="case_two_turn",
            question="统计客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
            protocol_version="1.1",
        ),
        oracle=ClarificationOracle(
            replies=replies,
            turns=(
                ClarificationTurn(expected_slots=("customer_level",), replies=(replies[0],)),
                ClarificationTurn(expected_slots=("region",), replies=(replies[1],)),
            ),
            completed_spec=SemanticSpec(
                metric="distinct_customer_count",
                filters=(
                    Filter(field="customer_level", operator="eq", values=("VIP",)),
                    Filter(field="region", operator="eq", values=("华东",)),
                ),
            ),
        ),
    )
    record = evaluate_case(case, TwoTurnClarifier(), gateway, repository)
    assert (record.outcome, record.reason_code) == ("pass", "CLARIFICATION_OK")
    assert record.clarification_rounds == 2
    assert record.mode == "scripted_multi_round"
