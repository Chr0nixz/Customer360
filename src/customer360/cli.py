import sys
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from customer360 import __version__
from customer360.application import FIXTURE_ANCHOR, run_single_case, run_smoke
from customer360.artifacts import json_text, write_json_new
from customer360.config import resolve_settings
from customer360.contracts.pack import GeneratedTaskPack
from customer360.evaluator.formal import evaluate_formal, write_formal_input
from customer360.evaluator.hidden import evaluate_hidden_pack, write_hidden_run
from customer360.evaluator.matrix import evaluate_matrix, resolve_eval_agent
from customer360.evaluator.perf import (
    collect_evaluate,
    collect_generate,
    collect_gold_execute,
    write_perf_run,
)
from customer360.evaluator.report import load_private_matrix, public_summary, write_matrix_run
from customer360.evaluator.score import build_score_inputs as bind_score_inputs
from customer360.evaluator.score import score_report, write_score
from customer360.metadata.metrics import MetadataRepository
from customer360.release import (
    bind_reproducible_build,
    bind_semantic_acceptance,
    check_formal_release,
    check_release,
    prepare_formal_release,
    prepare_release,
)
from customer360.synth.fixture import build_public_fixture
from customer360.synth.generator import generate_dataset, load_generation_config
from customer360.synth.schema import render_ddl
from customer360.synth.variants import generate_named_variant
from customer360.tasks.catalog import DEFAULT_TRUSTED_ORACLES, load_human_cases
from customer360.tasks.coverage import write_coverage_report
from customer360.tasks.generator import generate_task_pack, write_generated_pack
from customer360.tasks.gold import build_gold_package
from customer360.tasks.hidden import (
    generate_hidden_dataset,
    generate_hidden_pack,
    write_hidden_pack,
)
from customer360.tasks.hidden_variants import write_hidden_variant_set
from customer360.tasks.isolation import (
    check_generated_isolation,
    check_hidden_isolation,
    check_human_pack_frozen,
)
from customer360.tasks.pack_verify import write_pack_verify
from customer360.tasks.rewrites import validate_catalog_rewrites
from customer360.tasks.variant import write_variant_replay

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Customer360 v1.0 local/offline benchmark. Public and private scores "
        "are separate; ranking is disabled."
    ),
)


def _configure_utf8_stdio() -> None:
    """JSON reports include Chinese text; Windows cp1252 consoles must not crash."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError, AttributeError):
            continue


def run() -> None:
    """Console entry that forces UTF-8 stdio before Typer starts."""
    _configure_utf8_stdio()
    app()


@app.command()
def version_info() -> None:
    """Show package and protocol versions."""
    typer.echo(
        json_text(
            {
                "package": __version__,
                "protocol": "0.1",
                "evaluator": "0.6",
                "score_protocol": "1.0",
                "ranking_enabled": False,
            }
        )
    )


@app.command()
def doctor(
    config: Annotated[
        Path | None,
        typer.Option(help="YAML configuration path; packaged defaults if omitted"),
    ] = None,
) -> None:
    """Validate configuration and bundled catalog without mutating data."""
    try:
        settings = resolve_settings(config)
        repository = MetadataRepository()
    except (ValueError, OSError) as exc:
        typer.echo(f"Configuration/catalog error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json_text(
            {
                "status": "ok",
                **repository.consistency_report(),
                "artifact_dir": str(settings.artifact_dir),
                "versions": {
                    name: version(name) for name in ("duckdb", "pydantic", "sqlglot", "typer")
                },
                "profile": "public_fixture_only",
            }
        )
    )


@app.command()
def schema() -> None:
    """Print DDL generated from the single canonical catalog."""
    typer.echo(render_ddl(), nl=False)


@app.command()
def create_fixture(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    seed: Annotated[int, typer.Option(min=0)] = 42,
) -> None:
    """Build the six-customer PUBLIC fixture, not a Tiny scale generator."""
    try:
        output.mkdir(parents=True, exist_ok=False)
        manifest = build_public_fixture(output / "fixture.duckdb", seed)
        write_json_new(output / "manifest.json", manifest)
    except (OSError, ValueError) as exc:
        typer.echo(f"Fixture creation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(manifest))


@app.command()
def generate_data(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    scale: Annotated[str, typer.Option(help="Dataset scale: tiny, standard, or large")] = "tiny",
    seed: Annotated[int | None, typer.Option(min=0, help="Override the configured seed")] = None,
    config: Annotated[Path, typer.Option(help="YAML generation config path")] = Path(
        "configs/data_generation.yaml"
    ),
) -> None:
    """Generate a reproducible dataset. Tiny is 100/2000; Standard 10k/300k; Large 100k/3M."""
    try:
        generation_config = load_generation_config(config, scale=scale, seed=seed)
        manifest, quality = generate_dataset(generation_config, output)
    except (OSError, ValueError) as exc:
        typer.echo(f"Data generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(manifest))
    if not quality["all_passed"]:
        raise typer.Exit(1)


@app.command("generate-variant")
def generate_variant(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    variant_id: Annotated[
        str,
        typer.Option(
            help=(
                "tiny_seed_43_distribution, tiny_duplicate_fanout, "
                "tiny_null_empty_groups, or tiny_date_boundary"
            )
        ),
    ],
) -> None:
    """Generate one frozen Tiny data variant. Not an official score."""
    try:
        manifest = generate_named_variant(variant_id, output)  # type: ignore[arg-type]
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Variant generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(manifest))


@app.command()
def smoke(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    config: Annotated[
        Path | None,
        typer.Option(help="YAML configuration path; packaged defaults if omitted"),
    ] = None,
) -> None:
    """Verify 3 correct + 1 wrong + 1 unsafe submission through the real pipeline."""
    try:
        settings = resolve_settings(config)
        if settings.anchor_date != FIXTURE_ANCHOR:
            raise ValueError("public smoke fixture requires anchor_date=2025-06-30")
        report = run_smoke(output, settings.seed, settings.limits)
    except (OSError, ValueError) as exc:
        typer.echo(f"Smoke setup failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(report))
    if not report["verification_passed"]:
        raise typer.Exit(1)


@app.command("coverage-report")
def coverage_report(
    dataset: Annotated[Path, typer.Option(help="Existing Tiny dataset directory")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    oracles: Annotated[
        Path, typer.Option(help="Trusted oracle YAML; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Cross-check 20 Tiny planning cases with an independent Python oracle."""
    try:
        report = write_coverage_report(dataset, output, oracles=oracles)
    except (OSError, ValueError) as exc:
        typer.echo(f"Coverage report failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json_text(
            {
                "coverage_passed": report["coverage_passed"],
                "case_count": report["case_count"],
                "compilable_answers": report["compilable_answers"],
                "independent_oracle_matches": report["independent_oracle_matches"],
                "unsupported_capabilities": report["unsupported_capabilities"],
                "unscored_oracles": report["unscored_oracles"],
                "probes_passed": report["probes_passed"],
                "m2_complete": report["m2_complete"],
            }
        )
    )
    if not report["coverage_passed"]:
        raise typer.Exit(1)


@app.command("check-rewrites")
def check_rewrites(
    oracles: Annotated[
        Path, typer.Option(help="Trusted oracle YAML; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Validate catalog paraphrases against canonical date/metric/filter/Join slots."""
    try:
        catalog = load_human_cases(oracles=oracles, check_rewrites=False)
        report = validate_catalog_rewrites(catalog)
    except (OSError, ValueError) as exc:
        typer.echo(f"Rewrite check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    payload = report.model_dump(mode="json")
    typer.echo(json_text(payload))
    if not report.passed:
        raise typer.Exit(1)


@app.command("replay-variant")
def replay_variant(
    baseline: Annotated[Path, typer.Option(help="Canonical Tiny dataset directory (seed 42)")],
    variant: Annotated[Path, typer.Option(help="Frozen Tiny variant directory")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    oracles: Annotated[
        Path, typer.Option(help="Trusted oracle YAML; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
    mode: Annotated[
        str,
        typer.Option(
            help="Replay mode: same_sql, agent_rerun (injected Agent), or scoring",
        ),
    ] = "same_sql",
) -> None:
    """Replay a Tiny variant. same_sql does not call an Agent; agent_rerun is library-only."""
    try:
        report = write_variant_replay(
            baseline,
            variant,
            output,
            oracles=oracles,
            replay_mode=mode,  # type: ignore[arg-type]
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Variant replay failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json_text(
            {
                "passed": report["passed"],
                "replay_mode": report["replay_mode"],
                "variant_id": report["variant_id"],
                "independent_oracle_matches": report["independent_oracle_matches"],
                "results_differ_from_baseline": report["results_differ_from_baseline"],
                "m2_complete": report["m2_complete"],
                "scoring_applied": report["scoring_applied"],
            }
        )
    )
    if not report["passed"]:
        raise typer.Exit(1)


@app.command()
def evaluate(
    dataset: Annotated[Path, typer.Option(help="Canonical Tiny dataset directory (seed 42)")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    distribution_variant: Annotated[Path, typer.Option(help="tiny_seed_43_distribution directory")],
    duplicate_variant: Annotated[Path, typer.Option(help="tiny_duplicate_fanout directory")],
    null_variant: Annotated[Path, typer.Option(help="tiny_null_empty_groups directory")],
    date_variant: Annotated[Path, typer.Option(help="tiny_date_boundary directory")],
    agent: Annotated[str, typer.Option(help="Local driver: template or baseline")] = "template",
    mode: Annotated[str, typer.Option(help="same_sql, agent_rerun, or scoring")] = "same_sql",
    split: Annotated[str, typer.Option(help="Must remain dev for the human pack")] = "dev",
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Evaluate the human dev pack on Tiny baseline plus four variants. No official score."""
    try:
        if split != "dev":
            raise ValueError(
                "evaluate refuses to relabel C360_0001-0020 away from split=dev; "
                "use evaluate-hidden for the independent private pack"
            )
        if mode == "scoring":
            raise ValueError("robustness scoring is not enabled; scoring_applied remains false")
        resolved = resolve_eval_agent(agent)
        report = evaluate_matrix(
            dataset,
            {
                "tiny_seed_43_distribution": distribution_variant,
                "tiny_duplicate_fanout": duplicate_variant,
                "tiny_null_empty_groups": null_variant,
                "tiny_date_boundary": date_variant,
            },
            resolved,
            agent_id=agent,
            replay_mode=mode,  # type: ignore[arg-type]
            oracles=oracles,
        )
        summary = write_matrix_run(output, report)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Evaluation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["integrity_passed"]:
        raise typer.Exit(1)


@app.command()
def report(
    source: Annotated[
        Path,
        typer.Option("--input", help="evaluate output directory with private/matrix.json"),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", help="json, markdown, html, or all"),
    ] = "all",
) -> None:
    """Render a desensitized public report from a private matrix run."""
    try:
        matrix = load_private_matrix(source)
        summary = public_summary(matrix)
        payload = summary.model_dump(mode="json")
        if output_format not in {"json", "markdown", "html", "all"}:
            raise ValueError("format must be json, markdown, html, or all")
    except (OSError, ValueError) as exc:
        typer.echo(f"Report failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    if output_format in {"json", "all"}:
        typer.echo(json_text(payload))
    if output_format == "markdown":
        from customer360.evaluator.report import render_markdown

        typer.echo(render_markdown(summary), nl=False)
    if output_format == "html":
        from customer360.evaluator.report import render_html

        typer.echo(render_html(summary), nl=False)


@app.command("generate-tasks")
def generate_tasks(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    count: Annotated[int, typer.Option(min=8, help="Independent semantic cases; 120 or 300")] = 120,
    seed: Annotated[int, typer.Option(min=0)] = 42,
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Generate an independent public task pack. Does not relabel C360_0001-0020."""
    try:
        pack = generate_task_pack(seed=seed, count=count, oracles=oracles)
        summary = write_generated_pack(output, pack, oracles=oracles)
    except (OSError, ValueError) as exc:
        typer.echo(f"Task generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["isolation_passed"]:
        raise typer.Exit(1)


@app.command("check-isolation")
def check_isolation(
    pack: Annotated[
        Path | None,
        typer.Option(help="Generated public pack directory with pack.json"),
    ] = None,
    hidden: Annotated[
        Path | None,
        typer.Option(help="Independent hidden pack directory; not a relabel of C360_0001-0020"),
    ] = None,
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Verify human 20 stay split=dev and generated/hidden families do not cross splits."""
    try:
        human = load_human_cases(oracles=oracles, check_rewrites=False)
        if pack is None and hidden is None:
            issues = check_human_pack_frozen(human)
            payload = {
                "passed": not issues,
                "human_pack_untouched": not issues,
                "scoring_applied": False,
                "issue_count": len(issues),
                "issues": [item.model_dump(mode="json") for item in issues],
            }
        elif pack is None:
            raise ValueError("hidden isolation requires --pack for the public generated pack")
        else:
            generated = GeneratedTaskPack.model_validate_json(
                (pack / "pack.json").read_text(encoding="utf-8")
            )
            if hidden is None:
                report = check_generated_isolation(human, generated)
            else:
                from customer360.tasks.hidden import load_hidden_pack

                report = check_hidden_isolation(human, generated, load_hidden_pack(hidden))
            payload = report.model_dump(mode="json")
    except (OSError, ValueError) as exc:
        typer.echo(f"Isolation check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))
    if not payload["passed"]:
        raise typer.Exit(1)


@app.command("run-case")
def run_case(
    case_id: Annotated[str, typer.Option(help="Human pack case id such as C360_0001")],
    dataset: Annotated[Path, typer.Option(help="Canonical Tiny dataset directory (seed 42)")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    agent: Annotated[str, typer.Option(help="Local driver: baseline or template")] = "baseline",
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Run one human-pack case. Official baseline is local; not an official score."""
    try:
        resolved = resolve_eval_agent(agent)
        summary = run_single_case(
            dataset,
            output,
            case_id,
            resolved,
            agent_id=agent,
            oracles=oracles,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"run-case failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if summary["outcome"] != "pass":
        raise typer.Exit(1)


@app.command("generate-hidden")
def generate_hidden(
    output: Annotated[Path, typer.Option(help="New hidden pack directory; must not exist")],
    public_pack: Annotated[Path, typer.Option(help="Public generated pack to isolate against")],
    count: Annotated[int, typer.Option(min=8, help="Independent hidden semantic cases")] = 30,
    seed: Annotated[int, typer.Option(min=0)] = 42,
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Generate an independent private pack. Does not relabel C360_0001-0020."""
    try:
        public = GeneratedTaskPack.model_validate_json(
            (public_pack / "pack.json").read_text(encoding="utf-8")
        )
        pack = generate_hidden_pack(public, seed=seed, count=count, oracles=oracles)
        summary = write_hidden_pack(output, pack, public, oracles=oracles)
    except (OSError, ValueError) as exc:
        typer.echo(f"Hidden pack generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["isolation_passed"]:
        raise typer.Exit(1)


@app.command("generate-hidden-data")
def generate_hidden_data(
    output: Annotated[Path, typer.Option(help="New hidden Tiny directory; must not exist")],
    seed: Annotated[int, typer.Option(min=0, help="Must not be public seed 42 or 43")] = 1042,
    config: Annotated[Path, typer.Option(help="YAML generation config path")] = Path(
        "configs/data_generation.yaml"
    ),
) -> None:
    """Generate isolated Tiny data for hidden evaluation. Not seed 42/43."""
    try:
        profile = generate_hidden_dataset(output, seed=seed, config=config)
    except (OSError, ValueError) as exc:
        typer.echo(f"Hidden data generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(profile.model_dump(mode="json")))


@app.command("generate-hidden-variants")
def generate_hidden_variants_cmd(
    dataset: Annotated[Path, typer.Option(help="Hidden Tiny baseline directory")],
    output: Annotated[Path, typer.Option(help="New private variant set directory")],
) -> None:
    """Generate the four private hidden same-SQL replay variants."""
    try:
        summary = write_hidden_variant_set(dataset, output)
    except (OSError, ValueError) as exc:
        typer.echo(f"Hidden variant generation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))


@app.command("verify-pack")
def verify_pack(
    dataset: Annotated[Path, typer.Option(help="Public Tiny seed-42 directory")],
    pack: Annotated[Path, typer.Option(help="Generated public pack directory")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    variant: Annotated[
        list[Path] | None,
        typer.Option(
            help=(
                "Tiny variant directory for same_sql replay; optional for 120-case packs, "
                "repeat in frozen order for 300-case packs"
            )
        ),
    ] = None,
) -> None:
    """Cross-check generated pack Gold with an independent oracle. Not an official score."""
    try:
        summary = write_pack_verify(
            dataset, pack, output, variant_dirs=tuple(variant or ()), hidden=False
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Pack verify failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["semantic_passed"]:
        raise typer.Exit(1)


@app.command("verify-hidden")
def verify_hidden(
    dataset: Annotated[Path, typer.Option(help="Hidden Tiny directory with hidden_profile.json")],
    pack: Annotated[Path, typer.Option(help="Independent hidden pack directory")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
) -> None:
    """Cross-check hidden pack Gold on isolated Tiny (baseline-only). Not an official score."""
    try:
        summary = write_pack_verify(dataset, pack, output, hidden=True)
    except (OSError, ValueError) as exc:
        typer.echo(f"Hidden pack verify failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["semantic_passed"]:
        raise typer.Exit(1)


@app.command("evaluate-hidden")
def evaluate_hidden(
    dataset: Annotated[Path, typer.Option(help="Hidden Tiny directory with hidden_profile.json")],
    pack: Annotated[Path, typer.Option(help="Independent hidden pack directory")],
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    agent: Annotated[str, typer.Option(help="Local driver: baseline or template")] = "baseline",
    variant: Annotated[
        list[Path] | None,
        typer.Option(
            help="Private hidden variant directory; repeat exactly four times for formal replay"
        ),
    ] = None,
    formal: Annotated[
        bool, typer.Option(help="Require four private variants and formal input")
    ] = False,
) -> None:
    """Evaluate hidden baseline and optionally perform formal four-variant replay."""
    try:
        resolved = resolve_eval_agent(agent)
        if formal or variant:
            summary = write_formal_input(
                output,
                evaluate_formal(
                    dataset, pack, tuple(variant or ()), resolved, agent_id=agent, hidden=True
                ),
            )
        else:
            report, private_records = evaluate_hidden_pack(dataset, pack, resolved, agent_id=agent)
            summary = write_hidden_run(output, report, private_records)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Hidden evaluation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["integrity_passed"]:
        raise typer.Exit(1)


@app.command("score")
def score_cmd(
    public_report: Annotated[Path, typer.Option(help="Formal generated-dev 120 evaluator input")],
    hidden_report: Annotated[Path, typer.Option(help="Private hidden evaluator report")],
    output: Annotated[Path, typer.Option(help="New formal score directory")],
    agent: Annotated[
        str | None, typer.Option(help="Optional identity assertion; never relabels")
    ] = None,
) -> None:
    """Produce separate public_dev and private_hidden formal local scores."""
    try:
        reports = (
            score_report(public_report, split="public_dev", agent_id=agent),
            score_report(hidden_report, split="private_hidden", agent_id=agent),
        )
        payload = write_score(output, reports)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Score failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))
    if not all(all(gate.passed for gate in report.hard_gates) for report in reports):
        raise typer.Exit(1)


@app.command("build-score-inputs")
def build_score_inputs(
    public_report: Annotated[Path, typer.Option(help="Private public matrix report")],
    hidden_report: Annotated[Path, typer.Option(help="Private hidden report")],
    output: Annotated[Path, typer.Option(help="New private score input directory")],
) -> None:
    """Bind the two private evaluator reports for a reproducible score run."""
    try:
        payload = bind_score_inputs(public_report, hidden_report, output)
    except (OSError, ValueError) as exc:
        typer.echo(f"Score input preparation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))


@app.command("evaluate-public")
def evaluate_public(
    dataset: Annotated[Path, typer.Option(help="Public Tiny seed-42 baseline")],
    pack: Annotated[Path, typer.Option(help="Trusted 300-case generated pack")],
    variant: Annotated[list[Path], typer.Option(help="Repeat four ordered public variants")],
    output: Annotated[Path, typer.Option(help="New private/public evaluator output")],
    agent: Annotated[
        str, typer.Option(help="Local baseline or deliberately wrong driver")
    ] = "baseline",
) -> None:
    """Evaluate only generated-dev 120; human 20 and train are never scored."""
    try:
        payload = write_formal_input(
            output,
            evaluate_formal(
                dataset, pack, tuple(variant), resolve_eval_agent(agent), agent_id=agent
            ),
        )
    except (ValueError, OSError, TypeError) as exc:
        typer.echo(f"Public evaluation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))


@app.command("perf-baseline")
def perf_baseline(
    output: Annotated[Path, typer.Option(help="New output directory; must not exist")],
    workload: Annotated[
        str,
        typer.Option(help="generate, gold-execute, or evaluate"),
    ] = "gold-execute",
    dataset: Annotated[
        Path | None,
        typer.Option(help="Generated dataset directory; destination for generate"),
    ] = None,
    scale: Annotated[
        str | None,
        typer.Option(help="Required for generate: tiny, standard, or large"),
    ] = None,
    seed: Annotated[int, typer.Option(min=0, help="Generation seed; ignored otherwise")] = 42,
    agent: Annotated[str, typer.Option(help="Local driver for evaluate: baseline or template")] = (
        "baseline"
    ),
    config: Annotated[Path, typer.Option(help="YAML generation config path")] = Path(
        "configs/data_generation.yaml"
    ),
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Collect a resource-budgeted performance baseline. Not an official score."""
    try:
        if workload == "scoring":
            raise ValueError("robustness scoring is not enabled; scoring_applied remains false")
        if workload == "generate":
            if dataset is None:
                raise ValueError(
                    "generate workload requires --dataset as the new dataset directory"
                )
            if scale not in {"tiny", "standard", "large"}:
                raise ValueError("generate workload requires --scale tiny, standard, or large")
            report, private_records = collect_generate(
                scale=scale, seed=seed, dataset_dir=dataset, config=config
            )
        elif workload == "gold-execute":
            if dataset is None:
                raise ValueError("gold-execute requires an existing --dataset directory")
            report, private_records = collect_gold_execute(dataset, oracles=oracles)
        elif workload == "evaluate":
            if dataset is None:
                raise ValueError("evaluate workload requires an existing --dataset directory")
            report, private_records = collect_evaluate(dataset, agent_id=agent, oracles=oracles)
        else:
            raise ValueError("workload must be generate, gold-execute, or evaluate")
        summary = write_perf_run(output, report, private_records)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Performance baseline failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(summary))
    if not summary["integrity_passed"]:
        raise typer.Exit(1)


@app.command("prepare-release")
def prepare_release_cmd(
    output: Annotated[Path, typer.Option(help="New release directory; must not exist")],
    public_pack: Annotated[
        Path | None, typer.Option(help="Optional public generated pack for 300-case structure")
    ] = None,
    hidden_pack: Annotated[
        Path | None, typer.Option(help="Optional hidden pack; only the case count is recorded")
    ] = None,
    oracles: Annotated[
        Path, typer.Option(help="Trusted human oracles; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Write a candidate release manifest. No scores, Docker or hidden files."""
    try:
        payload = prepare_release(
            output, public_pack=public_pack, hidden_pack=hidden_pack, oracles=oracles
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Release preparation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))


@app.command("check-release")
def check_release_cmd(
    source: Annotated[Path, typer.Option("--input", help="Directory with release_manifest.json")],
) -> None:
    """Verify a candidate release manifest still excludes scores, Docker and hidden files."""
    try:
        payload = check_release(source)
    except (OSError, ValueError) as exc:
        typer.echo(f"Release check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))
    if not payload["passed"]:
        raise typer.Exit(1)


@app.command("prepare-formal-release")
def prepare_formal_release_cmd(
    output: Annotated[Path, typer.Option(help="New formal release directory")],
    public_pack: Annotated[Path, typer.Option(help="300-case public generated pack")],
    score_dir: Annotated[
        Path | None, typer.Option(help="Optional private formal score directory")
    ] = None,
    public_report: Annotated[
        Path | None, typer.Option(help="Optional private public evaluator report")
    ] = None,
    hidden_report: Annotated[
        Path | None, typer.Option(help="Optional private hidden evaluator report")
    ] = None,
    docker_digest: Annotated[str, typer.Option(help="Immutable sha256 Docker image digest")] = "",
    semantic_report: Annotated[
        Path | None, typer.Option(help="Private semantic acceptance evidence")
    ] = None,
    conformance_report: Annotated[
        Path | None, typer.Option(help="Baseline conformance evidence")
    ] = None,
    negative_control_report: Annotated[
        Path | None, typer.Option(help="Wrong-agent negative control evidence")
    ] = None,
    docker_smoke_report: Annotated[
        Path | None, typer.Option(help="Docker network/root/leakage smoke evidence")
    ] = None,
    reproducible_build_report: Annotated[
        Path | None, typer.Option(help="Two-build reproducibility evidence")
    ] = None,
) -> None:
    """Prepare the Apache-2.0 v1.0 public release boundary."""
    try:
        payload = prepare_formal_release(
            output,
            public_pack=public_pack,
            score_dir=score_dir,
            public_report=public_report,
            hidden_report=hidden_report,
            docker_digest=docker_digest,
            semantic_report=semantic_report,
            conformance_report=conformance_report,
            negative_control_report=negative_control_report,
            docker_smoke_report=docker_smoke_report,
            reproducible_build_report=reproducible_build_report,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Formal release preparation failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))


@app.command("bind-rc-evidence")
def bind_rc_evidence_cmd(
    gate: Annotated[str, typer.Option(help="semantic_acceptance or reproducible_build")],
    output: Annotated[Path, typer.Option(help="New typed RC evidence JSON")],
    public_verify: Annotated[
        Path | None, typer.Option(help="verify-pack output for semantic_acceptance")
    ] = None,
    hidden_verify: Annotated[
        Path | None, typer.Option(help="verify-hidden output for semantic_acceptance")
    ] = None,
    first_dist: Annotated[
        Path | None, typer.Option(help="First uv build --out-dir for reproducible_build")
    ] = None,
    second_dist: Annotated[
        Path | None, typer.Option(help="Second uv build --out-dir for reproducible_build")
    ] = None,
) -> None:
    """Bind native reports into typed RC evidence. File existence is not a pass."""
    try:
        if gate == "semantic_acceptance":
            if public_verify is None or hidden_verify is None:
                raise ValueError("semantic_acceptance requires --public-verify and --hidden-verify")
            payload = bind_semantic_acceptance(public_verify, hidden_verify).model_dump(mode="json")
        elif gate == "reproducible_build":
            if first_dist is None or second_dist is None:
                raise ValueError("reproducible_build requires --first-dist and --second-dist")
            payload = bind_reproducible_build(first_dist, second_dist, root=Path.cwd()).model_dump(
                mode="json"
            )
        else:
            raise ValueError("gate must be semantic_acceptance or reproducible_build")
        write_json_new(output, payload)
    except (OSError, ValueError) as exc:
        typer.echo(f"RC evidence bind failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))


@app.command("check-formal-release")
def check_formal_release_cmd(
    source: Annotated[Path, typer.Option("--input", help="Formal release directory")],
) -> None:
    """Verify the formal v1.0 release manifest and public leakage boundary."""
    try:
        payload = check_formal_release(source)
    except (OSError, ValueError) as exc:
        typer.echo(f"Formal release check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json_text(payload))
    if not payload["passed"]:
        raise typer.Exit(1)


@app.command("build-gold")
def build_gold(
    dataset: Annotated[Path, typer.Option(help="Existing Tiny dataset directory")],
    output: Annotated[Path, typer.Option(help="New private Gold output directory; do not publish")],
    oracles: Annotated[
        Path, typer.Option(help="Trusted oracle YAML; not shipped in the wheel")
    ] = DEFAULT_TRUSTED_ORACLES,
) -> None:
    """Build trusted-side Gold for the fixed human-case catalog."""
    try:
        report = build_gold_package(dataset, output, oracles=oracles)
    except (OSError, ValueError) as exc:
        typer.echo(f"Gold build failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json_text(
            {
                "artifact_kind": report["artifact_kind"],
                "case_count": report["case_count"],
                "compilable_answers": report["compilable_answers"],
                "unsupported_capabilities": report["unsupported_capabilities"],
                "non_answer_oracles": report["non_answer_oracles"],
                "dataset_manifest_hash": report["dataset_manifest_hash"],
            }
        )
    )


if __name__ == "__main__":
    run()
