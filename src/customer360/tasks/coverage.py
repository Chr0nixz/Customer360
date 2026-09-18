"""Formal human-case coverage: Tiny probes, independent oracle, compiler cross-check."""

from pathlib import Path

from customer360.artifacts import digest, json_text, write_json_new
from customer360.contracts.coverage import CaseCoverage, CoverageReport
from customer360.contracts.generation import DatasetManifest, GenerationConfig
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.boundaries import evaluate_probes
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset, normalize_sql_result

LIMITATIONS = (
    "Not an official score, multi-turn runner or model baseline",
    (
        "Grouping is region-only; latest-snapshot is per-customer MAX then SUM; "
        "only the frozen customer_transactions Join is enabled"
    ),
    "Clarification and refuse oracles are recorded but not scored",
    "Independent oracle never executes SQL; compiler SQL is compared afterwards",
    "Boundary probes read Tiny slices only; they do not change the generator",
)


_sql_result = normalize_sql_result


def _markdown(report: CoverageReport) -> str:
    lines = [
        "# Tiny boundary coverage",
        "",
        "Versioned M2 dev material for 20 human cases. Not an official score or ranked report.",
        "",
        f"- coverage_passed: `{report.coverage_passed}`",
        f"- compilable_answers: `{report.compilable_answers}`",
        f"- independent_oracle_matches: `{report.independent_oracle_matches}`",
        f"- unsupported_capabilities: `{report.unsupported_capabilities}`",
        f"- unscored_oracles: `{report.unscored_oracles}`",
        f"- probes_passed: `{report.probes_passed}`",
        f"- m2_complete: `{report.m2_complete}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(
        [
            "",
            "## Boundary probes",
            "",
            "| probe | passed | observed |",
            "|---|---|---|",
        ]
    )
    for probe in report.probes:
        observed = json_text(probe.observed)
        lines.append(f"| `{probe.probe_id}` | `{probe.passed}` | `{observed}` |")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case_id | action | category | material | match | failure |",
            "|---|---|---|---|---|---|",
        ]
    )
    for case in report.cases:
        match = "n/a" if case.compiled_match is None else str(case.compiled_match)
        lines.append(
            f"| `{case.case_id}` | {case.expected_action} | {case.category} | "
            f"{case.material_status} | `{match}` | {case.intended_failure_class} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_coverage_report(
    database: Path,
    manifest: object,
    repository: MetadataRepository | None = None,
    config: GenerationConfig | None = None,
    oracles: Path | None = None,
) -> CoverageReport:
    repository = repository or MetadataRepository()
    config = config or GenerationConfig()
    catalog = load_human_cases(oracles=oracles)
    slices = load_table_slices(database, repository.catalog)
    probes = evaluate_probes(slices, repository, config)
    probe_map = {item.probe_id: item for item in probes}
    cases: list[CaseCoverage] = []
    matches = 0
    for item in catalog.cases:
        required = tuple(probe_map[name] for name in item.required_probes)
        if item.material_status != "compilable_answer":
            cases.append(
                CaseCoverage(
                    case_id=item.case_id,
                    task_version=item.task_version,
                    split=item.split,
                    expected_action=item.expected_action,
                    category=item.category,
                    material_status=item.material_status,
                    intended_failure_class=item.intended_failure_class,
                    question=item.question,
                    rewrites=item.rewrites,
                    unsupported_reason=item.unsupported_reason,
                    required_probes=item.required_probes,
                )
            )
            continue
        spec = item.semantic_spec()
        independent = compute_independent(spec, repository, slices)
        compiled = compile_semantic(spec, repository)
        compiled_result = _sql_result(database, compiled)
        matched = compare_results(independent, compiled_result) and all(
            probe.passed for probe in required
        )
        matches += int(matched)
        cases.append(
            CaseCoverage(
                case_id=item.case_id,
                task_version=item.task_version,
                split=item.split,
                expected_action=item.expected_action,
                category=item.category,
                material_status=item.material_status,
                intended_failure_class=item.intended_failure_class,
                question=item.question,
                rewrites=item.rewrites,
                compiled_match=matched,
                independent_result=independent,
                compiled_sql=compiled.sql,
                required_probes=item.required_probes,
            )
        )
    probes_passed = all(item.passed for item in probes)
    compilable = sum(item.material_status == "compilable_answer" for item in catalog.cases)
    unsupported = sum(item.material_status == "unsupported_capability" for item in catalog.cases)
    unscored = sum(item.material_status == "unscored_oracle" for item in catalog.cases)
    return CoverageReport(
        coverage_passed=probes_passed and matches == compilable,
        compilable_answers=compilable,
        unsupported_capabilities=unsupported,
        unscored_oracles=unscored,
        independent_oracle_matches=matches,
        probes_passed=probes_passed,
        dataset_manifest_hash=digest(manifest),
        limitations=LIMITATIONS,
        probes=probes,
        cases=tuple(cases),
    )


def write_coverage_report(dataset_dir: Path, output_dir: Path, oracles: Path | None = None) -> dict:
    database, loaded = load_verified_dataset(dataset_dir)
    if not isinstance(loaded, DatasetManifest) or loaded.artifact_kind != "tiny_dataset":
        raise ValueError("coverage-report requires a Tiny dataset, not a public fixture")
    report = build_coverage_report(database, loaded.model_dump(mode="json"), oracles=oracles)
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = report.model_dump(mode="json")
    write_json_new(output_dir / "coverage.json", payload)
    with (output_dir / "coverage.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_markdown(report))
    return payload
