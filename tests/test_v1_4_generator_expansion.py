"""v1.4 Task Generator expansion tests: Top-K and Composite Join synthesis."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from customer360.cli import app
from customer360.evaluator.compare import ComparisonPolicy, compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.family import fingerprint_for, infer_template_id
from customer360.tasks.generator import _pool_drafts, generate_task_pack
from customer360.tasks.independent import compute_independent
from customer360.tasks.pack_rewrites import case_rewrites_pass, check_generated_rewrite
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import normalize_sql_result

runner = CliRunner()


def test_generator_pool_includes_v1_4_drafts():
    repo = MetadataRepository()
    default_pool = _pool_drafts(repo, include_v1_4=False)
    v1_4_pool = _pool_drafts(repo, include_v1_4=True)

    assert len(v1_4_pool) > len(default_pool)

    # Composite join drafts
    comp_joins = [
        d for d in v1_4_pool if d.join and d.join.path == "customer_transactions_and_holdings"
    ]
    assert len(comp_joins) >= 6

    # Top-K drafts
    topk_drafts = [d for d in v1_4_pool if d.limit is not None]
    assert len(topk_drafts) >= 10
    assert all(d.order_by and d.order_direction in {"asc", "desc"} for d in topk_drafts)
    assert all(d.category == "grouping" for d in topk_drafts)


def test_fingerprint_includes_topk_and_composite_join():
    tpl_topk = infer_template_id(
        expected_action="answer",
        join=None,
        group_by=("region",),
        time_window=None,
        filters=(),
        missing_slots=(),
        limit=3,
    )
    assert tpl_topk == "t_topk"

    fp_topk = fingerprint_for(
        expected_action="answer",
        metric="distinct_customer_count",
        group_by=("region",),
        limit=3,
        order_by=("customer_count",),
        order_direction="desc",
    )
    assert fp_topk.template_id == "t_topk"
    assert "customer_count:desc:3" in fp_topk.canonical

    fp_comp = fingerprint_for(
        expected_action="answer",
        metric="distinct_customer_count",
        join=_pool_drafts(MetadataRepository(), include_v1_4=True)[-1].join
        if _pool_drafts(MetadataRepository(), include_v1_4=True)[-1].join
        else None,
    )
    assert fp_comp.family_id.startswith("fam_")


def test_generate_task_pack_v1_4_count_120():
    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)

    assert pack.case_count == 120
    assert pack.m3_complete is True

    # 1. Contains Top-K cases
    topk_cases = [c for c in pack.cases if c.limit is not None]
    assert len(topk_cases) >= 2
    for c in topk_cases:
        assert c.order_by is not None
        assert c.order_direction in {"asc", "desc"}
        assert c.limit in {3, 5}
        assert c.group_by
        assert c.family.template_id == "t_topk"

    # 2. Contains Composite Join cases
    comp_cases = [
        c for c in pack.cases if c.join and c.join.path == "customer_transactions_and_holdings"
    ]
    assert len(comp_cases) >= 2
    for c in comp_cases:
        assert c.join.time_window is not None
        assert c.family.join_path == "customer_transactions_and_holdings"

    # 3. All cases compile and have clean rewrites
    compiled_count = 0
    for case in pack.cases:
        if case.material_status == "compilable_answer":
            spec = case.semantic_spec()
            compiled = compile_semantic(spec, repo)
            assert compiled.sql
            compiled_count += 1
        assert case_rewrites_pass(case, repo) is True

    assert compiled_count >= 80


def test_generate_task_pack_v1_4_count_300():
    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=300, repository=repo, include_v1_4=True)

    assert pack.case_count == 300
    assert pack.m3_complete is True
    assert pack.m6_structure is True

    # Check that both Dev and Train splits contain Top-K and Composite Join cases
    dev_cases = [c for c in pack.cases if c.split == "dev"]
    train_cases = [c for c in pack.cases if c.split == "train"]

    assert len(dev_cases) == 120
    assert len(train_cases) == 180

    dev_topk = [c for c in dev_cases if c.limit is not None]
    dev_comp = [
        c for c in dev_cases if c.join and c.join.path == "customer_transactions_and_holdings"
    ]
    assert len(dev_topk) >= 2
    assert len(dev_comp) >= 2

    # Zero rewrite issues
    for case in pack.cases:
        issues = []
        for text in (case.question, *case.rewrites):
            found = check_generated_rewrite(case, text, repo)
            if found:
                issues.extend(found)
        assert len(issues) == 0, f"Found rewrite issues for {case.case_id}: {issues}"


def test_v1_4_generated_cases_duckdb_and_oracle_parity(baseline: Path):
    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)
    slices = load_table_slices(baseline / "dataset.duckdb", repo.catalog)

    # Pick a Top-K case and a Composite Join case
    topk_case = next(c for c in pack.cases if c.limit is not None)
    comp_case = next(
        c for c in pack.cases if c.join and c.join.path == "customer_transactions_and_holdings"
    )

    for case in (topk_case, comp_case):
        spec = case.semantic_spec()
        compiled = compile_semantic(spec, repo)
        sql_result = normalize_sql_result(baseline / "dataset.duckdb", compiled)
        oracle_result = compute_independent(spec, repo, slices)

        cmp_policy = ComparisonPolicy(ordered=spec.order_by is not None)
        assert compare_results(sql_result, oracle_result, policy=cmp_policy) is True


def test_cli_generate_tasks_v1_4_flag(tmp_path: Path):
    out_dir = tmp_path / "v1_4_pack"
    result = runner.invoke(
        app,
        ["generate-tasks", "--output", str(out_dir), "--count", "120", "--v1-4"],
    )
    assert result.exit_code == 0
    assert (out_dir / "public_cases.yaml").exists()
    assert (out_dir / "generated_oracles.yaml").exists()
    assert (out_dir / "pack.json").exists()
    assert (out_dir / "isolation.json").exists()

    # Verify public cases DO NOT leak limit or order_by
    public_yaml = yaml.safe_load((out_dir / "public_cases.yaml").read_text(encoding="utf-8"))
    for case in public_yaml["cases"]:
        assert "limit" not in case
        assert "order_by" not in case
        assert "expected_action" not in case

    # Verify trusted oracles contain limit and order_by for Top-K
    trusted_yaml = yaml.safe_load((out_dir / "generated_oracles.yaml").read_text(encoding="utf-8"))
    trusted_topk = [c for c in trusted_yaml["cases"] if c.get("limit") is not None]
    assert len(trusted_topk) >= 2
    for c in trusted_topk:
        assert c["order_by"] is not None
        assert c["order_direction"] in {"asc", "desc"}
