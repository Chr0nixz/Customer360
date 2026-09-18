from datetime import date
from decimal import Decimal
from pathlib import Path

from customer360.metadata.metrics import load_catalog

_SQL_TYPES = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "decimal": "DECIMAL(24,2)",
    "date": "DATE",
    "boolean": "BOOLEAN",
}


def render_literal(value) -> str:
    """Render one typed Python value as a DuckDB literal for trusted bulk inserts.

    Only schema kinds (string/integer/decimal/date/boolean plus NULL) are accepted;
    anything else fails closed instead of being stringified.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"unsupported literal type: {type(value).__name__}")


def render_ddl(catalog=None) -> str:
    catalog = catalog or load_catalog()
    chunks = []
    for table in catalog.tables:
        columns = []
        for column in table.columns:
            sql_type = _SQL_TYPES[column.kind]
            nullable = "" if column.nullable else " NOT NULL"
            primary = " PRIMARY KEY" if column.primary_key else ""
            columns.append(f'    "{column.column_name}" {sql_type}{nullable}{primary}')
        for key in table.unique_keys:
            columns.append("    UNIQUE (" + ", ".join(f'"{name}"' for name in key) + ")")
        for fk in table.foreign_keys:
            columns.append(
                f'    FOREIGN KEY ("{fk.column}") REFERENCES '
                f'"{fk.target_table}" ("{fk.target_column}")'
            )
        chunks.append(f'CREATE TABLE "{table.table_name}" (\n' + ",\n".join(columns) + "\n);")
    return "\n\n".join(chunks) + "\n"


def write_ddl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(render_ddl())
