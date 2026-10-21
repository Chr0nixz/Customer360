"""Test v1.4 planner expansion: Top-K, Composite Joins, HAVING, and Derived Ratios."""

from __future__ import annotations

from datetime import date

from customer360.agent.adapter import AdapterPacket, LocalDeterministicAdapter
from customer360.agent.sqlgen import PlanFilter, QueryPlan, render_sql
from customer360.metadata.metrics import MetadataRepository


def test_topk_planning_and_rendering():
    planner = LocalDeterministicAdapter()
    repo = MetadataRepository()
    packet = AdapterPacket(
        question="按地区统计客户人数，按客户数降序排列取前3名。",
        conversation=(),
        anchor_date=date(2025, 6, 30),
        metrics=tuple(m.model_dump(mode="json") for m in repo.metrics.metrics),
        columns=(),
        joins=(),
        glossary=(),
    )
    intent, _ = planner.complete(packet)
    assert intent.action == "answer"
    assert intent.group_by == ("region",)
    assert intent.limit == 3
    assert intent.order_direction == "desc"

    plan = QueryPlan(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="customer_count",
        group_by=intent.group_by,
        limit=intent.limit,
        order_by=intent.order_by,
        order_direction=intent.order_direction,
    )
    sql = render_sql(plan)
    assert 'GROUP BY "region"' in sql
    assert 'ORDER BY "customer_count" DESC, "region" ASC' in sql
    assert "LIMIT 3" in sql


def test_having_planning_and_rendering():
    planner = LocalDeterministicAdapter()
    repo = MetadataRepository()
    packet = AdapterPacket(
        question="按客户等级统计客户人数大于50的各等级及人数。",
        conversation=(),
        anchor_date=date(2025, 6, 30),
        metrics=tuple(m.model_dump(mode="json") for m in repo.metrics.metrics),
        columns=(),
        joins=(),
        glossary=(),
    )
    intent, _ = planner.complete(packet)
    assert intent.action == "answer"
    assert intent.group_by == ("customer_level",)
    assert intent.having_operator == "gt"
    assert intent.having_threshold == 50

    plan = QueryPlan(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="distinct_customer_count",
        group_by=intent.group_by,
        having_operator=intent.having_operator,
        having_threshold=intent.having_threshold,
    )
    sql = render_sql(plan)
    assert 'HAVING COUNT(DISTINCT "customer_id") > 50' in sql


def test_ratio_planning_and_rendering():
    planner = LocalDeterministicAdapter()
    repo = MetadataRepository()
    packet = AdapterPacket(
        question="按地区统计近30天笔均交易金额。",
        conversation=(),
        anchor_date=date(2025, 6, 30),
        metrics=tuple(m.model_dump(mode="json") for m in repo.metrics.metrics),
        columns=(),
        joins=(),
        glossary=(),
    )
    intent, _ = planner.complete(packet)
    assert intent.action == "answer"
    assert intent.ratio_alias == "avg_ticket"

    plan = QueryPlan(
        source_table="fact_transaction",
        operation="ratio",
        measure_column="amount",
        output_column="avg_ticket",
        ratio_alias=intent.ratio_alias,
        group_by=("channel",),
    )
    sql = render_sql(plan)
    assert "ROUND(CAST(SUM(" in sql
    assert "NULLIF(COUNT(" in sql
    assert 'AS "avg_ticket"' in sql


def test_composite_join_planning_and_rendering():
    planner = LocalDeterministicAdapter()
    repo = MetadataRepository()
    joins = tuple(j.model_dump(mode="json") for j in repo.join_paths.paths)
    packet = AdapterPacket(
        question="统计华东地区近30天有成功交易且持有产品的去重客户数。",
        conversation=(),
        anchor_date=date(2025, 6, 30),
        metrics=tuple(m.model_dump(mode="json") for m in repo.metrics.metrics),
        columns=(),
        joins=joins,
        glossary=(),
    )
    intent, _ = planner.complete(packet)
    assert intent.action == "answer"
    assert intent.join_path == "customer_transactions_and_holdings"

    plan = QueryPlan(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="distinct_customer_count",
        join_path=intent.join_path,
        predicates=(
            PlanFilter(field="region", operator="eq", values=("华东",), alias="c"),
            PlanFilter(field="status", operator="eq", values=("success",), alias="t"),
            PlanFilter(field="holding_status", operator="eq", values=("active",), alias="h"),
        ),
    )
    sql = render_sql(plan)
    assert 'FROM "dim_customer" AS "c"' in sql
    assert 'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id"' in sql
    assert 'JOIN "fact_holding" AS "h" ON "c"."customer_id" = "h"."customer_id"' in sql
    assert '"c"."region" = \'华东\'' in sql
    assert '"t"."status" = \'success\'' in sql
    assert '"h"."holding_status" = \'active\'' in sql
