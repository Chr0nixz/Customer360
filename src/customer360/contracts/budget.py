"""Named resource budgets bound to dataset scale. Not Agent-controlled."""

from typing import Literal

from customer360.contracts.execution import SqlLimits
from customer360.contracts.generation import DatasetManifest, Scale

BudgetName = Literal["tiny", "standard", "large"]

TINY_MAX_INPUT_ROWS = 10_000
STANDARD_MAX_INPUT_ROWS = 400_000
LARGE_MAX_INPUT_ROWS = 4_000_000


def limits_for_budget(name: BudgetName) -> SqlLimits:
    if name == "tiny":
        return SqlLimits()
    if name == "standard":
        return SqlLimits(
            timeout_seconds=60,
            memory_mb=512,
            max_rows=100,
            max_sql_chars=10_000,
            max_input_rows=STANDARD_MAX_INPUT_ROWS,
        )
    return SqlLimits(
        timeout_seconds=180,
        memory_mb=1024,
        max_rows=100,
        max_sql_chars=10_000,
        max_input_rows=LARGE_MAX_INPUT_ROWS,
    )


def budget_for_scale(scale: Scale) -> BudgetName:
    return scale


def require_budget_matches_manifest(budget: BudgetName, manifest: DatasetManifest) -> None:
    if budget != manifest.scale:
        raise ValueError(f"budget profile {budget} does not match dataset scale {manifest.scale}")


def limits_for_manifest(manifest: DatasetManifest) -> SqlLimits:
    budget = budget_for_scale(manifest.scale)
    require_budget_matches_manifest(budget, manifest)
    return limits_for_budget(budget)
