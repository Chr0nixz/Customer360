"""Public GitHub tree: community files, gitignore, no hidden artifacts in source roots."""

from __future__ import annotations

import json
from pathlib import Path

from customer360.contracts.evidence import DockerRuntimeEvidence
from customer360.release import _pyproject_excludes_hidden

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src", "tests", "configs", "docs", ".github", "data")
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
FORBIDDEN_NAMES = {
    "hidden_oracles.yaml",
    "hidden_profile.json",
    "hidden_variant_manifest.json",
    "generated_oracles.yaml",
    ".env",
}
ALLOWED_TRUSTED = {
    Path("data/trusted/human_oracles.yaml"),
    Path("data/trusted/README.txt"),
}
COMMUNITY_FILES = (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CITATION.cff",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    "Dockerfile",
    ".github/workflows/ci.yml",
    ".github/scripts/record_docker_runtime.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    "docs/github-publish.md",
    "docs/user-guide.md",
)
GITIGNORE_PATTERNS = (
    "outputs/",
    "data/hidden/",
    ".private/",
    ".env",
    "tmp-*/",
    "dist-*/",
    "*.duckdb",
)


def test_community_files_exist() -> None:
    missing = [name for name in COMMUNITY_FILES if not (REPO / name).is_file()]
    assert missing == []


def test_gitignore_covers_private_worktrees() -> None:
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    missing = [pattern for pattern in GITIGNORE_PATTERNS if pattern not in text]
    assert missing == []
    assert _pyproject_excludes_hidden(REPO) is True


def test_source_roots_exclude_private_artifacts() -> None:
    leaked: list[str] = []
    for root_name in SCAN_ROOTS:
        root = REPO / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(REPO)
            if relative in ALLOWED_TRUSTED:
                continue
            if path.name in FORBIDDEN_NAMES or path.suffix.lower() == ".duckdb":
                leaked.append(str(relative).replace("\\", "/"))
    assert leaked == []


def test_trusted_oracles_are_public_human_cases_only() -> None:
    text = (REPO / "data/trusted/human_oracles.yaml").read_text(encoding="utf-8")
    assert "C360_0001" in text
    assert "C360_0020" in text
    assert "C360_4001" not in text
    assert "C360_1001" not in text


def test_docker_runtime_evidence_shape_matches_ci_script() -> None:
    digest = "sha256:" + "ab" * 32
    payload = {
        "artifact_kind": "rc_evidence",
        "gate": "docker_runtime",
        "passed": True,
        "docker_digest": digest,
        "network": "none",
        "read_only": True,
        "non_root_user": "c360",
        "hidden_in_image": False,
        "command": "c360 doctor",
        "artifact_digests": {"image_id": digest},
        "limitations": [
            "Digest is docker inspect image Id; registry RepoDigest only exists after push",
        ],
    }
    row = DockerRuntimeEvidence.model_validate(json.loads(json.dumps(payload)))
    assert row.passed is True
    assert row.docker_digest == digest


def test_pyproject_keeps_apache_literal_for_license_gate() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = {text = "Apache-2.0"}' in text
    assert "CONTRIBUTING.md" in text
    assert "data/trusted" in text
