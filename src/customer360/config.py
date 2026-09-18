from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from customer360.contracts.base import Contract
from customer360.contracts.execution import SqlLimits


class BenchmarkConfig(Contract):
    config_version: Literal["0.1"] = "0.1"
    artifact_dir: Path = Path("../outputs")
    seed: int = Field(default=42, ge=0)
    anchor_date: date = date(2025, 6, 30)
    limits: SqlLimits = SqlLimits()


DEFAULT_CONFIG_PATH = Path("configs") / "benchmark.yaml"


def load_config(path: Path) -> BenchmarkConfig:
    """Relative paths are relative to the config file, never the caller's cwd."""
    path = path.resolve(strict=True)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = BenchmarkConfig.model_validate(raw)
    artifact_dir = (path.parent / config.artifact_dir).resolve()
    return config.model_copy(update={"artifact_dir": artifact_dir})


def resolve_settings(config: Path | None = None) -> BenchmarkConfig:
    """Use an explicit YAML, then ./configs/benchmark.yaml, else packaged defaults."""
    if config is not None:
        return load_config(config)
    if DEFAULT_CONFIG_PATH.is_file():
        return load_config(DEFAULT_CONFIG_PATH)
    return BenchmarkConfig()
