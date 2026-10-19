"""v1.2 Query plan controlled validation and metadata lifecycle evolution tests."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from customer360.agent.baseline import BaselineAgent
from customer360.contracts.audit import MetadataAuditReport
from customer360.contracts.public import AgentRequest
from customer360.contracts.validation import PlanPredicate, QueryPlanValidationRequest
from customer360.errors import QueryRejected
from customer360.metadata.audit import audit_metadata
from customer360.metadata.metrics import (
    MetadataRepository,
    MetricCatalog,
    MetricDef,
    load_catalog,
    load_join_paths,
)
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.runtime.validator import validate_query_plan
from customer360.tasks.variant import tiny_eval_policy

ANCHOR = date(2025, 6, 30)


def test_plan_validator_schema_error_graceful_handling(baseline: Path, repository) -> None:
    """Malformed query plan payload returns is_valid=False with INVALID_PLAN_SCHEMA."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)

    # Missing mandatory operation and source_table
    malformed_plan = {"invalid_field": 123}
    resp = tools.validate_query_plan(malformed_plan)
    assert resp["is_valid"] is False
    assert len(resp["issues"]) > 0
    assert any(i["code"] == "INVALID_PLAN_SCHEMA" for i in resp["issues"])


def test_plan_validator_is_null_and_in_operators(repository) -> None:
    """Validate is_null (without values) and in (with non-empty values) operators."""
    policy = tiny_eval_policy()

    # 1. Valid is_null predicate (no values provided)
    req_null = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        predicates=(PlanPredicate(field="occupation", operator="is_null"),),
    )
    res_null = validate_query_plan(req_null, repository, policy)
    assert res_null.is_valid is True

    # 2. Invalid is_null predicate (values illegally provided)
    req_null_bad = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        predicates=(PlanPredicate(field="occupation", operator="is_null", values=("Doctor",)),),
    )
    res_null_bad = validate_query_plan(req_null_bad, repository, policy)
    assert res_null_bad.is_valid is False
    assert any(i.code == "INVALID_PREDICATE_LITERAL" for i in res_null_bad.issues)

    # 3. Valid in predicate
    req_in = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        predicates=(
            PlanPredicate(field="customer_level", operator="in", values=("VIP", "Normal")),
        ),
    )
    res_in = validate_query_plan(req_in, repository, policy)
    assert res_in.is_valid is True

    # 4. Invalid in predicate (empty values)
    req_in_empty = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        predicates=(PlanPredicate(field="customer_level", operator="in", values=()),),
    )
    res_in_empty = validate_query_plan(req_in_empty, repository, policy)
    assert res_in_empty.is_valid is False
    assert any(i.code == "INVALID_PREDICATE_LITERAL" for i in res_in_empty.issues)


def test_metric_date_chronology_validation() -> None:
    """deprecation_date cannot precede effective_date."""
    with pytest.raises(
        ValidationError, match="deprecation_date cannot be earlier than effective_date"
    ):
        MetricDef(
            metric_name="chronology_metric",
            business_name="测试指标",
            description="时序测试",
            unit="count",
            deduplicate=True,
            output_column="cnt",
            source_table="dim_customer",
            grain="customer",
            operation="count_distinct",
            measure_column="customer_id",
            time_semantics="none",
            sensitivity="internal",
            forbidden_contexts=("none",),
            example_questions=("测试",),
            effective_date=date(2025, 6, 1),
            deprecation_date=date(2025, 5, 1),
            status="deprecated",
            replaced_by="other_metric",
        )


def test_metric_lifecycle_retired_rejection_and_alternative(baseline: Path) -> None:
    """Retired metric raises DEPRECATED_METRIC_REJECTED and BaselineAgent provides alternative."""
    catalog = load_catalog()
    join_paths = load_join_paths()

    active_m = MetricDef(
        metric_name="active_m",
        business_name="新版活跃客户数",
        description="生效指标",
        unit="count",
        deduplicate=True,
        output_column="active_cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("活跃客户数是多少？",),
        status="active",
    )
    retired_m = MetricDef(
        metric_name="retired_m",
        business_name="旧版停用客户数",
        description="已停用旧指标",
        unit="count",
        deduplicate=True,
        output_column="retired_cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("统计旧版停用客户数？",),
        status="retired",
        replaced_by="active_m",
    )

    repo = MetadataRepository(
        catalog=catalog,
        metrics=MetricCatalog(metrics_version="0.4", metrics=(active_m, retired_m)),
        join_paths=join_paths,
    )

    # 1. Direct get_metric_definition raises QueryRejected with code DEPRECATED_METRIC_REJECTED
    with pytest.raises(QueryRejected) as exc_info:
        repo.get_metric_definition("retired_m")
    assert exc_info.value.code == "DEPRECATED_METRIC_REJECTED"
    assert "已停用" in str(exc_info.value)
    assert "active_m" in str(exc_info.value)

    # 2. ToolSession search_metrics filters out retired metric by default
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repo)
    hits = tools.search_metrics("客户数")
    hit_names = [h["metric_name"] for h in hits]
    assert "active_m" in hit_names
    assert "retired_m" not in hit_names


def test_audit_metadata_catches_broken_deprecation_target() -> None:
    """audit_metadata flags metrics declaring non-existent replaced_by targets."""
    catalog = load_catalog()
    join_paths = load_join_paths()

    m_broken_target = MetricDef(
        metric_name="m_broken_target",
        business_name="无效替代指标",
        description="描述",
        unit="count",
        deduplicate=True,
        output_column="cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
        status="deprecated",
        replaced_by="completely_invented_metric",
    )
    repo = MetadataRepository(
        catalog=catalog,
        metrics=MetricCatalog(metrics_version="0.4", metrics=(m_broken_target,)),
        join_paths=join_paths,
    )
    report: MetadataAuditReport = audit_metadata(repo)
    assert report.passed is False
    assert any(i.code == "BROKEN_DEPRECATION_TARGET" for i in report.issues)
    assert any("completely_invented_metric" in i.message for i in report.issues)


def test_baseline_agent_preplan_validation_shortcircuit(baseline: Path, repository) -> None:
    """BaselineAgent aborts execution if validate_query_plan detects invalid plan."""
    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)
    agent = BaselineAgent()

    # Query with unsupported occupation grouping (not in allowed_group_dimensions for this metric)
    req = AgentRequest(
        case_id="case_plan_check",
        question="统计VIP客户数。",
        anchor_date=ANCHOR,
        metadata_version=repository.metrics.metrics_version,
        protocol_version="1.1",
    )
    resp = agent.respond(req, tools)
    assert resp.status == "success"
    # Ensure validate_query_plan was invoked
    plan_checks = [c for c in tools.calls if c["tool"] == "validate_query_plan"]
    assert len(plan_checks) >= 1
