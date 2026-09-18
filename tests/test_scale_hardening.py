"""M1 复盘加固: illegal Standard/Large counts and Tiny-as-other-scale fail closed."""

from datetime import date

import pytest
from pydantic import ValidationError

from customer360.artifacts import digest
from customer360.contracts.generation import (
    SNAPSHOT_VERSION,
    DatasetManifest,
    GenerationConfig,
    meets_boundary_ratio,
)


def test_hardening_illegal_standard_and_large_counts_fail_closed():
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="standard", customers=100, transactions=2000)
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="large", customers=10_000, transactions=300_000)
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="tiny", customers=10_000, transactions=300_000)


def test_hardening_standard_and_large_meet_business_boundary_ratios():
    standard = GenerationConfig(scale="standard")
    large = GenerationConfig(scale="large")
    tiny = GenerationConfig()
    for config in (tiny, standard, large):
        assert meets_boundary_ratio(config.customers_without_transactions, config.customers, 1, 20)
        assert meets_boundary_ratio(config.customers_without_positions, config.customers, 1, 20)
        assert meets_boundary_ratio(config.customers_with_null_occupation, config.customers, 3, 100)
    assert (standard.customers_without_transactions, standard.customers_without_positions) == (
        500,
        500,
    )
    assert standard.customers_with_null_occupation == 300
    assert (large.customers_without_transactions, large.customers_with_null_occupation) == (
        5_000,
        3_000,
    )
    with pytest.raises(ValidationError, match="at least"):
        GenerationConfig(scale="standard", customers_without_transactions=50)
    assert SNAPSHOT_VERSION["tiny"] == "tiny-v1"
    assert SNAPSHOT_VERSION["standard"] == "standard-v2"
    assert SNAPSHOT_VERSION["large"] == "large-v2"


def test_hardening_tiny_manifest_cannot_be_relabeled_standard():
    tables = (
        "dim_customer",
        "dim_date",
        "dim_product",
        "dim_service_manager",
        "fact_asset_snapshot",
        "fact_cash_flow",
        "fact_holding",
        "fact_service_relation",
        "fact_transaction",
    )
    hashes = {name: digest(name) for name in tables}
    counts = dict.fromkeys(tables, 1)
    with pytest.raises(ValidationError, match="artifact_kind must match scale"):
        DatasetManifest(
            artifact_kind="tiny_dataset",
            snapshot_version="tiny-v1",
            scale="standard",
            seed=42,
            anchor_date=date(2025, 6, 30),
            config_hash=digest("config"),
            catalog_hash=digest("catalog"),
            row_counts=counts,
            content_hashes=hashes,
            quality_report_hash=digest("quality"),
            environment={},
        )
