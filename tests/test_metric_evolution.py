import pytest

from customer360.errors import QueryRejected
from customer360.metadata.metrics import (
    MetadataRepository,
    MetricCatalog,
    MetricDef,
    load_catalog,
    load_join_paths,
)


def test_metric_lifecycle_validation():
    # 1. retired metric missing replaced_by must fail validation
    with pytest.raises(ValueError, match="retired metric must declare replaced_by"):
        MetricDef(
            metric_name="old_metric",
            business_name="旧指标",
            description="已停用的旧指标",
            status="retired",
            replaced_by=None,
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
        )

    # 2. replaced_by pointing to itself must fail
    with pytest.raises(ValueError, match="replaced_by cannot point to the metric itself"):
        MetricDef(
            metric_name="old_metric",
            business_name="旧指标",
            description="已停用的旧指标",
            status="retired",
            replaced_by="old_metric",
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
        )

    # 3. active metric declaring replaced_by must fail
    with pytest.raises(ValueError, match="active metric must not declare replaced_by"):
        MetricDef(
            metric_name="active_metric",
            business_name="活跃指标",
            description="生效中指标",
            status="active",
            replaced_by="other_metric",
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
        )


def test_metric_search_and_get_lifecycle():
    catalog = load_catalog()
    join_paths = load_join_paths()

    m_active = MetricDef(
        metric_name="cust_active",
        business_name="客户数A",
        description="活跃指标",
        status="active",
        metric_version="0.2",
        unit="count",
        deduplicate=True,
        output_column="cust_active_cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("统计客户数A。",),
    )
    m_deprecated = MetricDef(
        metric_name="cust_deprecated",
        business_name="客户数B",
        description="将被废弃的指标",
        status="deprecated",
        metric_version="0.1",
        replaced_by="cust_active",
        unit="count",
        deduplicate=True,
        output_column="cust_deprecated_cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("统计客户数B。",),
    )
    m_retired = MetricDef(
        metric_name="cust_retired",
        business_name="客户数C",
        description="已停用的历史指标",
        status="retired",
        metric_version="0.1",
        replaced_by="cust_active",
        unit="count",
        deduplicate=True,
        output_column="cust_retired_cnt",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("统计客户数C。",),
    )

    metric_catalog = MetricCatalog(
        metrics_version="0.3",
        metrics=(m_active, m_deprecated, m_retired),
    )
    repo = MetadataRepository(catalog=catalog, metrics=metric_catalog, join_paths=join_paths)

    # search_metrics defaults to excluding retired
    hits = repo.search_metrics("")
    hit_names = [m.metric_name for m in hits]
    assert "cust_active" in hit_names
    assert "cust_deprecated" in hit_names
    assert "cust_retired" not in hit_names

    # search_metrics with include_retired=True
    all_hits = repo.search_metrics("", include_retired=True)
    all_names = [m.metric_name for m in all_hits]
    assert "cust_retired" in all_names

    # get_metric_definition on active and deprecated succeeds
    assert repo.get_metric_definition("cust_active").metric_name == "cust_active"
    assert repo.get_metric_definition("cust_deprecated").metric_name == "cust_deprecated"

    # get_metric_definition on retired raises DEPRECATED_METRIC_REJECTED
    with pytest.raises(QueryRejected) as exc_info:
        repo.get_metric_definition("cust_retired")
    assert exc_info.value.code == "DEPRECATED_METRIC_REJECTED"
    assert "cust_active" in str(exc_info.value)
