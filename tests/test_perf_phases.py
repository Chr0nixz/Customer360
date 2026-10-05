from customer360.contracts.perf import (
    PUBLIC_PERF_FORBIDDEN,
    PerfBaselineReport,
    PerfEnvironment,
    PerfPhaseBreakdown,
    PerfQueryRecord,
    PhasePercentileSummary,
)
from customer360.evaluator.perf import _compute_phase_summary, _markdown, public_perf_summary


def test_compute_phase_summary():
    # Empty
    empty_res = _compute_phase_summary([])
    assert empty_res.p50_ms is None

    # Single
    single_res = _compute_phase_summary([100.0])
    assert single_res.p50_ms == 100.0
    assert single_res.p95_ms == 100.0

    # Multiple
    multi_res = _compute_phase_summary([10.0, 20.0, 30.0, 40.0, 50.0])
    assert multi_res.p50_ms == 30.0
    assert multi_res.p90_ms == 46.0
    assert multi_res.p95_ms == 48.0


def test_perf_phase_breakdown_contract_and_markdown():
    phases = PerfPhaseBreakdown(
        plan_ms=5.2,
        guard_ms=1.1,
        exec_ms=14.3,
        e2e_ms=20.6,
    )
    record = PerfQueryRecord(
        case_id="case_perf_1",
        status="ok",
        elapsed_ms=20.6,
        phases=phases,
    )
    phase_stats = {
        "plan": PhasePercentileSummary(p50_ms=5.0, p90_ms=8.0, p95_ms=9.0, p99_ms=10.0),
        "exec": PhasePercentileSummary(p50_ms=14.0, p90_ms=20.0, p95_ms=22.0, p99_ms=25.0),
    }
    env = PerfEnvironment(
        python="3.11",
        platform="Windows",
        machine="x86_64",
        duckdb="1.5.5",
        pydantic="2.13.5",
        sqlglot="30.18.0",
    )
    report = PerfBaselineReport(
        workload="evaluate",
        budget_profile="standard",
        query_count=1,
        success_count=1,
        failure_count=0,
        skipped_count=0,
        elapsed_ms=20.6,
        p50_ms=20.6,
        p95_ms=20.6,
        integrity_passed=True,
        environment=env,
        limitations=("test limitation",),
        phase_stats=phase_stats,
        queries=(record,),
    )

    summary = public_perf_summary(report)
    assert summary.phase_stats is not None
    assert "plan" in summary.phase_stats
    assert summary.phase_stats["plan"].p50_ms == 5.0

    # Test Markdown rendering
    md = _markdown(summary)
    assert "## Phase Latency Breakdown (ms)" in md
    assert "plan" in md
    assert "5.0" in md

    # Anti-leakage guard check
    for forbidden in PUBLIC_PERF_FORBIDDEN:
        assert f'"{forbidden}"' not in md
