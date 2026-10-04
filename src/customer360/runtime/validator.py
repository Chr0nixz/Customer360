"""Controlled query plan validator.

Performs static authorization, schema, and semantic checks against a QueryPlan
without executing SQL or accessing customer data.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from customer360.contracts.execution import AccessPolicy
from customer360.contracts.validation import (
    PlanPredicate,
    QueryPlanIssue,
    QueryPlanValidationRequest,
    QueryPlanValidationResponse,
)
from customer360.metadata.metrics import EXECUTABLE_JOIN_PATH, MetadataRepository


def _is_valid_date_str(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    try:
        date.fromisoformat(val)
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_decimal_literal(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        try:
            d = Decimal(val)
            return d.is_finite()
        except (InvalidOperation, ValueError, TypeError):
            return False
    return False


def validate_query_plan(
    request: QueryPlanValidationRequest,
    repository: MetadataRepository,
    policy: AccessPolicy | None = None,
) -> QueryPlanValidationResponse:
    """Validate a candidate query plan against metadata and security policy."""
    issues: list[QueryPlanIssue] = []

    # 1. Check source table
    granted_tables: set[str] | None = None
    granted_columns: dict[str, set[str]] | None = None
    if policy is not None:
        granted_tables = {grant.table for grant in policy.grants}
        granted_columns = {grant.table: set(grant.columns) for grant in policy.grants}

    catalog = repository.catalog
    table_def = None
    try:
        table_def = catalog.table(request.source_table)
    except KeyError:
        issues.append(
            QueryPlanIssue(
                code="UNKNOWN_SOURCE_TABLE",
                field=request.source_table,
                message=f"Table '{request.source_table}' is unknown or not declared in catalog.",
            )
        )

    if table_def is not None and granted_tables is not None:
        if request.source_table not in granted_tables:
            issues.append(
                QueryPlanIssue(
                    code="UNKNOWN_SOURCE_TABLE",
                    field=request.source_table,
                    message=f"Table '{request.source_table}' is not granted in policy.",
                )
            )

    # 2. Check operation
    if request.operation not in {"count", "count_distinct", "sum"}:
        issues.append(
            QueryPlanIssue(
                code="UNSUPPORTED_OPERATION",
                message=f"Operation '{request.operation}' is not supported.",
            )
        )

    # 3. Check measure column
    if table_def is not None:
        try:
            measure_col = table_def.column(request.measure_column)
            if granted_columns is not None:
                if request.measure_column not in granted_columns.get(request.source_table, set()):
                    issues.append(
                        QueryPlanIssue(
                            code="INVALID_MEASURE_COLUMN",
                            field=request.measure_column,
                            message=f"Column '{request.measure_column}' is not granted.",
                        )
                    )
            if request.operation == "sum" and measure_col.kind != "decimal":
                issues.append(
                    QueryPlanIssue(
                        code="INVALID_MEASURE_COLUMN",
                        field=request.measure_column,
                        message=f"SUM requires decimal measure, got '{measure_col.kind}'.",
                    )
                )
        except KeyError:
            issues.append(
                QueryPlanIssue(
                    code="INVALID_MEASURE_COLUMN",
                    field=request.measure_column,
                    message=f"Column '{request.measure_column}' not in '{request.source_table}'.",
                )
            )

    # 4. Check join path
    join_target_def = None
    if request.join_path is not None:
        if request.join_path != EXECUTABLE_JOIN_PATH:
            issues.append(
                QueryPlanIssue(
                    code="UNSUPPORTED_JOIN_PATH",
                    field=request.join_path,
                    message=f"Join path '{request.join_path}' is not an executable reviewed path.",
                )
            )
        else:
            try:
                join_target_def = catalog.table("fact_transaction")
                if granted_tables is not None and "fact_transaction" not in granted_tables:
                    issues.append(
                        QueryPlanIssue(
                            code="UNSUPPORTED_JOIN_PATH",
                            field="fact_transaction",
                            message="Join target table 'fact_transaction' is not granted.",
                        )
                    )
            except KeyError:
                issues.append(
                    QueryPlanIssue(
                        code="UNSUPPORTED_JOIN_PATH",
                        field="fact_transaction",
                        message="Table 'fact_transaction' does not exist in catalog.",
                    )
                )

    # 5. Check predicates (allowed columns, type compatibility)
    has_transaction_success_filter = False
    for pred in request.predicates:
        target_table_def = table_def
        target_table_name = request.source_table
        if pred.alias == "t" and join_target_def is not None:
            target_table_def = join_target_def
            target_table_name = "fact_transaction"

        # Check column existence & grant
        col_def = None
        if target_table_def is not None:
            try:
                col_def = target_table_def.column(pred.field)
                if granted_columns is not None:
                    if pred.field not in granted_columns.get(target_table_name, set()):
                        issues.append(
                            QueryPlanIssue(
                                code="DISALLOWED_FILTER_COLUMN",
                                field=pred.field,
                                message=f"Filter '{pred.field}' is not granted.",
                            )
                        )
            except KeyError:
                issues.append(
                    QueryPlanIssue(
                        code="DISALLOWED_FILTER_COLUMN",
                        field=pred.field,
                        message=f"Filter '{pred.field}' not in table '{target_table_name}'.",
                    )
                )

        # Check join specific required predicate
        if (
            target_table_name == "fact_transaction"
            and pred.field == "status"
            and pred.operator == "eq"
            and ("success",) in (pred.values,)
        ):
            has_transaction_success_filter = True

        # Check predicate literals compatibility
        if col_def is not None:
            _check_predicate_literals(pred, col_def, issues)

    # 6. Check required join predicates
    if request.join_path == EXECUTABLE_JOIN_PATH and not has_transaction_success_filter:
        issues.append(
            QueryPlanIssue(
                code="INVALID_JOIN_PREDICATES",
                field="status",
                message="Join with fact_transaction requires 'status = success' predicate.",
            )
        )

    # 7. Check group_by dimensions
    if request.group_by:
        if request.join_path is not None:
            issues.append(
                QueryPlanIssue(
                    code="INVALID_GROUP_DIMENSION",
                    message="group_by is not permitted on join queries.",
                )
            )
        if len(set(request.group_by)) != len(request.group_by):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_GROUP_DIMENSION",
                    message="duplicate group_by dimension.",
                )
            )
        if table_def is not None:
            for g_field in request.group_by:
                try:
                    table_def.column(g_field)
                    if granted_columns is not None:
                        if g_field not in granted_columns.get(request.source_table, set()):
                            issues.append(
                                QueryPlanIssue(
                                    code="INVALID_GROUP_DIMENSION",
                                    field=g_field,
                                    message=f"Group column '{g_field}' is not granted.",
                                )
                            )
                except KeyError:
                    issues.append(
                        QueryPlanIssue(
                            code="INVALID_GROUP_DIMENSION",
                            field=g_field,
                            message=f"Group column '{g_field}' not in '{request.source_table}'.",
                        )
                    )

    return QueryPlanValidationResponse(
        is_valid=len(issues) == 0,
        issues=tuple(issues),
    )


def _check_predicate_literals(
    pred: PlanPredicate,
    col_def: Any,
    issues: list[QueryPlanIssue],
) -> None:
    """Validate literal arity and type consistency against column definition."""
    op = pred.operator
    expected_count = 0 if op in {"is_null", "is_not_null"} else (None if op == "in" else 1)

    if expected_count == 0 and pred.values:
        issues.append(
            QueryPlanIssue(
                code="INVALID_PREDICATE_LITERAL",
                field=pred.field,
                message=f"Operator '{op}' must not specify values.",
            )
        )
        return

    if expected_count == 1 and len(pred.values) != 1:
        issues.append(
            QueryPlanIssue(
                code="INVALID_PREDICATE_LITERAL",
                field=pred.field,
                message=f"Operator '{op}' requires exactly one value.",
            )
        )
        return

    if op == "in" and not pred.values:
        issues.append(
            QueryPlanIssue(
                code="INVALID_PREDICATE_LITERAL",
                field=pred.field,
                message="Operator 'in' requires non-empty values.",
            )
        )
        return

    kind = col_def.kind
    for val in pred.values:
        if val is None:
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Null literal not permitted in '{op}'; use is_null/is_not_null.",
                )
            )
            continue

        if kind == "boolean" and not isinstance(val, bool):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Expected boolean for '{pred.field}', got {type(val).__name__}.",
                )
            )
        elif kind == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Expected integer for '{pred.field}', got {type(val).__name__}.",
                )
            )
        elif kind == "date" and not _is_valid_date_str(val):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Expected ISO date for '{pred.field}', got '{val}'.",
                )
            )
        elif kind == "decimal" and not _is_valid_decimal_literal(val):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Expected numeric literal for decimal '{pred.field}', got '{val}'.",
                )
            )
        elif kind == "string" and not isinstance(val, str):
            issues.append(
                QueryPlanIssue(
                    code="INVALID_PREDICATE_LITERAL",
                    field=pred.field,
                    message=f"Expected string for '{pred.field}', got {type(val).__name__}.",
                )
            )
