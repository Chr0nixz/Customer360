"""Typed RC evidence. A path existing is not a passed gate."""

import re
from typing import Literal

from pydantic import Field, model_validator

from customer360.contracts.base import Contract, Text

RC_GATE_NAMES = (
    "score_inputs",
    "semantic_acceptance",
    "conformance",
    "negative_control",
    "public_artifacts",
    "license",
    "docker_runtime",
    "reproducible_build",
)
RcGateName = Literal[
    "score_inputs",
    "semantic_acceptance",
    "conformance",
    "negative_control",
    "public_artifacts",
    "license",
    "docker_runtime",
    "reproducible_build",
]
DOCKER_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SCORE_HARD_GATES = (
    "integrity",
    "p0_safety",
    "robustness_coverage",
    "nonempty_denominators",
)


class RcEvidence(Contract):
    artifact_kind: Literal["rc_evidence"] = "rc_evidence"
    gate: RcGateName
    passed: bool
    artifact_digests: dict[str, Text] = Field(default_factory=dict)
    limitations: tuple[Text, ...] = ()


class ScoreInputsEvidence(RcEvidence):
    gate: Literal["score_inputs"] = "score_inputs"
    agent_id: Literal["baseline"] = "baseline"
    public_case_count: Literal[120] = 120
    hidden_case_count: int = Field(ge=8)
    ranking_enabled: Literal[False] = False
    scoring_applied: Literal[True] = True
    hard_gates_passed: bool
    score_protocol_version: Literal["1.0"] = "1.0"

    @model_validator(mode="after")
    def score_pass_matches_hard_gates(self) -> "ScoreInputsEvidence":
        if self.passed != self.hard_gates_passed:
            raise ValueError("score_inputs passed requires both splits' hard gates")
        if not self.artifact_digests:
            raise ValueError("score_inputs evidence requires score artifact digests")
        return self


class SemanticAcceptanceEvidence(RcEvidence):
    gate: Literal["semantic_acceptance"] = "semantic_acceptance"
    public_semantic_passed: bool
    hidden_semantic_passed: bool
    public_case_count: Literal[300] = 300
    hidden_case_count: int = Field(ge=8)
    public_variant_count: Literal[4] = 4
    hidden_variant_count: Literal[0] = 0
    scoring_applied: Literal[False] = False

    @model_validator(mode="after")
    def both_verifies_must_pass(self) -> "SemanticAcceptanceEvidence":
        expected = (
            self.public_semantic_passed and self.hidden_semantic_passed and not self.scoring_applied
        )
        if self.passed != expected:
            raise ValueError("semantic_acceptance passed does not match nested verify results")
        if not self.artifact_digests:
            raise ValueError("semantic_acceptance evidence requires verify summary digests")
        return self


class ConformanceEvidence(RcEvidence):
    gate: Literal["conformance"] = "conformance"
    agent_id: Literal["baseline"] = "baseline"
    split: Literal["public_dev"] = "public_dev"
    case_count: Literal[120] = 120
    integrity_passed: bool
    evaluator_version: Literal["0.6"] = "0.6"

    @model_validator(mode="after")
    def integrity_is_the_pass_bit(self) -> "ConformanceEvidence":
        if self.passed != self.integrity_passed:
            raise ValueError("conformance passed is integrity_passed, not a weighted score")
        if not self.artifact_digests:
            raise ValueError("conformance evidence requires formal_input digests")
        return self


class NegativeControlEvidence(RcEvidence):
    gate: Literal["negative_control"] = "negative_control"
    agent_id: Literal["wrong"] = "wrong"
    split: Literal["public_dev"] = "public_dev"
    case_count: Literal[120] = 120
    integrity_passed: bool
    correctness_full_pass: bool
    public_leaked: bool = False

    @model_validator(mode="after")
    def wrong_agent_must_not_fully_pass(self) -> "NegativeControlEvidence":
        expected = (
            self.integrity_passed and not self.correctness_full_pass and not self.public_leaked
        )
        if self.passed != expected:
            raise ValueError("negative_control passed requires a failing wrong agent with no leak")
        if self.correctness_full_pass and self.passed:
            raise ValueError("negative_control cannot pass when correctness is a full pass")
        if not self.artifact_digests:
            raise ValueError("negative_control evidence requires formal_input digests")
        return self


class PublicArtifactsEvidence(RcEvidence):
    gate: Literal["public_artifacts"] = "public_artifacts"
    wheel_present: bool
    sdist_present: bool
    leak_count: int = Field(ge=0)

    @model_validator(mode="after")
    def no_leaks(self) -> "PublicArtifactsEvidence":
        expected = self.wheel_present and self.sdist_present and self.leak_count == 0
        if self.passed != expected:
            raise ValueError("public_artifacts passed requires wheel, sdist and zero leaks")
        return self


class LicenseEvidence(RcEvidence):
    gate: Literal["license"] = "license"
    apache_license: bool
    notice_present: bool
    third_party_notices: bool
    pyproject_apache: bool

    @model_validator(mode="after")
    def apache_files(self) -> "LicenseEvidence":
        expected = (
            self.apache_license
            and self.notice_present
            and self.third_party_notices
            and self.pyproject_apache
        )
        if self.passed != expected:
            raise ValueError("license passed requires Apache-2.0 LICENSE, NOTICE and pyproject")
        return self


class DockerRuntimeEvidence(RcEvidence):
    gate: Literal["docker_runtime"] = "docker_runtime"
    docker_digest: str = ""
    network: Literal["none"] = "none"
    read_only: Literal[True] = True
    non_root_user: Text = "c360"
    hidden_in_image: bool = False
    command: Text = "c360 doctor"

    @model_validator(mode="after")
    def real_digest_only_when_passed(self) -> "DockerRuntimeEvidence":
        if self.passed:
            if not DOCKER_DIGEST.fullmatch(self.docker_digest):
                raise ValueError("passed docker_runtime requires sha256:<64 hex> digest")
            if self.network != "none" or not self.read_only:
                raise ValueError("passed docker_runtime requires --read-only --network=none")
            if self.hidden_in_image:
                raise ValueError("passed docker_runtime cannot include hidden artifacts")
        elif self.docker_digest:
            raise ValueError("unsigned docker_runtime cannot carry a digest")
        return self


class ReproducibleBuildEvidence(RcEvidence):
    gate: Literal["reproducible_build"] = "reproducible_build"
    package_version: Literal["1.0.0"] = "1.0.0"
    uv_lock_digest: Text
    member_names_match: bool
    byte_identical: bool

    @model_validator(mode="after")
    def byte_identical_required(self) -> "ReproducibleBuildEvidence":
        if not SHA256.fullmatch(self.uv_lock_digest):
            raise ValueError("uv.lock digest must be sha256 hex")
        expected = self.member_names_match and self.byte_identical
        if self.passed != expected:
            raise ValueError(
                "reproducible_build passed requires matching members and byte-identical artifacts"
            )
        if not self.artifact_digests:
            raise ValueError("reproducible_build evidence requires build artifact digests")
        return self


class RcEvidenceBundle(Contract):
    """Validated gate map written into the formal release manifest."""

    gates: dict[str, bool]
    evidence_digests: dict[str, Text] = Field(default_factory=dict)
    docker_digest: str = ""

    @model_validator(mode="after")
    def named_gates_only(self) -> "RcEvidenceBundle":
        if tuple(sorted(self.gates)) != tuple(sorted(RC_GATE_NAMES)):
            raise ValueError("formal release requires all named RC evidence gates")
        if self.gates.get("docker_runtime"):
            if not DOCKER_DIGEST.fullmatch(self.docker_digest):
                raise ValueError("passed docker_runtime requires an immutable digest")
        elif self.docker_digest:
            raise ValueError("unsigned docker_runtime cannot carry a digest")
        return self
