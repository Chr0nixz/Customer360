import pytest
from pydantic import ValidationError

from customer360.metadata.metrics import (
    MetadataRepository,
    MetricCatalog,
    load_catalog,
    load_metrics,
)
from customer360.metadata.models import Catalog, CatalogColumn


def _replace_customer_columns(extra: CatalogColumn) -> Catalog:
    catalog = load_catalog()
    customer = catalog.table("dim_customer")
    replaced = customer.model_copy(update={"columns": (*customer.columns, extra)})
    tables = tuple(
        replaced if table.table_name == "dim_customer" else table for table in catalog.tables
    )
    return Catalog(tables=tables)


def test_bundled_catalog_is_self_consistent(repository):
    report = repository.consistency_report()
    column_count = sum(len(table.columns) for table in repository.catalog.tables)
    assert report == {
        "tables": 9,
        "columns": column_count,
        "metrics": 30,
        "join_paths": 20,
        "executable_join_paths": 1,
        "foreign_keys": 8,
        "glossary_entries": 9 + column_count + 30,
        "checks_passed": True,
    }
    assert column_count == len(repository.search_columns(""))


def test_search_tables_by_technical_and_business_name(repository):
    by_name = repository.search_tables("dim_customer")
    by_business = repository.search_tables("客户信息表")
    assert [table.table_name for table in by_name] == ["dim_customer"]
    assert by_name == by_business
    assert repository.search_tables("no-such-table") == ()


def test_search_columns_by_field_and_business_name(repository):
    by_field = repository.search_columns("customer_level")
    by_business = repository.search_columns("客户等级")
    assert {(hit.table_name, hit.column_name) for hit in by_field} == {
        ("dim_customer", "customer_level")
    }
    assert by_field == by_business
    qualified = repository.search_columns("dim_customer.customer_id")
    assert [hit.column_name for hit in qualified] == ["customer_id"]
    assert repository.search_columns("no_such_column") == ()


def test_search_metrics_uses_examples_without_inventing_aliases(repository):
    vip = repository.search_metrics("VIP客户数")
    rolling = {metric.metric_name for metric in repository.search_metrics("近90天")}
    assert [metric.metric_name for metric in vip] == ["distinct_customer_count"]
    assert rolling >= {
        "successful_transaction_count",
        "successful_transaction_amount",
        "failed_transaction_count",
        "successful_net_cash_flow",
        "successful_cash_inflow",
    }
    assert all(
        repository.get_metric_definition(name).time_semantics == "rolling_required"
        for name in rolling
    )
    assert repository.search_metrics("资产规模") == ()
    assert repository.search_metrics("最近三个月") == ()
    assert {metric.metric_name for metric in repository.search_metrics("最新快照")} == {
        "latest_total_asset"
    }


def test_glossary_covers_catalog_and_metrics_only(repository):
    customer_table = repository.get_business_glossary("客户信息表")
    customer_count = repository.get_business_glossary("客户数")
    amount = repository.get_business_glossary("successful_transaction_amount")
    assert [entry.kind for entry in customer_table] == ["table"]
    assert {entry.metric_name for entry in customer_count if entry.kind == "metric"} == {
        "distinct_customer_count",
        "active_customer_count",
    }
    assert [entry.metric_name for entry in amount] == ["successful_transaction_amount"]
    assert repository.get_business_glossary("phone") == ()
    assert repository.get_business_glossary("id_card") == ()
    assert repository.get_business_glossary("身份证") == ()


def test_restricted_columns_are_searchable_on_the_trusted_repository(repository):
    hits = repository.search_columns("客户名称")
    assert [(hit.table_name, hit.column_name, hit.sensitivity) for hit in hits] == [
        ("dim_customer", "customer_name", "restricted")
    ]


def test_join_paths_are_reviewed_business_paths(repository):
    paths = repository.get_join_paths("")
    assert len(paths) == 20
    executable = [path.path_name for path in paths if path.compile_status == "executable"]
    assert executable == ["customer_transactions"]
    names = [path.path_name for path in paths]
    assert len(set(names)) == 20
    assert "customer_managers" in names
    assert "current_primary_customer_manager" in names
    assert repository.get_join_paths("customer_transactions")[0].compile_status == "executable"


def test_get_metric_definition_unknown(repository):
    with pytest.raises(KeyError, match="unknown metric"):
        repository.get_metric_definition("windowed_asset")


def test_metric_unknown_column_fails_closed():
    metrics = load_metrics()
    broken = metrics.metrics[0].model_copy(update={"measure_column": "not_a_column"})
    with pytest.raises(ValueError, match="unknown schema field"):
        MetadataRepository(metrics=MetricCatalog(metrics=(broken, *metrics.metrics[1:])))


def test_non_temporal_metric_rejects_time_column():
    metrics = load_metrics()
    broken = metrics.metrics[0].model_copy(update={"time_column": "registration_date"})
    with pytest.raises(ValueError, match="non-temporal"):
        MetadataRepository(metrics=MetricCatalog(metrics=(broken, *metrics.metrics[1:])))


def test_duplicate_metric_business_name_fails_closed():
    metrics = load_metrics()
    duplicate = metrics.metrics[1].model_copy(
        update={"business_name": metrics.metrics[0].business_name}
    )
    with pytest.raises(ValidationError, match="duplicate metric business_name"):
        MetricCatalog(metrics=(metrics.metrics[0], duplicate, metrics.metrics[2]))


def test_point_in_time_metric_needs_time_column():
    snapshot = next(
        metric for metric in load_metrics().metrics if metric.metric_name == "snapshot_total_asset"
    )
    payload = snapshot.model_dump()
    payload["time_column"] = None
    with pytest.raises(ValidationError, match="temporal metric"):
        type(snapshot).model_validate(payload)


def test_boolean_fixed_filter_rejects_string():
    primary = next(
        metric
        for metric in load_metrics().metrics
        if metric.metric_name == "current_primary_service_relation_count"
    )
    broken = primary.model_copy(update={"fixed_filters": {"is_primary": "true"}})
    with pytest.raises(ValueError, match="boolean"):
        MetadataRepository(metrics=MetricCatalog(metrics=(broken,)))


def test_undeclared_entity_fields_fail_closed():
    poisoned = _replace_customer_columns(
        CatalogColumn(
            column_name="phone",
            business_name="手机号",
            kind="string",
            nullable=True,
            sensitivity="restricted",
        )
    )
    with pytest.raises(ValueError, match="undeclared entity field"):
        MetadataRepository(catalog=poisoned, metrics=load_metrics())
