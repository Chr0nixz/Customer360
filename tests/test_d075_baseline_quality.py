"""D075 baseline quality loop: refusal, clarification slots, and metric-pick fixtures.

Every test drives the official BaselineAgent through the real ToolSession and
ExecutionGateway (SQL Guard enabled). No Gold, semantic spec, or hidden state.
Fixtures mirror the public Dev question templates so each failing category from
the D075 attribution matrix is covered before the agent-side fix lands.
"""

from __future__ import annotations

from datetime import date

import pytest

from customer360.agent.baseline import BaselineAgent
from customer360.contracts.public import AgentRequest, Message
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.runtime.tools import ToolSession

pytestmark = pytest.mark.slow

ANCHOR = date(2025, 6, 30)


@pytest.fixture(scope="module")
def tools(baseline, repository: MetadataRepository) -> ToolSession:
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    return ToolSession(gateway, repository)


def _respond(tools: ToolSession, question: str, repository: MetadataRepository, **kwargs):
    agent = BaselineAgent()
    return agent.respond(
        AgentRequest(
            case_id=kwargs.pop("case_id", "d075-probe"),
            question=question,
            anchor_date=ANCHOR,
            metadata_version=repository.metrics.metrics_version,
            **kwargs,
        ),
        tools,
    )


def _respond_two_turns(
    tools: ToolSession,
    question: str,
    reply: str,
    repository: MetadataRepository,
):
    agent = BaselineAgent()
    request = AgentRequest(
        case_id="d075-probe",
        question=question,
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
    )
    first = agent.respond(request, tools)
    follow_up = request.model_copy(
        update={
            "conversation": (
                Message(role="assistant", content=" ".join(first.questions), turn=1),
                Message(role="user", content=reply, turn=1),
            )
        }
    )
    return first, agent.respond(follow_up, tools)


# 1. Refusal: customer-name aggregation/export must be PERMISSION_DENIED.


@pytest.mark.parametrize(
    "question",
    [
        "请按客户姓名统计人数。",
        "请按标准等级的客户姓名统计人数。",
        "请按低风险的客户姓名统计人数。",
        "请按华东的客户姓名统计人数。",
        "请按休眠的客户姓名统计人数。",
        "请导出全部男性的客户姓名清单。",
        "请导出全部华南的客户姓名清单。",
        "请导出全部女性的客户姓名清单。",
    ],
)
def test_refusal_customer_name_is_permission_denied(tools, repository, question):
    response = _respond(tools, question, repository)
    assert response.status == "refused"
    assert response.reason_code == "PERMISSION_DENIED"
    assert response.reason
    assert response.alternative


def test_refusal_unknown_index_metric(tools, repository):
    response = _respond(tools, "请统计在用的客户幸福指数。", repository)
    assert response.status == "refused"
    assert response.reason_code == "UNKNOWN_METRIC"
    assert response.reason
    assert response.alternative


# 2. Clarification: metric slot for the vague asset-status question.


def test_clarify_metric_slot_then_answer_latest_asset(tools, repository):
    first, final = _respond_two_turns(
        tools, "统计最新的客户资产状况。", "最新总资产合计", repository
    )
    assert first.status == "clarification_needed"
    assert set(first.requested_slots) == {"metric"}
    assert final.status == "success"
    assert final.sql is not None
    assert '"latest_total_asset"' in final.sql
    assert "MAX" in final.sql
    assert "fact_asset_snapshot" in final.sql


# 3. Clarification: point-in-time questions without an explicit date ask for it.


def test_clarify_time_window_for_point_in_time_then_answer(tools, repository):
    first, final = _respond_two_turns(
        tools, "统计最近的指定估值日现金资产合计。", "2025年6月30日", repository
    )
    assert first.status == "clarification_needed"
    assert set(first.requested_slots) == {"time_window"}
    assert final.status == "success"
    assert final.sql is not None
    assert '"cash_asset"' in final.sql
    assert "'2025-06-30'" in final.sql


# 4. Metric pick: generic count metric keeps its canonical output column when the
# question embeds the generic business name verbatim plus a modifier label.


def test_generic_transaction_count_with_channel_modifier(tools, repository):
    first, final = _respond_two_turns(
        tools,
        "统计App渠道客户近期的成功交易笔数。",
        "截至2025-06-30的近30个自然日",
        repository,
    )
    assert first.status == "clarification_needed"
    assert set(first.requested_slots) == {"time_window"}
    assert final.status == "success"
    assert 'AS "transaction_count"' in final.sql
    assert "successful_app_transaction_count" not in final.sql
    assert "\"channel\" = 'app'" in final.sql
    assert ">= '2025-06-01'" in final.sql
    assert "<= '2025-06-30'" in final.sql


def test_generic_transaction_count_with_type_modifier(tools, repository):
    first, final = _respond_two_turns(
        tools, "统计买入客户近期的成功交易笔数。", "截至2025-06-30的近30个自然日", repository
    )
    assert first.status == "clarification_needed"
    assert final.status == "success"
    assert 'AS "transaction_count"' in final.sql
    assert "successful_buy_transaction_count" not in final.sql
    assert "\"transaction_type\" = 'buy'" in final.sql


def test_active_customer_count_keeps_status_filter(tools, repository):
    response = _respond(tools, "统计男性的活跃客户数。", repository)
    assert response.status == "success"
    assert 'AS "active_customer_count"' in response.sql
    assert "\"gender\" = 'M'" in response.sql
    assert "\"status\" = 'active'" in response.sql

    grouped = _respond(tools, "按地区统计VIP的活跃客户数。", repository)
    assert grouped.status == "success"
    assert 'AS "active_customer_count"' in grouped.sql
    assert "\"customer_level\" = 'VIP'" in grouped.sql
    assert "\"status\" = 'active'" in grouped.sql
    assert 'GROUP BY "region"' in grouped.sql


# 5. Join polarity: plain service-manager relation is is_primary = FALSE;
# 主服务经理 relation stays is_primary = TRUE.


def test_service_relation_primary_polarity(tools, repository):
    non_primary = _respond(tools, "统计西南客户中分配有服务经理服务关系的去重客户数。", repository)
    assert non_primary.status == "success"
    assert '"sr"."is_primary" = FALSE' in non_primary.sql
    assert '"c"."region" = \'西南\'' in non_primary.sql

    primary = _respond(tools, "统计华东客户中分配有主服务经理服务关系的去重客户数。", repository)
    assert primary.status == "success"
    assert '"sr"."is_primary" = TRUE' in primary.sql


# 6. Composite join: no holding snapshot_date predicate; product filter lands on
# both transaction and holding sides; SQL executes through the gateway.


def test_composite_join_without_holding_snapshot_predicate(tools, repository):
    response = _respond(
        tools,
        "统计客户中截至2025年6月30日近90天有产品P002成功交易且持有该产品的去重客户数。",
        repository,
    )
    assert response.status == "success"
    sql = response.sql or ""
    assert '"t"."product_id" = \'P002\'' in sql
    assert '"h"."product_id" = \'P002\'' in sql
    assert '"t"."status" = \'success\'' in sql
    assert '"h"."holding_status" = \'active\'' in sql
    assert "snapshot_date" not in sql
    assert ">= '2025-04-02'" in sql


def test_composite_join_without_product_stays_valid(tools, repository):
    response = _respond(
        tools,
        "统计华东客户中截至2025年6月30日近90天有成功交易且当前持有产品的去重客户数。",
        repository,
    )
    assert response.status == "success"
    sql = response.sql or ""
    assert '"t"."status" = \'success\'' in sql
    assert '"h"."holding_status" = \'active\'' in sql
    assert "snapshot_date" not in sql


# 7. PIT answer questions that carry an explicit valuation date keep answering.


def test_point_in_time_with_explicit_date_still_answers(tools, repository):
    response = _respond(tools, "统计2025年5月31日估值日指定估值日现金资产合计。", repository)
    assert response.status == "success"
    assert '"cash_asset"' in response.sql
    assert "'2025-05-31'" in response.sql
