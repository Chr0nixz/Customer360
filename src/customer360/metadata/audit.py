"""Static metadata integrity auditor.

Validates catalog schema consistency, metric referential integrity,
deprecation topologies, and join path closures.
"""

from customer360.contracts.audit import MetadataAuditIssue, MetadataAuditReport
from customer360.metadata.metrics import (
    EXECUTABLE_JOIN_PATH,
    UNDECLARED_ENTITY_FIELDS,
    MetadataRepository,
)


def audit_metadata(repository: MetadataRepository) -> MetadataAuditReport:
    """Run a comprehensive static integrity audit across metadata models."""
    issues: list[MetadataAuditIssue] = []
    catalog = repository.catalog
    metrics = repository.metrics
    join_paths = repository.join_paths

    # 1. Catalog schema & sensitive field boundary
    table_map = {}
    for table in catalog.tables:
        table_map[table.table_name] = table
        col_names = {col.column_name for col in table.columns}
        blocked = col_names & UNDECLARED_ENTITY_FIELDS
        if blocked:
            b_field = sorted(blocked)[0]
            issues.append(
                MetadataAuditIssue(
                    code="UNDECLARED_ENTITY_FIELD",
                    target=table.table_name,
                    message=f"Table '{table.table_name}' declares forbidden field '{b_field}'.",
                )
            )

    # 2. Metric referential integrity
    metric_map = {m.metric_name: m for m in metrics.metrics}
    for m in metrics.metrics:
        # Source table check
        if m.source_table not in table_map:
            issues.append(
                MetadataAuditIssue(
                    code="BROKEN_TABLE_REFERENCE",
                    target=m.metric_name,
                    message=f"Metric references unknown source table '{m.source_table}'.",
                )
            )
            continue

        table = table_map[m.source_table]
        col_names = {col.column_name for col in table.columns}

        # Measure column check
        if m.measure_column not in col_names:
            issues.append(
                MetadataAuditIssue(
                    code="BROKEN_COLUMN_REFERENCE",
                    target=m.metric_name,
                    message=f"Measure '{m.measure_column}' not in table '{m.source_table}'.",
                )
            )
        else:
            col_def = table.column(m.measure_column)
            if m.operation == "sum" and col_def.kind != "decimal":
                issues.append(
                    MetadataAuditIssue(
                        code="INVALID_MEASURE_TYPE",
                        target=m.metric_name,
                        message=f"SUM operation requires decimal measure, got '{col_def.kind}'.",
                    )
                )

        # Time column check
        if m.time_column:
            if m.time_column not in col_names:
                issues.append(
                    MetadataAuditIssue(
                        code="BROKEN_COLUMN_REFERENCE",
                        target=m.metric_name,
                        message=f"Time column '{m.time_column}' not in table '{m.source_table}'.",
                    )
                )
            else:
                col_def = table.column(m.time_column)
                if col_def.kind != "date":
                    issues.append(
                        MetadataAuditIssue(
                            code="INVALID_TIME_COLUMN_TYPE",
                            target=m.metric_name,
                            message=f"Time column must be DATE, got '{col_def.kind}'.",
                        )
                    )

        # Filter columns check
        all_referenced_cols = (
            *m.fixed_filters.keys(),
            *m.fixed_null_columns,
            *m.allowed_filter_columns,
            *m.allowed_group_dimensions,
        )
        for ref_col in all_referenced_cols:
            if ref_col not in col_names:
                issues.append(
                    MetadataAuditIssue(
                        code="BROKEN_COLUMN_REFERENCE",
                        target=m.metric_name,
                        message=f"Referenced column '{ref_col}' not in table '{m.source_table}'.",
                    )
                )

        # 3. Deprecation topology check
        if m.replaced_by:
            if m.replaced_by not in metric_map:
                issues.append(
                    MetadataAuditIssue(
                        code="BROKEN_DEPRECATION_TARGET",
                        target=m.metric_name,
                        message=f"Metric replacement target '{m.replaced_by}' does not exist.",
                    )
                )
            else:
                target_metric = metric_map[m.replaced_by]
                if target_metric.status == "retired":
                    issues.append(
                        MetadataAuditIssue(
                            code="DEAD_DEPRECATION_CHAIN",
                            target=m.metric_name,
                            message=f"Metric replacement '{m.replaced_by}' is also retired.",
                        )
                    )

            # Cycle detection
            visited = [m.metric_name]
            curr = m.replaced_by
            while curr and curr in metric_map:
                if curr in visited:
                    cycle_str = " -> ".join([*visited, curr])
                    issues.append(
                        MetadataAuditIssue(
                            code="CIRCULAR_DEPRECATION",
                            target=m.metric_name,
                            message=f"Circular deprecation detected: {cycle_str}.",
                        )
                    )
                    break
                visited.append(curr)
                curr = metric_map[curr].replaced_by

    # 4. Join path topology closure
    executable_count = 0
    for jp in join_paths.paths:
        if jp.compile_status == "executable":
            executable_count += 1
            if jp.path_name != EXECUTABLE_JOIN_PATH:
                issues.append(
                    MetadataAuditIssue(
                        code="INVALID_EXECUTABLE_JOIN_PATH",
                        target=jp.path_name,
                        message=f"Expected '{EXECUTABLE_JOIN_PATH}', got '{jp.path_name}'.",
                    )
                )

        for hop in jp.hops:
            for t_name, c_name in (
                (hop.left_table, hop.left_column),
                (hop.right_table, hop.right_column),
            ):
                if t_name not in table_map:
                    issues.append(
                        MetadataAuditIssue(
                            code="BROKEN_JOIN_TABLE",
                            target=jp.path_name,
                            message=f"Join hop references unknown table '{t_name}'.",
                        )
                    )
                elif c_name not in {col.column_name for col in table_map[t_name].columns}:
                    issues.append(
                        MetadataAuditIssue(
                            code="BROKEN_JOIN_COLUMN",
                            target=jp.path_name,
                            message=f"Join hop column '{c_name}' not found on table '{t_name}'.",
                        )
                    )

    if executable_count != 1:
        issues.append(
            MetadataAuditIssue(
                code="EXECUTABLE_JOIN_COUNT_INVALID",
                target="join_paths",
                message=f"Expected exactly 1 executable join path, found {executable_count}.",
            )
        )

    passed = len(issues) == 0
    summary = (
        f"Metadata Audit: {len(catalog.tables)} tables, {len(metrics.metrics)} metrics, "
        f"{len(join_paths.paths)} join paths audited. "
        f"Issues found: {len(issues)}. Passed: {passed}."
    )

    return MetadataAuditReport(
        tables_count=len(catalog.tables),
        metrics_count=len(metrics.metrics),
        join_paths_count=len(join_paths.paths),
        issues=tuple(issues),
        passed=passed,
        summary=summary,
    )
