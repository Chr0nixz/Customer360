"""Cross-engine dialect transpiler and capability matrix.

Translates candidate and Gold queries between DuckDB and PostgreSQL ASTs
while stabilizing NULL ordering, quoted identifiers, and date intervals.
"""

from typing import cast

import sqlglot
from sqlglot import exp

from customer360.contracts.dialects import (
    DialectCapability,
    EngineDialect,
    TranspiledQuery,
)

DIALECT_CAPABILITIES: dict[str, DialectCapability] = {
    "duckdb": DialectCapability(
        dialect="duckdb",
        identifier_quote='"',
        date_interval_format="INTERVAL N DAY",
        nulls_ordering_default="NULLS LAST (asc)",
        decimal_type_name="DECIMAL",
        supports_read_only_pragma=True,
        capability_only=False,
        live_instance_required=False,
    ),
    "postgres": DialectCapability(
        dialect="postgres",
        identifier_quote='"',
        date_interval_format="INTERVAL 'N days'",
        nulls_ordering_default="NULLS FIRST (desc) / LAST (asc)",
        decimal_type_name="NUMERIC",
        supports_read_only_pragma=False,
        capability_only=True,
        live_instance_required=False,
    ),
    "ansi": DialectCapability(
        dialect="ansi",
        identifier_quote='"',
        date_interval_format="INTERVAL 'N' DAY",
        nulls_ordering_default="NULLS LAST",
        decimal_type_name="DECIMAL",
        supports_read_only_pragma=False,
        capability_only=True,
        live_instance_required=False,
    ),
}


def get_dialect_capabilities(dialect: str) -> DialectCapability:
    """Retrieve capabilities for a supported dialect."""
    key = dialect.strip().lower()
    if key not in DIALECT_CAPABILITIES:
        raise ValueError(f"unsupported dialect: {dialect}")
    return DIALECT_CAPABILITIES[key]


def transpile_sql(
    sql: str,
    source_dialect: EngineDialect = "duckdb",
    target_dialect: EngineDialect = "postgres",
) -> TranspiledQuery:
    """Transpile a query string from source dialect to target dialect using SQLGlot AST."""
    source_key = str(source_dialect).lower()
    target_key = str(target_dialect).lower()

    if source_key not in DIALECT_CAPABILITIES:
        raise ValueError(f"unsupported source dialect: {source_dialect}")
    if target_key not in DIALECT_CAPABILITIES:
        raise ValueError(f"unsupported target dialect: {target_dialect}")

    ast = sqlglot.parse_one(sql, read=source_key)
    differences: list[str] = []

    # 1. Stabilize NULLs ordering on any Order expressions
    has_order = False
    for order_node in ast.find_all(exp.Ordered):
        has_order = True
        # If nulls are not explicitly declared, force NULLS LAST for cross-engine stability
        if order_node.args.get("nulls_are_large") is None:
            order_node.set("nulls_are_large", False)

    if has_order:
        differences.append("nulls_ordering_stabilized")

    # 2. Check interval transformation
    has_interval = False
    for _ in ast.find_all(exp.Interval):
        has_interval = True
        break
    if has_interval and source_key != target_key:
        differences.append("interval_syntax_converted")

    # Render target SQL with quoted identifiers preserved
    transpiled = ast.sql(dialect=target_key, identify=True)
    if source_key != target_key:
        differences.append(f"transpiled_from_{source_key}_to_{target_key}")

    return TranspiledQuery(
        source_sql=sql,
        source_dialect=cast(EngineDialect, source_key),
        target_dialect=cast(EngineDialect, target_key),
        transpiled_sql=transpiled,
        ast_valid=True,
        differences=tuple(differences),
    )
