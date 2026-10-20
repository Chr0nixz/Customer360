"""Test baking new-generation v1.4 task packs (Public 300 & Hidden 100)."""

from __future__ import annotations

from decimal import Decimal

import duckdb
import yaml

from customer360.contracts.coverage import PRIVATE_ORACLE_FIELDS
from customer360.contracts.public import QueryResult
from customer360.evaluator.compare import ComparisonPolicy, compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.dialects import transpile_sql
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.generator import generate_task_pack, write_generated_pack
from customer360.tasks.hidden import generate_hidden_pack, write_hidden_pack
from customer360.tasks.independent import compute_independent
from customer360.tasks.isolation import check_generated_isolation, check_hidden_isolation
from customer360.tasks.slices import load_table_slices


def test_bake_public_300_v1_4_pack(tmp_path):
    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=300, repository=repo, include_v1_4=True)

    assert pack.case_count == 300
    assert pack.m3_complete is True
    assert pack.m6_structure is True
    assert sum(c.split == "train" for c in pack.cases) == 180
    assert sum(c.split == "dev" for c in pack.cases) == 120

    # 1. Feature presence in Public 300
    topk_cases = [c for c in pack.cases if c.limit is not None]
    comp_join_cases = [
        c for c in pack.cases if c.join and c.join.path == "customer_transactions_and_holdings"
    ]
    having_cases = [c for c in pack.cases if c.having]
    ratio_cases = [c for c in pack.cases if c.ratio is not None]

    assert len(topk_cases) >= 2
    assert len(comp_join_cases) >= 2
    assert len(having_cases) >= 2
    assert len(ratio_cases) >= 2

    # 2. Output files and physical privacy
    out_dir = tmp_path / "public_300"
    write_generated_pack(out_dir, pack)

    public_yaml = yaml.safe_load((out_dir / "public_cases.yaml").read_text(encoding="utf-8"))
    for case in public_yaml["cases"]:
        for forbidden in PRIVATE_ORACLE_FIELDS:
            assert forbidden not in case

    trusted_yaml = yaml.safe_load((out_dir / "generated_oracles.yaml").read_text(encoding="utf-8"))
    trusted_cases = trusted_yaml["cases"]
    assert len(trusted_cases) == 300

    # 3. Isolation
    human = load_human_cases(check_rewrites=False)
    isolation = check_generated_isolation(human, pack)
    assert isolation.passed is True


def test_bake_hidden_100_v1_4_pack(tmp_path):
    repo = MetadataRepository()
    public_pack = generate_task_pack(seed=42, count=300, repository=repo, include_v1_4=True)
    hidden_pack = generate_hidden_pack(
        public_pack, seed=42, count=100, repository=repo, include_v1_4=True
    )

    assert hidden_pack.case_count == 100

    # 1. Quota distribution (61 Answer / 23 Clarification / 16 Refusal)
    action_counts = {}
    for c in hidden_pack.cases:
        action_counts[c.expected_action] = action_counts.get(c.expected_action, 0) + 1
    assert action_counts["answer"] == 61
    assert action_counts["clarification_needed"] == 23
    assert action_counts["refuse"] == 16

    # 2. Feature presence in Hidden 100
    topk_cases = [c for c in hidden_pack.cases if c.limit is not None]
    comp_join_cases = [
        c
        for c in hidden_pack.cases
        if c.join and c.join.path == "customer_transactions_and_holdings"
    ]
    having_cases = [c for c in hidden_pack.cases if c.having]
    ratio_cases = [c for c in hidden_pack.cases if c.ratio is not None]

    assert len(topk_cases) >= 2
    assert len(comp_join_cases) >= 2
    assert len(having_cases) >= 2
    assert len(ratio_cases) >= 2

    # 3. Output files and physical privacy
    out_dir = tmp_path / "hidden_100"
    write_hidden_pack(out_dir, hidden_pack, public_pack)

    agent_cases_yaml = yaml.safe_load((out_dir / "agent_cases.yaml").read_text(encoding="utf-8"))
    for case in agent_cases_yaml["cases"]:
        for forbidden in PRIVATE_ORACLE_FIELDS:
            assert forbidden not in case

    # 4. Strict isolation against Public 300 and Human 20
    human = load_human_cases(check_rewrites=False)
    isolation = check_hidden_isolation(human, public_pack, hidden_pack)
    assert isolation.passed is True


def test_v1_4_transpile_and_oracle_agreement(baseline):
    repo = MetadataRepository()
    db_file = baseline / "dataset.duckdb"
    slices = load_table_slices(db_file, repo.catalog)

    # Sample representative v1.4 cases from both packs
    pub = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)
    hid = generate_hidden_pack(pub, seed=42, count=30, repository=repo, include_v1_4=True)

    def is_v1_4(c):
        has_j3 = c.join and c.join.path == "customer_transactions_and_holdings"
        return bool(c.limit or c.having or c.ratio or has_j3)

    test_cases = [c for c in pub.cases if c.expected_action == "answer" and is_v1_4(c)] + [
        c for c in hid.cases if c.expected_action == "answer" and is_v1_4(c)
    ]

    assert len(test_cases) >= 8

    conn = duckdb.connect(str(db_file), read_only=True)
    for c in test_cases:
        spec = c.semantic_spec()
        compiled = compile_semantic(spec, repo)

        # 1. Transpilation to Postgres AST must be valid
        transpiled = transpile_sql(compiled.sql, source_dialect="duckdb", target_dialect="postgres")
        assert transpiled.ast_valid is True

        # 2. DuckDB execution matches Independent Oracle 100%
        duck_rows = conn.execute(compiled.sql).fetchall()
        norm_rows = []
        for r in duck_rows:
            norm_rows.append(
                tuple(str(cell) if isinstance(cell, (float, Decimal)) else cell for cell in r)
            )
        duck_res = QueryResult(columns=compiled.columns, rows=tuple(norm_rows))

        oracle_res = compute_independent(spec, repo, slices)
        policy = ComparisonPolicy(ordered=bool(spec.order_by) or spec.limit is not None)
        assert compare_results(duck_res, oracle_res, policy=policy) is True
    conn.close()


def test_cli_generate_and_check_isolation(tmp_path):
    from typer.testing import CliRunner

    from customer360.cli import app

    runner = CliRunner()
    pub_dir = tmp_path / "cli_pub"
    hid_dir = tmp_path / "cli_hid"

    # 1. Generate public pack with --v1-4
    res_pub = runner.invoke(
        app, ["generate-tasks", "--count", "120", "--v1-4", "--output", str(pub_dir)]
    )
    assert res_pub.exit_code == 0
    assert (pub_dir / "pack.json").exists()

    # 2. Generate hidden pack with --v1-4
    res_hid = runner.invoke(
        app,
        [
            "generate-hidden",
            "--count",
            "60",
            "--v1-4",
            "--public-pack",
            str(pub_dir),
            "--output",
            str(hid_dir),
        ],
    )
    assert res_hid.exit_code == 0
    assert (hid_dir / "pack.json").exists()

    # 3. Check isolation via CLI
    res_iso = runner.invoke(
        app, ["check-isolation", "--pack", str(pub_dir), "--hidden", str(hid_dir)]
    )
    assert res_iso.exit_code == 0
    assert '"passed": true' in res_iso.stdout.lower() or '"passed":true' in res_iso.stdout.lower()


def test_verify_task_pack_semantic_acceptance_v1_4(baseline):
    from customer360.tasks.pack_verify import verify_task_pack

    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=120, repository=repo, include_v1_4=True)

    report = verify_task_pack(baseline, pack)
    assert report.semantic_passed is True
    assert all(
        c.independent_match for c in report.cases if c.material_status == "compilable_answer"
    )
    assert all(c.failure is None for c in report.cases)
