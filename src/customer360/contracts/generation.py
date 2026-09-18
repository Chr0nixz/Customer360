"""Generation-layer contracts: config, dataset manifest and quality records.

Scale sizes are frozen. Tiny identifiers and seed-42 recipes stay C001-style.
"""

from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Identifier, Text
from customer360.contracts.manifest import Hash, NineTableDigests

GeneratorVersion = Literal["0.1.0"]
Scale = Literal["tiny", "standard", "large"]
SCALE_SIZES = {
    "tiny": (100, 2000),
    "standard": (10_000, 300_000),
    "large": (100_000, 3_000_000),
}
SCALE_PRESETS: dict[str, dict[str, Any]] = {
    "tiny": {
        "scale": "tiny",
        "customers": 100,
        "transactions": 2000,
        "managers": 10,
        "products": 8,
        "cash_flows": 800,
        "customers_without_transactions": 5,
        "customers_without_positions": 5,
        "customers_with_null_occupation": 3,
    },
    "standard": {
        "scale": "standard",
        "customers": 10_000,
        "transactions": 300_000,
        "managers": 100,
        "products": 8,
        "cash_flows": 8_000,
        "customers_without_transactions": 500,
        "customers_without_positions": 500,
        "customers_with_null_occupation": 300,
    },
    "large": {
        "scale": "large",
        "customers": 100_000,
        "transactions": 3_000_000,
        "managers": 1_000,
        "products": 8,
        "cash_flows": 80_000,
        "customers_without_transactions": 5_000,
        "customers_without_positions": 5_000,
        "customers_with_null_occupation": 3_000,
    },
}
ARTIFACT_KIND = {
    "tiny": "tiny_dataset",
    "standard": "standard_dataset",
    "large": "large_dataset",
}
SNAPSHOT_VERSION = {
    "tiny": "tiny-v1",
    "standard": "standard-v2",
    "large": "large-v2",
}
SIZE_KEYS = frozenset(SCALE_PRESETS["tiny"]) - {"scale"}
# Original plan §5.3 floors: 5% without transactions, 5% without positions, 3% null occupation.
BOUNDARY_RATIOS = {
    "customers_without_transactions": (1, 20),
    "customers_without_positions": (1, 20),
    "customers_with_null_occupation": (3, 100),
}


def min_boundary_count(customers: int, numerator: int, denominator: int) -> int:
    return (customers * numerator + denominator - 1) // denominator


def meets_boundary_ratio(count: int, customers: int, numerator: int, denominator: int) -> bool:
    return count * denominator >= customers * numerator


class GenerationConfig(Contract):
    config_version: Literal["0.1"] = "0.1"
    scale: Scale = "tiny"
    seed: int = Field(default=42, ge=0)
    anchor_date: date = date(2025, 6, 30)
    horizon_start: date = date(2024, 7, 1)
    customers: int = Field(default=100, ge=1)
    transactions: int = Field(default=2000, ge=1)
    managers: int = Field(default=10, ge=1)
    products: int = Field(default=8, ge=1)
    cash_flows: int = Field(default=800, ge=1)
    snapshot_dates: tuple[date, ...] = (
        date(2024, 12, 31),
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 3, 31),
        date(2025, 4, 30),
        date(2025, 5, 31),
        date(2025, 6, 30),
    )
    customers_without_transactions: int = Field(default=5, ge=5)
    customers_without_positions: int = Field(default=5, ge=5)
    customers_with_null_occupation: int = Field(default=3, ge=3)

    @model_validator(mode="before")
    @classmethod
    def fill_scale_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        scale = data.get("scale", "tiny")
        if scale not in SCALE_PRESETS:
            return data
        filled = dict(data)
        for key, value in SCALE_PRESETS[scale].items():
            filled.setdefault(key, value)
        return filled

    @model_validator(mode="after")
    def frozen_scale_sizes(self) -> "GenerationConfig":
        expected = SCALE_SIZES[self.scale]
        if (self.customers, self.transactions) != expected:
            raise ValueError(
                f"{self.scale} scale is strictly {expected[0]} customers "
                f"and {expected[1]} transactions"
            )
        if self.horizon_start >= self.anchor_date:
            raise ValueError("horizon_start must precede anchor_date")
        dates = self.snapshot_dates
        if len(dates) < 2 or any(a >= b for a, b in zip(dates, dates[1:], strict=False)):
            raise ValueError("snapshot_dates need at least two strictly ascending dates")
        if dates[-1] != self.anchor_date or dates[0] < self.horizon_start:
            raise ValueError("snapshot_dates must start inside the horizon and end at anchor")
        designated = (
            self.customers_without_transactions
            + self.customers_without_positions
            + self.customers_with_null_occupation
        )
        if designated > self.customers:
            raise ValueError("disjoint designated groups must fit the customer count")
        for field, (numerator, denominator) in BOUNDARY_RATIOS.items():
            observed = getattr(self, field)
            required = min_boundary_count(self.customers, numerator, denominator)
            if observed < required:
                raise ValueError(
                    f"{field} must be at least {numerator}/{denominator} of customers "
                    f"({required} of {self.customers})"
                )
        return self


class DatasetManifest(NineTableDigests):
    """Generated dataset identity. Tiny is never marked as the six-customer fixture."""

    artifact_kind: Literal["tiny_dataset", "standard_dataset", "large_dataset"] = "tiny_dataset"
    generator_version: GeneratorVersion = "0.1.0"
    snapshot_version: Literal["tiny-v1", "standard-v2", "large-v2"] = "tiny-v1"
    schema_version: Literal["0.1"] = "0.1"
    metadata_version: Literal["0.1"] = "0.1"
    scale: Scale = "tiny"
    seed: int = Field(ge=0)
    anchor_date: date
    config_hash: Hash
    quality_report_hash: Hash
    environment: dict[str, Text]

    @model_validator(mode="after")
    def kind_matches_scale(self) -> "DatasetManifest":
        if self.artifact_kind != ARTIFACT_KIND[self.scale]:
            raise ValueError("artifact_kind must match scale")
        if self.snapshot_version != SNAPSHOT_VERSION[self.scale]:
            raise ValueError("snapshot_version must match scale")
        return self


class QualityCheck(Contract):
    check_id: Identifier
    description: Text
    passed: bool
    observed: Text


class QualityReport(Contract):
    quality_version: Literal["0.1"] = "0.1"
    generator_version: GeneratorVersion = "0.1.0"
    scale: Scale = "tiny"
    seed: int = Field(ge=0)
    anchor_date: date
    checks: tuple[QualityCheck, ...] = Field(min_length=30)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    all_passed: bool

    @model_validator(mode="after")
    def consistent_counts(self) -> "QualityReport":
        ids = [check.check_id for check in self.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate quality check id")
        passed = sum(1 for check in self.checks if check.passed)
        if passed != self.passed_count or len(self.checks) - passed != self.failed_count:
            raise ValueError("pass/fail counts do not match the check records")
        if self.all_passed != (self.failed_count == 0):
            raise ValueError("all_passed does not match failed_count")
        return self
