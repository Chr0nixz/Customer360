from datetime import date
from pathlib import Path

from customer360.agent.protocol import Agent
from customer360.agent.submission import SqlSubmissionAgent
from customer360.artifacts import digest, write_json_new, write_jsonl_new
from customer360.contracts.evaluation import EVALUATOR_VERSION
from customer360.contracts.execution import AccessPolicy, SqlLimits, TableGrant
from customer360.contracts.oracle import AnswerOracle, PrivateCase
from customer360.contracts.public import AgentRequest
from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.synth.fixture import build_public_fixture
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.variant import load_baseline_tiny, tiny_eval_policy

FIXTURE_ANCHOR = date(2025, 6, 30)


def fixture_policy(customer_ids: tuple[str, ...] | None = None) -> AccessPolicy:
    return AccessPolicy(
        role="fixture_analyst",
        customer_ids=customer_ids
        if customer_ids is not None
        else tuple(f"C{i:03d}" for i in range(1, 7)),
        grants=(
            TableGrant(
                table="dim_customer",
                columns=(
                    "customer_id",
                    "customer_level",
                    "gender",
                    "risk_level",
                    "region",
                    "city",
                    "occupation",
                    "registration_date",
                    "status",
                ),
            ),
            TableGrant(
                table="fact_transaction",
                columns=(
                    "customer_id",
                    "transaction_id",
                    "transaction_date",
                    "product_id",
                    "transaction_type",
                    "amount",
                    "quantity",
                    "fee",
                    "status",
                    "channel",
                ),
            ),
            TableGrant(
                table="fact_asset_snapshot",
                columns=(
                    "snapshot_date",
                    "customer_id",
                    "total_asset",
                    "cash_asset",
                    "investment_asset",
                    "liability",
                    "net_asset",
                ),
            ),
        ),
    )


def run_smoke(output: Path, seed: int = 42, limits: SqlLimits | None = None) -> dict:
    """Public conformance test, not train/dev/test scoring."""
    output.mkdir(parents=True, exist_ok=False)
    database = output / "fixture.duckdb"
    manifest = build_public_fixture(database, seed)
    write_json_new(output / "manifest.json", manifest)
    repository = MetadataRepository()
    gateway = ExecutionGateway(database, fixture_policy(), limits)
    examples = [
        (
            "smoke_customers",
            "统计VIP客户数。",
            SemanticSpec(
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
            ),
            "SELECT COUNT(DISTINCT customer_id) AS customer_count "
            "FROM dim_customer WHERE customer_level = 'VIP'",
            "pass",
            "OK",
        ),
        (
            "smoke_transactions",
            "统计截至2025年6月30日近90天成功交易笔数。",
            SemanticSpec(
                metric="successful_transaction_count",
                time_window=RollingWindow(days=90, anchor_date=FIXTURE_ANCHOR),
            ),
            "SELECT COUNT(transaction_id) AS transaction_count FROM fact_transaction "
            "WHERE status = 'success' AND transaction_date >= '2025-04-02' "
            "AND transaction_date <= '2025-06-30'",
            "pass",
            "OK",
        ),
        (
            "smoke_amount",
            "统计截至2025年6月30日近90天成功交易金额。",
            SemanticSpec(
                metric="successful_transaction_amount",
                time_window=RollingWindow(days=90, anchor_date=FIXTURE_ANCHOR),
            ),
            "SELECT SUM(amount) AS transaction_amount FROM fact_transaction "
            "WHERE status = 'success' AND transaction_date >= '2025-04-02' "
            "AND transaction_date <= '2025-06-30'",
            "pass",
            "OK",
        ),
        (
            "smoke_wrong_sql",
            "统计VIP客户数。",
            SemanticSpec(
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
            ),
            "SELECT COUNT(*) AS customer_count FROM dim_customer",
            "fail",
            "RESULT_MISMATCH",
        ),
        (
            "smoke_unsafe_sql",
            "统计客户数。",
            SemanticSpec(metric="distinct_customer_count"),
            "DROP TABLE dim_customer",
            "fail",
            "UNSAFE_SQL",
        ),
    ]
    records, expectations = [], []
    for case_id, question, spec, sql, outcome, reason in examples:
        case = PrivateCase(
            request=AgentRequest(
                case_id=case_id,
                question=question,
                anchor_date=FIXTURE_ANCHOR,
                metadata_version="0.3",
            ),
            oracle=AnswerOracle(semantic_spec=spec),
        )
        record = evaluate_case(case, SqlSubmissionAgent(sql), gateway, repository)
        records.append(record.model_dump(mode="json"))
        expectations.append(record.outcome == outcome and record.reason_code == reason)
    report = {
        "protocol_version": "0.1",
        "evaluator_version": EVALUATOR_VERSION,
        "agent_version": "sql-submission-conformance-0.1",
        "dataset_manifest_hash": digest(manifest),
        "mode": "public_architecture_smoke",
        "verification_passed": all(expectations),
        "checks": len(records),
        "expected_passes": 3,
        "expected_failures": 2,
        "records": records,
        "limitations": [
            "Not a Tiny dataset, official baseline, private evaluation or benchmark score",
            "Answer-only; no joins, grouping, multi-turn or drift execution",
            "SQL worker is killable; arbitrary Python Agent plugins are NOT sandboxed",
            "DB scan count is unavailable; scoped materialization cap is "
            f"{(limits or SqlLimits()).max_input_rows} rows",
        ],
    }
    write_json_new(output / "report.json", report)
    write_jsonl_new(output / "records.jsonl", records)
    return report


def run_single_case(
    dataset_dir: Path,
    output: Path,
    case_id: str,
    agent: Agent,
    *,
    agent_id: str,
    oracles: Path | None = None,
) -> dict:
    """Run one human-pack case through the evaluator. Not an official score."""
    catalog = load_human_cases(oracles=oracles)
    item = next((case for case in catalog.cases if case.case_id == case_id), None)
    if item is None:
        raise ValueError(f"unknown case_id: {case_id}")
    if item.split != "dev":
        raise ValueError("run-case refuses to relabel C360_0001-0020 away from split=dev")
    database, _manifest = load_baseline_tiny(dataset_dir)
    repository = MetadataRepository()
    gateway = ExecutionGateway(database, tiny_eval_policy())
    record = evaluate_case(
        PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.question,
                anchor_date=FIXTURE_ANCHOR,
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=item.oracle(),
            task_version=item.task_version,
        ),
        agent,
        gateway,
        repository,
    )
    adapter_calls = [call.model_dump(mode="json") for call in getattr(agent, "calls", ())]
    summary = {
        "case_id": case_id,
        "agent_id": agent_id,
        "split": item.split,
        "outcome": record.outcome,
        "reason_code": record.reason_code,
        "agent_status": record.agent_status,
        "scoring_applied": False,
        "network_used": any(call.get("network_used") for call in adapter_calls),
        "adapter_calls": len(adapter_calls),
        "limitations": (
            "Not an official score; ROADMAP section 8 weights are not applied",
            "TemplateAgent is not the official baseline",
        ),
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json_new(output / "record.json", record.model_dump(mode="json"))
    write_json_new(output / "summary.json", summary)
    if adapter_calls:
        write_json_new(output / "adapter_calls.json", adapter_calls)
    return summary
