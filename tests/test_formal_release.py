"""v1.0 formal score and RC evidence boundaries."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from customer360.artifacts import write_json_new
from customer360.contracts.evidence import (
    DockerRuntimeEvidence,
    NegativeControlEvidence,
    ScoreInputsEvidence,
    SemanticAcceptanceEvidence,
)
from customer360.contracts.formal import FormalSnapshot
from customer360.contracts.release import FormalReleaseManifest
from customer360.contracts.score import SCORE_WEIGHTS, ScoreDimension, ScoreGate, ScoreRunReport
from customer360.evaluator.score import load_score_input
from customer360.release import (
    check_formal_release,
    license_evidence,
    load_docker_runtime,
    load_score_inputs,
    load_semantic_acceptance,
    prepare_formal_release,
    public_artifacts_evidence,
)

REPO = Path(__file__).resolve().parents[1]


def _formal_dist_present(root: Path) -> bool:
    dist = root / "dist"
    wheels = sorted(dist.glob("customer360_agent_benchmark-1.0.0-*.whl"))
    sdists = sorted(dist.glob("customer360_agent_benchmark-1.0.0.tar.gz"))
    return bool(wheels and sdists)


@pytest.fixture(scope="module")
def formal_distributions() -> None:
    """CI checkouts do not commit dist/; build 1.0.0 artifacts when missing."""
    if _formal_dist_present(REPO):
        return
    uv = shutil.which("uv")
    assert uv, "uv executable is required to build 1.0.0 wheel/sdist"
    dest = REPO / "dist"
    dest.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [uv, "build", "--out-dir", str(dest)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert _formal_dist_present(REPO), completed.stderr or completed.stdout


def _dimension(name: str, passed: int, eligible: int) -> ScoreDimension:
    ratio = passed / eligible if eligible else 0.0
    return ScoreDimension(
        name=name,  # type: ignore[arg-type]
        weight=SCORE_WEIGHTS[name],
        passed=passed,
        eligible=eligible,
        score=ratio,
        contribution=ratio * SCORE_WEIGHTS[name],
        unavailable=("token_count", "scan_count") if name == "efficiency" else (),
    )


def _score_report(split: str, case_count: int, *, agent_id: str = "baseline") -> ScoreRunReport:
    dimensions = (
        _dimension("correctness", case_count * 9, case_count * 9),
        _dimension("safety", case_count, case_count),
        _dimension("interaction", case_count, case_count),
        _dimension("efficiency", case_count, case_count),
        _dimension("robustness", case_count, case_count),
    )
    return ScoreRunReport(
        split=split,  # type: ignore[arg-type]
        agent_id=agent_id,
        agent_version="1.0.0",
        case_count=case_count,
        eligible_count=case_count,
        weighted_score=sum(item.contribution for item in dimensions),
        dimensions=dimensions,
        hard_gates=tuple(
            ScoreGate(name=name, passed=True, reason="ok")
            for name in (
                "integrity",
                "p0_safety",
                "robustness_coverage",
                "nonempty_denominators",
            )
        ),
        environment={"os": "test"},
        input_report_digests={"formal_input": "a" * 64},
        evaluator_version="0.6",
        data_version="tiny-v1",
        task_version="generated-0.1",
        metadata_version="0.3",
        limitations=("local",),
    )


def _write_score_dir(path: Path, *, public_count: int = 120, hidden_count: int = 30) -> Path:
    path.mkdir()
    (path / "private").mkdir()
    write_json_new(
        path / "private/score.json",
        {
            "score_protocol_version": "1.0",
            "reports": [
                _score_report("public_dev", public_count).model_dump(mode="json"),
                _score_report("private_hidden", hidden_count).model_dump(mode="json"),
            ],
        },
    )
    return path


def test_formal_snapshot_requires_explicit_gold_policy_code() -> None:
    with pytest.raises(ValueError, match="policy code"):
        FormalSnapshot(snapshot_id="baseline", applicable=False)
    row = FormalSnapshot(
        snapshot_id="hidden_distribution",
        applicable=False,
        policy_code="AGGREGATION_TOO_SMALL",
    )
    assert row.independent_match is False


def test_historical_reports_cannot_be_scored(tmp_path: Path) -> None:
    path = tmp_path / "matrix.json"
    path.write_text('{"report_kind":"tiny_matrix_evaluation"}', encoding="utf-8")
    with pytest.raises(ValueError, match="formal_input"):
        load_score_input(path)


def test_formal_release_manifest_requires_all_rc_gates() -> None:
    with pytest.raises(ValueError, match="all named RC evidence gates"):
        FormalReleaseManifest(
            protocol_version="0.1",
            public_artifact_digests={"wheel": "a" * 64},
            checksum_file="SHA256SUMS",
            sbom_file="sbom.json",
            docker_digest="sha256:" + "a" * 64,
            gates={"license": True},
            limitations=("local",),
        )


def test_unsigned_docker_cannot_carry_a_digest() -> None:
    with pytest.raises(ValueError, match="unsigned docker_runtime"):
        FormalReleaseManifest(
            protocol_version="0.1",
            public_artifact_digests={"wheel": "a" * 64},
            checksum_file="SHA256SUMS",
            sbom_file="sbom.json",
            docker_digest="sha256:" + "a" * 64,
            gates={
                "score_inputs": False,
                "semantic_acceptance": False,
                "conformance": False,
                "negative_control": False,
                "public_artifacts": True,
                "license": True,
                "docker_runtime": False,
                "reproducible_build": False,
            },
            limitations=("local",),
        )


def test_empty_evidence_file_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_docker_runtime(empty)
    blank = tmp_path / "blank.json"
    blank.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be empty"):
        load_docker_runtime(blank)


def test_negative_control_cannot_pass_when_correctness_is_full() -> None:
    with pytest.raises(ValueError, match="failing wrong agent"):
        NegativeControlEvidence(
            passed=True,
            integrity_passed=True,
            correctness_full_pass=True,
            artifact_digests={"formal_input": "a" * 64},
            limitations=("x",),
        )


def test_fake_docker_digest_cannot_pass() -> None:
    with pytest.raises(ValueError, match="sha256"):
        DockerRuntimeEvidence(passed=True, docker_digest="sha256:abc123")


def test_score_inputs_reject_short_public_roster(tmp_path: Path) -> None:
    score_dir = _write_score_dir(tmp_path / "score", public_count=8)
    with pytest.raises(ValueError, match="120"):
        load_score_inputs(score_dir)


def test_score_inputs_accept_baseline_120(tmp_path: Path) -> None:
    score_dir = _write_score_dir(tmp_path / "score")
    evidence = load_score_inputs(score_dir)
    assert isinstance(evidence, ScoreInputsEvidence)
    assert evidence.passed is True
    assert evidence.agent_id == "baseline"
    assert evidence.public_case_count == 120


def test_semantic_acceptance_requires_nested_pass(tmp_path: Path) -> None:
    payload = {
        "gate": "semantic_acceptance",
        "passed": True,
        "public_semantic_passed": True,
        "hidden_semantic_passed": False,
        "hidden_case_count": 30,
        "artifact_digests": {"public_summary": "a" * 64},
        "limitations": ("x",),
    }
    path = tmp_path / "semantic.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match nested"):
        load_semantic_acceptance(path)


def test_semantic_acceptance_typed_file(tmp_path: Path) -> None:
    evidence = SemanticAcceptanceEvidence(
        passed=True,
        public_semantic_passed=True,
        hidden_semantic_passed=True,
        hidden_case_count=30,
        artifact_digests={"public_summary": "a" * 64, "hidden_summary": "b" * 64},
        limitations=("semantic_passed is not an official score",),
    )
    path = tmp_path / "semantic.json"
    path.write_text(json.dumps(evidence.model_dump(mode="json")), encoding="utf-8")
    loaded = load_semantic_acceptance(path)
    assert loaded.passed is True
    assert loaded.public_variant_count == 4


def test_public_artifacts_missing_dist_is_unsigned(tmp_path: Path) -> None:
    artifacts = public_artifacts_evidence(tmp_path)
    assert artifacts.wheel_present is False
    assert artifacts.sdist_present is False
    assert artifacts.leak_count == 1
    assert artifacts.passed is False


def test_license_and_public_artifacts_from_repo(formal_distributions) -> None:
    license_row = license_evidence(REPO)
    assert license_row.passed is True
    artifacts = public_artifacts_evidence(REPO)
    assert artifacts.wheel_present is True
    assert artifacts.sdist_present is True
    assert artifacts.leak_count == 0
    assert artifacts.passed is True


def test_prepare_formal_release_unsigned_docker_fails_check(
    tmp_path: Path, formal_distributions
) -> None:
    from customer360.tasks.generator import generate_task_pack, write_generated_pack

    pack_dir = tmp_path / "pack"
    write_generated_pack(pack_dir, generate_task_pack(seed=42, count=300))
    output = tmp_path / "release"
    payload = prepare_formal_release(output, public_pack=pack_dir, root=REPO)
    assert payload["gates"]["license"] is True
    assert payload["gates"]["public_artifacts"] is True
    assert payload["gates"]["docker_runtime"] is False
    assert payload["docker_digest"] == ""
    checked = check_formal_release(output, root=REPO)
    assert checked["passed"] is False
    assert any("docker_runtime" in item for item in checked["issues"])
