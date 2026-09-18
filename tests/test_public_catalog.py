"""M2-06: public case inputs stay separate from trusted oracles."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.coverage import (
    PRIVATE_ORACLE_FIELDS,
    PUBLIC_CASE_FIELDS,
    HumanCaseCatalog,
    PublicCase,
    PublicCaseCatalog,
    TrustedOracleCatalog,
)
from customer360.tasks.catalog import (
    join_public_and_trusted,
    load_human_cases,
    load_public_cases,
    load_trusted_oracles,
)

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_packaged_cases_are_public_inputs_only():
    catalog = load_public_cases()
    assert catalog.catalog_version == "0.3"
    assert catalog.artifact_kind == "public_human_cases"
    assert len(catalog.cases) == 20
    path = ROOT / "src/customer360/resources/human_cases.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        assert set(case) <= PUBLIC_CASE_FIELDS
        assert not (PRIVATE_ORACLE_FIELDS & set(case))
    with pytest.raises(ValidationError):
        HumanCaseCatalog.model_validate(payload)
    with pytest.raises(ValidationError):
        TrustedOracleCatalog.model_validate(payload)


def test_joined_catalog_stays_trusted_and_complete():
    catalog = load_human_cases()
    assert catalog.catalog_version == "0.3"
    assert sum(item.material_status == "compilable_answer" for item in catalog.cases) == 18
    assert catalog.cases[0].metric == "distinct_customer_count"
    assert catalog.cases[18].missing_slots == ("time_window",)
    assert catalog.cases[19].accepted_reason_codes == ("UNKNOWN_FIELD",)


def test_public_case_rejects_expected_action():
    with pytest.raises(ValidationError):
        PublicCase(
            case_id="C360_0001",
            question="统计VIP客户数。",
            rewrites=(
                "VIP客户一共有多少人？",
                "请给出VIP客户数量。",
                "目前VIP等级客户的总数是多少？",
            ),
            expected_action="answer",
        )


def test_join_fail_closes_on_id_mismatch():
    public = load_public_cases()
    trusted = load_trusted_oracles()
    swapped = list(trusted.cases)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    broken = TrustedOracleCatalog.model_construct(
        catalog_version="0.3",
        artifact_kind="trusted_human_oracles",
        cases=tuple(swapped),
    )
    with pytest.raises(ValueError, match="case_id sequences must match"):
        join_public_and_trusted(public, broken)


def test_missing_oracles_fail_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="trusted human oracles not found"):
        load_human_cases()
    assert load_public_cases().catalog_version == "0.3"


def test_doctor_stdout_does_not_leak_oracles():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    for needle in ("missing_slots", "accepted_reason_codes", "intended_failure_class"):
        assert needle not in result.output


def test_public_catalog_roundtrip():
    catalog = load_public_cases()
    assert PublicCaseCatalog.model_validate_json(catalog.model_dump_json()) == catalog
