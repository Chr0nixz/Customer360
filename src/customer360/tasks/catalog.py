"""Load public case inputs and trusted oracles as separate artifacts.

Public YAML is wheel-safe. Trusted oracles live in the repository and must not
be copied into src/customer360 or published in wheel/sdist.
"""

from pathlib import Path

import yaml

from customer360.contracts.coverage import (
    HumanCaseBlueprint,
    HumanCaseCatalog,
    PublicCaseCatalog,
    TrustedOracleCatalog,
)
from customer360.tasks.rewrites import format_rewrite_failures, validate_catalog_rewrites

DEFAULT_TRUSTED_ORACLES = Path("data/trusted/human_oracles.yaml")


def load_public_cases() -> PublicCaseCatalog:
    path = Path(__file__).parents[1] / "resources" / "human_cases.yaml"
    return PublicCaseCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_trusted_oracles(path: Path | None = None) -> TrustedOracleCatalog:
    path = path or DEFAULT_TRUSTED_ORACLES
    if not path.is_file():
        raise ValueError(
            f"trusted human oracles not found at {path}; "
            "this file is not shipped in the wheel or sdist"
        )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TrustedOracleCatalog.model_validate(payload)


def join_public_and_trusted(
    public: PublicCaseCatalog, trusted: TrustedOracleCatalog
) -> HumanCaseCatalog:
    if tuple(item.case_id for item in public.cases) != tuple(
        item.case_id for item in trusted.cases
    ):
        raise ValueError("public and trusted case_id sequences must match")
    cases = []
    for visible, oracle in zip(public.cases, trusted.cases, strict=True):
        if visible.task_version != oracle.task_version or visible.split != oracle.split:
            raise ValueError(f"version/split mismatch for {visible.case_id}")
        payload = oracle.model_dump(mode="json")
        payload["question"] = visible.question
        payload["rewrites"] = list(visible.rewrites)
        cases.append(HumanCaseBlueprint.model_validate(payload))
    return HumanCaseCatalog(cases=tuple(cases))


def load_human_cases(
    *, oracles: Path | None = None, check_rewrites: bool = True
) -> HumanCaseCatalog:
    catalog = join_public_and_trusted(load_public_cases(), load_trusted_oracles(oracles))
    if check_rewrites:
        report = validate_catalog_rewrites(catalog)
        if not report.passed:
            raise ValueError(format_rewrite_failures(report))
    return catalog
