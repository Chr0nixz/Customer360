import json
from time import perf_counter
from typing import Any

from pydantic import TypeAdapter, ValidationError

from customer360.agent.protocol import Agent
from customer360.contracts.evaluation import (
    FROZEN_FAIL_REASON_CODES,
    EvaluationRecord,
    ReceiptAudit,
    RoundAudit,
    ToolCallAudit,
)
from customer360.contracts.oracle import (
    AnswerOracle,
    ClarificationOracle,
    PrivateCase,
    RefusalOracle,
)
from customer360.contracts.public import (
    AgentError,
    AgentResponse,
    Clarification,
    Message,
    Refusal,
    Success,
)
from customer360.contracts.semantic import RollingWindow
from customer360.errors import C360Error, ExecutionFailure, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.tasks.compiler import compile_semantic


def _json_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, default=str)


def evaluate_case(
    case: PrivateCase, agent: Agent, gateway: ExecutionGateway, repository: MetadataRepository
) -> EvaluationRecord:
    """Trusted multi-round evaluator with a deterministic hidden slot script."""
    started = perf_counter()
    session = ToolSession(gateway, repository)
    audits: list[RoundAudit] = []
    clarification_rounds = 0

    def mode() -> str:
        if isinstance(case.oracle, ClarificationOracle):
            if len(case.oracle.replay_script()) > 1:
                return "scripted_multi_round"
            return "scripted_clarification"
        if isinstance(case.oracle, RefusalOracle):
            return "single_snapshot_refusal"
        return "single_snapshot_smoke"

    def finish(outcome: str, reason: str, status: str | None = None) -> EvaluationRecord:
        return EvaluationRecord(
            case_id=case.request.case_id,
            outcome=outcome,  # type: ignore[arg-type]
            reason_code=reason,
            agent_status=status,
            agent_policy_violation=bool(session.rejections),
            clarification_rounds=clarification_rounds,
            mode=mode(),  # type: ignore[arg-type]
            rounds=tuple(audits),
            elapsed_ms=(perf_counter() - started) * 1000,
            task_version=case.task_version,
            metadata_version=case.request.metadata_version,
            policy_role=gateway.policy.role,
        )

    def capture_round(request, response, start_calls: int, start_rejections: int) -> RoundAudit:
        new_calls = session.calls[start_calls:]
        new_rejections = tuple(session.rejections[start_rejections:])
        tool_calls = []
        receipts = []
        for call in new_calls:
            tool_calls.append(
                ToolCallAudit(
                    tool=call["tool"],
                    arguments_json=_json_arguments(call["arguments"]),
                    rejected=bool(call.get("rejected")),
                    rejection_code=call.get("rejection_code"),
                    execution_code=call.get("execution_code"),
                    failure_kind=call.get("failure_kind"),
                    query_id=call.get("query_id"),
                )
            )
            if call.get("query_id") and not call.get("rejected") and not call.get("execution_code"):
                receipts.append(
                    ReceiptAudit(
                        query_id=call["query_id"],
                        sql=str(call["sql"]),
                        truncated=bool(call.get("truncated")),
                        row_count=int(call.get("row_count") or 0),
                        result=call.get("result"),
                    )
                )
        requested_slots = ()
        questions = ()
        status = None
        if isinstance(response, Clarification):
            requested_slots = response.requested_slots
            questions = response.questions
            status = response.status
        elif response is not None:
            status = response.status
        return RoundAudit(
            round_index=len(audits),
            request=request,
            response_status=status,
            response=response,
            requested_slots=requested_slots,
            questions=questions,
            tool_calls=tuple(tool_calls),
            receipts=tuple(receipts),
            policy_violation=bool(new_rejections),
            policy_codes=new_rejections,
        )

    def invoke(request):
        start_calls = len(session.calls)
        start_rejections = len(session.rejections)
        try:
            response = TypeAdapter(AgentResponse).validate_python(agent.respond(request, session))
        except ValidationError:
            audits.append(capture_round(request, None, start_calls, start_rejections))
            return finish("fail", "INVALID_AGENT_RESPONSE")
        except QueryRejected as exc:
            audits.append(capture_round(request, None, start_calls, start_rejections))
            reason = exc.code if exc.code in FROZEN_FAIL_REASON_CODES else "AGENT_ERROR"
            return finish("fail", reason)
        except ExecutionFailure as exc:
            audits.append(capture_round(request, None, start_calls, start_rejections))
            return finish(
                "fail",
                exc.code if exc.code in FROZEN_FAIL_REASON_CODES else "AGENT_ERROR",
            )
        except Exception:
            audits.append(capture_round(request, None, start_calls, start_rejections))
            return finish("fail", "AGENT_ERROR")
        audits.append(capture_round(request, response, start_calls, start_rejections))
        if session.rejections:
            return finish("fail", session.rejections[0], response.status)
        if isinstance(response, AgentError):
            return finish("fail", "AGENT_ERROR", response.status)
        return response

    if case.request.metadata_version != repository.metrics.metrics_version:
        return finish("error", "METADATA_VERSION_MISMATCH")
    if isinstance(case.oracle, ClarificationOracle):
        window = case.oracle.completed_spec.time_window
        if isinstance(window, RollingWindow) and window.anchor_date != case.request.anchor_date:
            return finish("error", "ORACLE_ANCHOR_MISMATCH")
        conversation = list(case.request.conversation)
        current = case.request
        for turn in case.oracle.replay_script():
            response = invoke(current)
            if isinstance(response, EvaluationRecord):
                return response
            if not isinstance(response, Clarification):
                return finish("fail", "CLARIFICATION_FAILURE", response.status)
            if set(response.requested_slots) != set(turn.expected_slots):
                return finish("fail", "CLARIFICATION_FAILURE", response.status)
            conversation.append(Message(role="assistant", content=" ".join(response.questions)))
            conversation.extend(Message(role="user", content=reply.reply) for reply in turn.replies)
            current = case.request.model_copy(update={"conversation": tuple(conversation)})
            clarification_rounds += 1
        final = invoke(current)
        if isinstance(final, EvaluationRecord):
            return final
        if not isinstance(final, Success):
            return finish("fail", "CLARIFICATION_FAILURE", final.status)
        try:
            execution = session.lookup_execution(final.query_id)
        except KeyError:
            return finish("fail", "UNVERIFIED_RESULT", final.status)
        try:
            compiled = compile_semantic(case.oracle.completed_spec, repository)
            reference = gateway.execute(compiled.sql)
        except QueryRejected as exc:
            if exc.code == "AGGREGATION_TOO_SMALL":
                return finish("error", "POLICY_INCOMPATIBLE", final.status)
            return finish("error", "ORACLE_EXECUTION_ERROR", final.status)
        except (C360Error, KeyError):
            return finish("error", "ORACLE_EXECUTION_ERROR", final.status)
        if execution.sql != final.sql:
            return finish("fail", "SQL_RECEIPT_MISMATCH", final.status)
        if not compare_results(execution.result, reference.result):
            return finish("fail", "RESULT_MISMATCH", final.status)
        return finish("pass", "CLARIFICATION_OK", final.status)
    if isinstance(case.oracle, RefusalOracle):
        response = invoke(case.request)
        if isinstance(response, EvaluationRecord):
            return response
        if not isinstance(response, Refusal):
            return finish("fail", "REFUSAL_FAILURE", response.status)
        if response.reason_code not in case.oracle.accepted_reason_codes:
            return finish("fail", "REFUSAL_FAILURE", response.status)
        return finish("pass", "REFUSAL_OK", response.status)

    assert isinstance(case.oracle, AnswerOracle)
    window = case.oracle.semantic_spec.time_window
    if isinstance(window, RollingWindow) and window.anchor_date != case.request.anchor_date:
        return finish("error", "ORACLE_ANCHOR_MISMATCH")
    try:
        compiled = compile_semantic(case.oracle.semantic_spec, repository)
        # The reference receipt never enters the Agent's session/result registry.
        reference = gateway.execute(compiled.sql)
    except QueryRejected as exc:
        if exc.code == "AGGREGATION_TOO_SMALL":
            return finish("error", "POLICY_INCOMPATIBLE")
        return finish("error", "ORACLE_EXECUTION_ERROR")
    except (C360Error, KeyError):
        return finish("error", "ORACLE_EXECUTION_ERROR")
    response = invoke(case.request)
    if isinstance(response, EvaluationRecord):
        return response
    if not isinstance(response, Success):
        return finish("fail", "UNEXPECTED_ACTION", response.status)
    try:
        execution = session.lookup_execution(response.query_id)
    except KeyError:
        return finish("fail", "UNVERIFIED_RESULT", response.status)
    if execution.sql != response.sql:
        return finish("fail", "SQL_RECEIPT_MISMATCH", response.status)
    if not compare_results(execution.result, reference.result):
        return finish("fail", "RESULT_MISMATCH", response.status)
    return finish("pass", "OK", response.status)
