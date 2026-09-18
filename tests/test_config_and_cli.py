import json
from pathlib import Path

from typer.testing import CliRunner

from customer360.cli import app
from customer360.config import BenchmarkConfig, load_config, resolve_settings

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_config_paths_are_relative_to_config_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = load_config(ROOT / "configs" / "benchmark.yaml")
    assert settings.artifact_dir == ROOT / "outputs"


def test_help_exposes_only_real_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "create-fixture" in result.output
    assert "generate-data" in result.output
    assert "coverage-report" in result.output
    assert "check-rewrites" in result.output
    assert "replay-variant" in result.output
    assert "generate-variant" in result.output
    assert "run-case" in result.output
    assert "evaluate" in result.output
    assert "generate-hidden" in result.output
    assert "evaluate-hidden" in result.output
    assert "verify-pack" in result.output
    assert "verify-hidden" in result.output
    assert "perf-baseline" in result.output
    assert "prepare-release" in result.output


def test_generate_data_creates_tiny_dataset(tmp_path):
    output = tmp_path / "tiny"
    result = runner.invoke(
        app,
        [
            "generate-data",
            "--output",
            str(output),
            "--config",
            str(ROOT / "configs" / "data_generation.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_kind"] == "tiny_dataset"
    assert manifest["generator_version"] == "0.1.0"
    assert manifest["row_counts"]["dim_customer"] == 100
    assert manifest["row_counts"]["fact_transaction"] == 2000


def test_generate_data_rejects_unknown_scale(tmp_path):
    result = runner.invoke(
        app,
        [
            "generate-data",
            "--scale",
            "xlarge",
            "--output",
            str(tmp_path / "xlarge"),
            "--config",
            str(ROOT / "configs" / "data_generation.yaml"),
        ],
    )
    assert result.exit_code == 2
    assert "not supported" in result.output
    assert not (tmp_path / "xlarge").exists()


def test_load_standard_scale_from_cli_flag_does_not_keep_tiny_counts():
    from customer360.synth.generator import load_generation_config

    config = load_generation_config(
        ROOT / "configs" / "data_generation.yaml", scale="standard", seed=42
    )
    assert config.scale == "standard"
    assert (config.customers, config.transactions) == (10_000, 300_000)


def test_generate_data_refuses_overwrite(tmp_path):
    output = tmp_path / "tiny"
    args = ["--output", str(output), "--config", str(ROOT / "configs" / "data_generation.yaml")]
    first = runner.invoke(app, ["generate-data", *args])
    assert first.exit_code == 0, first.output
    before = (output / "manifest.json").read_bytes()
    second = runner.invoke(app, ["generate-data", *args])
    assert second.exit_code == 2
    assert (output / "manifest.json").read_bytes() == before


def test_doctor_runs_from_another_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor", "--config", str(ROOT / "configs/benchmark.yaml")])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tables"] == 9
    assert payload["metrics"] == 30
    assert payload["join_paths"] == 20
    assert payload["executable_join_paths"] == 1
    assert payload["foreign_keys"] == 8
    assert payload["checks_passed"] is True
    assert (
        payload["glossary_entries"] == payload["tables"] + payload["columns"] + payload["metrics"]
    )


def test_doctor_uses_packaged_defaults_without_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert resolve_settings() == BenchmarkConfig()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["checks_passed"] is True
    assert payload["tables"] == 9
    assert payload["metrics"] == 30


def test_cli_refuses_overwrite(tmp_path):
    output = tmp_path / "fixture"
    first = runner.invoke(app, ["create-fixture", "--output", str(output)])
    assert first.exit_code == 0, first.output
    before = (output / "manifest.json").read_bytes()
    second = runner.invoke(app, ["create-fixture", "--output", str(output)])
    assert second.exit_code == 2
    assert (output / "manifest.json").read_bytes() == before


def test_unknown_config_field_fails(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("disable_safety: true\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--config", str(config)])
    assert result.exit_code == 2
