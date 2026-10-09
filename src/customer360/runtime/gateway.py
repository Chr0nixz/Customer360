"""Execution gateways for database engines.

Provides multi-engine abstraction, policy enforcement, process isolation,
and dual-level timeout containment.
"""

import multiprocessing
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from customer360.contracts.execution import AccessPolicy, SqlLimits
from customer360.contracts.public import Column, QueryReceipt, QueryResult
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.metadata.metrics import load_catalog
from customer360.runtime.dialects import transpile_sql
from customer360.runtime.worker import execute_worker_query, run_worker
from customer360.safety.result_guard import validate_result
from customer360.safety.sql_guard import validate_sql


def _stop(process: multiprocessing.Process) -> None:
    """Forcefully terminate and clean up a worker process to prevent hanging handles."""
    try:
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
    except (OSError, ValueError):
        pass


class BaseExecutionGateway(ABC):
    """Abstract base for execution engines enforcing authorization, limits, and isolation."""

    def __init__(self, policy: AccessPolicy, limits: SqlLimits | None = None):
        self.policy = policy
        self.limits = limits or SqlLimits()
        self.catalog = load_catalog()

    @property
    @abstractmethod
    def engine_name(self) -> str: ...

    @abstractmethod
    def execute(self, sql: str) -> QueryReceipt: ...


class DuckDBExecutionGateway(BaseExecutionGateway):
    """Trusted DuckDB execution boundary running within isolated child processes."""

    def __init__(self, database: Path, policy: AccessPolicy, limits: SqlLimits | None = None):
        super().__init__(policy, limits)
        self.database = database.resolve(strict=True)
        for grant in policy.grants:
            try:
                table = self.catalog.table(grant.table)
                columns = [table.column(c) for c in grant.columns]
            except KeyError as exc:
                raise QueryRejected("PERMISSION_DENIED", "invalid configured grant") from exc
            if table.scope != "customer" or "customer_id" not in grant.columns:
                raise QueryRejected(
                    "UNSUPPORTED_QUERY", "v0.1 only supports customer-scoped tables"
                )
            if any(c.sensitivity == "restricted" for c in columns):
                raise QueryRejected("PERMISSION_DENIED", "restricted columns cannot be granted")

    @property
    def engine_name(self) -> str:
        return "duckdb"

    def execute(self, sql: str) -> QueryReceipt:
        guarded = validate_sql(sql, self.catalog, self.policy, self.limits)
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=run_worker,
            args=(send, str(self.database), guarded, self.policy, self.limits),
            daemon=True,
        )
        started = perf_counter()
        try:
            process.start()
            send.close()
            # Dual-level timeout check
            if not receive.poll(self.limits.timeout_seconds):
                raise ExecutionFailure("TIMEOUT", "query exceeded its wall-clock budget")
            try:
                payload = receive.recv()
            except EOFError as exc:
                raise ExecutionFailure(
                    "WORKER_CRASH", "query worker exited without a result"
                ) from exc
            if "rejected" in payload:
                raise QueryRejected(payload["rejected"], payload["message"])
            if "error" in payload:
                raise ExecutionFailure(payload["error"], payload["message"])
            result = QueryResult.model_validate(payload["result"])
            validate_result(result, guarded, self.limits)
            return QueryReceipt(
                query_id=uuid4().hex,
                result=result,
                elapsed_ms=(perf_counter() - started) * 1000,
            )
        finally:
            try:
                receive.close()
            except OSError:
                pass
            try:
                send.close()
            except OSError:
                pass
            if process.pid is not None:
                _stop(process)
                try:
                    process.close()
                except OSError:
                    pass

    def execute_direct(self, sql: str) -> QueryReceipt:
        """Internal trusted-side direct execution without worker spawn.

        WARNING: Strictly restricted to trusted offline dataset verification.
        Never expose this method to benchmarked agents or untrusted callers.
        External/eval calls must strictly invoke `execute()` to maintain OS-level
        process isolation, wall-clock timeout killing, and resource fencing.
        """
        guarded = validate_sql(sql, self.catalog, self.policy, self.limits)
        started = perf_counter()
        payload = execute_worker_query(str(self.database), guarded, self.policy, self.limits)
        if "rejected" in payload:
            raise QueryRejected(payload["rejected"], payload["message"])
        if "error" in payload:
            raise ExecutionFailure(payload["error"], payload["message"])
        result = QueryResult.model_validate(payload["result"])
        validate_result(result, guarded, self.limits)
        return QueryReceipt(
            query_id=uuid4().hex,
            result=result,
            elapsed_ms=(perf_counter() - started) * 1000,
        )

    # Explicit trusted alias for verify scripts
    execute_trusted_direct = execute_direct


def _get_pg_driver():
    try:
        import psycopg

        return psycopg
    except ImportError:
        try:
            import psycopg2

            return psycopg2
        except ImportError:
            return None


def _pg_cell(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or type(value) in {int, str, bool}:
        return value
    if isinstance(value, float):
        return str(Decimal(str(value)))
    return str(value)


def _infer_pg_kind(val: object) -> str:
    if isinstance(val, (int, bool)) and not isinstance(val, bool):
        return "integer"
    if isinstance(val, (Decimal, float)):
        return "decimal"
    if isinstance(val, (date, datetime)):
        return "date"
    return "string"


class PostgreSQLExecutionGateway(BaseExecutionGateway):
    """PostgreSQL execution gateway adapter.

    Enforces connection-level statement_timeout, transaction read-only fences,
    and automatic SQL transpilation from DuckDB to PostgreSQL.
    """

    def __init__(
        self,
        connection_uri: str | None,
        policy: AccessPolicy,
        limits: SqlLimits | None = None,
    ):
        super().__init__(policy, limits)
        self.connection_uri = connection_uri

    @property
    def engine_name(self) -> str:
        return "postgres"

    def execute(self, sql: str) -> QueryReceipt:
        if not self.connection_uri:
            raise QueryRejected(
                "ENGINE_UNAVAILABLE",
                "PostgreSQL live execution engine is not configured; "
                "dialect transpilation and AST checks remain active.",
            )
        pg = _get_pg_driver()
        if pg is None:
            raise QueryRejected(
                "ENGINE_UNAVAILABLE",
                "PostgreSQL driver (psycopg or psycopg2) is not installed in the environment.",
            )

        transpile_res = transpile_sql(sql, source_dialect="duckdb", target_dialect="postgres")
        if not transpile_res.ast_valid:
            raise QueryRejected(
                "UNSUPPORTED_QUERY",
                f"SQL transpilation failed: {transpile_res.differences}",
            )
        pg_sql = transpile_res.transpiled_sql

        started = perf_counter()
        timeout_ms = int(self.limits.timeout_seconds * 1000)
        try:
            with pg.connect(self.connection_uri) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;")
                    cur.execute(f"SET statement_timeout = {timeout_ms};")
                    cur.execute(pg_sql)
                    raw_rows = cur.fetchmany(self.limits.max_rows + 1)
                    truncated = len(raw_rows) > self.limits.max_rows
                    rows = raw_rows[: self.limits.max_rows]
                    desc = cur.description or []
                    sample_row = rows[0] if rows else ()
                    columns = tuple(
                        Column(
                            name=col[0],
                            kind=_infer_pg_kind(sample_row[idx])
                            if idx < len(sample_row)
                            else "string",
                        )
                        for idx, col in enumerate(desc)
                    )
                    receipt_rows = tuple(tuple(_pg_cell(v) for v in row) for row in rows)
                    result = QueryResult(
                        columns=columns,
                        rows=receipt_rows,
                        truncated=truncated,
                    )
                    return QueryReceipt(
                        query_id=uuid4().hex,
                        result=result,
                        elapsed_ms=(perf_counter() - started) * 1000,
                    )
        except Exception as exc:
            err_str = str(exc)
            if "statement_timeout" in err_str.lower() or "timeout" in err_str.lower():
                raise ExecutionFailure(
                    "TIMEOUT", "query exceeded statement_timeout budget"
                ) from exc
            raise ExecutionFailure(
                "EXECUTION_ERROR", f"PostgreSQL live query failed: {err_str}"
            ) from exc


# Backward compatibility alias
ExecutionGateway = DuckDBExecutionGateway
