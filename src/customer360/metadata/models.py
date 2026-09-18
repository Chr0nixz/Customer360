from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text

ColumnKind = Literal["string", "integer", "decimal", "date", "boolean"]
Sensitivity = Literal["internal", "restricted", "financial"]


class CatalogColumn(Contract):
    column_name: Identifier
    business_name: Text
    kind: ColumnKind
    nullable: bool
    primary_key: bool = False
    sensitivity: Sensitivity


class ForeignKey(Contract):
    column: Identifier
    target_table: Identifier
    target_column: Identifier


class CatalogForeignKey(Contract):
    source_table: Identifier
    column: Identifier
    target_table: Identifier
    target_column: Identifier


class JoinHop(Contract):
    left_table: Identifier
    left_column: Identifier
    right_table: Identifier
    right_column: Identifier


class JoinPath(Contract):
    path_name: Identifier
    left_table: Identifier
    left_column: Identifier
    right_table: Identifier
    right_column: Identifier
    cardinality: Literal["one_to_one", "one_to_many", "many_to_many"]
    target_grain: Text
    description: Text
    hops: tuple[JoinHop, ...] = ()
    compile_status: Literal["executable", "metadata_only"] = "metadata_only"
    time_validity: Text = "none"
    duplicate_count_risk: Text = "unspecified"
    pre_aggregation: Text = "none"

    @model_validator(mode="after")
    def default_single_hop(self) -> "JoinPath":
        hops = self.hops or (
            JoinHop(
                left_table=self.left_table,
                left_column=self.left_column,
                right_table=self.right_table,
                right_column=self.right_column,
            ),
        )
        object.__setattr__(self, "hops", hops)
        if self.compile_status == "executable" and self.path_name != "customer_transactions":
            raise ValueError("only customer_transactions is executable")
        if self.path_name == "customer_transactions" and self.compile_status != "executable":
            raise ValueError("customer_transactions must be executable")
        return self

    def tables(self) -> frozenset[str]:
        names = {self.left_table, self.right_table}
        for hop in self.hops:
            names.add(hop.left_table)
            names.add(hop.right_table)
        return frozenset(names)


class TableHit(Contract):
    table_name: Identifier
    business_name: Text
    grain: Text
    scope: Literal["customer", "global"]
    time_column: Identifier | None = None


class ColumnHit(Contract):
    table_name: Identifier
    table_business_name: Text
    column_name: Identifier
    business_name: Text
    kind: ColumnKind
    nullable: bool
    sensitivity: Sensitivity


class GlossaryEntry(Contract):
    term: Text
    kind: Literal["table", "column", "metric"]
    aliases: tuple[Text, ...]
    definition: Text
    table_name: Identifier | None = None
    column_name: Identifier | None = None
    metric_name: Identifier | None = None


class TableDef(Contract):
    table_name: Identifier
    business_name: Text
    grain: Text
    scope: Literal["customer", "global"]
    time_column: Identifier | None = None
    columns: tuple[CatalogColumn, ...] = Field(min_length=1)
    unique_keys: tuple[tuple[Identifier, ...], ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()

    @model_validator(mode="after")
    def check_columns(self) -> "TableDef":
        names = [c.column_name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate columns in {self.table_name}")
        business = [c.business_name for c in self.columns]
        if len(set(business)) != len(business):
            raise ValueError(f"duplicate column business_name in {self.table_name}")
        if sum(1 for c in self.columns if c.primary_key) > 1:
            raise ValueError(f"multiple primary keys in {self.table_name}")
        if self.time_column and self.time_column not in names:
            raise ValueError("time_column must exist")
        if self.scope == "customer" and "customer_id" not in names:
            raise ValueError("customer-scoped table needs customer_id")
        if any(not key or not set(key) <= set(names) for key in self.unique_keys):
            raise ValueError("invalid unique key")
        if any(fk.column not in names for fk in self.foreign_keys):
            raise ValueError("unknown foreign key column")
        return self

    def column(self, name: str) -> CatalogColumn:
        for column in self.columns:
            if column.column_name == name:
                return column
        raise KeyError(f"unknown column: {self.table_name}.{name}")


class Catalog(Contract):
    catalog_version: Literal["0.1"] = "0.1"
    tables: tuple[TableDef, ...] = Field(min_length=9)

    @model_validator(mode="after")
    def unique_tables(self) -> "Catalog":
        names = [t.table_name for t in self.tables]
        if len(set(names)) != len(names):
            raise ValueError("duplicate table")
        business = [t.business_name for t in self.tables]
        if len(set(business)) != len(business):
            raise ValueError("duplicate table business_name")
        if len(names) != 9:
            raise ValueError("v0.1 requires exactly nine core tables")
        for table in self.tables:
            for fk in table.foreign_keys:
                try:
                    self.table(fk.target_table).column(fk.target_column)
                except KeyError as exc:
                    raise ValueError("unknown foreign key target") from exc
        return self

    def table(self, name: str) -> TableDef:
        for table in self.tables:
            if table.table_name == name:
                return table
        raise KeyError(f"unknown table: {name}")
