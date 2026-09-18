"""Private hidden Tiny variant provenance and release contracts."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text

HIDDEN_VARIANT_IDS = (
    "hidden_distribution",
    "hidden_duplicate_fanout",
    "hidden_null_empty_groups",
    "hidden_date_boundary",
)


class HiddenVariantManifest(Contract):
    artifact_kind: Literal["hidden_tiny_variant"] = "hidden_tiny_variant"
    hidden: Literal[True] = True
    variant_id: Literal[
        "hidden_distribution",
        "hidden_duplicate_fanout",
        "hidden_null_empty_groups",
        "hidden_date_boundary",
    ]
    parent_seed: int = Field(ge=0)
    seed: int = Field(ge=0)
    snapshot_version: Literal["tiny-v1"] = "tiny-v1"
    generator_version: Literal["0.1.0"] = "0.1.0"
    catalog_hash: Text
    parent_manifest_hash: Text
    manifest_hash: Text
    mutation_config_hash: Text
    content_hashes: dict[str, Text]
    row_counts: dict[str, int]

    @model_validator(mode="after")
    def private_provenance(self) -> "HiddenVariantManifest":
        if self.seed in {42, 43} or self.parent_seed in {42, 43}:
            raise ValueError("hidden variants cannot reuse public seeds")
        if self.seed == self.parent_seed:
            raise ValueError("hidden variant seed must be independently derived")
        if self.manifest_hash == self.parent_manifest_hash:
            raise ValueError("hidden variant must differ from its parent manifest")
        return self


class HiddenVariantSetManifest(Contract):
    artifact_kind: Literal["hidden_tiny_variant_set"] = "hidden_tiny_variant_set"
    hidden: Literal[True] = True
    parent_seed: int = Field(ge=0)
    parent_manifest_hash: Text
    variant_ids: tuple[
        Literal[
            "hidden_distribution",
            "hidden_duplicate_fanout",
            "hidden_null_empty_groups",
            "hidden_date_boundary",
        ],
        ...,
    ] = HIDDEN_VARIANT_IDS
    variant_manifest_hashes: dict[str, Text]
    generator_version: Literal["0.1.0"] = "0.1.0"
    snapshot_version: Literal["tiny-v1"] = "tiny-v1"

    @model_validator(mode="after")
    def complete_set(self) -> "HiddenVariantSetManifest":
        if self.variant_ids != HIDDEN_VARIANT_IDS:
            raise ValueError("hidden variant set must contain all four variants in order")
        if set(self.variant_manifest_hashes) != set(HIDDEN_VARIANT_IDS):
            raise ValueError("hidden variant manifest hashes must contain all four variants")
        if self.parent_seed in {42, 43}:
            raise ValueError("hidden variant set cannot reuse public seeds")
        return self
