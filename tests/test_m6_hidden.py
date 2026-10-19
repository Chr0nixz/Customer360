"""Stage F / M6: 300 public cases, independent hidden pack, release candidate."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.family import (
    ERROR_CLASSES_REQUIRED,
    HIDDEN_CASE_ID_MIN,
    M6_PUBLIC_COUNT,
    RESERVED_HUMAN_CASE_IDS,
)
from customer360.contracts.hidden import (
    PUBLIC_HIDDEN_FIELDS,
    PUBLIC_HIDDEN_FORBIDDEN,
    HiddenEvalRecord,
    HiddenEvalReport,
    HiddenTaskPack,
)
from customer360.metadata.metrics import MetadataRepository
from customer360.release import check_release, prepare_release
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.family import fingerprint_human_case
from customer360.tasks.generator import generate_task_pack, write_generated_pack
from customer360.tasks.hidden import (
    generate_hidden_dataset,
    generate_hidden_pack,
    load_hidden_dataset,
    write_hidden_pack,
)
from customer360.tasks.isolation import check_hidden_isolation, check_human_pack_frozen

pytestmark = pytest.mark.slow

runner = CliRunner()
ROOT = Path(__file__).parents[1]


def test_public_300_pack_is_isolated_and_not_human():
    pack = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    human = load_human_cases()
    assert pack.m3_complete is True
    assert pack.m6_structure is True
    assert pack.scoring_applied is False
    assert pack.case_count == 300
    assert sum(item.split == "train" for item in pack.cases) == 180
    assert sum(item.split == "dev" for item in pack.cases) == 120
    assert {item.split for item in pack.cases} <= {"train", "dev"}
    assert {item.case_id for item in pack.cases}.isdisjoint(RESERVED_HUMAN_CASE_IDS)
    assert all(1001 <= int(item.case_id[5:]) <= 3999 for item in pack.cases)
    assert ERROR_CLASSES_REQUIRED <= {item.intended_failure_class for item in pack.cases}
    families = [item.family.family_id for item in pack.cases]
    assert len(set(families)) == 300
    human_families = {fingerprint_human_case(case).family_id for case in human.cases}
    assert set(families).isdisjoint(human_families)
    assert check_human_pack_frozen(human) == ()


def test_dev_stratified_coverage_quality_gates():
    from collections import Counter, defaultdict

    pack = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    dev_cases = [c for c in pack.cases if c.split == "dev"]
    train_cases = [c for c in pack.cases if c.split == "train"]

    # 1. Total counts
    assert len(train_cases) == 180
    assert len(dev_cases) == 120

    # 2. Action quotas: Dev (90/18/12), Train (150/18/12)
    dev_actions = Counter(c.expected_action for c in dev_cases)
    assert dev_actions["answer"] == 90
    assert dev_actions["clarification_needed"] == 18
    assert dev_actions["refuse"] == 12

    train_actions = Counter(c.expected_action for c in train_cases)
    assert train_actions["answer"] == 150
    assert train_actions["clarification_needed"] == 18
    assert train_actions["refuse"] == 12

    # 3. 30/30 metrics covered in Dev, each >= 2 independent families
    dev_metric_families = defaultdict(set)
    for c in dev_cases:
        if c.metric:
            dev_metric_families[c.metric].add(c.family.family_id)
    assert len(dev_metric_families) == 30
    for m, fams in dev_metric_families.items():
        assert len(fams) >= 2, f"metric {m} has fewer than 2 families in Dev: {len(fams)}"

    # 4. Join coverage: >= 15 cases in Dev, all 5 executable join paths >= 3
    executable_paths = {
        "customer_transactions",
        "customer_cash_flows",
        "customer_holdings",
        "customer_asset_snapshots",
        "customer_service_relations",
    }
    dev_join_paths = Counter(c.join.path for c in dev_cases if c.join)
    assert sum(dev_join_paths.values()) >= 15
    for path in executable_paths:
        assert dev_join_paths[path] >= 3, f"join path {path} has < 3 in Dev: {dev_join_paths[path]}"

    # 5. Grouping coverage: >= 15 cases in Dev, across >= 4 allowed dimensions, NO Join+GROUP BY
    dev_groups = [c for c in dev_cases if c.group_by]
    assert len(dev_groups) >= 15
    assert all(c.join is None for c in dev_groups), "Join + GROUP BY is forbidden"
    group_dims = {c.group_by[0] for c in dev_groups}
    assert len(group_dims) >= 4

    # 6. Null / Edge coverage: >= 12 cases in Dev
    dev_null_edge = [
        c
        for c in dev_cases
        if c.category == "null_handling"
        or any(f.operator == "is_null" for f in c.filters)
        or any(f.values == ("closed",) for f in c.filters)
    ]
    assert len(dev_null_edge) >= 12

    # 7. Family isolation between train and dev
    train_families = {c.family.family_id for c in train_cases}
    dev_families = {c.family.family_id for c in dev_cases}
    assert train_families.isdisjoint(dev_families)


def test_hidden_pack_is_independent_of_public_and_human(tmp_path):
    public = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    hidden = generate_hidden_pack(public, seed=42, count=30)
    human = load_human_cases()
    report = check_hidden_isolation(human, public, hidden)
    assert report.passed is True
    assert hidden.scoring_applied is False
    assert hidden.hidden is True
    assert all(item.split == "private" for item in hidden.cases)
    assert all(int(item.case_id[5:]) >= HIDDEN_CASE_ID_MIN for item in hidden.cases)
    assert {item.case_id for item in hidden.cases}.isdisjoint(RESERVED_HUMAN_CASE_IDS)
    assert {item.case_id for item in hidden.cases}.isdisjoint(
        {item.case_id for item in public.cases}
    )
    assert {item.family.family_id for item in hidden.cases}.isdisjoint(
        {item.family.family_id for item in public.cases}
    )
    assert ERROR_CLASSES_REQUIRED <= {item.intended_failure_class for item in hidden.cases}
    output = tmp_path / "hidden-pack"
    summary = write_hidden_pack(output, hidden, public)
    assert summary["isolation_passed"] is True
    agent_text = (output / "agent_cases.yaml").read_text(encoding="utf-8")
    for field in ("expected_action", "semantic_spec", "missing_slots", "reason_code"):
        assert field not in agent_text
    assert "C360_0001" not in agent_text


def test_hidden_and_public_answer_specs_compile():
    repository = MetadataRepository()
    public = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    hidden = generate_hidden_pack(public, seed=42, count=30)
    public_answers = sum(c.material_status == "compilable_answer" for c in public.cases)
    hidden_answers = sum(c.material_status == "compilable_answer" for c in hidden.cases)
    assert 240 <= public_answers <= 270
    assert 15 <= hidden_answers <= 25

    compiled = 0
    for pack in (public, hidden):
        for case in pack.cases:
            if case.material_status != "compilable_answer":
                continue
            compiled_query = compile_semantic(case.semantic_spec(), repository)
            assert compiled_query.sql
            compiled += 1
    assert compiled == public_answers + hidden_answers
    assert compiled >= 260


def test_hidden_100_pack_stratified_and_isolated(tmp_path):
    from collections import Counter

    public = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    hidden = generate_hidden_pack(public, seed=42, count=100)
    human = load_human_cases()
    report = check_hidden_isolation(human, public, hidden)
    assert report.passed is True
    assert hidden.case_count == 100
    assert len(hidden.cases) == 100
    assert all(item.split == "private" for item in hidden.cases)

    # 1. Action stratification: ~60% answer, ~23% clarification, ~16% refuse
    actions = Counter(c.expected_action for c in hidden.cases)
    assert actions["answer"] == 61
    assert actions["clarification_needed"] == 23
    assert actions["refuse"] == 16

    # 2. Category depth: multi-table join, grouping, point in time, null handling
    categories = Counter(c.category for c in hidden.cases)
    assert categories["join"] >= 8
    assert categories["grouping"] >= 8
    assert categories["time_window"] >= 7
    assert categories["point_in_time"] >= 10
    assert categories["null_handling"] >= 10
    assert categories["clarification"] >= 20
    assert categories["refuse"] >= 15

    # 3. 8 required error classes
    assert ERROR_CLASSES_REQUIRED <= {item.intended_failure_class for item in hidden.cases}

    # 4. Metric breadth: >= 25 independent business metrics
    metrics = {c.metric for c in hidden.cases if c.metric}
    assert len(metrics) >= 25

    # 5. All compilable answers produce valid SQL
    repository = MetadataRepository()
    compilable_count = 0
    for case in hidden.cases:
        if case.material_status == "compilable_answer":
            compiled = compile_semantic(case.semantic_spec(), repository)
            assert compiled.sql
            compilable_count += 1
    assert compilable_count == 61

    # 6. Public agent view leakage defense
    out = tmp_path / "hidden-100"
    summary = write_hidden_pack(out, hidden, public)
    assert summary["isolation_passed"] is True
    agent_text = (out / "agent_cases.yaml").read_text(encoding="utf-8")
    for field in ("expected_action", "semantic_spec", "missing_slots", "reason_code"):
        assert field not in agent_text
    assert "C360_0001" not in agent_text


def test_generate_hidden_cli_and_check_isolation(tmp_path):
    public_dir = tmp_path / "public"
    public = generate_task_pack(seed=42, count=120)
    write_generated_pack(public_dir, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    hidden_dir = tmp_path / "hidden"
    result = runner.invoke(
        app,
        [
            "generate-hidden",
            "--output",
            str(hidden_dir),
            "--public-pack",
            str(public_dir),
            "--count",
            "8",
            "--seed",
            "42",
            "--oracles",
            str(ROOT / "data/trusted/human_oracles.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"hidden":true' in result.output.replace(" ", "")
    check = runner.invoke(
        app,
        [
            "check-isolation",
            "--pack",
            str(public_dir),
            "--hidden",
            str(hidden_dir),
            "--oracles",
            str(ROOT / "data/trusted/human_oracles.yaml"),
        ],
    )
    assert check.exit_code == 0, check.output
    assert '"hidden_case_count":8' in check.output.replace(" ", "")


def test_generate_hidden_data_rejects_public_seeds(tmp_path):
    result = runner.invoke(
        app,
        [
            "generate-hidden-data",
            "--output",
            str(tmp_path / "hidden-tiny"),
            "--seed",
            "42",
            "--config",
            str(ROOT / "configs/data_generation.yaml"),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "42" in result.output
    assert not (tmp_path / "hidden-tiny").exists()


def test_evaluate_hidden_rejects_public_tiny(baseline, tmp_path):
    public = generate_task_pack(seed=42, count=120)
    hidden = generate_hidden_pack(public, seed=42, count=8)
    pack_dir = tmp_path / "hidden-pack"
    write_hidden_pack(pack_dir, hidden, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    result = runner.invoke(
        app,
        [
            "evaluate-hidden",
            "--dataset",
            str(baseline),
            "--pack",
            str(pack_dir),
            "--output",
            str(tmp_path / "hidden-eval"),
            "--agent",
            "template",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "hidden_profile.json" in result.output


def test_hidden_eval_public_summary_hides_seed_and_questions(tmp_path):
    public = generate_task_pack(seed=42, count=120)
    hidden = generate_hidden_pack(public, seed=42, count=8)
    pack_dir = tmp_path / "hidden-pack"
    write_hidden_pack(pack_dir, hidden, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    data_dir = tmp_path / "hidden-tiny"
    generate_hidden_dataset(data_dir, seed=1042, config=ROOT / "configs/data_generation.yaml")
    result = runner.invoke(
        app,
        [
            "evaluate-hidden",
            "--dataset",
            str(data_dir),
            "--pack",
            str(pack_dir),
            "--output",
            str(tmp_path / "hidden-eval"),
            "--agent",
            "template",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"scoring_applied":false' in result.output.replace(" ", "")
    summary = (tmp_path / "hidden-eval" / "public" / "summary.json").read_text(encoding="utf-8")
    assert "1042" not in summary
    assert "semantic_spec" not in summary
    assert "candidate_sql" not in summary
    assert hidden.cases[0].question not in summary
    private = (tmp_path / "hidden-eval" / "private" / "hidden.json").read_text(encoding="utf-8")
    assert "C360_4001" in private


def test_prepare_and_check_release(tmp_path):
    public = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    public_dir = tmp_path / "public300"
    write_generated_pack(public_dir, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    hidden = generate_hidden_pack(public, seed=42, count=8)
    hidden_dir = tmp_path / "hidden"
    write_hidden_pack(hidden_dir, hidden, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    release_dir = tmp_path / "release"
    payload = prepare_release(
        release_dir,
        public_pack=public_dir,
        hidden_pack=hidden_dir,
        oracles=ROOT / "data/trusted/human_oracles.yaml",
        root=ROOT,
    )
    assert payload["scoring_applied"] is False
    assert payload["docker_included"] is False
    assert payload["hidden_included"] is False
    assert payload["m6_structure"] is True
    assert payload["human_pack_untouched"] is True
    assert payload["public_generated_case_count"] == 300
    assert payload["hidden_case_count"] == 8
    text = (release_dir / "release_manifest.json").read_text(encoding="utf-8")
    for field in PUBLIC_HIDDEN_FORBIDDEN:
        assert f'"{field}"' not in text
    checked = check_release(release_dir, root=ROOT)
    assert checked["passed"] is True


def test_public_hidden_fields_do_not_include_oracles():
    assert "expected_action" not in PUBLIC_HIDDEN_FIELDS
    assert "metric" not in PUBLIC_HIDDEN_FIELDS
    assert "family" not in PUBLIC_HIDDEN_FIELDS


def test_hidden_eval_report_rejects_inconsistent_case_counts():
    record = HiddenEvalRecord(
        case_id="C360_4001",
        outcome="pass",
        material_status="compilable_answer",
    )
    with pytest.raises(ValueError, match="case_count"):
        HiddenEvalReport(
            agent_id="baseline",
            case_count=2,
            compilable_answers=1,
            integrity_passed=True,
            data_seed=1042,
            limitations=(),
            cases=(record,),
        )


def test_hidden_pack_rejects_missing_required_error_class():
    public = generate_task_pack(seed=42, count=M6_PUBLIC_COUNT)
    hidden = generate_hidden_pack(public, seed=42, count=8)
    omitted = hidden.cases[0].intended_failure_class
    cases = tuple(item for item in hidden.cases if item.intended_failure_class != omitted)
    with pytest.raises(ValueError, match="missing error classes"):
        HiddenTaskPack(
            seed=hidden.seed,
            case_count=len(cases),
            public_pack_id=hidden.public_pack_id,
            metrics_version=hidden.metrics_version,
            join_paths_version=hidden.join_paths_version,
            cases=cases,
        )


def test_hidden_dataset_rejects_profile_version_drift(tmp_path):
    data_dir = tmp_path / "hidden-tiny"
    generate_hidden_dataset(data_dir, seed=1042, config=ROOT / "configs/data_generation.yaml")
    profile_path = data_dir / "hidden_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["generator_version"] = "0.1.1"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="hidden_profile|generator"):
        load_hidden_dataset(data_dir)


def test_release_check_rejects_short_public_pack(tmp_path):
    public = generate_task_pack(seed=42, count=120)
    public_dir = tmp_path / "public120"
    write_generated_pack(public_dir, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    release_dir = tmp_path / "release"
    prepare_release(
        release_dir,
        public_pack=public_dir,
        oracles=ROOT / "data/trusted/human_oracles.yaml",
        root=ROOT,
    )
    checked = check_release(release_dir, root=ROOT)
    assert checked["passed"] is False
    assert any("300" in issue for issue in checked["issues"])
