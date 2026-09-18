"""A killable SQL worker. Only a materialized, scoped projection sees candidate SQL."""

import csv
import tempfile
from datetime import date
from decimal import Decimal
from multiprocessing.connection import Connection
from pathlib import Path

import duckdb
import sqlglot

from customer360.contracts.execution import AccessPolicy, SqlLimits
from customer360.contracts.public import Column, QueryResult
from customer360.metadata.metrics import load_catalog
from customer360.safety.sql_guard import GuardedQuery
from customer360.synth.schema import _SQL_TYPES, render_literal

_ID_BATCH = 500
_TINY_INPUT_ROWS = 10_000


def _fetch_scoped_rows(source, select_columns: str, table_name: str, customer_ids, cap: int):
    """Apply row-level scope in ID batches so large policies do not blow the IN list."""

    if not customer_ids:
        return []
    rows: list = []
    for start in range(0, len(customer_ids), _ID_BATCH):
        batch = customer_ids[start : start + _ID_BATCH]
        placeholders = ", ".join("?" for _ in batch)
        cursor = source.execute(
            f'SELECT {select_columns} FROM "{table_name}" WHERE "customer_id" IN ({placeholders})',
            list(batch),
        )
        while True:
            window = cap + 1 - len(rows)
            if window <= 0:
                return rows
            chunk = cursor.fetchmany(min(8192, window))
            if not chunk:
                break
            rows.extend(chunk)
        if len(rows) > cap:
            return rows
    return rows


def _csv_cell(value, kind: str) -> str:
    if value is None:
        return "\\N"
    if kind == "boolean":
        return "TRUE" if value else "FALSE"
    if kind == "date":
        return value.isoformat() if isinstance(value, date) else str(value)
    if kind == "decimal":
        return format(value, "f") if isinstance(value, Decimal) else str(value)
    if kind == "integer":
        return str(int(value))
    if isinstance(value, str):
        return value
    raise TypeError(f"unsupported csv cell type: {type(value).__name__}")


def _insert_values(scoped, table_name: str, rows: tuple) -> None:
    for start in range(0, len(rows), 250):
        chunk = rows[start : start + 250]
        values = ", ".join("(" + ", ".join(render_literal(v) for v in row) + ")" for row in chunk)
        scoped.execute(f'INSERT INTO "{table_name}" VALUES {values}')


def _insert_copy(scoped, table_name: str, kinds: tuple[str, ...], rows: tuple) -> None:
    """Trusted-side COPY into the isolated memory DB. File access is closed before SQL."""

    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", suffix=".csv", delete=False
    )
    path = Path(handle.name)
    try:
        writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(_csv_cell(value, kind) for value, kind in zip(row, kinds, strict=True))
        handle.close()
        sql_path = str(path).replace("\\", "/").replace("'", "''")
        scoped.execute(
            f"COPY \"{table_name}\" FROM '{sql_path}' "
            "(FORMAT CSV, HEADER false, NULL '\\N', DATEFORMAT '%Y-%m-%d')"
        )
    finally:
        handle.close()
        path.unlink(missing_ok=True)


def _escape_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/").replace("'", "''")


def _project_via_attach(
    database: str,
    table_names: tuple[str, ...],
    grants: dict,
    catalog,
    policy: AccessPolicy,
    limits: SqlLimits,
    settings: dict,
):
    """Copy authorized rows with one DuckDB join, then detach the source file."""

    load_settings = dict(settings)
    load_settings["enable_external_access"] = "true"
    scoped = duckdb.connect(":memory:", config=load_settings)
    scoped.execute(f"ATTACH '{_escape_path(database)}' AS src (READ_ONLY)")
    scoped.execute('CREATE TABLE authorized_ids ("customer_id" VARCHAR)')
    if policy.customer_ids:
        _insert_copy(
            scoped,
            "authorized_ids",
            ("string",),
            tuple((customer_id,) for customer_id in policy.customer_ids),
        )
        scope = '"customer_id" IN (SELECT "customer_id" FROM authorized_ids)'
    else:
        scope = "FALSE"
    cap = limits.max_input_rows
    for table_name in table_names:
        table = catalog.table(table_name)
        grant = grants[table_name]
        columns = tuple(table.column(name) for name in grant.columns)
        select_columns = ", ".join(f'"{c.column_name}"' for c in columns)
        scoped.execute(
            f'CREATE TABLE "{table_name}" AS SELECT {select_columns} '
            f'FROM src."{table_name}" WHERE {scope} LIMIT {cap + 1}'
        )
        count = scoped.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        if count > cap:
            scoped.execute("DETACH src")
            scoped.close()
            raise _InputLimit()
    scoped.execute("DETACH src")
    scoped.execute("DROP TABLE authorized_ids")
    scoped.execute("SET enable_external_access = false")
    scoped.execute("SET lock_configuration = true")
    return scoped


class _InputLimit(Exception):
    pass


def _cell(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if value is None or type(value) in {int, str, bool}:
        return value
    raise ValueError("unsupported result cell")


def run_worker(
    pipe: Connection, database: str, query: GuardedQuery, policy: AccessPolicy, limits: SqlLimits
) -> None:
    source = scoped = None
    try:
        settings = {
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "threads": "1",
            "memory_limit": f"{limits.memory_mb}MB",
        }
        catalog = load_catalog()
        table_names = query.tables or (query.table,)
        grants = {grant.table: grant for grant in policy.grants}
        use_attach = limits.max_input_rows > _TINY_INPUT_ROWS
        if use_attach:
            try:
                scoped = _project_via_attach(
                    database, table_names, grants, catalog, policy, limits, settings
                )
            except _InputLimit:
                pipe.send(
                    {"error": "INPUT_LIMIT", "message": "fixture materialization limit exceeded"}
                )
                return
        else:
            source = duckdb.connect(database, read_only=True, config=settings)
            materialized: dict[str, tuple[tuple, ...]] = {}
            definitions: dict[str, str] = {}
            for table_name in table_names:
                table = catalog.table(table_name)
                grant = grants[table_name]
                columns = tuple(table.column(name) for name in grant.columns)
                select_columns = ", ".join(f'"{c.column_name}"' for c in columns)
                cap = limits.max_input_rows
                rows = _fetch_scoped_rows(
                    source, select_columns, table_name, policy.customer_ids, cap
                )
                if len(rows) > cap:
                    pipe.send(
                        {
                            "error": "INPUT_LIMIT",
                            "message": "fixture materialization limit exceeded",
                        }
                    )
                    return
                materialized[table_name] = tuple(rows)
                definitions[table_name] = ", ".join(
                    f'"{c.column_name}" {_SQL_TYPES[c.kind]}' for c in columns
                )
            source.close()
            source = None
            scoped = duckdb.connect(":memory:", config=settings)
            for table_name in table_names:
                scoped.execute(f'CREATE TABLE "{table_name}" ({definitions[table_name]})')
                rows = materialized[table_name]
                if not rows:
                    continue
                _insert_values(scoped, table_name, rows)
            scoped.execute("SET lock_configuration = true")
        tree = sqlglot.parse_one(query.sql, read="duckdb")
        if query.contributor_sql:
            contributors = scoped.execute(query.contributor_sql).fetchone()[0]
        elif query.tables:
            contributors = scoped.execute(query.sql).fetchone()[0]
        else:
            where = tree.args.get("where")
            support_sql = f'SELECT COUNT(DISTINCT customer_id) FROM "{query.table}"'
            if where is not None:
                support_sql += " " + where.sql(dialect="duckdb")
            contributors = scoped.execute(support_sql).fetchone()[0]
        if contributors < policy.min_group_size:
            pipe.send(
                {
                    "rejected": "AGGREGATION_TOO_SMALL",
                    "message": "query does not meet minimum aggregation size",
                }
            )
            return
        cursor = scoped.execute(query.sql)
        result_rows = cursor.fetchmany(limits.max_rows + 1)
        result = QueryResult(
            columns=tuple(
                Column(name=item[0], kind=kind)
                for item, kind in zip(cursor.description, query.output_kinds, strict=True)
            ),
            rows=tuple(tuple(_cell(v) for v in row) for row in result_rows[: limits.max_rows]),
            truncated=len(result_rows) > limits.max_rows,
        )
        pipe.send({"result": result.model_dump(mode="json")})
    except Exception:
        # Never send raw DB error/paths/data back across the Agent boundary.
        pipe.send({"error": "EXECUTION_ERROR", "message": "query worker failed"})
    finally:
        if source is not None:
            source.close()
        if scoped is not None:
            scoped.close()
        pipe.close()
