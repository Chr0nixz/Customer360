from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.public import QueryResult


class SqlLimits(Contract):
    """Tiny defaults stay 15s / 128MB / 100 result rows / 10k materialized rows."""

    timeout_seconds: float = Field(default=15, gt=0, le=180)
    memory_mb: int = Field(default=128, ge=64, le=1024)
    max_rows: int = Field(default=100, ge=1, le=10000)
    max_sql_chars: int = Field(default=10000, ge=1, le=100000)
    max_input_rows: int = Field(default=10000, ge=1, le=5_000_000)


class TableGrant(Contract):
    table: Identifier
    columns: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_columns(self) -> "TableGrant":
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("duplicate grant column")
        return self


class AccessPolicy(Contract):
    """Trusted context: explicit scope, no wildcard/all-customer escape hatch."""

    role: Identifier
    customer_ids: tuple[Text, ...]
    grants: tuple[TableGrant, ...] = Field(min_length=1)
    min_group_size: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def unique_tables(self) -> "AccessPolicy":
        if len({g.table for g in self.grants}) != len(self.grants):
            raise ValueError("duplicate grant table")
        if len(set(self.customer_ids)) != len(self.customer_ids):
            raise ValueError("duplicate customer scope")
        return self


class ExecutionRecord(Contract):
    query_id: Text
    sql: Text
    result: QueryResult
    elapsed_ms: float = Field(ge=0)
