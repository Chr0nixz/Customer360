"""Contracts for multi-engine dialects, capabilities, and AST transpilation.

Decouples query AST logic from DuckDB-specific dialect assumptions.
"""

from typing import Literal

from pydantic import Field

from customer360.contracts.base import Contract, Text

EngineDialect = Literal["duckdb", "postgres", "ansi"]


class DialectCapability(Contract):
    """Formal capability description of a supported database engine dialect."""

    dialect: EngineDialect
    identifier_quote: str = '"'
    date_interval_format: Text
    nulls_ordering_default: Text
    decimal_type_name: Text
    supports_read_only_pragma: bool
    capability_only: bool = True
    live_instance_required: bool = False


class TranspiledQuery(Contract):
    """Result of cross-dialect AST transpilation."""

    source_sql: Text
    source_dialect: EngineDialect
    target_dialect: EngineDialect
    transpiled_sql: Text
    ast_valid: bool = True
    differences: tuple[Text, ...] = Field(default_factory=tuple)
