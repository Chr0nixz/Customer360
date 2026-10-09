import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from customer360.cli import app
from customer360.synth.env import setup_benchmark_env

runner = CliRunner()


def test_setup_env_cli_help():
    result = runner.invoke(app, ["setup-env", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.output
    assert "--force" in result.output


def test_setup_env_refuses_overwrite(tmp_path):
    target = tmp_path / "env"
    target.mkdir()
    (target / "dummy.txt").write_text("content", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        setup_benchmark_env(target, force=False)


def test_setup_env_orchestration_mocked(tmp_path):
    target = tmp_path / "env"
    mock_manifest = {"dataset_id": "test"}

    with (
        patch(
            "customer360.synth.env.generate_dataset",
            return_value=(mock_manifest, None),
        ),
        patch(
            "customer360.synth.env.generate_named_variant",
            return_value=mock_manifest,
        ),
    ):
        result = setup_benchmark_env(target, force=False)

    assert result["env_version"] == "1.0"
    assert result["scale"] == "tiny"
    assert "baseline" in result
    assert "variants" in result
    assert set(result["variants"].keys()) == {"distribution", "fanout", "null", "date"}

    manifest_file = target / "env_manifest.json"
    assert manifest_file.exists()
    saved = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert saved["scale"] == "tiny"


def test_setup_env_failure_cleans_staging(tmp_path):
    target = tmp_path / "failing_env"
    staging = tmp_path / f"{target.name}.staging"

    with patch(
        "customer360.synth.env.generate_dataset",
        side_effect=RuntimeError("Simulated disk error during baseline generation"),
    ):
        with pytest.raises(RuntimeError, match="Simulated disk error"):
            setup_benchmark_env(target, force=False)

    assert not target.exists()
    assert not staging.exists()


@pytest.mark.slow
def test_setup_env_real_run(tmp_path):
    target = tmp_path / "real_env"
    setup_benchmark_env(target, force=False)
    assert (target / "baseline" / "dataset.duckdb").exists()
    assert (target / "variants" / "distribution" / "dataset.duckdb").exists()
    assert (target / "variants" / "fanout" / "dataset.duckdb").exists()
    assert (target / "variants" / "null" / "dataset.duckdb").exists()
    assert (target / "variants" / "date" / "dataset.duckdb").exists()
    assert (target / "env_manifest.json").exists()
