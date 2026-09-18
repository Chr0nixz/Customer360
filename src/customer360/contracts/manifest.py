from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from customer360.contracts.base import Contract, Identifier, Text

Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RowCount = Annotated[int, Field(ge=0)]


class NineTableDigests(Contract):
    """Digest block shared by every dataset manifest: per-table counts and content hashes."""

    row_counts: dict[Identifier, RowCount]
    catalog_hash: Hash
    content_hashes: dict[Identifier, Hash]

    @model_validator(mode="after")
    def same_tables(self) -> "NineTableDigests":
        if len(self.row_counts) != 9 or self.row_counts.keys() != self.content_hashes.keys():
            raise ValueError("row counts and content hashes must cover the same nine tables")
        return self


class FixtureManifest(NineTableDigests):
    artifact_kind: Literal["public_fixture_not_tiny"] = "public_fixture_not_tiny"
    generator_version: Literal["fixture-0.1"] = "fixture-0.1"
    snapshot_version: Literal["fixture-v1"] = "fixture-v1"
    schema_version: Literal["0.1"] = "0.1"
    seed: int = Field(ge=0)
    config_hash: Hash
    environment: dict[str, Text]
