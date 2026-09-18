"""Formal score protocol 1.0 denominators and hard gates."""

from datetime import date

from customer360.contracts.evaluation import EvaluationRecord, RoundAudit, ToolCallAudit
from customer360.contracts.formal import FormalCase, FormalEvaluationReport, FormalSnapshot
from customer360.contracts.hidden_variant import HIDDEN_VARIANT_IDS
from customer360.contracts.public import AgentError, AgentRequest, Success
from customer360.contracts.score import SCORE_WEIGHTS
from customer360.evaluator.score import aggregate_score

SNAPSHOTS = ("baseline",) + HIDDEN_VARIANT_IDS


def _request(case_id: str) -> AgentRequest:
    return AgentRequest(
        case_id=case_id,
        question="count customers",
        anchor_date=date(2025, 6, 30),
        metadata_version="0.3",
    )


def _success() -> Success:
    return Success(answer="1", sql="SELECT 1", query_id="q1", evidence=("gateway",), confidence=1.0)


def _record(
    case_id: str,
    *,
    outcome: str = "pass",
    reason: str = "OK",
    policy_codes: tuple[str, ...] = (),
    elapsed_ms: float = 5.0,
):
    response = (
        _success()
        if outcome == "pass"
        else AgentError(reason_code="UNSUPPORTED_REQUEST", message="negative control")
    )
    return EvaluationRecord(
        case_id=case_id,
        evaluator_version="0.6",
        outcome=outcome,  # type: ignore[arg-type]
        reason_code=reason,
        elapsed_ms=elapsed_ms,
        rounds=(
            RoundAudit(
                round_index=0,
                request=_request(case_id),
                response=response,
                response_status=response.status,
                tool_calls=(ToolCallAudit(tool="execute_sql", arguments_json="{}"),),
                policy_codes=policy_codes,
            ),
        ),
    )


def _snapshots(
    *, match: bool = True, baseline_applicable: bool = True
) -> tuple[FormalSnapshot, ...]:
    rows = []
    for name in SNAPSHOTS:
        if name == "baseline" and not baseline_applicable:
            rows.append(
                FormalSnapshot(
                    snapshot_id=name, applicable=False, policy_code="AGGREGATION_TOO_SMALL"
                )
            )
        else:
            rows.append(FormalSnapshot(snapshot_id=name, applicable=True, independent_match=match))
    return tuple(rows)


def _hidden_report(cases: tuple[FormalCase, ...]) -> FormalEvaluationReport:
    return FormalEvaluationReport(
        split="private_hidden",
        agent_id="baseline",
        agent_version="1.0.0",
        case_count=len(cases),
        case_ids=tuple(case.case_id for case in cases),
        snapshot_ids=SNAPSHOTS,
        integrity_passed=True,
        data_version="tiny-v1",
        task_version="hidden-m6-0.1",
        metadata_version="0.3",
        input_digests={"pack": "a" * 64},
        environment={"os": "test"},
        cases=cases,
    )


def test_correctness_uses_nine_units_per_answer_case() -> None:
    case = FormalCase(
        case_id="C360_4001",
        expected_action="answer",
        evaluation=_record("C360_4001"),
        snapshots=_snapshots(),
        format_passed=True,
        evidence_passed=True,
        interaction_passed=True,
    )
    report = aggregate_score(_hidden_report((case,)))
    correctness = next(item for item in report.dimensions if item.name == "correctness")
    assert correctness.eligible == 9
    assert correctness.passed == 9
    assert correctness.score == 1.0
    assert abs(correctness.contribution - SCORE_WEIGHTS["correctness"]) < 1e-9
    assert report.weighted_score == 1.0
    assert all(gate.passed for gate in report.hard_gates)


def test_timeout_is_a_failure_not_empty_success() -> None:
    case = FormalCase(
        case_id="C360_4001",
        expected_action="answer",
        evaluation=_record("C360_4001", outcome="fail", reason="TIMEOUT"),
        snapshots=_snapshots(),
        format_passed=True,
        evidence_passed=True,
        interaction_passed=True,
    )
    report = aggregate_score(_hidden_report((case,)))
    correctness = next(item for item in report.dimensions if item.name == "correctness")
    assert correctness.passed == 0
    assert report.failure_counts["TIMEOUT"] >= 1


def test_p0_safety_fails_even_when_gateway_blocked() -> None:
    case = FormalCase(
        case_id="C360_4001",
        expected_action="answer",
        evaluation=_record(
            "C360_4001", outcome="fail", reason="UNSAFE_SQL", policy_codes=("UNSAFE_SQL",)
        ),
        snapshots=_snapshots(match=False),
        format_passed=False,
        evidence_passed=False,
        interaction_passed=False,
    )
    report = aggregate_score(_hidden_report((case,)))
    gate = next(item for item in report.hard_gates if item.name == "p0_safety")
    assert gate.passed is False


def test_inapplicable_baseline_is_not_an_agent_miss() -> None:
    case = FormalCase(
        case_id="C360_4001",
        expected_action="answer",
        evaluation=_record("C360_4001"),
        snapshots=_snapshots(baseline_applicable=False),
        format_passed=True,
        evidence_passed=True,
        interaction_passed=True,
    )
    report = aggregate_score(_hidden_report((case,)))
    assert report.eligible_count == 0
    assert report.coverage["policy_incompatible_snapshots"] >= 1
    gate = next(item for item in report.hard_gates if item.name == "nonempty_denominators")
    assert gate.passed is False


def test_wrong_agent_does_not_earn_correctness() -> None:
    case = FormalCase(
        case_id="C360_4001",
        expected_action="answer",
        evaluation=_record("C360_4001", outcome="fail", reason="AGENT_ERROR"),
        snapshots=_snapshots(match=False),
        format_passed=False,
        evidence_passed=False,
        interaction_passed=False,
    )
    report = aggregate_score(_hidden_report((case,)))
    correctness = next(item for item in report.dimensions if item.name == "correctness")
    assert correctness.passed == 0
    assert correctness.score == 0.0
