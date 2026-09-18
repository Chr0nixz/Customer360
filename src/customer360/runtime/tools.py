from collections.abc import Callable
from typing import Any, TypeVar

from customer360.contracts.execution import ExecutionRecord
from customer360.contracts.public import QueryReceipt
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway

T = TypeVar("T")


class ToolSession:
    """Trusted host implementation. Pass its AgentTools interface, not oracle objects."""

    def __init__(self, gateway: ExecutionGateway, repository: MetadataRepository):
        self._gateway = gateway
        self._repository = repository
        self._records: dict[str, ExecutionRecord] = {}
        self.rejections: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def _grants(self) -> dict[str, set[str]]:
        return {grant.table: set(grant.columns) for grant in self._gateway.policy.grants}

    def _trace(self, tool: str, arguments: dict[str, object], fn: Callable[[], T]) -> T:
        try:
            result = fn()
        except QueryRejected as exc:
            self.calls.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "rejected": True,
                    "rejection_code": exc.code,
                    "execution_code": None,
                    "failure_kind": "policy",
                }
            )
            # Every rejected tool request is a policy event.  Keeping this
            # outside the SQL-only branch prevents an Agent from probing a
            # denied metadata surface and then presenting a successful answer.
            self.rejections.append(exc.code)
            raise
        except ExecutionFailure as exc:
            self.calls.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "rejected": False,
                    "rejection_code": None,
                    "execution_code": exc.code,
                    "failure_kind": "execution",
                    "sql": arguments.get("sql"),
                }
            )
            raise
        except Exception as exc:
            # Do not leak repository/driver details across the Agent boundary,
            # but keep a stable, auditable failure code for the evaluator.
            self.calls.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "rejected": False,
                    "rejection_code": None,
                    "execution_code": "EXECUTION_ERROR",
                    "failure_kind": "execution",
                    "sql": arguments.get("sql"),
                }
            )
            raise ExecutionFailure("EXECUTION_ERROR", "tool execution failed") from exc
        entry: dict[str, Any] = {
            "tool": tool,
            "arguments": arguments,
            "rejected": False,
            "rejection_code": None,
            "execution_code": None,
            "failure_kind": None,
        }
        if tool == "execute_sql":
            receipt = result  # type: ignore[assignment]
            assert isinstance(receipt, QueryReceipt)
            self._records[receipt.query_id] = ExecutionRecord(
                query_id=receipt.query_id,
                sql=str(arguments["sql"]),
                result=receipt.result,
                elapsed_ms=receipt.elapsed_ms,
            )
            entry["query_id"] = receipt.query_id
            entry["sql"] = arguments["sql"]
            entry["truncated"] = receipt.result.truncated
            entry["row_count"] = len(receipt.result.rows)
            entry["result"] = receipt.result
        self.calls.append(entry)
        return result

    def execute_sql(self, sql: str) -> QueryReceipt:
        return self._trace("execute_sql", {"sql": sql}, lambda: self._gateway.execute(sql))

    def search_tables(self, query: str) -> tuple[dict, ...]:
        def run() -> tuple[dict, ...]:
            granted = set(self._grants())
            return tuple(
                hit.model_dump(mode="json")
                for hit in self._repository.table_hits(query)
                if hit.table_name in granted
            )

        return self._trace("search_tables", {"query": query}, run)

    def search_columns(self, query: str) -> tuple[dict, ...]:
        def run() -> tuple[dict, ...]:
            grants = self._grants()
            return tuple(
                hit.model_dump(mode="json")
                for hit in self._repository.search_columns(query)
                if hit.column_name in grants.get(hit.table_name, set())
            )

        return self._trace("search_columns", {"query": query}, run)

    def _authorized_metrics(self, query: str) -> tuple[dict, ...]:
        grants = self._grants()
        result = []
        for metric in self._repository.search_metrics(query):
            required = {
                metric.measure_column,
                *metric.fixed_filters.keys(),
                *metric.fixed_null_columns,
            }
            if metric.time_column:
                required.add(metric.time_column)
            if required <= grants.get(metric.source_table, set()):
                result.append(metric.model_dump(mode="json"))
        return tuple(result)

    def search_metrics(self, query: str) -> tuple[dict, ...]:
        return self._trace(
            "search_metrics", {"query": query}, lambda: self._authorized_metrics(query)
        )

    def get_table_schema(self, table_name: str) -> tuple[dict, ...]:
        def run() -> tuple[dict, ...]:
            grant = next(
                (item for item in self._gateway.policy.grants if item.table == table_name),
                None,
            )
            if grant is None:
                raise QueryRejected("PERMISSION_DENIED", "table is not granted")
            table = self._repository.get_table_schema(table_name)
            return tuple(table.column(name).model_dump(mode="json") for name in grant.columns)

        return self._trace("get_table_schema", {"table_name": table_name}, run)

    def get_metric_definition(self, metric_name: str) -> dict:
        def run() -> dict:
            authorized = {item["metric_name"]: item for item in self._authorized_metrics("")}
            if metric_name in authorized:
                return authorized[metric_name]
            try:
                self._repository.get_metric_definition(metric_name)
            except KeyError as exc:
                raise QueryRejected("UNKNOWN_METRIC", "metric is not defined") from exc
            raise QueryRejected("PERMISSION_DENIED", "metric is not granted")

        return self._trace("get_metric_definition", {"metric_name": metric_name}, run)

    def get_business_glossary(self, term: str) -> tuple[dict, ...]:
        def run() -> tuple[dict, ...]:
            grants = self._grants()
            authorized_metrics = {item["metric_name"] for item in self._authorized_metrics("")}
            visible: list[dict] = []
            for entry in self._repository.get_business_glossary(term):
                if entry.kind == "table" and entry.table_name not in grants:
                    continue
                if entry.kind == "column" and entry.column_name not in grants.get(
                    entry.table_name or "", set()
                ):
                    continue
                if entry.kind == "metric" and entry.metric_name not in authorized_metrics:
                    continue
                visible.append(entry.model_dump(mode="json"))
            return tuple(visible)

        return self._trace("get_business_glossary", {"term": term}, run)

    def get_join_paths(self, query: str) -> tuple[dict, ...]:
        def run() -> tuple[dict, ...]:
            grants = set(self._grants())
            return tuple(
                path.model_dump(mode="json")
                for path in self._repository.get_join_paths(query)
                if path.tables() <= grants
            )

        return self._trace("get_join_paths", {"query": query}, run)

    def lookup_execution(self, query_id: str) -> ExecutionRecord:
        """Host-only: results must originate from THIS session."""
        return self._records[query_id]
