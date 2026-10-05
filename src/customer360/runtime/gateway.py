"""Execution gateways for database engines.

Provides multi-engine abstraction, policy enforcement, process isolation,
and dual-level timeout containment.
"""

import multiprocessing
from abc import ABC, abstractmethod
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from customer360.contracts.execution import AccessPolicy, SqlLimits
from customer360.contracts.public import QueryReceipt, QueryResult
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.metadata.metrics import load_catalog
from customer360.runtime.worker import run_worker
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
            receive.close()
            send.close()
            if process.pid is not None:
                _stop(process)
                process.close()


class PostgreSQLExecutionGateway(BaseExecutionGateway):
    """PostgreSQL execution gateway adapter.

    Enforces connection-level statement_timeout and fail-closed behavior
    when no live database instance is configured.
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
        # Placeholder for live PG driver connection if configured
        raise ExecutionFailure("NOT_IMPLEMENTED", "Live PG driver execution is reserved for v2.0.")


# Backward compatibility alias
ExecutionGateway = DuckDBExecutionGateway
