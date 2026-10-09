"""Automated benchmark environment setup.

Generates the canonical seed-42 Tiny baseline dataset and all four
frozen evaluation variants in a structured workspace.
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from customer360.artifacts import write_json_new
from customer360.contracts.generation import GenerationConfig
from customer360.synth.generator import generate_dataset
from customer360.synth.variants import generate_named_variant


def setup_benchmark_env(target_dir: Path, *, force: bool = False) -> dict:
    """Setup a complete local benchmark environment with baseline and all variants."""
    target_path = target_dir.resolve()
    if target_path.exists():
        if not force and any(target_path.iterdir()):
            raise FileExistsError(
                f"Refusing to overwrite non-empty target directory: {target_path}. "
                "Use --force to overwrite."
            )

    staging_dir = target_path.parent / f"{target_path.name}.staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        baseline_dir = staging_dir / "baseline"
        var_dist_dir = staging_dir / "variants" / "distribution"
        var_fanout_dir = staging_dir / "variants" / "fanout"
        var_null_dir = staging_dir / "variants" / "null"
        var_date_dir = staging_dir / "variants" / "date"

        # 1. Baseline seed-42 Tiny
        baseline_manifest, _ = generate_dataset(GenerationConfig(seed=42), baseline_dir)

        # 2. Four frozen variants
        dist_manifest = generate_named_variant("tiny_seed_43_distribution", var_dist_dir)
        fanout_manifest = generate_named_variant("tiny_duplicate_fanout", var_fanout_dir)
        null_manifest = generate_named_variant("tiny_null_empty_groups", var_null_dir)
        date_manifest = generate_named_variant("tiny_date_boundary", var_date_dir)

        env_manifest = {
            "env_version": "1.0",
            "scale": "tiny",
            "created_at": datetime.now(UTC).isoformat(),
            "baseline": {
                "path": str(target_path / "baseline"),
                "manifest": baseline_manifest,
            },
            "variants": {
                "distribution": {
                    "variant_id": "tiny_seed_43_distribution",
                    "path": str(target_path / "variants" / "distribution"),
                    "manifest": dist_manifest,
                },
                "fanout": {
                    "variant_id": "tiny_duplicate_fanout",
                    "path": str(target_path / "variants" / "fanout"),
                    "manifest": fanout_manifest,
                },
                "null": {
                    "variant_id": "tiny_null_empty_groups",
                    "path": str(target_path / "variants" / "null"),
                    "manifest": null_manifest,
                },
                "date": {
                    "variant_id": "tiny_date_boundary",
                    "path": str(target_path / "variants" / "date"),
                    "manifest": date_manifest,
                },
            },
        }

        manifest_file = staging_dir / "env_manifest.json"
        write_json_new(manifest_file, env_manifest)

        # Atomic replacement / move to target_dir
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)
        staging_dir.rename(target_path)
        return env_manifest
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise
