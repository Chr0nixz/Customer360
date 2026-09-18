"""Candidate and formal local release checks."""

import hashlib
import json
import shutil
import tomllib
from pathlib import Path
from tarfile import TarFile
from zipfile import ZipFile

from customer360 import __version__
from customer360.artifacts import digest, write_json_new
from customer360.contracts.evaluation import EVALUATOR_VERSION
from customer360.contracts.evidence import (
    RC_GATE_NAMES,
    SCORE_HARD_GATES,
    ConformanceEvidence,
    DockerRuntimeEvidence,
    LicenseEvidence,
    NegativeControlEvidence,
    PublicArtifactsEvidence,
    RcEvidence,
    ReproducibleBuildEvidence,
    ScoreInputsEvidence,
    SemanticAcceptanceEvidence,
)
from customer360.contracts.family import M6_PUBLIC_COUNT
from customer360.contracts.formal import FormalEvaluationReport
from customer360.contracts.hidden import HiddenTaskPack
from customer360.contracts.pack import GeneratedTaskPack
from customer360.contracts.pack_verify import PUBLIC_VERIFY_FORBIDDEN, PublicPackVerifySummary
from customer360.contracts.release import FormalReleaseManifest, ReleaseManifest
from customer360.contracts.score import ScoreRunReport
from customer360.evaluator.score import aggregate_score
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.catalog import load_human_cases, load_public_cases
from customer360.tasks.isolation import check_generated_isolation, check_human_pack_frozen

LIMITATIONS = (
    "Not an official weighted score; ROADMAP section 8 denominators are unfrozen",
    "Docker images are deferred until ROADMAP section 10 run-location is confirmed",
    "Hidden cases and hidden Tiny never enter wheel, sdist or this public manifest's files",
    "C360_0001-0020 remain split=dev and are not relabeled private",
    "TemplateAgent is not the official baseline; network adapters stay fail-closed",
)

REPO_ROOT = Path(__file__).resolve().parents[2]

FORMAL_LIMITATIONS = (
    "Scores are local audit artifacts; ranking_enabled is permanently false",
    "Hidden data, trusted Gold and private evaluator inputs are not public artifacts",
    "Token count and scan volume remain unavailable rather than reported as zero",
    "v1.0.0 is unsigned until every RC evidence gate passes, including docker_runtime",
)
ARCHIVE_FORBIDDEN_PARTS = frozenset(
    {"outputs", ".venv", ".private", "hidden", "trusted", "secrets"}
)
ARCHIVE_FORBIDDEN_NAMES = frozenset(
    {
        "generated_oracles.yaml",
        "hidden_oracles.yaml",
        "hidden_profile.json",
        "hidden_variant_manifest.json",
    }
)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _archive_names(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            return tuple(archive.namelist())
    with TarFile.open(path, "r:gz") as archive:
        return tuple(archive.getnames())


def distribution_leaks(path: Path) -> tuple[str, ...]:
    leaked: list[str] = []
    for raw in _archive_names(path):
        parts = Path(raw.replace("\\", "/")).parts
        labels = [part.lower() for part in parts]
        filename = labels[-1] if labels else ""
        if any(part in ARCHIVE_FORBIDDEN_PARTS for part in labels):
            leaked.append(raw)
        elif filename in ARCHIVE_FORBIDDEN_NAMES:
            leaked.append(raw)
        elif filename.endswith(".duckdb") or filename == ".env" or filename.startswith(".env."):
            leaked.append(raw)
    return tuple(leaked)


def _formal_distributions(root: Path) -> tuple[Path, Path]:
    dist = root / "dist"
    wheels = sorted(dist.glob("customer360_agent_benchmark-1.0.0-*.whl"))
    sdists = sorted(dist.glob("customer360_agent_benchmark-1.0.0.tar.gz"))
    if not wheels or not sdists:
        raise ValueError("formal release requires the 1.0.0 wheel and sdist in dist/")
    return wheels[-1], sdists[-1]


def _sbom_document(root: Path) -> dict:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    components = [{"type": "library", "name": "customer360-agent-benchmark", "version": "1.0.0"}]
    seen: set[tuple[str, str]] = {("customer360-agent-benchmark", "1.0.0")}
    for package in lock.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if not name or not version or (name, version) in seen:
            continue
        seen.add((name, version))
        components.append({"type": "library", "name": name, "version": version})
    components.sort(key=lambda item: (item["name"], item["version"]))
    return {
        "bomFormat": "cyclonedx",
        "specVersion": "1.5",
        "version": 1,
        "components": components,
    }


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"RC evidence is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"RC evidence cannot be empty: {path}")
    return payload


def _public_verify_summary(path: Path) -> PublicPackVerifySummary:
    summary = path / "public/summary.json" if path.is_dir() else path
    if not summary.is_file():
        raise ValueError(f"pack verify summary not found: {summary}")
    return PublicPackVerifySummary.model_validate(_load_json(summary))


def bind_semantic_acceptance(
    public_verify: Path, hidden_verify: Path
) -> SemanticAcceptanceEvidence:
    public = _public_verify_summary(public_verify)
    hidden = _public_verify_summary(hidden_verify)
    if public.hidden or not public.m6_structure or public.case_count != 300:
        raise ValueError("semantic_acceptance public verify must be the 300-case pack")
    if public.variant_count != 4 or public.scoring_applied:
        raise ValueError("semantic_acceptance public verify requires four variants and no score")
    if not hidden.hidden or hidden.variant_count != 0 or hidden.scoring_applied:
        raise ValueError("semantic_acceptance hidden verify must be baseline-only")
    if hidden.case_count < 8:
        raise ValueError("semantic_acceptance hidden verify roster is too small")
    leaked = PUBLIC_VERIFY_FORBIDDEN & set(public.model_dump(mode="json"))
    leaked |= PUBLIC_VERIFY_FORBIDDEN & set(hidden.model_dump(mode="json"))
    if leaked:
        raise ValueError("semantic_acceptance public summary leaked " + ",".join(sorted(leaked)))
    return SemanticAcceptanceEvidence(
        passed=public.semantic_passed and hidden.semantic_passed,
        public_semantic_passed=public.semantic_passed,
        hidden_semantic_passed=hidden.semantic_passed,
        hidden_case_count=hidden.case_count,
        artifact_digests={
            "public_summary": digest(public.model_dump(mode="json")),
            "hidden_summary": digest(hidden.model_dump(mode="json")),
        },
        limitations=("semantic_passed is not an official score",),
    )


def load_semantic_acceptance(path: Path) -> SemanticAcceptanceEvidence:
    if path.is_dir():
        public = path / "public_summary.json"
        hidden = path / "hidden_summary.json"
        if public.is_file() and hidden.is_file():
            return bind_semantic_acceptance(public, hidden)
        raise ValueError(
            "semantic_acceptance directory needs public_summary.json and hidden_summary.json"
        )
    payload = _load_json(path)
    if payload.get("gate") == "semantic_acceptance":
        return SemanticAcceptanceEvidence.model_validate(payload)
    raise ValueError("semantic_acceptance evidence must be typed rc_evidence")


def load_score_bundle(score_dir: Path) -> tuple[ScoreRunReport, ScoreRunReport]:
    path = score_dir / "private/score.json" if score_dir.is_dir() else score_dir
    if not path.is_file():
        raise ValueError("score_dir must contain private/score.json")
    payload = _load_json(path)
    reports = tuple(ScoreRunReport.model_validate(item) for item in payload.get("reports", ()))
    if tuple(item.split for item in reports) != ("public_dev", "private_hidden"):
        raise ValueError("score requires exactly public_dev and private_hidden, separately")
    if len({item.agent_id for item in reports}) != 1:
        raise ValueError("score inputs must describe the same agent")
    return reports[0], reports[1]


def load_score_inputs(score_dir: Path) -> ScoreInputsEvidence:
    public, hidden = load_score_bundle(score_dir)
    if public.agent_id != "baseline" or hidden.agent_id != "baseline":
        raise ValueError("score_inputs RC evidence requires agent_id=baseline")
    if public.case_count != 120:
        raise ValueError("score_inputs public_dev requires 120 generated-dev cases")
    if hidden.case_count < 8:
        raise ValueError("score_inputs hidden roster is too small")
    if public.ranking_enabled or hidden.ranking_enabled:
        raise ValueError("score_inputs cannot enable ranking")
    for report in (public, hidden):
        names = {item.name for item in report.hard_gates}
        if set(SCORE_HARD_GATES) - names:
            raise ValueError("score_inputs missing frozen hard gates")
    hard = all(item.passed for report in (public, hidden) for item in report.hard_gates)
    score_path = score_dir / "private/score.json" if score_dir.is_dir() else score_dir
    return ScoreInputsEvidence(
        passed=hard,
        hidden_case_count=hidden.case_count,
        hard_gates_passed=hard,
        artifact_digests={"score": _sha256(score_path)},
        limitations=public.limitations,
    )


def _load_formal_input(path: Path) -> FormalEvaluationReport:
    report_path = path / "private/formal_input.json" if path.is_dir() else path
    if not report_path.is_file():
        raise ValueError(f"formal_input not found: {report_path}")
    try:
        return FormalEvaluationReport.model_validate(_load_json(report_path))
    except Exception as exc:
        raise ValueError("RC evidence is not a formal_input report") from exc


def _public_summary_leaked(path: Path) -> bool:
    summary = path / "public/summary.json" if path.is_dir() else None
    if summary is None or not summary.is_file():
        return True
    text = summary.read_text(encoding="utf-8")
    return any(
        token in text for token in ("semantic_spec", "candidate_sql", "hidden_seed", "compiled_sql")
    )


def load_conformance(path: Path) -> ConformanceEvidence:
    report = _load_formal_input(path)
    if report.agent_id != "baseline" or report.split != "public_dev":
        raise ValueError("conformance requires evaluate-public --agent baseline")
    if report.case_count != 120 or report.evaluator_version != "0.6":
        raise ValueError("conformance requires 120 public_dev cases on evaluator 0.6")
    if report.scoring_applied:
        raise ValueError("conformance formal_input cannot already apply scores")
    report_path = path / "private/formal_input.json" if path.is_dir() else path
    return ConformanceEvidence(
        passed=report.integrity_passed,
        integrity_passed=report.integrity_passed,
        artifact_digests={"formal_input": _sha256(report_path)},
        limitations=("weighted score is not the conformance pass bit",),
    )


def load_negative_control(path: Path) -> NegativeControlEvidence:
    report = _load_formal_input(path)
    if report.agent_id != "wrong" or report.split != "public_dev":
        raise ValueError("negative_control requires evaluate-public --agent wrong")
    if report.case_count != 120:
        raise ValueError("negative_control requires 120 public_dev cases")
    scored = aggregate_score(report)
    correctness = next(item for item in scored.dimensions if item.name == "correctness")
    full_pass = correctness.eligible > 0 and correctness.passed == correctness.eligible
    leaked = _public_summary_leaked(path)
    report_path = path / "private/formal_input.json" if path.is_dir() else path
    return NegativeControlEvidence(
        passed=report.integrity_passed and not full_pass and not leaked,
        integrity_passed=report.integrity_passed,
        correctness_full_pass=full_pass,
        public_leaked=leaked,
        artifact_digests={"formal_input": _sha256(report_path)},
        limitations=("WrongAgent is a negative control, not an official baseline",),
    )


def load_docker_runtime(path: Path) -> DockerRuntimeEvidence:
    return DockerRuntimeEvidence.model_validate(_load_json(path))


def load_reproducible_build(path: Path) -> ReproducibleBuildEvidence:
    return ReproducibleBuildEvidence.model_validate(_load_json(path))


def bind_reproducible_build(
    first_dist: Path, second_dist: Path, *, root: Path
) -> ReproducibleBuildEvidence:
    first_wheel, first_sdist = _distributions_in(first_dist)
    second_wheel, second_sdist = _distributions_in(second_dist)
    first_names = tuple(sorted(_archive_names(first_wheel))) + tuple(
        sorted(_archive_names(first_sdist))
    )
    second_names = tuple(sorted(_archive_names(second_wheel))) + tuple(
        sorted(_archive_names(second_sdist))
    )
    lock = root / "uv.lock"
    first_hashes = {"wheel": _sha256(first_wheel), "sdist": _sha256(first_sdist)}
    second_hashes = {"wheel": _sha256(second_wheel), "sdist": _sha256(second_sdist)}
    return ReproducibleBuildEvidence(
        passed=first_names == second_names and first_hashes == second_hashes,
        uv_lock_digest=_sha256(lock),
        member_names_match=first_names == second_names,
        byte_identical=first_hashes == second_hashes,
        artifact_digests={
            "first_wheel": first_hashes["wheel"],
            "first_sdist": first_hashes["sdist"],
            "second_wheel": second_hashes["wheel"],
            "second_sdist": second_hashes["sdist"],
        },
        limitations=("Byte-identical wheels are required; timestamps cannot be ignored",),
    )


def _distributions_in(directory: Path) -> tuple[Path, Path]:
    wheels = sorted(directory.glob("customer360_agent_benchmark-1.0.0-*.whl"))
    sdists = sorted(directory.glob("customer360_agent_benchmark-1.0.0.tar.gz"))
    if not wheels or not sdists:
        raise ValueError(f"reproducible build directory missing 1.0.0 wheel/sdist: {directory}")
    return wheels[-1], sdists[-1]


def license_evidence(root: Path) -> LicenseEvidence:
    license_path = root / "LICENSE"
    notice_path = root / "NOTICE"
    third = root / "THIRD_PARTY_NOTICES.md"
    pyproject = root / "pyproject.toml"
    license_text = license_path.read_text(encoding="utf-8") if license_path.is_file() else ""
    notice_text = notice_path.read_text(encoding="utf-8") if notice_path.is_file() else ""
    project_text = pyproject.read_text(encoding="utf-8") if pyproject.is_file() else ""
    apache = "Apache License" in license_text and "Version 2.0" in license_text
    pyproject_apache = 'license = {text = "Apache-2.0"}' in project_text
    return LicenseEvidence(
        passed=apache and notice_path.is_file() and third.is_file() and pyproject_apache,
        apache_license=apache,
        notice_present=notice_path.is_file() and "Apache-2.0" in notice_text,
        third_party_notices=third.is_file(),
        pyproject_apache=pyproject_apache,
        artifact_digests={
            name: _sha256(path)
            for name, path in (
                ("LICENSE", license_path),
                ("NOTICE", notice_path),
                ("THIRD_PARTY_NOTICES.md", third),
            )
            if path.is_file()
        },
        limitations=("Apache-2.0 covers the package; hidden data is not a public artifact",),
    )


def public_artifacts_evidence(root: Path) -> PublicArtifactsEvidence:
    try:
        wheel, sdist = _formal_distributions(root)
    except ValueError:
        return PublicArtifactsEvidence(
            passed=False,
            wheel_present=False,
            sdist_present=False,
            leak_count=1,
            limitations=("1.0.0 wheel and sdist must exist in dist/",),
        )
    leaks = distribution_leaks(wheel) + distribution_leaks(sdist)
    return PublicArtifactsEvidence(
        passed=not leaks,
        wheel_present=True,
        sdist_present=True,
        leak_count=len(leaks),
        artifact_digests={"wheel": _sha256(wheel), "sdist": _sha256(sdist)},
        limitations=("Hidden data, trusted Gold and oracles must not appear in distributions",),
    )


def _artifact_files(root: Path) -> list[Path]:
    forbidden = {"hidden", "trusted", "outputs", ".private"}
    private_names = {"generated_oracles.yaml", "hidden_oracles.yaml"}
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in forbidden for part in relative.parts) or path.name in private_names:
            continue
        files.append(path)
    return files


def _public_leak_issues(root: Path) -> list[str]:
    issues: list[str] = []
    forbidden_names = {"hidden_profile.json", "hidden_variant_manifest.json", "variant_set.json"}
    for path in _artifact_files(root):
        if path.name in forbidden_names or "gold" in path.name.lower():
            issues.append(f"forbidden public artifact: {path.relative_to(root)}")
        if path.suffix.lower() in {".json", ".jsonl", ".yaml", ".yml", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in ("hidden_seed", "semantic_spec", "candidate_sql")):
                issues.append(
                    f"private evaluator field in public artifact: {path.relative_to(root)}"
                )
    return issues


def _pyproject_excludes_hidden(root: Path) -> bool:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    return (
        "data/hidden" in text
        and "data/hidden/" in gitignore
        and "outputs/" in gitignore
        and "tmp-*/" in gitignore
        and "*.duckdb" in gitignore
    )


def prepare_release(
    output_dir: Path,
    *,
    public_pack: Path | None = None,
    hidden_pack: Path | None = None,
    oracles: Path | None = None,
    root: Path | None = None,
) -> dict:
    root = root or REPO_ROOT
    human = load_human_cases(oracles=oracles, check_rewrites=False)
    human_issues = check_human_pack_frozen(human)
    public_cases = load_public_cases()
    repository = MetadataRepository()
    generated = None
    hidden = None
    isolation_passed = not human_issues
    if public_pack is not None:
        generated = GeneratedTaskPack.model_validate_json(
            (public_pack / "pack.json").read_text(encoding="utf-8")
        )
        if (
            generated.metrics_version != repository.metrics.metrics_version
            or generated.join_paths_version != repository.join_paths.join_paths_version
        ):
            raise ValueError("public generated pack metadata version does not match the repository")
        isolation = check_generated_isolation(human, generated)
        isolation_passed = isolation.passed
    if hidden_pack is not None:
        if generated is None:
            raise ValueError("hidden pack isolation requires the public generated pack")
        hidden = HiddenTaskPack.model_validate_json(
            (hidden_pack / "pack.json").read_text(encoding="utf-8")
        )
        if (
            hidden.metrics_version != repository.metrics.metrics_version
            or hidden.join_paths_version != repository.join_paths.join_paths_version
        ):
            raise ValueError("hidden pack metadata version does not match the repository")
        from customer360.tasks.isolation import check_hidden_isolation

        isolation_passed = check_hidden_isolation(human, generated, hidden).passed
    packaging_ok = _pyproject_excludes_hidden(root)
    digests = {
        "human_public_cases": digest(public_cases.model_dump(mode="json")),
        "metrics": digest(repository.metrics.model_dump(mode="json")),
    }
    if generated is not None:
        digests["public_generated_questions"] = digest(
            tuple((item.case_id, item.split, item.question) for item in generated.cases)
        )
    manifest = ReleaseManifest(
        release_id=f"c360-{__version__}-m6-candidate",
        package_version=__version__,
        protocol_version="0.1",
        evaluator_version=EVALUATOR_VERSION,
        metrics_version=repository.metrics.metrics_version,
        human_pack_untouched=not human_issues,
        m3_complete=bool(generated and generated.m3_complete),
        m6_structure=bool(
            generated
            and generated.m6_structure
            and generated.case_count == M6_PUBLIC_COUNT
            and sum(item.split == "train" for item in generated.cases) == 180
            and sum(item.split == "dev" for item in generated.cases) == 120
        ),
        public_generated_case_count=generated.case_count if generated else 0,
        public_generated_train_count=(
            sum(item.split == "train" for item in generated.cases) if generated else 0
        ),
        public_generated_dev_count=(
            sum(item.split == "dev" for item in generated.cases) if generated else 0
        ),
        hidden_case_count=hidden.case_count if hidden else 0,
        isolation_passed=isolation_passed,
        packaging_excludes_hidden=packaging_ok,
        limitations=LIMITATIONS,
        artifact_digests=digests,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json_new(output_dir / "release_manifest.json", manifest.model_dump(mode="json"))
    payload = manifest.model_dump(mode="json")
    text = (output_dir / "release_manifest.json").read_text(encoding="utf-8")
    for leaked in ("semantic_spec", "candidate_sql", "hidden_oracles", "hidden_seed"):
        if leaked in text:
            raise ValueError(f"release manifest leaked {leaked}")
    return payload


def check_release(manifest_dir: Path, *, root: Path | None = None) -> dict:
    root = root or REPO_ROOT
    path = manifest_dir / "release_manifest.json"
    if not path.is_file():
        raise ValueError("release_manifest.json not found")
    manifest = ReleaseManifest.model_validate_json(path.read_text(encoding="utf-8"))
    human = load_human_cases(check_rewrites=False)
    issues = []
    if check_human_pack_frozen(human):
        issues.append("human pack is not frozen split=dev")
    if manifest.scoring_applied:
        issues.append("scoring_applied must stay false")
    if manifest.docker_included:
        issues.append("Docker is not part of this release candidate")
    if manifest.hidden_included:
        issues.append("hidden artifacts must not be in the public release")
    if not _pyproject_excludes_hidden(root):
        issues.append("packaging does not exclude data/hidden")
    if not manifest.human_pack_untouched:
        issues.append("human pack was relabeled")
    if not manifest.isolation_passed:
        issues.append("task pack split isolation did not pass")
    if not manifest.packaging_excludes_hidden:
        issues.append("packaging does not exclude hidden artifacts")
    if manifest.public_generated_case_count != M6_PUBLIC_COUNT or not manifest.m6_structure:
        issues.append("M6 public structure is not verified (expected 300 cases: 180 train/120 dev)")
    passed = not issues and manifest.isolation_passed and manifest.packaging_excludes_hidden
    return {
        "passed": passed,
        "scoring_applied": manifest.scoring_applied,
        "docker_included": manifest.docker_included,
        "hidden_included": manifest.hidden_included,
        "human_pack_untouched": manifest.human_pack_untouched,
        "m6_structure": manifest.m6_structure,
        "issues": issues,
    }


def prepare_formal_release(
    output_dir: Path,
    *,
    public_pack: Path,
    score_dir: Path | None = None,
    public_report: Path | None = None,
    hidden_report: Path | None = None,
    docker_digest: str = "",
    semantic_report: Path | None = None,
    conformance_report: Path | None = None,
    negative_control_report: Path | None = None,
    docker_smoke_report: Path | None = None,
    reproducible_build_report: Path | None = None,
    root: Path | None = None,
) -> dict:
    """Create the v1.0 public release manifest and deterministic checksums.

    Private score inputs may be supplied for digest binding, but are never
    copied into the public release directory.
    """

    root = root or REPO_ROOT
    if output_dir.exists():
        raise FileExistsError(output_dir)
    generated = GeneratedTaskPack.model_validate_json(
        (public_pack / "pack.json").read_text(encoding="utf-8")
    )
    if not generated.m6_structure or generated.case_count != M6_PUBLIC_COUNT:
        raise ValueError("formal release requires the 300-case public generated pack")
    if sum(item.split == "train" for item in generated.cases) != 180:
        raise ValueError("formal release public pack must contain 180 train cases")
    if sum(item.split == "dev" for item in generated.cases) != 120:
        raise ValueError("formal release public pack must contain 120 dev cases")
    if not (root / "LICENSE").is_file() or not (root / "NOTICE").is_file():
        raise ValueError("formal release requires LICENSE and NOTICE")
    if not (root / "Dockerfile").is_file():
        raise ValueError("formal release requires Dockerfile")
    issues = _public_leak_issues(public_pack)
    if issues:
        raise ValueError("public pack failed leakage scan: " + "; ".join(issues))
    artifacts = public_artifacts_evidence(root)
    license_row = license_evidence(root)
    evidence_rows: dict[str, RcEvidence] = {
        "public_artifacts": artifacts,
        "license": license_row,
    }
    if score_dir is not None:
        evidence_rows["score_inputs"] = load_score_inputs(score_dir)
    if semantic_report is not None:
        evidence_rows["semantic_acceptance"] = load_semantic_acceptance(semantic_report)
    if conformance_report is not None:
        evidence_rows["conformance"] = load_conformance(conformance_report)
    if negative_control_report is not None:
        evidence_rows["negative_control"] = load_negative_control(negative_control_report)
    if docker_smoke_report is not None:
        evidence_rows["docker_runtime"] = load_docker_runtime(docker_smoke_report)
    if reproducible_build_report is not None:
        evidence_rows["reproducible_build"] = load_reproducible_build(reproducible_build_report)
    gates = {name: False for name in RC_GATE_NAMES}
    for name, row in evidence_rows.items():
        gates[name] = bool(row.passed)
    docker_row = evidence_rows.get("docker_runtime")
    resolved_digest = ""
    if isinstance(docker_row, DockerRuntimeEvidence) and docker_row.passed:
        resolved_digest = docker_row.docker_digest
    if docker_digest:
        if not gates["docker_runtime"]:
            raise ValueError("unsigned docker_runtime cannot carry a digest")
        if docker_digest != resolved_digest:
            raise ValueError("docker_digest does not match docker_runtime evidence")
    elif gates["docker_runtime"]:
        docker_digest = resolved_digest
    if not artifacts.passed:
        raise ValueError("public 1.0.0 artifacts leaked private paths or are missing")
    output_dir.mkdir(parents=True, exist_ok=False)
    public_dir = output_dir / "public"
    public_dir.mkdir()
    for name in ("pack.json", "public_cases.yaml", "isolation.json"):
        source = public_pack / name
        if not source.is_file():
            raise ValueError(f"public pack is missing {name}")
        shutil.copyfile(source, public_dir / name)
    wheel, sdist = _formal_distributions(root)
    for artifact in (wheel, sdist):
        shutil.copyfile(artifact, public_dir / artifact.name)
    for name in ("Dockerfile", ".dockerignore", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(root / name, public_dir / name)
    public_digests = {
        str(path.relative_to(public_dir)): _sha256(path) for path in _artifact_files(public_dir)
    }
    private_digests: dict[str, str] = {}
    oracle_path = public_pack / "generated_oracles.yaml"
    if oracle_path.is_file():
        private_digests["trusted_generated_oracles"] = _sha256(oracle_path)
    for label, path in (("public_report", public_report), ("hidden_report", hidden_report)):
        if path is not None:
            if not path.exists():
                raise ValueError(f"score input does not exist: {path}")
            private_digests[label] = _sha256(path)
    if score_dir is not None:
        score_file = score_dir / "private" / "score.json"
        private_digests["score"] = _sha256(score_file)
    for name, row in evidence_rows.items():
        payload = row.model_dump(mode="json")
        private_digests[f"evidence_{name}"] = digest(payload)
    checksum_lines = [f"{value}  {name}" for name, value in sorted(public_digests.items())]
    (output_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    (output_dir / "sbom.json").write_text(
        json.dumps(_sbom_document(root), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = FormalReleaseManifest(
        protocol_version="0.1",
        public_artifact_digests=public_digests,
        private_input_digests=private_digests,
        checksum_file="SHA256SUMS",
        sbom_file="sbom.json",
        docker_digest=docker_digest,
        gates=gates,
        limitations=FORMAL_LIMITATIONS,
    )
    write_json_new(output_dir / "formal_release_manifest.json", manifest.model_dump(mode="json"))
    return manifest.model_dump(mode="json")


def check_formal_release(manifest_dir: Path, *, root: Path | None = None) -> dict:
    """Fail closed unless a formal v1.0 manifest and public boundary are valid."""

    root = root or REPO_ROOT
    path = manifest_dir / "formal_release_manifest.json"
    if not path.is_file():
        raise ValueError("formal_release_manifest.json not found")
    manifest = FormalReleaseManifest.model_validate_json(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    if manifest.package_version != "1.0.0" or manifest.score_protocol_version != "1.0":
        issues.append("formal protocol versions are not frozen")
    if not (root / "LICENSE").is_file() or not (root / "NOTICE").is_file():
        issues.append("Apache-2.0 license files are missing")
    if not (root / "Dockerfile").is_file():
        issues.append("Dockerfile is missing")
    if manifest.hidden_included or manifest.ranking_enabled:
        issues.append("hidden artifacts or ranking cannot be enabled")
    for path_name in (manifest.checksum_file, manifest.sbom_file):
        if not (manifest_dir / path_name).is_file():
            issues.append(f"missing release artifact {path_name}")
    issues.extend(_public_leak_issues(manifest_dir))
    issues.extend(
        f"RC evidence gate not passed: {name}"
        for name, passed in manifest.gates.items()
        if not passed
    )
    passed = not issues and all(manifest.gates.values())
    return {
        "passed": passed,
        "package_version": manifest.package_version,
        "score_protocol_version": manifest.score_protocol_version,
        "scoring_applied": manifest.scoring_applied,
        "ranking_enabled": manifest.ranking_enabled,
        "hidden_included": manifest.hidden_included,
        "issues": issues,
    }
