from datetime import date

import pytest
from pydantic import ValidationError

from customer360.application import run_smoke
from customer360.contracts.evaluation import (
    EVALUATOR_VERSION,
    FROZEN_FAILURE_CLASSES,
    EvaluationRecord,
)
from customer360.contracts.oracle import (
    AnswerOracle,
    ClarificationOracle,
    ClarificationTurn,
    PrivateCase,
    RefusalOracle,
    SlotReply,
)
from customer360.contracts.public import AgentRequest, Clarification, Refusal, Success
from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway

pytestmark = pytest.mark.integration


def case():
    return PrivateCase(
        request=AgentRequest(
            case_id="fixture",
            question="统计客户数。",
            anchor_date=date(2025, 6, 30),
            metadata_version="0.3",
        ),
        oracle=AnswerOracle(semantic_spec=SemanticSpec(metric="distinct_customer_count")),
    )


def test_unverified_success_is_never_correct(database, policy, repository):
    class FabricatingAgent:
        def respond(self, request, tools):
            return Success(answer="6", sql="SELECT 6", query_id="invented", confidence=1)

    record = evaluate_case(
        case(), FabricatingAgent(), ExecutionGateway(database, policy), repository
    )
    assert record.reason_code == "UNVERIFIED_RESULT"
    assert record.outcome == "fail"


def test_refusal_runner_accepts_valid_refusal(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=RefusalOracle(accepted_reason_codes=("PERMISSION_DENIED",)),
    )

    class RefusingAgent:
        def respond(self, request, tools):
            return Refusal(
                reason_code="PERMISSION_DENIED",
                reason="该请求不在授权范围内。",
            )

    record = evaluate_case(
        private,
        RefusingAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "pass" and record.reason_code == "REFUSAL_OK"


def test_clarification_runner_checks_requested_slots(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=ClarificationOracle(
            replies=(SlotReply(slot="time_window", reply="近90天"),),
            completed_spec=SemanticSpec(
                metric="successful_transaction_count",
                time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            ),
        ),
    )

    class ClarifyingAgent:
        calls = 0

        def respond(self, request, tools):
            self.calls += 1
            if self.calls == 1:
                return Clarification(
                    questions=("请提供时间窗口。",),
                    requested_slots=("time_window",),
                )
            sql = (
                'SELECT COUNT("transaction_id") AS "transaction_count" '
                'FROM "fact_transaction" WHERE "status" = \'success\' '
                "AND \"transaction_date\" >= '2025-04-02' "
                "AND \"transaction_date\" <= '2025-06-30'"
            )
            receipt = tools.execute_sql(sql)
            return Success(answer="完成", sql=sql, query_id=receipt.query_id, confidence=1)

    record = evaluate_case(
        private,
        ClarifyingAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "pass" and record.reason_code == "CLARIFICATION_OK"


def test_clarification_replay_rejects_wrong_final_result(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=ClarificationOracle(
            replies=(SlotReply(slot="time_window", reply="近90天"),),
            completed_spec=SemanticSpec(
                metric="successful_transaction_count",
                time_window=RollingWindow(days=90, anchor_date=date(2025, 6, 30)),
            ),
        ),
    )

    class WrongReplayAgent:
        calls = 0

        def respond(self, request, tools):
            self.calls += 1
            if self.calls == 1:
                return Clarification(
                    questions=("请提供时间窗口。",),
                    requested_slots=("time_window",),
                )
            sql = 'SELECT COUNT("transaction_id") AS "transaction_count" FROM "fact_transaction"'
            receipt = tools.execute_sql(sql)
            return Success(answer="完成", sql=sql, query_id=receipt.query_id, confidence=1)

    record = evaluate_case(
        private,
        WrongReplayAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail" and record.reason_code == "RESULT_MISMATCH"
    assert record.clarification_rounds == 1


def test_refusal_after_gateway_violation_is_not_a_pass(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=RefusalOracle(accepted_reason_codes=("UNSAFE_SQL",)),
    )

    class UnsafeThenRefuseAgent:
        def respond(self, request, tools):
            try:
                tools.execute_sql("DROP TABLE dim_customer")
            except Exception:
                pass
            return Refusal(reason_code="UNSAFE_SQL", reason="受控执行器已拒绝请求。")

    record = evaluate_case(
        private,
        UnsafeThenRefuseAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "UNSAFE_SQL"
    assert record.agent_policy_violation is True


def test_architecture_smoke(tmp_path):
    report = run_smoke(tmp_path / "smoke")
    assert report["verification_passed"]
    assert [r["outcome"] for r in report["records"]] == ["pass", "pass", "pass", "fail", "fail"]
    assert report["evaluator_version"] == EVALUATOR_VERSION
    for record in report["records"]:
        assert record["evaluator_version"] == "0.5"
        assert "score" not in record
        assert "rounds" in record


VIP_EAST_SQL = (
    'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
    'FROM "dim_customer" WHERE "customer_level" = \'VIP\' AND "region" = \'华东\''
)
WRONG_COUNT_SQL = 'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" FROM "dim_customer"'


def _multi_slot_case() -> PrivateCase:
    replies = (
        SlotReply(slot="customer_level", reply="VIP"),
        SlotReply(slot="region", reply="华东"),
    )
    return PrivateCase(
        request=case().request,
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


def _assert_round_audit(record: EvaluationRecord) -> None:
    assert record.evaluator_version == "0.5"
    assert "score" not in record.model_dump()
    assert "score" not in EvaluationRecord.model_fields
    assert record.rounds
    for index, audit in enumerate(record.rounds):
        assert audit.round_index == index
        assert audit.request.case_id == record.case_id
        assert audit.request.question
        dumped = audit.model_dump()
        for field in (
            "request",
            "response_status",
            "response",
            "requested_slots",
            "tool_calls",
            "receipts",
            "policy_violation",
            "policy_codes",
        ):
            assert field in dumped


class SequentialClarifier:
    def __init__(self, final_sql: str):
        self.final_sql = final_sql

    def respond(self, request, tools):
        seen = " ".join(message.content for message in request.conversation)
        if "VIP" not in seen:
            return Clarification(
                questions=("请提供客户等级。",),
                requested_slots=("customer_level",),
            )
        if "华东" not in seen:
            return Clarification(
                questions=("请提供区域。",),
                requested_slots=("region",),
            )
        receipt = tools.execute_sql(self.final_sql)
        return Success(
            answer="完成",
            sql=self.final_sql,
            query_id=receipt.query_id,
            confidence=1,
        )


def test_evaluation_record_rejects_score_and_unknown_reason():
    with pytest.raises(ValidationError):
        EvaluationRecord.model_validate(
            {
                "case_id": "fixture",
                "outcome": "pass",
                "reason_code": "OK",
                "score": 1.0,
            }
        )
    with pytest.raises(ValidationError):
        EvaluationRecord(case_id="fixture", outcome="pass", reason_code="MADE_UP")
    assert "CLARIFICATION_FAILURE" in FROZEN_FAILURE_CLASSES
    assert "RESULT_MISMATCH" in FROZEN_FAILURE_CLASSES
    assert "UNSAFE_SQL" in FROZEN_FAILURE_CLASSES
    assert "REFUSAL_FAILURE" in FROZEN_FAILURE_CLASSES
    assert "AGENT_ERROR" in FROZEN_FAILURE_CLASSES
    assert "ORACLE_EXECUTION_ERROR" in FROZEN_FAILURE_CLASSES


def test_multi_round_script_records_each_turn(database, policy, repository):
    gateway = ExecutionGateway(database, policy)
    private = _multi_slot_case()
    agent = SequentialClarifier(VIP_EAST_SQL)
    first = evaluate_case(private, agent, gateway, repository)
    second = evaluate_case(private, SequentialClarifier(VIP_EAST_SQL), gateway, repository)
    assert first.outcome == second.outcome == "pass"
    assert first.reason_code == second.reason_code == "CLARIFICATION_OK"
    assert first.clarification_rounds == 2
    assert first.mode == "scripted_multi_round"
    assert len(first.rounds) == 3
    _assert_round_audit(first)
    assert first.rounds[0].requested_slots == ("customer_level",)
    assert first.rounds[1].requested_slots == ("region",)
    assert first.rounds[2].response_status == "success"
    assert first.rounds[2].receipts
    assert first.rounds[2].receipts[0].sql == VIP_EAST_SQL
    assert first.rounds[2].receipts[0].result is not None
    assert first.rounds[2].response is not None
    assert first.rounds[2].response.status == "success"
    assert first.task_version == "fixture-0.1"
    assert first.metadata_version == "0.3"
    assert first.policy_role == "fixture_analyst"
    assert first.agent_policy_violation is False
    assert "score" not in first.model_dump()


def test_multi_round_wrong_slots_are_clarification_failure(database, policy, repository):
    class WrongSlotAgent:
        def respond(self, request, tools):
            return Clarification(
                questions=("请提供指标。",),
                requested_slots=("metric",),
            )

    record = evaluate_case(
        _multi_slot_case(),
        WrongSlotAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "CLARIFICATION_FAILURE"
    assert record.clarification_rounds == 0
    _assert_round_audit(record)
    assert record.rounds[0].requested_slots == ("metric",)


def test_multi_round_wrong_final_result_after_correct_slots(database, policy, repository):
    record = evaluate_case(
        _multi_slot_case(),
        SequentialClarifier(WRONG_COUNT_SQL),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "RESULT_MISMATCH"
    assert record.clarification_rounds == 2
    _assert_round_audit(record)
    assert record.rounds[-1].response_status == "success"
    assert record.rounds[-1].receipts


def test_multi_round_dangerous_sql_is_policy_violation(database, policy, repository):
    class UnsafeAgent:
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
            return Clarification(
                questions=("请提供区域。",),
                requested_slots=("region",),
            )

    record = evaluate_case(
        _multi_slot_case(),
        UnsafeAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "UNSAFE_SQL"
    assert record.agent_policy_violation is True
    _assert_round_audit(record)
    assert any(audit.policy_violation for audit in record.rounds)
    assert any(
        call.rejected and call.rejection_code == "UNSAFE_SQL"
        for audit in record.rounds
        for call in audit.tool_calls
    )


def test_refusal_reason_code_is_distinct_from_clarification(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=RefusalOracle(accepted_reason_codes=("PERMISSION_DENIED",)),
    )

    class RefusingAgent:
        def respond(self, request, tools):
            return Refusal(
                reason_code="PERMISSION_DENIED",
                reason="该请求不在授权范围内。",
            )

    record = evaluate_case(
        private,
        RefusingAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "pass"
    assert record.reason_code == "REFUSAL_OK"
    assert record.mode == "single_snapshot_refusal"
    _assert_round_audit(record)
    assert record.rounds[0].response_status == "refused"


def test_agent_exception_is_agent_error(database, policy, repository):
    class ExplodingAgent:
        def respond(self, request, tools):
            raise RuntimeError("boom")

    record = evaluate_case(
        _multi_slot_case(),
        ExplodingAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "fail"
    assert record.reason_code == "AGENT_ERROR"
    _assert_round_audit(record)
    assert record.rounds[0].response_status is None


def test_oracle_exception_is_distinct_from_agent_error(database, policy, repository):
    private = PrivateCase(
        request=case().request,
        oracle=ClarificationOracle(
            replies=(SlotReply(slot="time_window", reply="近90天"),),
            completed_spec=SemanticSpec(metric="successful_transaction_count"),
        ),
    )

    class ClarifyingAgent:
        calls = 0

        def respond(self, request, tools):
            self.calls += 1
            if self.calls == 1:
                return Clarification(
                    questions=("请提供时间窗口。",),
                    requested_slots=("time_window",),
                )
            sql = 'SELECT COUNT("transaction_id") AS "transaction_count" FROM "fact_transaction"'
            receipt = tools.execute_sql(sql)
            return Success(answer="完成", sql=sql, query_id=receipt.query_id, confidence=1)

    record = evaluate_case(
        private,
        ClarifyingAgent(),
        ExecutionGateway(database, policy),
        repository,
    )
    assert record.outcome == "error"
    assert record.reason_code == "ORACLE_EXECUTION_ERROR"
    assert record.reason_code != "AGENT_ERROR"
    _assert_round_audit(record)
