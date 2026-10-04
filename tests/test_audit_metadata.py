from customer360.metadata.audit import audit_metadata
from customer360.metadata.metrics import (
    MetadataRepository,
    MetricCatalog,
    MetricDef,
    load_catalog,
    load_join_paths,
)


def test_official_metadata_audit_clean(repository):
    """The official repository must pass static audit cleanly with 0 issues."""
    report = audit_metadata(repository)
    assert report.passed is True
    assert len(report.issues) == 0
    assert report.tables_count == 9
    assert report.metrics_count == 30
    assert report.join_paths_count == 20


def test_audit_metadata_catches_deprecation_cycle_and_dead_chain():
    catalog = load_catalog()
    join_paths = load_join_paths()

    m_retired_target = MetricDef(
        metric_name="m_retired_target",
        business_name="已停用目标",
        description="描述",
        status="retired",
        replaced_by="active_m",
        unit="count",
        deduplicate=True,
        output_column="out_c",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
    )

    # Dead chain: points to a retired metric
    m_dead_chain = MetricDef(
        metric_name="m_dead_chain",
        business_name="死链指标",
        description="描述",
        status="retired",
        replaced_by="m_retired_target",
        unit="count",
        deduplicate=True,
        output_column="out_b",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
    )

    m_active = MetricDef(
        metric_name="active_m",
        business_name="生效指标",
        description="描述",
        status="active",
        unit="count",
        deduplicate=True,
        output_column="out_a",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
    )

    metrics_cat = MetricCatalog(
        metrics_version="0.3",
        metrics=(m_active, m_retired_target, m_dead_chain),
    )
    repo = MetadataRepository(catalog=catalog, metrics=metrics_cat, join_paths=join_paths)
    report = audit_metadata(repo)

    assert report.passed is False
    codes = [i.code for i in report.issues]
    assert "DEAD_DEPRECATION_CHAIN" in codes


def test_audit_metadata_catches_circular_deprecation():
    catalog = load_catalog()
    join_paths = load_join_paths()

    m1 = MetricDef(
        metric_name="metric_a",
        business_name="指标A",
        description="描述",
        status="deprecated",
        replaced_by="metric_b",
        unit="count",
        deduplicate=True,
        output_column="out_a",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
    )
    m2 = MetricDef(
        metric_name="metric_b",
        business_name="指标B",
        description="描述",
        status="deprecated",
        replaced_by="metric_a",
        unit="count",
        deduplicate=True,
        output_column="out_b",
        source_table="dim_customer",
        grain="customer",
        operation="count_distinct",
        measure_column="customer_id",
        time_semantics="none",
        sensitivity="internal",
        forbidden_contexts=("none",),
        example_questions=("q",),
    )

    metrics_cat = MetricCatalog(
        metrics_version="0.3",
        metrics=(m1, m2),
    )
    repo = MetadataRepository(catalog=catalog, metrics=metrics_cat, join_paths=join_paths)
    report = audit_metadata(repo)

    assert report.passed is False
    codes = [i.code for i in report.issues]
    assert "CIRCULAR_DEPRECATION" in codes
