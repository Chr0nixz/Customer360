from customer360.contracts.diagnostics import CaseFailureAttribution, DiagnosticQuadruple
from customer360.contracts.public import Column, QueryResult
from customer360.contracts.semantic import Filter, JoinSpec, RollingWindow, SemanticSpec
from customer360.evaluator.diagnostics import (
    build_diagnostic_summary,
    compute_diff_summary,
    extract_quadruple_from_spec,
)


def test_extract_quadruple_from_spec():
    spec = SemanticSpec(
        metric="active_customer_count",
        filters=(
            Filter(field="customer_level", operator="eq", values=("VIP",)),
            Filter(field="region", operator="eq", values=("华东",)),
        ),
        time_window=RollingWindow(days=90, anchor_date="2025-06-30"),
        join=JoinSpec(path="customer_transactions"),
    )
    quad = extract_quadruple_from_spec(spec)
    assert quad.metric_name == "active_customer_count"
    assert quad.filter_dimensions == ("customer_level", "region")
    assert quad.time_kind == "rolling"
    assert quad.join_path == "customer_transactions"


def test_compute_diff_summary():
    cols = (Column(name="cnt", kind="integer"),)
    res_actual = QueryResult(columns=cols, rows=((10,),))
    res_expected = QueryResult(columns=cols, rows=((10,), (20,)))
    summary = compute_diff_summary(res_actual, res_expected)
    assert summary == "row_count_mismatch: actual=1, expected=2"

    cols_other = (Column(name="amount", kind="decimal"),)
    res_col_mismatch = QueryResult(columns=cols_other, rows=(("100.00",),))
    assert "columns_mismatch" in compute_diff_summary(res_col_mismatch, res_expected)

    res_truncated = QueryResult(columns=cols, rows=((10,),), truncated=True)
    assert compute_diff_summary(res_truncated, res_expected) == "actual_result_truncated"


def test_build_diagnostic_summary_aggregation():
    q1 = DiagnosticQuadruple(
        metric_name="m1",
        filter_dimensions=("region",),
        time_kind="rolling",
        join_path=None,
    )
    q2 = DiagnosticQuadruple(
        metric_name="m1",
        filter_dimensions=("customer_level",),
        time_kind="rolling",
        join_path=None,
    )
    q3 = DiagnosticQuadruple(
        metric_name="m2",
        filter_dimensions=("region",),
        time_kind="point_in_time",
        join_path="customer_transactions",
    )

    all_quads = (q1, q2, q3)

    # Assume q1 and q3 failed
    attr1 = CaseFailureAttribution(
        case_id="case_1",
        split="dev",
        stage="comparison",
        primary_failure_code="RESULT_MISMATCH",
        quadruple=q1,
        diff_summary="row_count_mismatch: actual=0, expected=1",
    )
    attr3 = CaseFailureAttribution(
        case_id="case_3",
        split="dev",
        stage="execution",
        primary_failure_code="JOIN_ERROR",
        quadruple=q3,
        diff_summary="no_result",
    )

    summary = build_diagnostic_summary(
        total_count=3,
        passed_count=1,
        attributions=(attr1, attr3),
        all_quadruples=all_quads,
    )

    assert summary.total_cases == 3
    assert summary.passed_cases == 1
    assert summary.failed_cases == 2
    assert summary.pass_rate == 0.3333

    # Check aggregations
    agg_map = {(a.dimension_type, a.dimension_value): a for a in summary.aggregations}

    # metric m1: total 2, failed 1 (50%)
    assert agg_map[("metric", "m1")].total_cases == 2
    assert agg_map[("metric", "m1")].failed_cases == 1
    assert agg_map[("metric", "m1")].failure_rate == 0.5

    # metric m2: total 1, failed 1 (100%)
    assert agg_map[("metric", "m2")].total_cases == 1
    assert agg_map[("metric", "m2")].failed_cases == 1
    assert agg_map[("metric", "m2")].failure_rate == 1.0

    # filter region: total 2, failed 2 (100%)
    assert agg_map[("filter", "region")].total_cases == 2
    assert agg_map[("filter", "region")].failed_cases == 2
    assert agg_map[("filter", "region")].failure_rate == 1.0


def test_render_diagnostic_markdown_and_html():
    from customer360.evaluator.diagnostics import (
        render_diagnostic_html,
        render_diagnostic_markdown,
    )

    q = DiagnosticQuadruple(
        metric_name="m_test",
        filter_dimensions=("region",),
        time_kind="rolling",
    )
    attr = CaseFailureAttribution(
        case_id="case_fail_1",
        split="dev",
        stage="comparison",
        primary_failure_code="TIME_RANGE_ERROR",
        quadruple=q,
        diff_summary="row_count_mismatch: actual=0, expected=5",
    )
    summary = build_diagnostic_summary(
        total_count=10,
        passed_count=9,
        attributions=(attr,),
        all_quadruples=(q,),
    )

    # Test Markdown
    md = render_diagnostic_markdown(summary)
    assert "# Customer360 Evaluation Diagnostics" in md
    assert "m_test" in md
    assert "TIME_RANGE_ERROR" in md
    assert "90.0%" in md

    # Test HTML
    html = render_diagnostic_html(summary)
    assert "<!DOCTYPE html>" in html
    assert "Customer360 Evaluation Diagnostics" in html
    assert "m_test" in html
    assert "TIME_RANGE_ERROR" in html
    assert "case_fail_1" in html
    assert "row_count_mismatch" in html
    assert "90.0%" in html


def test_diagnose_matrix_run_and_write_report(tmp_path):
    from customer360.evaluator.diagnostics import diagnose_matrix_run, write_diagnostics_report

    class DummySnapshot:
        def __init__(self, applicable, outcome, stage="agent_submit", reason_code=None):
            self.applicable = applicable
            self.outcome = outcome
            self.stage = stage
            self.reason_code = reason_code
            self.failure_class = reason_code

    class DummyCaseItem:
        def __init__(self, case_id, snapshots):
            self.case_id = case_id
            self.split = "dev"
            self.snapshots = snapshots

    class DummyReport:
        def __init__(self, cases):
            self.cases = cases

    class DummyCatalogCase:
        def __init__(self, case_id, spec):
            self.case_id = case_id
            self.semantic_spec = spec

    spec1 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
    )
    spec2 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="region", operator="eq", values=("华东",)),),
    )

    catalog_cases = [
        DummyCatalogCase("case_pass", spec1),
        DummyCatalogCase("case_fail", spec2),
    ]

    report = DummyReport(
        cases=[
            DummyCaseItem("case_pass", [DummySnapshot("applicable", "pass")]),
            DummyCaseItem(
                "case_fail",
                [
                    DummySnapshot(
                        "applicable", "fail", stage="comparison", reason_code="RESULT_MISMATCH"
                    )
                ],
            ),
        ]
    )

    summary = diagnose_matrix_run(report, catalog_cases)
    assert summary.total_cases == 2
    assert summary.passed_cases == 1
    assert summary.failed_cases == 1
    assert summary.pass_rate == 0.5
    assert len(summary.attributions) == 1
    assert summary.attributions[0].case_id == "case_fail"
    assert summary.attributions[0].primary_failure_code == "RESULT_MISMATCH"

    # Test file writing
    out_dir = tmp_path / "diag_out"
    res = write_diagnostics_report(out_dir, summary)
    assert res["total_cases"] == 2
    assert res["passed_cases"] == 1
    assert res["failed_cases"] == 1

    assert (out_dir / "diagnostics.json").is_file()
    assert (out_dir / "diagnostics.md").is_file()
    assert (out_dir / "diagnostics.html").is_file()

    # Hardening test 1: Overwrite protection
    import pytest

    with pytest.raises(FileExistsError, match="already exist"):
        write_diagnostics_report(out_dir, summary)

    # Hardening test 2: Anti-leakage guard for forbidden private keys
    leak_dir = tmp_path / "leak_dir"
    leaked_attr = CaseFailureAttribution(
        case_id="case_leak",
        split="dev",
        stage="comparison",
        primary_failure_code="LEAK",
        quadruple=DiagnosticQuadruple(),
        diff_summary='leaked key "candidate_sql" must be blocked',
    )
    leaked_summary = build_diagnostic_summary(
        total_count=1,
        passed_count=0,
        attributions=(leaked_attr,),
    )
    with pytest.raises(ValueError, match="leaked candidate_sql"):
        write_diagnostics_report(leak_dir, leaked_summary)
