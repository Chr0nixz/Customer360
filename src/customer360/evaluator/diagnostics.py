"""Failure diagnostics engine.

Extracts business quadruples and aggregates dimensional failure stats.
All outputs are desensitized and safe for public reporting.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from customer360.artifacts import write_json_new
from customer360.contracts.diagnostics import (
    CaseFailureAttribution,
    DiagnosticQuadruple,
    DiagnosticSummary,
    DimensionFailureAggregation,
)
from customer360.contracts.matrix import PUBLIC_MATRIX_FORBIDDEN
from customer360.contracts.public import QueryResult
from customer360.contracts.semantic import SemanticSpec


def extract_quadruple_from_spec(spec: SemanticSpec | None) -> DiagnosticQuadruple:
    """Extract the four business facets from a semantic specification."""
    if spec is None:
        return DiagnosticQuadruple()

    metric_name = getattr(spec, "metric", None) or getattr(spec, "metric_name", None)
    filters = getattr(spec, "filters", ())
    filter_dims = tuple(str(f.field) for f in filters if hasattr(f, "field"))

    time_kind = None
    time_window = getattr(spec, "time_window", None)
    if time_window is not None:
        time_kind = getattr(time_window, "type", "window")
    elif getattr(spec, "latest_snapshot", False):
        time_kind = "latest_snapshot"

    join_path = None
    join_spec = getattr(spec, "join", None)
    if join_spec is not None:
        join_path = getattr(join_spec, "path", None)

    return DiagnosticQuadruple(
        metric_name=str(metric_name) if metric_name else None,
        filter_dimensions=filter_dims,
        time_kind=str(time_kind) if time_kind else None,
        join_path=str(join_path) if join_path else None,
    )


def compute_diff_summary(actual: QueryResult | None, expected: QueryResult | None) -> str | None:
    """Produce a safe, desensitized diff summary between actual and expected results."""
    if actual is None and expected is None:
        return None
    if actual is None:
        return "actual_result_missing"
    if expected is None:
        return "expected_result_missing"

    if actual.truncated:
        return "actual_result_truncated"
    if expected.truncated:
        return "expected_result_truncated"

    if [c.name for c in actual.columns] != [c.name for c in expected.columns]:
        actual_cols = ",".join(c.name for c in actual.columns)
        expected_cols = ",".join(c.name for c in expected.columns)
        return f"columns_mismatch: actual=[{actual_cols}] vs expected=[{expected_cols}]"

    len_act = len(actual.rows)
    len_exp = len(expected.rows)
    if len_act != len_exp:
        return f"row_count_mismatch: actual={len_act}, expected={len_exp}"

    # If row count matches but compare failed, it's a value/ordering deviation
    return "row_values_or_multiplicity_mismatch"


def build_diagnostic_summary(
    *,
    total_count: int,
    passed_count: int,
    attributions: Iterable[CaseFailureAttribution],
    all_quadruples: Iterable[DiagnosticQuadruple] | None = None,
) -> DiagnosticSummary:
    """Aggregate failure attributions across metric, filter, time, and join dimensions."""
    attr_list = tuple(attributions)
    failed_count = len(attr_list)
    pass_rate = passed_count / total_count if total_count > 0 else 0.0

    # Count total occurrences of each dimension if provided, else baseline on attributions
    totals: dict[tuple[str, str], int] = Counter()
    if all_quadruples is not None:
        for quad in all_quadruples:
            if quad.metric_name:
                totals[("metric", quad.metric_name)] += 1
            for f in quad.filter_dimensions:
                totals[("filter", f)] += 1
            if quad.time_kind:
                totals[("time", quad.time_kind)] += 1
            if quad.join_path:
                totals[("join", quad.join_path)] += 1

    # Count failures and failure codes per dimension
    failed_counts: dict[tuple[str, str], int] = Counter()
    codes_by_dim: dict[tuple[str, str], list[str]] = defaultdict(list)

    for attr in attr_list:
        q = attr.quadruple
        code = attr.primary_failure_code

        if q.metric_name:
            key = ("metric", q.metric_name)
            failed_counts[key] += 1
            codes_by_dim[key].append(code)
            if key not in totals:
                totals[key] = failed_counts[key]

        for f in q.filter_dimensions:
            key = ("filter", f)
            failed_counts[key] += 1
            codes_by_dim[key].append(code)
            if key not in totals:
                totals[key] = failed_counts[key]

        if q.time_kind:
            key = ("time", q.time_kind)
            failed_counts[key] += 1
            codes_by_dim[key].append(code)
            if key not in totals:
                totals[key] = failed_counts[key]

        if q.join_path:
            key = ("join", q.join_path)
            failed_counts[key] += 1
            codes_by_dim[key].append(code)
            if key not in totals:
                totals[key] = failed_counts[key]

    aggregations: list[DimensionFailureAggregation] = []
    for (dim_type, dim_val), tot in totals.items():
        fails = failed_counts[(dim_type, dim_val)]
        rate = fails / tot if tot > 0 else 0.0
        code_counts = Counter(codes_by_dim[(dim_type, dim_val)]).most_common(3)
        aggregations.append(
            DimensionFailureAggregation(
                dimension_type=dim_type,  # type: ignore[arg-type]
                dimension_value=dim_val,
                total_cases=tot,
                failed_cases=fails,
                failure_rate=round(rate, 4),
                top_failure_codes=tuple((code, cnt) for code, cnt in code_counts),
            )
        )

    # Sort aggregations: highest failure rate first, then total cases desc
    aggregations.sort(key=lambda a: (-a.failure_rate, -a.total_cases, a.dimension_value))

    limitations = (
        "Desensitized diagnostics summary; Gold queries and private datasets are never disclosed.",
        "Dimension failure rates reflect current test suite distribution.",
    )

    return DiagnosticSummary(
        total_cases=total_count,
        passed_cases=passed_count,
        failed_cases=failed_count,
        pass_rate=round(pass_rate, 4),
        attributions=attr_list,
        aggregations=tuple(aggregations),
        limitations=limitations,
    )


def _esc(text: str | None) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_diagnostic_markdown(summary: DiagnosticSummary) -> str:
    """Render a structured Markdown diagnostics report."""
    lines = [
        "# Customer360 Evaluation Diagnostics",
        "",
        "Fine-grained failure attribution and dimensional aggregations (desensitized).",
        "",
        f"- **Total Cases**: {summary.total_cases}",
        f"- **Passed Cases**: {summary.passed_cases}",
        f"- **Failed Cases**: {summary.failed_cases}",
        f"- **Pass Rate**: {summary.pass_rate:.1%}",
        "",
        "## Dimensional Failure Aggregations",
        "",
        "| Dimension Type | Dimension Value | Total | Failed | Failure Rate | Top Failure Codes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for agg in summary.aggregations:
        codes = ", ".join(f"{c}({cnt})" for c, cnt in agg.top_failure_codes)
        lines.append(
            f"| {agg.dimension_type} | {agg.dimension_value} | {agg.total_cases} | "
            f"{agg.failed_cases} | {agg.failure_rate:.1%} | {codes} |"
        )

    lines.extend(["", "## Failure Attributions Detail", ""])
    if not summary.attributions:
        lines.append("*(No failed cases)*\n")
    else:
        lines.extend(
            [
                "| Case ID | Stage | Failure Code | Metric | Filters | Diff Summary |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for attr in summary.attributions:
            q = attr.quadruple
            filters_str = ",".join(q.filter_dimensions) if q.filter_dimensions else "-"
            lines.append(
                f"| {attr.case_id} | {attr.stage} | {attr.primary_failure_code} | "
                f"{q.metric_name or '-'} | {filters_str} | {attr.diff_summary or '-'} |"
            )

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in summary.limitations)
    lines.append("")
    return "\n".join(lines)


def render_diagnostic_html(summary: DiagnosticSummary) -> str:
    """Render a self-contained, offline-compatible HTML dashboard for diagnostics."""
    agg_rows = []
    for agg in summary.aggregations:
        codes = ", ".join(f"{_esc(c)} ({cnt})" for c, cnt in agg.top_failure_codes)
        rate_cls = "badge-danger" if agg.failure_rate > 0.3 else "badge-warning"
        agg_rows.append(
            f"<tr>"
            f"<td><code>{_esc(agg.dimension_type)}</code></td>"
            f"<td><strong>{_esc(agg.dimension_value)}</strong></td>"
            f"<td>{agg.total_cases}</td>"
            f"<td>{agg.failed_cases}</td>"
            f"<td><span class='badge {rate_cls}'>{agg.failure_rate:.1%}</span></td>"
            f"<td><small>{codes}</small></td>"
            f"</tr>"
        )

    attr_rows = []
    for attr in summary.attributions:
        q = attr.quadruple
        filters_str = ", ".join(_esc(f) for f in q.filter_dimensions) or "-"
        attr_rows.append(
            f"<tr>"
            f"<td><strong>{_esc(attr.case_id)}</strong></td>"
            f"<td><span class='badge badge-stage'>{_esc(attr.stage)}</span></td>"
            f"<td><code>{_esc(attr.primary_failure_code)}</code></td>"
            f"<td>{_esc(q.metric_name) or '-'}</td>"
            f"<td>{filters_str}</td>"
            f"<td><small class='text-muted'>{_esc(attr.diff_summary) or '-'}</small></td>"
            f"</tr>"
        )

    empty_agg = '<tr><td colspan="6" class="text-muted">No aggregations</td></tr>'
    agg_body = "".join(agg_rows) if agg_rows else empty_agg

    empty_attr = '<tr><td colspan="6" class="text-muted">No failed cases</td></tr>'
    attr_body = "".join(attr_rows) if attr_rows else empty_attr

    limits = "".join(f"<li>{_esc(item)}</li>" for item in summary.limitations)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Customer360 Evaluation Diagnostics</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --border: #e2e8f0;
      --primary: #2563eb;
      --success: #16a34a;
      --danger: #dc2626;
      --warning: #d97706;
      --muted: #64748b;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      margin: 0;
      padding: 24px;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    h1, h2 {{
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .header {{
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }}
    .stat-label {{
      font-size: 0.875rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .stat-value {{
      font-size: 1.75rem;
      font-weight: 700;
      margin-top: 4px;
    }}
    .text-success {{ color: var(--success); }}
    .text-danger {{ color: var(--danger); }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 0.9rem;
    }}
    th, td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      background: #f1f5f9;
      font-weight: 600;
    }}
    code {{
      background: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.85em;
    }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .badge-danger {{ background: #fee2e2; color: #991b1b; }}
    .badge-warning {{ background: #fef3c7; color: #92400e; }}
    .badge-stage {{ background: #e0f2fe; color: #0369a1; }}
    .text-muted {{ color: var(--muted); }}
    ul.limitations {{
      font-size: 0.875rem;
      color: var(--muted);
      padding-left: 20px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Customer360 Evaluation Diagnostics</h1>
      <p class="text-muted">
        Fine-grained failure attribution and dimensional aggregations. Desensitized public view.
      </p>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Cases</div>
        <div class="stat-value">{summary.total_cases}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Passed Cases</div>
        <div class="stat-value text-success">{summary.passed_cases}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Failed Cases</div>
        <div class="stat-value text-danger">{summary.failed_cases}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pass Rate</div>
        <div class="stat-value">{summary.pass_rate:.1%}</div>
      </div>
    </div>

    <div class="card">
      <h2>Dimensional Failure Breakdown</h2>
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>Dimension</th>
            <th>Total</th>
            <th>Failed</th>
            <th>Failure Rate</th>
            <th>Top Failure Codes</th>
          </tr>
        </thead>
        <tbody>
          {agg_body}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Failure Attributions Detail</h2>
      <table>
        <thead>
          <tr>
            <th>Case ID</th>
            <th>Stage</th>
            <th>Code</th>
            <th>Metric</th>
            <th>Filters</th>
            <th>Diff Summary</th>
          </tr>
        </thead>
        <tbody>
          {attr_body}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Limitations & Boundaries</h2>
      <ul class="limitations">{limits}</ul>
    </div>
  </div>
</body>
</html>
"""


def diagnose_matrix_run(
    report: Any,
    catalog_cases: Iterable[Any],
) -> DiagnosticSummary:
    """Analyze a matrix run report and human/catalog blueprints to generate a diagnostic summary."""
    case_map = {}
    for case in catalog_cases:
        cid = getattr(case, "case_id", None)
        if cid:
            case_map[cid] = case

    all_quads: list[DiagnosticQuadruple] = []
    attributions: list[CaseFailureAttribution] = []
    passed_cases = 0

    for item in report.cases:
        blueprint = case_map.get(item.case_id)
        spec = getattr(blueprint, "semantic_spec", None)
        if spec is None and hasattr(blueprint, "oracle"):
            oracle_fn = blueprint.oracle
            oracle_obj = oracle_fn() if callable(oracle_fn) else oracle_fn
            spec = getattr(oracle_obj, "semantic_spec", None)

        quad = extract_quadruple_from_spec(spec)
        all_quads.append(quad)

        # Check outcomes across all applicable snapshots
        snapshots = item.snapshots
        failed_snap = None
        for snap in snapshots:
            if snap.applicable == "applicable" and snap.outcome != "pass":
                failed_snap = snap
                break

        if failed_snap is None:
            passed_cases += 1
        else:
            diff_summary = None
            if failed_snap.reason_code:
                diff_summary = f"reason: {failed_snap.reason_code}"
            stage_val = (
                failed_snap.stage
                if failed_snap.stage
                in {"plan", "sql_guard", "execution", "comparison", "interaction"}
                else "execution"
            )
            attributions.append(
                CaseFailureAttribution(
                    case_id=item.case_id,
                    split=item.split,
                    stage=stage_val,  # type: ignore[arg-type]
                    primary_failure_code=failed_snap.reason_code
                    or failed_snap.failure_class
                    or "FAILURE",
                    quadruple=quad,
                    diff_summary=diff_summary,
                )
            )

    return build_diagnostic_summary(
        total_count=len(report.cases),
        passed_count=passed_cases,
        attributions=attributions,
        all_quadruples=all_quads,
    )


def write_diagnostics_report(output_dir: Path, summary: DiagnosticSummary) -> dict[str, Any]:
    """Write desensitized JSON, Markdown, and HTML diagnostic reports to output directory.

    Strictly validates against PUBLIC_MATRIX_FORBIDDEN leakage before returning.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "diagnostics.json"
    md_path = output_dir / "diagnostics.md"
    html_path = output_dir / "diagnostics.html"

    if json_path.exists() or md_path.exists() or html_path.exists():
        raise FileExistsError(f"diagnostics artifacts already exist in {output_dir}")

    payload = summary.model_dump(mode="json")
    write_json_new(json_path, payload)
    md_path.write_text(render_diagnostic_markdown(summary), encoding="utf-8")
    html_path.write_text(render_diagnostic_html(summary), encoding="utf-8")

    # Anti-leakage verification: none of the public artifacts may contain forbidden private keys
    combined_public = (
        json_path.read_text(encoding="utf-8")
        + md_path.read_text(encoding="utf-8")
        + html_path.read_text(encoding="utf-8")
    )
    for field in PUBLIC_MATRIX_FORBIDDEN:
        if f'"{field}"' in combined_public:
            raise ValueError(f"public diagnostics artifacts leaked {field}")

    return {
        "total_cases": summary.total_cases,
        "passed_cases": summary.passed_cases,
        "failed_cases": summary.failed_cases,
        "pass_rate": summary.pass_rate,
        "report_dir": str(output_dir),
    }
