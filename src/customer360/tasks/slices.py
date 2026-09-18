"""Load catalog-ordered table slices from a DuckDB file. Not an oracle."""

from pathlib import Path

import duckdb

from customer360.metadata.models import Catalog
from customer360.tasks.independent import TableSlice


def load_table_slices(database: Path, catalog: Catalog) -> dict[str, TableSlice]:
    slices: dict[str, TableSlice] = {}
    with duckdb.connect(str(database), read_only=True) as connection:
        for table in catalog.tables:
            names = tuple(column.column_name for column in table.columns)
            kinds = tuple(column.kind for column in table.columns)
            select = ", ".join(f'"{name}"' for name in names)
            rows = connection.execute(f'SELECT {select} FROM "{table.table_name}"').fetchall()
            slices[table.table_name] = TableSlice(
                table_name=table.table_name,
                columns=names,
                kinds=kinds,
                rows=tuple(tuple(row) for row in rows),
            )
    return slices
