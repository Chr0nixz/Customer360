"""Shared trusted-side dataset loading, content verification and result rows.

Gold, coverage and variant replay must use the same integrity rules. Independent
Python oracles stay separate and must not import this module's SQL compiler path
for metric arithmetic.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
from pydantic import ValidationError

from customer360.artifacts import digest, json_text
from customer360.contracts.generation import DatasetManifest, GenerationConfig, QualityReport
from customer360.contracts.manifest import NineTableDigests
from customer360.contracts.public import QueryResult
from customer360.contracts.variant import VariantDatasetManifest
from customer360.metadata.metrics import load_catalog
from customer360.tasks.compiler import CompiledQuery

TrustedManifest = DatasetManifest | VariantDatasetManifest


def normalize_sql_result(database: Path, compiled: CompiledQuery) -> QueryResult:
    """Execute compiled SQL and keep every result row. Never use fetchone."""

    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(compiled.sql).fetchall()
    normalized = []
    for row in rows:
        cells = []
        for column, value in zip(compiled.columns, row, strict=True):
            if value is None:
                cells.append(None)
            elif column.kind == "decimal":
                cells.append(format(value, "f") if isinstance(value, Decimal) else str(value))
            elif column.kind == "integer":
                cells.append(int(value))
            elif column.kind == "date":
                cells.append(value.isoformat() if isinstance(value, date) else value)
            else:
                cells.append(value)
        normalized.append(tuple(cells))
    return QueryResult(columns=compiled.columns, rows=tuple(normalized))


def verify_manifest_contents(
    database: Path, manifest: NineTableDigests, catalog=None
) -> dict[str, str]:
    """Recompute catalog hash, row counts and nine-table content hashes from the DB."""

    catalog = catalog or load_catalog()
    catalog_tables = {table.table_name for table in catalog.tables}
    if set(manifest.row_counts) != catalog_tables or set(manifest.content_hashes) != catalog_tables:
        raise ValueError("dataset manifest must cover exactly the bundled nine tables")
    if manifest.catalog_hash != digest(catalog.model_dump(mode="json")):
        raise ValueError("dataset manifest catalog hash does not match bundled catalog")
    actual_hashes: dict[str, str] = {}
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            for table in catalog.tables:
                name = table.table_name
                count = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                rows = connection.execute(f'SELECT * FROM "{name}"').fetchall()
                if count != manifest.row_counts[name]:
                    raise ValueError(f"dataset row count mismatch for {name}")
                actual = digest(sorted(rows, key=json_text))
                if actual != manifest.content_hashes[name]:
                    raise ValueError(f"dataset content hash mismatch for {name}")
                actual_hashes[name] = actual
    except duckdb.Error as exc:
        raise ValueError("dataset database cannot be verified") from exc
    return actual_hashes


def _verify_generated_sidecars(dataset_dir: Path, manifest: DatasetManifest) -> None:
    """Verify the config and quality sidecars bound into a generated manifest."""

    config_path = dataset_dir / "generation_config.json"
    quality_path = dataset_dir / "quality_report.json"
    if not config_path.is_file() or not quality_path.is_file():
        raise ValueError(
            "generated dataset requires generation_config.json and quality_report.json"
        )
    try:
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
        quality_payload = json.loads(quality_path.read_text(encoding="utf-8"))
        config = GenerationConfig.model_validate(config_payload)
        quality = QualityReport.model_validate(quality_payload)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise ValueError("generated dataset sidecar is invalid") from exc
    if digest(config_payload) != manifest.config_hash:
        raise ValueError("dataset generation config hash does not match manifest")
    if digest(quality_payload) != manifest.quality_report_hash:
        raise ValueError("dataset quality report hash does not match manifest")
    if (
        config.scale != manifest.scale
        or config.seed != manifest.seed
        or config.anchor_date != manifest.anchor_date
        or quality.scale != manifest.scale
        or quality.seed != manifest.seed
        or quality.anchor_date != manifest.anchor_date
        or quality.generator_version != manifest.generator_version
        or not quality.all_passed
    ):
        raise ValueError("generated dataset sidecar identity does not match manifest")


def load_verified_dataset(dataset_dir: Path) -> tuple[Path, TrustedManifest]:
    """Load duckdb + manifest and refuse to proceed if on-disk contents drifted."""

    database = dataset_dir / "dataset.duckdb"
    manifest_path = dataset_dir / "manifest.json"
    if not database.is_file() or not manifest_path.is_file():
        raise ValueError("trusted dataset requires dataset.duckdb and manifest.json")
    try:
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("trusted dataset manifest is not valid JSON") from exc
    kind = parsed.get("artifact_kind") if isinstance(parsed, dict) else None
    try:
        if kind == "tiny_variant_dataset":
            manifest: TrustedManifest = VariantDatasetManifest.model_validate(parsed)
        elif kind in {"tiny_dataset", "standard_dataset", "large_dataset"}:
            manifest = DatasetManifest.model_validate(parsed)
        else:
            raise ValueError("trusted dataset artifact_kind is not a generated dataset")
    except ValidationError as exc:
        raise ValueError("trusted dataset manifest is invalid") from exc
    verify_manifest_contents(database, manifest)
    if isinstance(manifest, DatasetManifest):
        _verify_generated_sidecars(dataset_dir, manifest)
    return database, manifest
