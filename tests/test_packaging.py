"""T4 packaging: wheel/sdist install without the source tree and without private artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tarfile import TarFile
from zipfile import ZipFile

import pytest
import yaml

from customer360.config import BenchmarkConfig, load_config
from customer360.contracts.coverage import PRIVATE_ORACLE_FIELDS, PUBLIC_CASE_FIELDS

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN_SEGMENTS = frozenset({"outputs", ".venv", ".private", "hidden", "trusted", "secrets"})
REQUIRED_WHEEL = (
    "customer360/cli.py",
    "customer360/resources/catalog.yaml",
    "customer360/resources/metrics.yaml",
    "customer360/resources/human_cases.yaml",
    "customer360/resources/join_paths.yaml",
)
REQUIRED_SDIST = (
    "pyproject.toml",
    "uv.lock",
    "configs/benchmark.yaml",
    "configs/data_generation.yaml",
    "src/customer360/resources/catalog.yaml",
    "src/customer360/resources/human_cases.yaml",
    "tests/test_packaging.py",
    ".github/workflows/ci.yml",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".gitattributes",
    ".gitignore",
)


def _archive_names(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            return tuple(archive.namelist())
    with TarFile.open(path, "r:gz") as archive:
        return tuple(archive.getnames())


def leaked_distribution_paths(names: tuple[str, ...]) -> tuple[str, ...]:
    leaked: list[str] = []
    for raw in names:
        parts = Path(raw.replace("\\", "/")).parts
        labels = [part.lower() for part in parts]
        filename = labels[-1] if labels else ""
        if any(part in FORBIDDEN_SEGMENTS for part in labels):
            leaked.append(raw)
        elif filename == ".env" or filename.startswith(".env."):
            leaked.append(raw)
        elif filename.endswith(".duckdb"):
            leaked.append(raw)
    return tuple(leaked)


def _sdist_relative(name: str) -> str:
    parts = Path(name.replace("\\", "/")).parts
    if not parts:
        return name
    return "/".join(parts[1:]) if len(parts) > 1 else parts[0]


@pytest.fixture(scope="module")
def distributions(tmp_path_factory) -> tuple[Path, Path]:
    dest = tmp_path_factory.mktemp("dist")
    completed = subprocess.run(
        ["uv", "build", "--out-dir", str(dest)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    wheels = tuple(dest.glob("*.whl"))
    sdists = tuple(path for path in dest.glob("*.tar.gz") if path.stat().st_size > 1)
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return wheels[0], sdists[0]


def test_leaked_path_classifier_catches_private_artifacts() -> None:
    names = (
        "pkg/outputs/tiny/dataset.duckdb",
        "pkg/.venv/lib/python.py",
        "pkg/.private/gold.json",
        "pkg/data/hidden/secret.json",
        "pkg/.env",
        "pkg/.env.local",
        "pkg/src/customer360/resources/human_cases.yaml",
        "pkg/data/trusted/human_oracles.yaml",
        "pkg/docs/decisions.md",
    )
    leaked = leaked_distribution_paths(names)
    assert "pkg/outputs/tiny/dataset.duckdb" in leaked
    assert "pkg/.venv/lib/python.py" in leaked
    assert "pkg/.private/gold.json" in leaked
    assert "pkg/data/hidden/secret.json" in leaked
    assert "pkg/.env" in leaked
    assert "pkg/.env.local" in leaked
    assert "pkg/src/customer360/resources/human_cases.yaml" not in leaked
    assert "pkg/data/trusted/human_oracles.yaml" in leaked
    assert "pkg/docs/decisions.md" not in leaked


def test_distributions_exclude_private_artifacts(distributions: tuple[Path, Path]) -> None:
    wheel, sdist = distributions
    for archive in distributions:
        names = _archive_names(archive)
        assert names, archive
        leaked = leaked_distribution_paths(names)
        assert leaked == (), leaked
    wheel_names = _archive_names(wheel)
    for required in REQUIRED_WHEEL:
        assert required in wheel_names
    assert all(
        name.startswith("customer360/") or name.startswith("customer360_agent_benchmark-")
        for name in wheel_names
    )
    sdist_names = {_sdist_relative(name) for name in _archive_names(sdist)}
    for required in REQUIRED_SDIST:
        assert required in sdist_names
    with ZipFile(wheel) as archive:
        public_cases = yaml.safe_load(archive.read("customer360/resources/human_cases.yaml"))
    assert public_cases["artifact_kind"] == "public_human_cases"
    for case in public_cases["cases"]:
        assert set(case) <= PUBLIC_CASE_FIELDS
        assert not (PRIVATE_ORACLE_FIELDS & set(case))
    assert not any("human_oracles.yaml" in name.replace("\\", "/") for name in wheel_names)
    assert not any("human_oracles.yaml" in name.replace("\\", "/") for name in sdist_names)


def test_packaged_defaults_match_repo_benchmark_yaml() -> None:
    file_config = load_config(REPO / "configs" / "benchmark.yaml")
    defaults = BenchmarkConfig()
    assert defaults.config_version == file_config.config_version
    assert defaults.seed == file_config.seed
    assert defaults.anchor_date == file_config.anchor_date
    assert defaults.limits == file_config.limits
    raw = yaml.safe_load((REPO / "configs" / "benchmark.yaml").read_text(encoding="utf-8"))
    assert raw["artifact_dir"] == str(defaults.artifact_dir).replace("\\", "/")


def test_wheel_doctor_and_smoke_without_source_tree(
    distributions: tuple[Path, Path], tmp_path: Path
) -> None:
    wheel, _sdist = distributions
    site = tmp_path / "site"
    site.mkdir()
    with ZipFile(wheel) as archive:
        archive.extractall(site)
    work = tmp_path / "work"
    work.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)
    env["PYTHONNOUSERSITE"] = "1"
    located = subprocess.run(
        [
            sys.executable,
            "-c",
            "import customer360, pathlib; print(pathlib.Path(customer360.__file__).resolve())",
        ],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert located.returncode == 0, located.stderr
    loaded = Path(located.stdout.strip()).resolve()
    assert loaded == (site / "customer360" / "__init__.py").resolve()
    assert REPO.resolve() not in loaded.parents

    doctor = subprocess.run(
        [sys.executable, "-m", "customer360", "doctor"],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert doctor.returncode == 0, doctor.stderr
    payload = json.loads(doctor.stdout)
    assert payload["status"] == "ok"
    assert payload["checks_passed"] is True
    assert payload["tables"] == 9
    assert payload["metrics"] == 30
    assert payload["foreign_keys"] == 8
    assert payload["glossary_entries"] == 111

    cases = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from customer360.tasks.catalog import load_public_cases; "
                "print(len(load_public_cases().cases))"
            ),
        ],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert cases.returncode == 0, cases.stderr
    assert cases.stdout.strip() == "20"
    trusted = subprocess.run(
        [
            sys.executable,
            "-c",
            "from customer360.tasks.catalog import load_human_cases; load_human_cases()",
        ],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert trusted.returncode != 0
    assert "trusted human oracles" in (trusted.stderr + trusted.stdout)

    smoke_dir = work / "smoke"
    smoke = subprocess.run(
        [sys.executable, "-m", "customer360", "smoke", "--output", str(smoke_dir)],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0, smoke.stderr
    report = json.loads(smoke.stdout)
    assert report["verification_passed"] is True
    assert not (work / "configs").exists()
