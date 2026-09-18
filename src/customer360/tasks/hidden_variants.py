"""Private hidden Tiny variant generation and integrity loading."""

from pathlib import Path

from customer360.artifacts import digest
from customer360.contracts.generation import DatasetManifest
from customer360.contracts.hidden_variant import (
    HIDDEN_VARIANT_IDS,
    HiddenVariantManifest,
    HiddenVariantSetManifest,
)
from customer360.synth.variants import generate_hidden_variants
from customer360.tasks.hidden import load_hidden_dataset
from customer360.tasks.trusted_data import load_verified_dataset


def write_hidden_variant_set(parent_dir: Path, output_dir: Path) -> dict:
    _database, parent_manifest, _profile = load_hidden_dataset(parent_dir)
    payload = generate_hidden_variants(parent_dir, output_dir)
    if payload["parent_manifest_hash"] != digest(parent_manifest.model_dump(mode="json")):
        raise ValueError("hidden variant parent manifest changed during generation")
    return payload


def load_hidden_variant_set(parent_dir: Path, variant_root: Path):
    _database, parent_manifest, _profile = load_hidden_dataset(parent_dir)
    set_manifest = HiddenVariantSetManifest.model_validate_json(
        (variant_root / "variant_set.json").read_text(encoding="utf-8")
    )
    expected_parent = digest(parent_manifest.model_dump(mode="json"))
    if set_manifest.parent_manifest_hash != expected_parent:
        raise ValueError("hidden variant set parent manifest does not match baseline")
    if set_manifest.parent_seed != parent_manifest.seed:
        raise ValueError("hidden variant parent seed mismatch")
    loaded = []
    for variant_id in HIDDEN_VARIANT_IDS:
        variant_dir = variant_root / variant_id
        database, manifest = load_verified_dataset(variant_dir)
        if not isinstance(manifest, DatasetManifest):
            raise ValueError("hidden variant must use a generated Tiny manifest")
        private_path = variant_dir / "hidden_variant_manifest.json"
        private = HiddenVariantManifest.model_validate_json(
            private_path.read_text(encoding="utf-8")
        )
        if private.variant_id != variant_id or private.parent_manifest_hash != expected_parent:
            raise ValueError("hidden variant provenance does not match its set")
        if private.manifest_hash != digest(manifest.model_dump(mode="json")):
            raise ValueError("hidden variant manifest digest mismatch")
        if set_manifest.variant_manifest_hashes[variant_id] != digest(
            private.model_dump(mode="json")
        ):
            raise ValueError("hidden variant set digest mismatch")
        if (
            private.parent_seed != parent_manifest.seed
            or private.seed != parent_manifest.seed + 10000 + HIDDEN_VARIANT_IDS.index(variant_id)
            or private.catalog_hash != manifest.catalog_hash
            or private.row_counts != manifest.row_counts
            or private.content_hashes != manifest.content_hashes
            or private.mutation_config_hash
            != digest({"variant_id": variant_id, "seed": private.seed})
        ):
            raise ValueError("hidden variant provenance fields mismatch")
        if manifest.catalog_hash != parent_manifest.catalog_hash:
            raise ValueError("hidden variant catalog hash does not match baseline")
        if manifest.content_hashes["dim_date"] != parent_manifest.content_hashes["dim_date"]:
            raise ValueError("hidden variant date dimension must remain unchanged")
        loaded.append((variant_id, database, manifest, private))
    return parent_manifest, set_manifest, tuple(loaded)


def load_hidden_variant_paths(parent_dir: Path, variant_dirs: tuple[Path, ...]):
    """Reject missing/reordered/aliased paths before loading any private data."""
    if len(variant_dirs) != 4:
        raise ValueError("formal hidden evaluation requires exactly four --variant paths")
    resolved = tuple(path.resolve(strict=True) for path in variant_dirs)
    if len(set(resolved)) != 4 or tuple(path.name for path in resolved) != HIDDEN_VARIANT_IDS:
        raise ValueError("hidden variants must be unique and in frozen order")
    if len({path.parent for path in resolved}) != 1:
        raise ValueError("hidden variants must belong to a single provenance set")
    return load_hidden_variant_set(parent_dir, resolved[0].parent)
