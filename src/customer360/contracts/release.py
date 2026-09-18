"""Candidate release manifest. Hidden Gold, Docker and official scores stay out."""

from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text
from customer360.contracts.evidence import DOCKER_DIGEST, RC_GATE_NAMES
from customer360.contracts.family import M6_PUBLIC_COUNT


class ReleaseManifest(Contract):
    artifact_kind: Literal["release_manifest"] = "release_manifest"
    release_id: Text
    package_version: Text
    protocol_version: Text
    evaluator_version: Text
    metrics_version: Text
    scoring_applied: Literal[False] = False
    docker_included: Literal[False] = False
    hidden_included: Literal[False] = False
    human_pack_untouched: bool
    m3_complete: bool
    m6_structure: bool
    public_generated_case_count: int = Field(ge=0)
    public_generated_train_count: int = Field(default=0, ge=0)
    public_generated_dev_count: int = Field(default=0, ge=0)
    hidden_case_count: int = Field(ge=0)
    isolation_passed: bool
    packaging_excludes_hidden: bool
    limitations: tuple[Text, ...]
    artifact_digests: dict[str, Text] = Field(default_factory=dict)

    @model_validator(mode="after")
    def release_is_not_a_score(self) -> "ReleaseManifest":
        if self.scoring_applied or self.docker_included or self.hidden_included:
            raise ValueError("public release cannot include scores, Docker or hidden artifacts")
        if self.hidden_case_count < 0:
            raise ValueError("hidden_case_count cannot be negative")
        if (
            self.public_generated_train_count + self.public_generated_dev_count
            != self.public_generated_case_count
        ):
            raise ValueError("public generated split counts do not match case_count")
        if self.m6_structure:
            if self.public_generated_case_count != M6_PUBLIC_COUNT:
                raise ValueError("m6_structure requires exactly 300 public generated cases")
            if self.public_generated_train_count != 180:
                raise ValueError("m6_structure requires 180 public train cases")
            if self.public_generated_dev_count != 120:
                raise ValueError("m6_structure requires 120 public generated dev cases")
        return self


class FormalReleaseManifest(Contract):
    """Public v1.0 release manifest; private evaluator inputs are referenced only by digest."""

    artifact_kind: Literal["formal_release_manifest"] = "formal_release_manifest"
    release_id: Literal["c360-1.0.0"] = "c360-1.0.0"
    package_version: Literal["1.0.0"] = "1.0.0"
    protocol_version: Text
    score_protocol_version: Literal["1.0"] = "1.0"
    evaluator_version: Literal["0.6"] = "0.6"
    pack_verify_protocol_version: Literal["0.2"] = "0.2"
    license: Literal["Apache-2.0"] = "Apache-2.0"
    scoring_applied: Literal[True] = True
    ranking_enabled: Literal[False] = False
    docker_included: Literal[True] = True
    hidden_included: Literal[False] = False
    public_generated_case_count: Literal[300] = 300
    public_generated_train_count: Literal[180] = 180
    public_generated_dev_count: Literal[120] = 120
    hidden_variant_count: Literal[4] = 4
    public_artifact_digests: dict[str, Text] = Field(default_factory=dict)
    private_input_digests: dict[str, Text] = Field(default_factory=dict)
    checksum_file: Text
    sbom_file: Text
    docker_digest: str = ""
    gates: dict[str, bool]
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def formal_boundary(self) -> "FormalReleaseManifest":
        if self.ranking_enabled or not self.scoring_applied:
            raise ValueError("formal release must score locally without ranking")
        if self.hidden_included:
            raise ValueError("hidden artifacts cannot be included in public release")
        if set(self.gates) != set(RC_GATE_NAMES):
            raise ValueError("formal release requires all named RC evidence gates")
        if self.gates.get("docker_runtime"):
            if not DOCKER_DIGEST.fullmatch(self.docker_digest):
                raise ValueError("passed docker_runtime requires an immutable Docker digest")
        elif self.docker_digest:
            raise ValueError("unsigned docker_runtime cannot carry a digest")
        if not self.public_artifact_digests:
            raise ValueError("formal release requires actual public artifact digests")
        return self
