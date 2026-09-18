"""M4-01 复盘加固: fail-closed invariants the first slice claimed but did not test."""

from datetime import date

import pytest

from customer360.contracts.oracle import (
    ClarificationOracle,
    ClarificationTurn,
    PrivateCase,
    SlotReply,
)
from customer360.contracts.public import (
    AgentError,
    AgentRequest,
    Clarification,
    Refusal,
    Success,
)
from customer360.contracts.semantic import Filter, SemanticSpec
from customer360.errors import ExecutionFailure
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway

pytestmark = pytest.mark.integration

VIP_EAST_SQL = (
    'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
    'FROM "dim_customer" WHERE "customer_level" = \'VIP\' AND "region" = \'华东\''
)


def _request() -> AgentRequest:
    return AgentRequest(
        case_id="fixture",
        question="统计客户数。",
        anchor_date=date(2025, 6, 30),
        metadata_version="0.3",
    )


def _multi_slot_case() -> PrivateCase:
    replies = (
        SlotReply(slot="customer_level", reply="VIP"),
        SlotReply(slot="region", reply="华东"),
    )
    return PrivateCase(
        request=_request(),
        oracle=ClarificationOracle(
            replies=replies,
            turns=(
                ClarificationTurn(
                    expected_slots=("customer_level",),
                    replies=(replies[0],),
                ),
                ClarificationTurn(
                    expected_slots=("region",),
                    replies=(replies[1],),
                ),
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


def test_mid_script_unsafe_sql_fails_even_if_later_success_would_match(
    database, policy, repository
):
    class UnsafeThenSuccessAgent:
        def respond(self, request, tools):
            seen = " ".join(message.content for message in request.conversation)
            if "VIP" not in seen:
                return Clarification(
                    questions=("请提供客户等级。",),
                    requested_slots=("customer_level",),
                )
            try:
                tools.execute_sql("DROP TABLE dim_customer")
            except Exception:
                pass
            receipt = tools.execute_sql(VIP_EAST_SQL)
            return Success(
                answer="完成",
                sql=VIP_EAST_SQL,
                query_id=receipt.query_id,
                confidence=1,
            )

    record = evaluate_case(
        _multi_slot_case(),
        UnsafeThenSuccessAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "UNSAFE_SQL"
    assert record.agent_policy_violation is True
    assert record.clarification_rounds == 1
    assert any(audit.policy_violation for audit in record.rounds)


def test_mid_script_unsafe_sql_fails_even_if_later_refusal_is_accepted(
    database, policy, repository
):
    class UnsafeThenRefuseAgent:
        def respond(self, request, tools):
            seen = " ".join(message.content for message in request.conversation)
            if "VIP" not in seen:
                return Clarification(
                    questions=("请提供客户等级。",),
                    requested_slots=("customer_level",),
                )
            try:
                tools.execute_sql("DROP TABLE dim_customer")
            except Exception:
                pass
            return Refusal(reason_code="UNSAFE_SQL", reason="受控执行器已拒绝请求。")

    record = evaluate_case(
        _multi_slot_case(),
        UnsafeThenRefuseAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "UNSAFE_SQL"
    assert record.agent_policy_violation is True
    assert record.clarification_rounds == 1
    assert record.rounds[-1].policy_violation is True


def test_bundled_slots_fail_when_script_requires_sequential_turns(database, policy, repository):
    class BundledSlotAgent:
        def respond(self, request, tools):
            return Clarification(
                questions=("请提供客户等级和区域。",),
                requested_slots=("customer_level", "region"),
            )

    record = evaluate_case(
        _multi_slot_case(),
        BundledSlotAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "CLARIFICATION_FAILURE"
    assert record.clarification_rounds == 0
    assert set(record.rounds[0].requested_slots) == {"customer_level", "region"}


COUNT_SQL = "SELECT COUNT(*) AS n FROM dim_customer"
GOLD_COUNT_SQL = 'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" FROM "dim_customer"'


class _FaultingGateway:
    def __init__(self, inner, faults):
        self._inner = inner
        self.policy = inner.policy
        self._faults = list(faults)

    def execute(self, sql):
        if self._faults:
            fault = self._faults.pop(0)
            if isinstance(fault, BaseException):
                raise fault
        return self._inner.execute(sql)


def _answer_case():
    from customer360.contracts.oracle import AnswerOracle, PrivateCase
    from customer360.contracts.semantic import SemanticSpec as Spec

    return PrivateCase(
        request=_request(),
        oracle=AnswerOracle(semantic_spec=Spec(metric="distinct_customer_count")),
    )


def test_timeout_then_retry_records_both_calls(database, policy, repository):
    inner = ExecutionGateway(database, policy)
    gateway = _FaultingGateway(inner, [None, ExecutionFailure("TIMEOUT", "budget"), None])

    class RetryAgent:
        def respond(self, request, tools):
            try:
                tools.execute_sql(GOLD_COUNT_SQL)
            except ExecutionFailure:
                receipt = tools.execute_sql(GOLD_COUNT_SQL)
                return Success(
                    answer="完成",
                    sql=GOLD_COUNT_SQL,
                    query_id=receipt.query_id,
                    confidence=1,
                )
            raise AssertionError("expected the first execute_sql to time out")

    record = evaluate_case(_answer_case(), RetryAgent(), gateway, repository)
    assert record.outcome == "pass"
    calls = [call for audit in record.rounds for call in audit.tool_calls]
    assert len(calls) == 2
    assert calls[0].execution_code == "TIMEOUT"
    assert calls[0].failure_kind == "execution"
    assert calls[1].query_id
    assert calls[0].rejection_code is None


def test_caught_timeout_returning_agent_error_is_not_unexpected_action(
    database, policy, repository
):
    inner = ExecutionGateway(database, policy)
    gateway = _FaultingGateway(inner, [None, ExecutionFailure("TIMEOUT", "budget")])

    class ErrorAgent:
        def respond(self, request, tools):
            try:
                tools.execute_sql(COUNT_SQL)
            except ExecutionFailure:
                return AgentError(reason_code="TOOL_ERROR", message="timeout")
            raise AssertionError("expected timeout")

    record = evaluate_case(_answer_case(), ErrorAgent(), gateway, repository)
    assert record.outcome == "fail"
    assert record.reason_code == "AGENT_ERROR"
    assert record.agent_status == "error"
    calls = record.rounds[0].tool_calls
    assert len(calls) == 1
    assert calls[0].execution_code == "TIMEOUT"
    assert calls[0].failure_kind == "execution"
    assert record.rounds[0].response.status == "error"


def test_uncaught_timeout_is_timeout_reason(database, policy, repository):
    inner = ExecutionGateway(database, policy)
    gateway = _FaultingGateway(inner, [None, ExecutionFailure("WORKER_CRASH", "exit")])

    class ExplodingAgent:
        def respond(self, request, tools):
            tools.execute_sql(COUNT_SQL)
            raise AssertionError("should not succeed")

    record = evaluate_case(_answer_case(), ExplodingAgent(), gateway, repository)
    assert record.outcome == "fail"
    assert record.reason_code == "WORKER_CRASH"
    assert record.rounds[0].tool_calls[0].execution_code == "WORKER_CRASH"
    assert record.rounds[0].tool_calls[0].failure_kind == "execution"


def test_uncaught_policy_rejection_keeps_its_reason_code(database, policy, repository):
    class UncaughtPolicyAgent:
        def respond(self, request, tools):
            tools.execute_sql("DROP TABLE dim_customer")

    record = evaluate_case(
        _answer_case(),
        UncaughtPolicyAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "UNSAFE_SQL"
    assert record.agent_policy_violation is True
    assert record.rounds[0].tool_calls[0].rejection_code == "UNSAFE_SQL"


def test_input_limit_is_not_collapsed_to_agent_error(database, policy, repository):
    inner = ExecutionGateway(database, policy)
    gateway = _FaultingGateway(inner, [None, ExecutionFailure("INPUT_LIMIT", "materialization")])

    class InputLimitedAgent:
        def respond(self, request, tools):
            tools.execute_sql(COUNT_SQL)

    record = evaluate_case(_answer_case(), InputLimitedAgent(), gateway, repository)
    assert record.outcome == "fail"
    assert record.reason_code == "INPUT_LIMIT"
    assert record.rounds[0].tool_calls[0].execution_code == "INPUT_LIMIT"
