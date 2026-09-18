from customer360.contracts.execution import SqlLimits
from customer360.contracts.public import QueryResult
from customer360.errors import QueryRejected
from customer360.safety.sql_guard import GuardedQuery


def validate_result(result: QueryResult, guarded: GuardedQuery, limits: SqlLimits) -> QueryResult:
    if result.truncated or len(result.rows) > limits.max_rows:
        raise QueryRejected("UNSAFE_SQL", "result exceeds row limit")
    if tuple(column.name for column in result.columns) != guarded.output_names:
        raise QueryRejected("UNSAFE_SQL", "result columns do not match the guarded query")
    if tuple(column.kind for column in result.columns) != guarded.output_kinds:
        raise QueryRejected("UNSAFE_SQL", "result types do not match the guarded query")
    if any(len(row) != len(result.columns) for row in result.rows):
        raise QueryRejected("UNSAFE_SQL", "malformed result")
    return result
