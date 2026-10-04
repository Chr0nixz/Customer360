"""Stage E / M5 official local baseline. TemplateAgent remains a protocol driver."""

import ast
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.agent.adapter import LocalDeterministicAdapter, NetworkModelAdapter
from customer360.agent.baseline import BaselineAgent
from customer360.agent.template import TemplateAgent
from customer360.cli import app
from customer360.contracts.oracle import PrivateCase
from customer360.contracts.public import AgentRequest
from customer360.evaluator.matrix import resolve_eval_agent
from customer360.evaluator.runner import evaluate_case
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.variant import tiny_eval_policy

ROOT = Path(__file__).parents[1]
ANCHOR = date(2025, 6, 30)
runner = CliRunner()


def _denied_imports(path: Path) -> None:
    denied = (
        "customer360.contracts.oracle",
        "customer360.contracts.semantic",
        "customer360.tasks",
        "customer360.evaluator",
        "customer360.runtime",
        "duckdb",
        "subprocess",
        "httpx",
        "openai",
        "urllib",
        "requests",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(module == item or module.startswith(f"{item}.") for item in denied)
        if isinstance(node, ast.Import):
            assert all(not item.name.startswith(denied) for item in node.names)


def test_baseline_modules_have_no_gold_or_network_imports():
    root = ROOT / "src/customer360/agent"
    for path in root.glob("*.py"):
        _denied_imports(path)


def test_resolve_agent_distinguishes_template_and_official_baseline():
    baseline = resolve_eval_agent("baseline")
    template = resolve_eval_agent("template")
    assert isinstance(baseline, BaselineAgent)
    assert isinstance(template, TemplateAgent)
    assert not isinstance(baseline, TemplateAgent)
    with pytest.raises(ValueError, match="external model network is not permitted"):
        resolve_eval_agent("gpt")
    with pytest.raises(ValueError, match="unknown agent"):
        resolve_eval_agent("mystery")


def test_network_adapter_is_fail_closed():
    with pytest.raises(ValueError, match="external model network is not permitted"):
        NetworkModelAdapter()
    with pytest.raises(ValueError, match="fail-closed"):
        NetworkModelAdapter(network_enabled=True)


def test_local_adapter_records_cache_and_never_uses_network():
    adapter = LocalDeterministicAdapter()
    from customer360.agent.adapter import AdapterPacket

    packet = AdapterPacket(
        question="统计VIP客户数。",
        conversation=(),
        anchor_date=ANCHOR,
        metrics=(
            {
                "metric_name": "distinct_customer_count",
                "business_name": "客户数",
                "unit": "count",
                "time_semantics": "none",
                "example_questions": ["统计VIP客户数。"],
                "source_table": "dim_customer",
                "allowed_group_dimensions": [],
            },
        ),
        columns=(),
        joins=(),
        glossary=(),
    )
    intent, first = adapter.complete(packet)
    _, second = adapter.complete(packet)
    assert intent.action == "answer"
    assert intent.metric_name == "distinct_customer_count"
    assert first.network_used is False
    assert first.cache_hit is False
    assert first.retry_count == 0
    assert first.parameters.temperature == 0
    assert second.cache_hit is True
    assert second.network_used is False


def _run_case(agent, repository, gateway, item):
    return evaluate_case(
        PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.question,
                anchor_date=ANCHOR,
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=item.oracle(),
            task_version=item.task_version,
        ),
        agent,
        gateway,
        repository,
    )


def test_official_baseline_completes_human_pack(baseline, repository):
    catalog = load_human_cases()
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    outcomes = {}
    for item in catalog.cases:
        record = _run_case(agent, repository, gateway, item)
        outcomes[item.case_id] = (record.outcome, record.reason_code)
        assert item.split == "dev"
    assert outcomes["C360_0019"] == ("pass", "CLARIFICATION_OK")
    assert outcomes["C360_0020"] == ("pass", "REFUSAL_OK")
    assert outcomes["C360_0012"] == ("error", "POLICY_INCOMPATIBLE")
    failed = {
        case_id: result
        for case_id, result in outcomes.items()
        if result[0] != "pass" and case_id != "C360_0012"
    }
    assert failed == {}
    assert any(call.network_used is False for call in agent.calls)
    assert all(call.network_used is False for call in agent.calls)
    tools_used = [
        call.tool
        for record in [_run_case(BaselineAgent(), repository, gateway, catalog.cases[0])]
        for audit in record.rounds
        for call in audit.tool_calls
    ]
    assert "search_metrics" in tools_used
    assert "get_metric_definition" in tools_used


def test_official_baseline_uses_tools_not_gold_sql(baseline, repository):
    catalog = load_human_cases()
    item = next(case for case in catalog.cases if case.case_id == "C360_0001")
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    record = _run_case(agent, repository, gateway, item)
    assert record.outcome == "pass"
    tools = [call.tool for audit in record.rounds for call in audit.tool_calls]
    assert "search_metrics" in tools
    assert "get_metric_definition" in tools
    assert "execute_sql" in tools
    success = record.rounds[-1].response
    assert success is not None and success.status == "success"
    assert "official_baseline" in success.evidence
    assert "template_agent" not in success.evidence


def test_official_baseline_handles_rewrite_and_rejects_month_alias(baseline, repository):
    catalog = load_human_cases()
    item = next(case for case in catalog.cases if case.case_id == "C360_0001")
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    rewritten = evaluate_case(
        PrivateCase(
            request=AgentRequest(
                case_id=item.case_id,
                question=item.rewrites[0],
                anchor_date=ANCHOR,
                metadata_version=repository.metrics.metrics_version,
            ),
            oracle=item.oracle(),
            task_version=item.task_version,
        ),
        agent,
        gateway,
        repository,
    )
    assert rewritten.outcome == "pass"
    months = agent.respond(
        AgentRequest(
            case_id="probe",
            question="统计最近三个月成功交易笔数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        ToolSession(gateway, repository),
    )
    assert months.status == "clarification_needed"
    assert "time_window" in months.requested_slots


def test_official_baseline_does_not_emit_unsafe_sql(baseline, repository):
    from customer360.agent.sqlgen import sql_is_unsafe

    assert sql_is_unsafe("DROP TABLE dim_customer")
    assert sql_is_unsafe("SELECT 1; DELETE FROM dim_customer")
    catalog = load_human_cases()
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    for item in catalog.cases:
        record = _run_case(agent, repository, gateway, item)
        for audit in record.rounds:
            for receipt in audit.receipts:
                assert not sql_is_unsafe(receipt.sql)
            for call in audit.tool_calls:
                if call.tool == "execute_sql":
                    assert "drop" not in call.arguments_json.lower()
                    assert "delete" not in call.arguments_json.lower()


def test_run_case_cli_baseline(baseline, tmp_path):
    output = tmp_path / "run-case-0001"
    result = runner.invoke(
        app,
        [
            "run-case",
            "--case-id",
            "C360_0001",
            "--dataset",
            str(baseline),
            "--output",
            str(output),
            "--agent",
            "baseline",
        ],
    )
    assert result.exit_code == 0, result.output
    summary = (output / "summary.json").read_text(encoding="utf-8")
    assert '"scoring_applied":false' in summary.replace(" ", "")
    assert '"agent_id":"baseline"' in summary.replace(" ", "")
    assert (output / "adapter_calls.json").is_file()
    calls = (output / "adapter_calls.json").read_text(encoding="utf-8")
    assert "local_deterministic" in calls
    assert '"network_used":false' in calls.replace(" ", "")


def test_help_lists_run_case():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run-case" in result.output
    assert "evaluate" in result.output


def test_baseline_extended_filters_and_join_combinations(baseline, repository):
    """Verify Agent B expanded filters: risk, gender, tx type, channel, flow type, and joins."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    tools = ToolSession(gateway, repository)

    # 1. Risk level filter on distinct_customer_count
    resp = agent.respond(
        AgentRequest(
            case_id="probe_risk",
            question="统计低风险客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"risk_level\" = 'low'" in resp.sql

    # 2. Gender and standard level combined filter
    resp = agent.respond(
        AgentRequest(
            case_id="probe_gender_level",
            question="统计女性标准等级客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"gender\" = 'F'" in resp.sql
    assert "\"customer_level\" = 'standard'" in resp.sql

    # 3. Customer status (dormant)
    resp = agent.respond(
        AgentRequest(
            case_id="probe_dormant",
            question="统计休眠客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"status\" = 'dormant'" in resp.sql

    # 4. Transaction type (sell) on successful_transaction_count
    resp = agent.respond(
        AgentRequest(
            case_id="probe_tx_sell",
            question="统计截至2025年6月30日近90天卖出交易笔数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"transaction_type\" = 'sell'" in resp.sql

    # 5. Channel (branch) on successful_transaction_count
    resp = agent.respond(
        AgentRequest(
            case_id="probe_tx_branch",
            question="统计截至2025年6月30日近90天网点渠道成功交易笔数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"channel\" = 'branch'" in resp.sql

    # 6. Cash flow filter (flow_type = in, channel = bank)
    resp = agent.respond(
        AgentRequest(
            case_id="probe_cash_flow",
            question="统计截至2025年6月30日近90天银行渠道流入资金流笔数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "\"channel\" = 'bank'" in resp.sql
    assert "\"flow_type\" = 'in'" in resp.sql

    # 7. Join query with trade filters (App trade and customer level)
    resp = agent.respond(
        AgentRequest(
            case_id="probe_join_app",
            question="统计VIP客户中截至2025年6月30日近90天有成功App交易的去重客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert 'JOIN "fact_transaction"' in resp.sql
    assert '"c"."customer_level" = \'VIP\'' in resp.sql
    assert '"t"."status" = \'success\'' in resp.sql
    assert '"t"."channel" = \'app\'' in resp.sql

    # 8. Join query with trade transaction_type (buy trade and risk level)
    resp = agent.respond(
        AgentRequest(
            case_id="probe_join_buy",
            question="统计低风险客户中截至2025年6月30日近90天有成功买入交易的去重客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert 'JOIN "fact_transaction"' in resp.sql
    assert '"c"."risk_level" = \'low\'' in resp.sql
    assert '"t"."status" = \'success\'' in resp.sql
    assert '"t"."transaction_type" = \'buy\'' in resp.sql

    # 9. PII unknown field refusal remains fail-closed
    resp = agent.respond(
        AgentRequest(
            case_id="probe_pii",
            question="统计手机号以138开头的客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNKNOWN_FIELD"


def test_baseline_hardening_negation_join_distinction_and_conflict(baseline, repository):
    """Hardening checks: negation interception, join distinction, and conflict."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    agent = BaselineAgent()
    tools = ToolSession(gateway, repository)

    # 1. Distinction: Single-table app transaction count should not be treated as Join
    resp = agent.respond(
        AgentRequest(
            case_id="probe_app_tx_count",
            question="统计截至2025年6月30日近90天成功App交易笔数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "success"
    assert "JOIN" not in resp.sql
    assert "fact_transaction" in resp.sql

    # 2. Negation safety: Non-VIP must be refused fail-closed instead of positive match
    resp = agent.respond(
        AgentRequest(
            case_id="probe_neg_vip",
            question="统计非VIP客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"

    # 3. Negation safety: Occupation not null must be refused instead of matching is_null
    resp = agent.respond(
        AgentRequest(
            case_id="probe_neg_occ",
            question="统计职业不为空的客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"

    # 4. Negation safety: Non-low risk must be refused
    resp = agent.respond(
        AgentRequest(
            case_id="probe_neg_risk",
            question="统计非低风险客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"

    # 5. Mutually exclusive conflict: Multiple regions in single question
    resp = agent.respond(
        AgentRequest(
            case_id="probe_conflict_region",
            question="统计华东和华南的客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"

    # 6. Mutually exclusive conflict: Both VIP and standard customer level
    resp = agent.respond(
        AgentRequest(
            case_id="probe_conflict_level",
            question="统计VIP和标准等级客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"

    # 7. Mutually exclusive conflict: Both male and female
    resp = agent.respond(
        AgentRequest(
            case_id="probe_conflict_gender",
            question="统计男性和女性客户数。",
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
        ),
        tools,
    )
    assert resp.status == "refused"
    assert resp.reason_code == "UNSUPPORTED_QUERY"
