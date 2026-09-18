"""Semantic acceptance for generated and hidden packs. Trusted-side only."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from customer360.artifacts import write_json_new
from customer360.contracts.family import ERROR_CLASSES_REQUIRED, M6_PUBLIC_COUNT
from customer360.contracts.generation import DatasetManifest
from customer360.contracts.hidden import HiddenTaskPack
from customer360.contracts.pack import GeneratedTaskPack
from customer360.contracts.pack_verify import (
    PUBLIC_VERIFY_FORBIDDEN,
    PackVariantResult,
    PackVerifyCase,
    PackVerifyReport,
    PublicPackVerifySummary,
)
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.generator import load_generated_pack
from customer360.tasks.hidden import load_hidden_dataset, load_hidden_pack
from customer360.tasks.independent import TableSlice, compute_independent
from customer360.tasks.pack_rewrites import case_rewrites_pass
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset, normalize_sql_result
from customer360.tasks.variant import load_named_variant, tiny_eval_policy
from customer360.tasks.wrong_sql import distinguish_wrong_sql

LIMITATIONS = (
    "Not an official score; ROADMAP section 8 weights are not applied",
    "m6_structure remains pack structure; semantic_passed is independent",
    "Independent oracle never executes SQL; compiler SQL is compared afterwards",
    "same_sql variants replay compiled Gold and do not invoke an Agent",
    "Zero-contributor Gold is POLICY_INCOMPATIBLE, not an Agent miss",
    "Oracle comparison is required even when the Agent policy rejects compiled Gold",
    "PERMISSION_DENIED records Gold outside Tiny Agent grants, not semantic failure",
    (
        "Hidden verify intentionally checks baseline semantics only; "
        "public four-variant replay is separate"
    ),
    "Family isolation is the full fingerprint, not per-template or per-Join isolation",
    "Public summary omits questions, Gold, specs, SQL and dataset seeds",
)

HIDDEN_PROFILE = "hidden_profile.json"


def _markdown(report: PackVerifyReport) -> str:
    lines = [
        "# Pack semantic verify",
        "",
        "Generated or hidden pack acceptance. Not an official score.",
        "",
        f"- semantic_passed: `{report.semantic_passed}`",
        f"- m6_structure: `{report.m6_structure}`",
        f"- scoring_applied: `{report.scoring_applied}`",
        f"- hidden: `{report.hidden}`",
        f"- case_count: `{report.case_count}`",
        f"- compilable_answers: `{report.compilable_answers}`",
        f"- independent_oracle_matches: `{report.independent_oracle_matches}`",
        f"- wrong_sql_classes: `{','.join(report.wrong_sql_classes)}`",
        f"- rewrite_passed: `{report.rewrite_passed}`",
        f"- replay_mode: `{report.replay_mode}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report.limitations)
    lines.append("")
    return "\n".join(lines)


def _public_summary(report: PackVerifyReport) -> PublicPackVerifySummary:
    return PublicPackVerifySummary(
        hidden=report.hidden,
        pack_id=report.pack_id,
        m6_structure=report.m6_structure,
        semantic_passed=report.semantic_passed,
        case_count=report.case_count,
        compilable_answers=report.compilable_answers,
        independent_oracle_matches=report.independent_oracle_matches,
        unscored_oracles=report.unscored_oracles,
        policy_incompatible_count=report.policy_incompatible_count,
        wrong_sql_classes=report.wrong_sql_classes,
        rewrite_passed=report.rewrite_passed,
        variant_count=report.variant_count,
        replay_mode=report.replay_mode,
        limitations=report.limitations,
    )


def _load_public_tiny(dataset_dir: Path):
    if (dataset_dir / HIDDEN_PROFILE).is_file():
        raise ValueError("verify-pack cannot use a hidden Tiny dataset")
    database, manifest = load_verified_dataset(dataset_dir)
    if not isinstance(manifest, DatasetManifest) or manifest.artifact_kind != "tiny_dataset":
        raise ValueError("pack semantic verify requires a Tiny dataset, not a public fixture")
    if manifest.seed != 42:
        raise ValueError("public pack semantic verify requires Tiny seed 42")
    return database, manifest


def _policy_block_code(
    gateway: ExecutionGateway, sql: str
) -> Literal["AGGREGATION_TOO_SMALL", "PERMISSION_DENIED"] | None:
    """Return an explicit policy diagnostic, never infer it from result values.

    The semantic verifier covers the full catalog, while the Tiny Agent policy
    intentionally grants only a subset of tables.  A compiled Gold query that
    references an ungranted but valid catalog table is therefore outside this
    policy probe, not a semantic failure.  Only the explicit minimum-group
    rejection is recorded as policy-incompatible; other policy errors remain
    hard failures because they indicate a broken compiled query.
    """

    try:
        receipt = gateway.execute(sql)
    except QueryRejected as exc:
        if exc.code == "AGGREGATION_TOO_SMALL":
            return "AGGREGATION_TOO_SMALL"
        if exc.code == "PERMISSION_DENIED":
            return "PERMISSION_DENIED"
        raise ValueError(f"compiled Gold rejected during semantic verify: {exc.code}") from exc
    except ExecutionFailure as exc:
        raise ValueError(
            f"compiled Gold execution failed during semantic verify: {exc.code}"
        ) from exc
    if receipt.result.truncated:
        raise ValueError("compiled Gold exceeds execution row limit during semantic verify")
    return None


def verify_task_pack(
    dataset_dir: Path,
    pack: GeneratedTaskPack | HiddenTaskPack,
    *,
    variant_dirs: tuple[Path, ...] = (),
    hidden: bool = False,
) -> PackVerifyReport:
    repository = MetadataRepository()
    if (
        pack.metrics_version != repository.metrics.metrics_version
        or pack.join_paths_version != repository.join_paths.join_paths_version
    ):
        raise ValueError("pack metadata version does not match the repository")
    if hidden:
        if variant_dirs:
            raise ValueError("hidden semantic verify cannot replay public Tiny variants")
        if not isinstance(pack, HiddenTaskPack):
            raise ValueError("hidden semantic verify requires a hidden task pack")
        database, manifest, _profile = load_hidden_dataset(dataset_dir)
        m6_structure = False
    else:
        if isinstance(pack, HiddenTaskPack):
            raise ValueError("public semantic verify cannot use a hidden pack")
        if (pack.m6_structure or pack.case_count >= M6_PUBLIC_COUNT) and len(variant_dirs) != 4:
            raise ValueError("300-case semantic verify requires the four frozen Tiny variants")
        database, manifest = _load_public_tiny(dataset_dir)
        m6_structure = pack.m6_structure
    loaded_variants = [load_named_variant(path) for path in variant_dirs]
    variant_ids = tuple(row[2] for row in loaded_variants)
    if len(set(variant_ids)) != len(variant_ids):
        raise ValueError("duplicate Tiny variant directory")
    if not hidden and (m6_structure or pack.case_count >= M6_PUBLIC_COUNT):
        if variant_ids != SEMANTIC_VERIFY_VARIANT_IDS:
            raise ValueError("300-case semantic verify requires the four frozen Tiny variants")
    slices = load_table_slices(database, repository.catalog)
    variants: list[tuple[str, Path, dict[str, TableSlice]]] = []
    variant_gateways: dict[str, ExecutionGateway] = {}
    for variant_db, variant_manifest, variant_id, _seed in loaded_variants:
        if variant_manifest.catalog_hash != manifest.catalog_hash:
            raise ValueError("baseline and variant must share the same catalog hash")
        if variant_manifest.content_hashes["dim_date"] != manifest.content_hashes["dim_date"]:
            raise ValueError("baseline and variant must share the same date dimension")
        variants.append((variant_id, variant_db, load_table_slices(variant_db, repository.catalog)))
        variant_gateways[variant_id] = ExecutionGateway(variant_db, tiny_eval_policy())
    gateway = ExecutionGateway(database, tiny_eval_policy())
    records: list[PackVerifyCase] = []
    policy_count = 0
    distinguished_classes: set[str] = set()
    rewrites_ok = True
    differed = 0
    for item in pack.cases:
        rewrite_passed = case_rewrites_pass(item, repository)
        rewrites_ok = rewrites_ok and rewrite_passed
        if item.material_status != "compilable_answer":
            spec = None
            if item.expected_action == "clarification_needed":
                spec = item.semantic_spec()
            contrast = distinguish_wrong_sql(
                intended=item.intended_failure_class,
                spec=spec,
                gold=None,
                independent=None,
                database=database,
                repository=repository,
                slices=slices,
            )
            if contrast.distinguished:
                distinguished_classes.add(item.intended_failure_class)
            records.append(
                PackVerifyCase(
                    case_id=item.case_id,
                    split=item.split,
                    expected_action=item.expected_action,
                    material_status=item.material_status,
                    intended_failure_class=item.intended_failure_class,
                    rewrite_passed=rewrite_passed,
                    wrong_sql_distinguished=contrast.distinguished,
                    wrong_sql_mode=contrast.mode,  # type: ignore[arg-type]
                    failure=None if rewrite_passed else "rewrite",
                )
            )
            continue
        spec = item.semantic_spec()
        compiled = compile_semantic(spec, repository)
        independent = compute_independent(spec, repository, slices)
        compiled_result = normalize_sql_result(database, compiled)
        baseline_match = compare_results(independent, compiled_result)
        policy_block = _policy_block_code(gateway, compiled.sql)
        policy_incompatible = policy_block == "AGGREGATION_TOO_SMALL"
        policy_count += int(policy_incompatible)
        contrast = distinguish_wrong_sql(
            intended=item.intended_failure_class,
            spec=spec,
            gold=compiled,
            independent=independent,
            database=database,
            repository=repository,
            slices=slices,
        )
        if contrast.distinguished:
            distinguished_classes.add(item.intended_failure_class)
        variant_rows: list[PackVariantResult] = []
        for variant_id, variant_db, variant_slices in variants:
            variant_independent = compute_independent(spec, repository, variant_slices)
            variant_result = normalize_sql_result(variant_db, compiled)
            variant_policy_block = _policy_block_code(variant_gateways[variant_id], compiled.sql)
            # Trusted Gold correctness and Agent applicability are separate axes.
            # A gateway rejection must never hide a broken compiler/oracle result.
            variant_match = compare_results(variant_independent, variant_result)
            changed = not compare_results(compiled_result, variant_result)
            differed += int(changed)
            variant_rows.append(
                PackVariantResult(
                    variant_id=variant_id,
                    independent_match=variant_match,
                    policy_incompatible=variant_policy_block == "AGGREGATION_TOO_SMALL",
                    policy_block_code=variant_policy_block,
                    results_differ_from_baseline=changed,
                )
            )
        failure = None
        if not baseline_match:
            failure = "independent_oracle_mismatch"
        elif any(not row.independent_match for row in variant_rows):
            failure = "variant_independent_oracle_mismatch"
        elif not rewrite_passed:
            failure = "rewrite"
        records.append(
            PackVerifyCase(
                case_id=item.case_id,
                split=item.split,
                expected_action=item.expected_action,
                material_status=item.material_status,
                intended_failure_class=item.intended_failure_class,
                independent_match=baseline_match,
                policy_incompatible=policy_incompatible,
                policy_block_code=policy_block,
                rewrite_passed=rewrite_passed,
                wrong_sql_distinguished=contrast.distinguished,
                wrong_sql_mode=contrast.mode,  # type: ignore[arg-type]
                compiled_sql=compiled.sql,
                independent_result=independent,
                variants=tuple(variant_rows),
                failure=failure,
            )
        )
    compilable = sum(item.material_status == "compilable_answer" for item in pack.cases)
    unscored = sum(item.material_status == "unscored_oracle" for item in pack.cases)
    baseline_matches = sum(item.independent_match is True for item in records)
    variant_ok = True
    if variants:
        variant_ok = (
            all(
                row.independent_match is True
                for item in records
                for row in item.variants
                if item.material_status == "compilable_answer"
            )
            and differed >= 1
        )
    covered = ERROR_CLASSES_REQUIRED <= distinguished_classes
    semantic_passed = (
        compilable > 0
        and baseline_matches == compilable
        and rewrites_ok
        and covered
        and variant_ok
        and pack.scoring_applied is False
    )
    return PackVerifyReport(
        hidden=hidden,
        pack_id=pack.pack_id,
        m6_structure=m6_structure,
        semantic_passed=semantic_passed,
        case_count=len(records),
        compilable_answers=compilable,
        independent_oracle_matches=baseline_matches,
        unscored_oracles=unscored,
        policy_incompatible_count=policy_count,
        wrong_sql_classes=tuple(sorted(distinguished_classes)),
        rewrite_passed=rewrites_ok,
        variant_count=len(variants),
        replay_mode="same_sql" if variants else "none",
        dataset_seed=manifest.seed,
        limitations=LIMITATIONS,
        cases=tuple(records),
    )


def write_pack_verify(
    dataset_dir: Path,
    pack_dir: Path,
    output_dir: Path,
    *,
    variant_dirs: tuple[Path, ...] = (),
    hidden: bool = False,
) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    pack: GeneratedTaskPack | HiddenTaskPack
    if hidden:
        pack = load_hidden_pack(pack_dir)
    else:
        pack = load_generated_pack(pack_dir)
    report = verify_task_pack(dataset_dir, pack, variant_dirs=variant_dirs, hidden=hidden)
    output_dir.mkdir(parents=True, exist_ok=False)
    private_dir = output_dir / "private"
    public_dir = output_dir / "public"
    private_dir.mkdir()
    public_dir.mkdir()
    payload = report.model_dump(mode="json")
    write_json_new(private_dir / "verify.json", payload)
    summary = _public_summary(report)
    public_payload = summary.model_dump(mode="json")
    leaked = PUBLIC_VERIFY_FORBIDDEN & set(public_payload)
    if leaked:
        raise ValueError("public pack verify summary leaked " + ",".join(sorted(leaked)))
    write_json_new(public_dir / "summary.json", public_payload)
    with (output_dir / "verify.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_markdown(report))
    return public_payload
