"""Interactive single-case debugging and diagnostic inspection.

Provides detailed trajectory tracing, SQL AST Guard audit analysis,
and execution result diff comparison against ground truth oracles.
"""

from datetime import date
from pathlib import Path
from typing import Any

from customer360.agent.protocol import Agent
from customer360.contracts.oracle import (
    AnswerOracle,
    ClarificationOracle,
    PrivateCase,
    RefusalOracle,
)
from customer360.contracts.public import AgentRequest
from customer360.evaluator.compare import compare_results
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.variant import load_baseline_tiny, tiny_eval_policy

FIXTURE_ANCHOR = date(2025, 6, 30)


def debug_single_case(
    case_id: str,
    agent: Agent,
    dataset_dir: Path,
    *,
    oracles: Path | None = None,
) -> dict[str, Any]:
    """Execute a single case and return structured diagnostic details."""
    catalog = load_human_cases(oracles=oracles)
    item = next((case for case in catalog.cases if case.case_id == case_id), None)
    if item is None:
        raise ValueError(f"Unknown case_id: {case_id}")

    database, _manifest = load_baseline_tiny(dataset_dir)
    repository = MetadataRepository()
    gateway = ExecutionGateway(database, tiny_eval_policy())

    oracle = item.oracle()
    private_case = PrivateCase(
        request=AgentRequest(
            case_id=item.case_id,
            question=item.question,
            anchor_date=FIXTURE_ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        oracle=oracle,
        task_version=item.task_version,
    )

    # Compile reference SQL if answer or clarification
    reference_sql = None
    reference_result = None
    expected_reasons = ()
    if isinstance(oracle, AnswerOracle):
        try:
            compiled = compile_semantic(oracle.semantic_spec, repository)
            reference_sql = compiled.sql
            ref_receipt = gateway.execute(reference_sql)
            reference_result = ref_receipt.result.model_dump(mode="json")
        except Exception:
            reference_sql = None
            reference_result = None
    elif isinstance(oracle, ClarificationOracle):
        try:
            compiled = compile_semantic(oracle.completed_spec, repository)
            reference_sql = compiled.sql
            ref_receipt = gateway.execute(reference_sql)
            reference_result = ref_receipt.result.model_dump(mode="json")
        except Exception:
            reference_sql = None
            reference_result = None
    elif isinstance(oracle, RefusalOracle):
        expected_reasons = oracle.accepted_reason_codes

    record = evaluate_case(private_case, agent, gateway, repository)

    # Collect agent's last executed receipt if available
    agent_receipt = None
    for r in reversed(record.rounds):
        if r.receipts:
            agent_receipt = r.receipts[-1].model_dump(mode="json")
            break

    # Diff analysis
    diff_status = "N/A"
    diff_details: dict[str, Any] = {}
    if reference_result and agent_receipt and agent_receipt.get("result"):
        from customer360.contracts.public import QueryResult

        try:
            agent_qr = QueryResult.model_validate(agent_receipt["result"])
            ref_qr = QueryResult.model_validate(reference_result)
            matched = compare_results(agent_qr, ref_qr)
            diff_status = "MATCH" if matched else "MISMATCH"
            diff_details = {
                "agent_row_count": len(agent_qr.rows),
                "reference_row_count": len(ref_qr.rows),
                "agent_columns": [c.name for c in agent_qr.columns],
                "reference_columns": [c.name for c in ref_qr.columns],
                "sample_agent_row": agent_qr.rows[0].model_dump(mode="json")
                if agent_qr.rows
                else None,
                "sample_reference_row": ref_qr.rows[0].model_dump(mode="json")
                if ref_qr.rows
                else None,
            }
        except Exception as exc:
            diff_status = "DIFF_ERROR"
            diff_details = {"error": str(exc)}

    return {
        "case_id": case_id,
        "question": item.question,
        "split": item.split,
        "expected_action": oracle.expected_action,
        "expected_reasons": expected_reasons,
        "outcome": record.outcome,
        "reason_code": record.reason_code,
        "agent_status": record.agent_status,
        "agent_policy_violation": record.agent_policy_violation,
        "elapsed_ms": record.elapsed_ms,
        "rounds_count": len(record.rounds),
        "reference_sql": reference_sql,
        "agent_receipt": agent_receipt,
        "diff_status": diff_status,
        "diff_details": diff_details,
        "record": record.model_dump(mode="json"),
    }


def render_debug_view(info: dict[str, Any]) -> str:
    """Format debug diagnostics into a readable terminal output."""
    lines = [
        "=" * 70,
        f"  CUSTOMER360 CASE DIAGNOSTICS: {info['case_id']}",
        "=" * 70,
        f"Question         : {info['question']}",
        f"Split            : {info['split']}",
        f"Expected Action  : {info['expected_action']}",
        f"Evaluation Result: {info['outcome'].upper()} (Reason: {info['reason_code']})",
        f"Agent Status     : {info['agent_status']}",
        f"Policy Violation : {info['agent_policy_violation']}",
        f"Elapsed Time     : {info['elapsed_ms']:.2f} ms",
        "-" * 70,
        "GROUND TRUTH REFERENCE:",
        f"  Reference SQL    : {info.get('reference_sql') or '(None)'}",
        f"  Expected Reasons : {list(info.get('expected_reasons', [])) or '(None)'}",
        "-" * 70,
        "AGENT EXECUTION & TOOL TRAJECTORY:",
    ]

    record = info.get("record", {})
    rounds = record.get("rounds", [])
    for idx, rnd in enumerate(rounds):
        lines.append(f"  [Round {idx + 1}]")
        tool_calls = rnd.get("tool_calls", [])
        if not tool_calls:
            lines.append("    (No tool calls)")
        for tc in tool_calls:
            if tc.get("rejected"):
                status_str = f"REJECTED [{tc.get('rejection_code')}]"
            else:
                status_str = "SUCCESS"
            lines.append(f"    - Tool: {tc.get('tool')} -> {status_str}")
            lines.append(f"      Args: {tc.get('arguments_json')}")
        resp = rnd.get("response")
        if resp:
            lines.append(f"    Response Status: {rnd.get('response_status')}")

    lines.extend(
        [
            "-" * 70,
            "RESULT DIFF COMPARISON:",
            f"  Status        : {info.get('diff_status')}",
        ]
    )

    diff = info.get("diff_details", {})
    if diff:
        lines.extend(
            [
                f"  Agent Rows    : {diff.get('agent_row_count')}",
                f"  Reference Rows: {diff.get('reference_row_count')}",
                f"  Agent Columns : {diff.get('agent_columns')}",
                f"  Ref Columns   : {diff.get('reference_columns')}",
                f"  Sample Agent  : {diff.get('sample_agent_row')}",
                f"  Sample Ref    : {diff.get('sample_reference_row')}",
            ]
        )

    lines.append("=" * 70)
    return "\n".join(lines)
