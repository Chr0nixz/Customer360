from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.metadata.models import (
    Catalog,
    CatalogForeignKey,
    ColumnHit,
    GlossaryEntry,
    JoinPath,
    TableDef,
    TableHit,
)

UNDECLARED_ENTITY_FIELDS = frozenset({"phone", "id_card"})
EXECUTABLE_JOIN_PATH = "customer_transactions"

Operation = Literal["count_distinct", "count", "sum"]
TimeSemantics = Literal[
    "none", "rolling_required", "point_in_time_required", "latest_snapshot_required"
]
FixedFilterValue = str | bool


class MetricDef(Contract):
    metric_name: Identifier
    business_name: Text
    description: Text
    metric_version: Literal["0.1"] = "0.1"
    unit: Literal["count", "CNY"]
    null_policy: Literal["exclude"] = "exclude"
    deduplicate: bool
    output_column: Identifier
    allowed_group_dimensions: tuple[Identifier, ...] = ()
    forbidden_contexts: tuple[Text, ...]
    example_questions: tuple[Text, ...] = Field(min_length=1)
    source_table: Identifier
    grain: Text
    operation: Operation
    measure_column: Identifier
    time_semantics: TimeSemantics
    time_column: Identifier | None = None
    fixed_filters: dict[Identifier, FixedFilterValue] = Field(default_factory=dict)
    fixed_null_columns: tuple[Identifier, ...] = ()
    allowed_filter_columns: tuple[Identifier, ...] = ()
    sensitivity: Literal["internal", "financial"]

    @model_validator(mode="after")
    def validate_metric(self) -> "MetricDef":
        if self.time_semantics in {
            "rolling_required",
            "point_in_time_required",
            "latest_snapshot_required",
        } and not (self.time_column):
            raise ValueError("temporal metric needs time_column")
        if self.operation == "sum" and self.sensitivity != "financial":
            raise ValueError("sum metric must be financial")
        if self.deduplicate != (self.operation == "count_distinct"):
            raise ValueError("deduplication must match the compiler operation")
        if len(set(self.allowed_group_dimensions)) != len(self.allowed_group_dimensions):
            raise ValueError("duplicate group dimension")
        if len(set(self.fixed_null_columns)) != len(self.fixed_null_columns):
            raise ValueError("duplicate fixed null column")
        if set(self.fixed_null_columns) & set(self.fixed_filters):
            raise ValueError("fixed null column cannot also be a fixed equality filter")
        return self


class MetricCatalog(Contract):
    metrics_version: Literal["0.3"] = "0.3"
    metrics: tuple[MetricDef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_metrics(self) -> "MetricCatalog":
        names = [m.metric_name for m in self.metrics]
        if len(set(names)) != len(names):
            raise ValueError("duplicate metric")
        business = [m.business_name for m in self.metrics]
        if len(set(business)) != len(business):
            raise ValueError("duplicate metric business_name")
        outputs = [m.output_column for m in self.metrics]
        if len(set(outputs)) != len(outputs):
            raise ValueError("duplicate metric output_column")
        return self


def load_catalog(path: Path | None = None) -> Catalog:
    path = path or Path(__file__).parents[1] / "resources" / "catalog.yaml"
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class JoinPathCatalog(Contract):
    join_paths_version: Literal["0.1"] = "0.1"
    paths: tuple[JoinPath, ...] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def reviewed_paths(self) -> "JoinPathCatalog":
        names = [item.path_name for item in self.paths]
        if len(set(names)) != len(names):
            raise ValueError("duplicate join path_name")
        executable = [item for item in self.paths if item.compile_status == "executable"]
        if [item.path_name for item in executable] != [EXECUTABLE_JOIN_PATH]:
            raise ValueError("exactly one executable join path is allowed")
        seen: set[tuple[tuple[str, str, str, str], ...]] = set()
        reversed_seen: set[tuple[tuple[str, str, str, str], ...]] = set()
        for item in self.paths:
            key = tuple(
                (hop.left_table, hop.left_column, hop.right_table, hop.right_column)
                for hop in item.hops
            )
            rev = tuple(
                (hop.right_table, hop.right_column, hop.left_table, hop.left_column)
                for hop in reversed(item.hops)
            )
            if key in reversed_seen:
                raise ValueError(f"join path {item.path_name} reverses an existing edge")
            seen.add(key)
            reversed_seen.add(rev)
        return self


def load_metrics(path: Path | None = None) -> MetricCatalog:
    path = path or Path(__file__).parents[1] / "resources" / "metrics.yaml"
    return MetricCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_join_paths(path: Path | None = None) -> JoinPathCatalog:
    path = path or Path(__file__).parents[1] / "resources" / "join_paths.yaml"
    return JoinPathCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _matches(query: str, *parts: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    return needle in " ".join(parts).lower()


class MetadataRepository:
    def __init__(
        self,
        catalog: Catalog | None = None,
        metrics: MetricCatalog | None = None,
        join_paths: JoinPathCatalog | None = None,
    ):
        self.catalog = catalog or load_catalog()
        self.metrics = metrics or load_metrics()
        self.join_paths = join_paths or load_join_paths()
        self._assert_catalog_policy()
        self._assert_metric_schema()
        self._assert_metrics_searchable()
        self._assert_join_paths()

    def _assert_catalog_policy(self) -> None:
        for table in self.catalog.tables:
            names = {column.column_name for column in table.columns}
            blocked = names & UNDECLARED_ENTITY_FIELDS
            if blocked:
                raise ValueError(
                    "catalog contains undeclared entity field "
                    f"{sorted(blocked)[0]}; phone/id_card are not in the v0.1 schema"
                )

    def _assert_metric_schema(self) -> None:
        for metric in self.metrics.metrics:
            try:
                table = self.catalog.table(metric.source_table)
                measure = table.column(metric.measure_column)
                if metric.operation == "sum" and measure.kind != "decimal":
                    raise ValueError("SUM measure must be decimal")
                for name in (
                    *metric.fixed_filters,
                    *metric.fixed_null_columns,
                    *metric.allowed_filter_columns,
                    *metric.allowed_group_dimensions,
                ):
                    table.column(name)
                for name, value in metric.fixed_filters.items():
                    kind = table.column(name).kind
                    if kind == "boolean" and type(value) is not bool:
                        raise ValueError("boolean fixed filter needs a boolean")
                    if kind == "string" and type(value) is not str:
                        raise ValueError("string fixed filter needs a string")
                for name in metric.fixed_null_columns:
                    if not table.column(name).nullable:
                        raise ValueError("fixed null column must be nullable")
                if metric.time_semantics == "none" and metric.time_column:
                    raise ValueError("non-temporal metric must not set time_column")
                if metric.time_column and table.column(metric.time_column).kind != "date":
                    raise ValueError("time column must be DATE")
            except KeyError as exc:
                raise ValueError("metric references an unknown schema field") from exc

    def _assert_metrics_searchable(self) -> None:
        for metric in self.metrics.metrics:
            hits = {item.metric_name for item in self.search_metrics(metric.business_name)}
            if metric.metric_name not in hits:
                raise ValueError(f"metric {metric.metric_name} is not searchable by business_name")

    def search_tables(self, query: str) -> tuple[TableDef, ...]:
        return tuple(
            table
            for table in self.catalog.tables
            if _matches(query, table.table_name, table.business_name)
        )

    def table_hits(self, query: str) -> tuple[TableHit, ...]:
        return tuple(
            TableHit(
                table_name=table.table_name,
                business_name=table.business_name,
                grain=table.grain,
                scope=table.scope,
                time_column=table.time_column,
            )
            for table in self.search_tables(query)
        )

    def get_table_schema(self, table_name: str) -> TableDef:
        return self.catalog.table(table_name)

    def search_columns(self, query: str) -> tuple[ColumnHit, ...]:
        hits: list[ColumnHit] = []
        for table in self.catalog.tables:
            for column in table.columns:
                if _matches(
                    query,
                    table.table_name,
                    f"{table.table_name}.{column.column_name}",
                    column.column_name,
                    column.business_name,
                ):
                    hits.append(
                        ColumnHit(
                            table_name=table.table_name,
                            table_business_name=table.business_name,
                            column_name=column.column_name,
                            business_name=column.business_name,
                            kind=column.kind,
                            nullable=column.nullable,
                            sensitivity=column.sensitivity,
                        )
                    )
        return tuple(hits)

    def search_metrics(self, query: str) -> tuple[MetricDef, ...]:
        return tuple(
            metric
            for metric in self.metrics.metrics
            if _matches(
                query,
                metric.metric_name,
                metric.business_name,
                metric.description,
                *metric.example_questions,
            )
        )

    def get_metric_definition(self, metric_name: str) -> MetricDef:
        for metric in self.metrics.metrics:
            if metric.metric_name == metric_name:
                return metric
        raise KeyError(f"unknown metric: {metric_name}")

    def get_business_glossary(self, term: str) -> tuple[GlossaryEntry, ...]:
        return tuple(
            entry
            for entry in self._glossary_entries()
            if _matches(term, entry.term, *entry.aliases)
        )

    def list_foreign_keys(self) -> tuple[CatalogForeignKey, ...]:
        return tuple(
            CatalogForeignKey(
                source_table=table.table_name,
                column=fk.column,
                target_table=fk.target_table,
                target_column=fk.target_column,
            )
            for table in self.catalog.tables
            for fk in table.foreign_keys
        )

    def _assert_join_paths(self) -> None:
        for path in self.join_paths.paths:
            for hop in path.hops:
                try:
                    self.catalog.table(hop.left_table).column(hop.left_column)
                    self.catalog.table(hop.right_table).column(hop.right_column)
                except KeyError as exc:
                    raise ValueError(
                        f"join path {path.path_name} references unknown schema"
                    ) from exc

    def get_join_paths(self, query: str = "") -> tuple[JoinPath, ...]:
        needle = query.strip().lower()
        return tuple(
            path
            for path in self.join_paths.paths
            if not needle
            or needle
            in (
                f"{path.path_name} {path.left_table} {path.right_table} "
                f"{path.description} {path.time_validity}"
            ).lower()
        )

    def consistency_report(self) -> dict[str, int | bool]:
        columns = sum(len(table.columns) for table in self.catalog.tables)
        return {
            "tables": len(self.catalog.tables),
            "columns": columns,
            "metrics": len(self.metrics.metrics),
            "join_paths": len(self.join_paths.paths),
            "executable_join_paths": sum(
                1 for path in self.join_paths.paths if path.compile_status == "executable"
            ),
            "foreign_keys": len(self.list_foreign_keys()),
            "glossary_entries": len(self.get_business_glossary("")),
            "checks_passed": True,
        }

    def _glossary_entries(self) -> tuple[GlossaryEntry, ...]:
        entries: list[GlossaryEntry] = []
        for table in self.catalog.tables:
            entries.append(
                GlossaryEntry(
                    term=table.business_name,
                    kind="table",
                    aliases=(table.table_name,),
                    definition=table.grain,
                    table_name=table.table_name,
                )
            )
            for column in table.columns:
                entries.append(
                    GlossaryEntry(
                        term=column.business_name,
                        kind="column",
                        aliases=(column.column_name, f"{table.table_name}.{column.column_name}"),
                        definition=(
                            f"{table.business_name}字段，类型{column.kind}，"
                            f"敏感级别{column.sensitivity}"
                        ),
                        table_name=table.table_name,
                        column_name=column.column_name,
                    )
                )
        for metric in self.metrics.metrics:
            entries.append(
                GlossaryEntry(
                    term=metric.business_name,
                    kind="metric",
                    aliases=(metric.metric_name,),
                    definition=metric.description,
                    metric_name=metric.metric_name,
                )
            )
        return tuple(entries)
