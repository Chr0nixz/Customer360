from pathlib import Path

import pytest

from customer360.synth.generator import generate_dataset, load_generation_config
from customer360.tasks.gold import build_gold_package


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    output = tmp_path_factory.getbasetemp() / "gold-tiny"
    config = Path(__file__).parents[1] / "configs" / "data_generation.yaml"
    generate_dataset(load_generation_config(config), output)
    return output


def test_gold_package_contains_all_cases_and_only_compilable_gold(tiny, tmp_path):
    payload = build_gold_package(tiny, tmp_path / "gold")
    assert payload["artifact_kind"] == "private_human_case_gold"
    assert payload["case_count"] == 20
    assert payload["compilable_answers"] == 18
    assert payload["unsupported_capabilities"] == 0
    assert payload["non_answer_oracles"] == 2
    assert payload["gold_version"] == "0.1"
    assert payload["task_version"] == "human-0.1"
    assert payload["catalog_version"] == "0.3"
    assert payload["m2_complete"] is False
    assert payload["metadata_version"] == "0.3"
    by_id = {item["case_id"]: item for item in payload["cases"]}
    assert by_id["C360_0001"]["sql"]
    assert by_id["C360_0001"]["split"] == "dev"
    assert len(by_id["C360_0001"]["rewrites"]) == 3
    assert "result" in by_id["C360_0001"]
    assert "sql" in by_id["C360_0016"]
    assert "sql" in by_id["C360_0017"]
    assert "sql" in by_id["C360_0018"]
    assert "GROUP BY" in by_id["C360_0018"]["sql"]
    assert "ROW_NUMBER" not in by_id["C360_0017"]["sql"].upper()
    assert by_id["C360_0019"]["missing_slots"] == ["time_window"]
    assert by_id["C360_0020"]["accepted_reason_codes"] == ["UNKNOWN_FIELD"]
    assert (tmp_path / "gold" / "README.txt").is_file()
