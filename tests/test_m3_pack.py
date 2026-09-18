"""M3 semantic family, split isolation, 30 metrics, 20 join paths, 120 cases."""

from pathlib import Path

from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.family import ERROR_CLASSES_REQUIRED, RESERVED_HUMAN_CASE_IDS
from customer360.contracts.pack import PUBLIC_GENERATED_FIELDS
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.catalog import load_human_cases, load_public_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.family import fingerprint_human_case
from customer360.tasks.generator import generate_task_pack, write_generated_pack
from customer360.tasks.isolation import check_generated_isolation, check_human_pack_frozen

runner = CliRunner()
ROOT = Path(__file__).parents[1]


def test_human_pack_stays_dev_and_unrelabeled():
    public = load_public_cases()
    human = load_human_cases()
    assert tuple(item.case_id for item in public.cases) == RESERVED_HUMAN_CASE_IDS
    assert all(item.split == "dev" for item in human.cases)
    assert check_human_pack_frozen(human) == ()
    families = [fingerprint_human_case(case).family_id for case in human.cases]
    assert len(set(families)) == 20


def test_generated_pack_is_isolated_and_seed_stable(tmp_path):
    first = generate_task_pack(seed=42, count=120)
    second = generate_task_pack(seed=42, count=120)
    third = generate_task_pack(seed=43, count=120)
    human = load_human_cases()
    report = check_generated_isolation(human, first)
    assert report.passed is True
    assert first.m3_complete is True
    assert first.scoring_applied is False
    assert first.case_count == 120
    assert [item.case_id for item in first.cases] == [item.case_id for item in second.cases]
    assert [item.family.family_id for item in first.cases] == [
        item.family.family_id for item in second.cases
    ]
    assert [item.question for item in first.cases] == [item.question for item in second.cases]
    assert [item.family.family_id for item in first.cases] != [
        item.family.family_id for item in third.cases
    ]
    assert {item.case_id for item in first.cases}.isdisjoint(RESERVED_HUMAN_CASE_IDS)
    assert {item.split for item in first.cases} <= {"train", "dev"}
    assert ERROR_CLASSES_REQUIRED <= {item.intended_failure_class for item in first.cases}
    assert sum(item.split == "train" for item in first.cases) == 90
    assert sum(item.split == "dev" for item in first.cases) == 30
    output = tmp_path / "generated-m3"
    summary = write_generated_pack(output, first)
    assert summary["isolation_passed"] is True
    public_text = (output / "public_cases.yaml").read_text(encoding="utf-8")
    for field in ("expected_action", "semantic_spec", "missing_slots", "reason_code"):
        assert field not in public_text


def test_generated_answer_specs_compile():
    repository = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120)
    compiled = 0
    for case in pack.cases:
        if case.material_status != "compilable_answer":
            continue
        compiled_query = compile_semantic(case.semantic_spec(), repository)
        assert compiled_query.sql
        compiled += 1
    assert compiled >= 100


def test_generate_tasks_cli_and_check_isolation(tmp_path):
    output = tmp_path / "tasks"
    result = runner.invoke(
        app,
        [
            "generate-tasks",
            "--output",
            str(output),
            "--count",
            "120",
            "--seed",
            "42",
            "--oracles",
            str(ROOT / "data/trusted/human_oracles.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"m3_complete":true' in result.output.replace(" ", "")
    check = runner.invoke(
        app,
        [
            "check-isolation",
            "--pack",
            str(output),
            "--oracles",
            str(ROOT / "data/trusted/human_oracles.yaml"),
        ],
    )
    assert check.exit_code == 0, check.output
    frozen = runner.invoke(
        app,
        ["check-isolation", "--oracles", str(ROOT / "data/trusted/human_oracles.yaml")],
    )
    assert frozen.exit_code == 0, frozen.output


def test_public_generated_fields_do_not_include_oracles():
    assert "expected_action" not in PUBLIC_GENERATED_FIELDS
    assert "metric" not in PUBLIC_GENERATED_FIELDS
    assert "family" not in PUBLIC_GENERATED_FIELDS


def test_metrics_and_join_inventory():
    repository = MetadataRepository()
    assert len(repository.metrics.metrics) == 30
    assert repository.metrics.metrics_version == "0.3"
    assert len(repository.join_paths.paths) == 20
    assert sum(path.compile_status == "executable" for path in repository.join_paths.paths) == 1
