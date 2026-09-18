"""Named Tiny data variants. Canonical seed-42 Tiny is not rewritten."""

import shutil
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path

import duckdb

from customer360.artifacts import digest, json_text, write_json_new
from customer360.contracts.generation import DatasetManifest, GenerationConfig
from customer360.contracts.hidden_variant import (
    HIDDEN_VARIANT_IDS,
    HiddenVariantManifest,
    HiddenVariantSetManifest,
)
from customer360.contracts.variant import (
    MUTATION_VARIANT_IDS,
    VARIANT_ID,
    NamedVariantId,
    VariantDatasetManifest,
)
from customer360.metadata.metrics import load_catalog
from customer360.synth.generator import DATABASE_NAME, MANIFEST_NAME, generate_dataset

ANCHOR = date(2025, 6, 30)
WINDOW_START = ANCHOR - timedelta(days=89)
WINDOW_OUTSIDE = WINDOW_START - timedelta(days=1)
DUPLICATE_COPIES = 40
DATE_SHIFTS = 20
EXTRA_NULL_OCCUPATIONS = 5


def generate_named_variant(variant_id: NamedVariantId, output_dir: Path) -> dict:
    """Publish one frozen Tiny variant directory. Output must not exist."""
    allowed = (VARIANT_ID, *MUTATION_VARIANT_IDS)
    if variant_id not in allowed:
        raise ValueError(f"unknown Tiny variant: {variant_id}")
    if variant_id == VARIANT_ID:
        manifest, _quality = generate_dataset(GenerationConfig(seed=43), output_dir)
        return manifest
    if variant_id not in MUTATION_VARIANT_IDS:
        raise ValueError(f"unknown Tiny variant: {variant_id}")
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite dataset directory: {output_dir}")
    staging = output_dir.parent / f"{output_dir.name}.staging"
    if staging.exists():
        raise FileExistsError(f"refusing to overwrite staging directory: {staging}")
    generate_dataset(GenerationConfig(seed=42), staging)
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(staging / DATABASE_NAME, output_dir / DATABASE_NAME)
    conn = duckdb.connect(str(output_dir / DATABASE_NAME))
    try:
        if variant_id == "tiny_duplicate_fanout":
            _duplicate_fanout(conn)
        elif variant_id == "tiny_null_empty_groups":
            _null_empty_groups(conn)
        else:
            _date_boundary(conn)
        catalog = load_catalog()
        tables = tuple(table.table_name for table in catalog.tables)
        row_counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables
        }
        content_hashes = {
            table: digest(
                sorted(conn.execute(f'SELECT * FROM "{table}"').fetchall(), key=json_text)
            )
            for table in tables
        }
        parent = DatasetManifest.model_validate_json(
            (staging / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        manifest = VariantDatasetManifest(
            variant_id=variant_id,
            seed=42,
            anchor_date=ANCHOR,
            config_hash=parent.config_hash,
            catalog_hash=parent.catalog_hash,
            row_counts=row_counts,
            content_hashes=content_hashes,
            environment={name: version(name) for name in ("duckdb", "pydantic")},
        ).model_dump(mode="json")
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    write_json_new(output_dir / MANIFEST_NAME, manifest)
    shutil.rmtree(staging)
    return manifest


def generate_hidden_variants(parent_dir: Path, output_dir: Path) -> dict:
    """Generate the private four-variant set from an isolated hidden Tiny."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite hidden variant set: {output_dir}")
    parent_manifest = DatasetManifest.model_validate_json(
        (parent_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    if parent_manifest.seed in {42, 43}:
        raise ValueError("hidden variants require an isolated hidden parent seed")
    output_dir.mkdir(parents=True, exist_ok=False)
    parent_manifest_hash = digest(parent_manifest.model_dump(mode="json"))
    manifest_hashes: dict[str, str] = {}
    for offset, variant_id in enumerate(HIDDEN_VARIANT_IDS):
        derived_seed = parent_manifest.seed + 10000 + offset
        variant_dir = output_dir / variant_id
        if variant_id == "hidden_distribution":
            config = GenerationConfig.model_validate_json(
                (parent_dir / "generation_config.json").read_text(encoding="utf-8")
            ).model_copy(update={"seed": derived_seed})
            generate_dataset(config, variant_dir)
        else:
            _copy_and_mutate_hidden(parent_dir, variant_dir, variant_id)
        child = DatasetManifest.model_validate_json(
            (variant_dir / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        content_hashes = child.content_hashes
        private_manifest = HiddenVariantManifest(
            variant_id=variant_id,
            parent_seed=parent_manifest.seed,
            seed=derived_seed,
            catalog_hash=child.catalog_hash,
            parent_manifest_hash=parent_manifest_hash,
            manifest_hash=digest(child.model_dump(mode="json")),
            mutation_config_hash=digest({"variant_id": variant_id, "seed": derived_seed}),
            content_hashes=content_hashes,
            row_counts=child.row_counts,
        )
        write_json_new(
            variant_dir / "hidden_variant_manifest.json", private_manifest.model_dump(mode="json")
        )
        manifest_hashes[variant_id] = digest(private_manifest.model_dump(mode="json"))
    variant_set = HiddenVariantSetManifest(
        parent_seed=parent_manifest.seed,
        parent_manifest_hash=parent_manifest_hash,
        variant_manifest_hashes=manifest_hashes,
    )
    write_json_new(output_dir / "variant_set.json", variant_set.model_dump(mode="json"))
    return variant_set.model_dump(mode="json")


def _copy_and_mutate_hidden(parent_dir: Path, output_dir: Path, variant_id: str) -> None:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite hidden variant: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(parent_dir / DATABASE_NAME, output_dir / DATABASE_NAME)
    # Mutated hidden children retain the parent's generation provenance.  Copy
    # both sidecars so ``load_verified_dataset`` can validate that provenance
    # instead of treating the private child as an unverified ad-hoc database.
    for sidecar in ("generation_config.json", "quality_report.json"):
        source = parent_dir / sidecar
        if not source.is_file():
            raise ValueError(f"hidden parent is missing {sidecar}")
        shutil.copyfile(source, output_dir / sidecar)
    conn = duckdb.connect(str(output_dir / DATABASE_NAME))
    try:
        if variant_id == "hidden_duplicate_fanout":
            _duplicate_fanout(conn)
        elif variant_id == "hidden_null_empty_groups":
            _null_empty_groups(conn)
        elif variant_id == "hidden_date_boundary":
            _date_boundary(conn)
        else:
            raise ValueError(f"unknown hidden variant: {variant_id}")
        catalog = load_catalog()
        row_counts = {
            table.table_name: conn.execute(f'SELECT COUNT(*) FROM "{table.table_name}"').fetchone()[
                0
            ]
            for table in catalog.tables
        }
        content_hashes = {
            table.table_name: digest(
                sorted(
                    conn.execute(f'SELECT * FROM "{table.table_name}"').fetchall(), key=json_text
                )
            )
            for table in catalog.tables
        }
        parent = DatasetManifest.model_validate_json(
            (parent_dir / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        manifest = parent.model_copy(
            update={"row_counts": row_counts, "content_hashes": content_hashes}
        )
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    write_json_new(output_dir / MANIFEST_NAME, manifest.model_dump(mode="json"))


def _duplicate_fanout(conn) -> None:
    rows = conn.execute(
        """
        SELECT transaction_date, customer_id, product_id, transaction_type,
               amount, quantity, fee, status, channel
        FROM fact_transaction
        WHERE status = 'success'
          AND transaction_date >= ?
          AND transaction_date <= ?
        ORDER BY transaction_id
        LIMIT ?
        """,
        [WINDOW_START, ANCHOR, DUPLICATE_COPIES],
    ).fetchall()
    if len(rows) < DUPLICATE_COPIES:
        raise ValueError("duplicate variant needs 40 in-window success transactions")
    maximum = conn.execute(
        "SELECT MAX(CAST(substr(transaction_id, 2) AS INTEGER)) FROM fact_transaction"
    ).fetchone()[0]
    for offset, row in enumerate(rows, start=1):
        conn.execute(
            """
            INSERT INTO fact_transaction VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [f"T{maximum + offset:04d}", *row],
        )


def _null_empty_groups(conn) -> None:
    conn.execute(
        """
        UPDATE dim_customer
        SET region = '华南'
        WHERE customer_level = 'VIP' AND region = '华东'
        """
    )
    targets = conn.execute(
        """
        SELECT customer_id FROM dim_customer
        WHERE occupation IS NOT NULL AND customer_level = 'standard'
        ORDER BY customer_id
        LIMIT ?
        """,
        [EXTRA_NULL_OCCUPATIONS],
    ).fetchall()
    if len(targets) < EXTRA_NULL_OCCUPATIONS:
        raise ValueError("null variant needs extra standard customers with occupations")
    for (customer_id,) in targets:
        conn.execute(
            "UPDATE dim_customer SET occupation = NULL WHERE customer_id = ?",
            [customer_id],
        )


def _date_boundary(conn) -> None:
    targets = conn.execute(
        """
        SELECT transaction_id FROM fact_transaction
        WHERE status = 'success'
          AND transaction_date > ?
          AND transaction_date < ?
        ORDER BY transaction_id
        LIMIT ?
        """,
        [WINDOW_START, ANCHOR, DATE_SHIFTS],
    ).fetchall()
    if len(targets) < DATE_SHIFTS:
        raise ValueError("date-boundary variant needs interior success transactions")
    for (transaction_id,) in targets:
        conn.execute(
            "UPDATE fact_transaction SET transaction_date = ? WHERE transaction_id = ?",
            [WINDOW_OUTSIDE, transaction_id],
        )
