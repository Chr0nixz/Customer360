"""Stage S: generated/hidden pack semantic acceptance. Not an official score."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from customer360.cli import app
from customer360.contracts.family import ERROR_CLASSES_REQUIRED
from customer360.contracts.pack_verify import (
    PUBLIC_VERIFY_FORBIDDEN,
    PackVariantResult,
    PackVerifyReport,
)
from customer360.contracts.public import Column, QueryReceipt, QueryResult
from customer360.contracts.variant import SEMANTIC_VERIFY_VARIANT_IDS
from customer360.errors import ExecutionFailure, QueryRejected
from customer360.tasks import pack_verify
from customer360.tasks.generator import generate_task_pack, write_generated_pack
from customer360.tasks.hidden import (
    generate_hidden_dataset,
    generate_hidden_pack,
    write_hidden_pack,
)
from customer360.tasks.pack_verify import verify_task_pack, write_pack_verify

runner = CliRunner()
ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def public_300():
    return generate_task_pack(seed=42, count=300)


@pytest.fixture(scope="module")
def report_300(baseline, variant, duplicate_variant, null_variant, date_variant, public_300):
    return verify_task_pack(
        baseline,
        public_300,
        variant_dirs=(variant, duplicate_variant, null_variant, date_variant),
    )


def test_generated_300_replays_all_four_variants(report_300):
    assert report_300.semantic_passed is True
    assert report_300.variant_count == 4
    assert report_300.m6_structure is True
    assert report_300.protocol_version == "0.2"
    assert PackVerifyReport.model_validate_json(report_300.model_dump_json()) == report_300
    executable = [c for c in report_300.cases if c.material_status == "compilable_answer"]
    assert all(
        tuple(row.variant_id for row in case.variants) == SEMANTIC_VERIFY_VARIANT_IDS
        for case in executable
    )
    assert all(row.independent_match for case in executable for row in case.variants)
    assert any(row.policy_incompatible for case in executable for row in case.variants)
    assert any(case.policy_block_code == "PERMISSION_DENIED" for case in executable)


def test_generated_120_pack_matches_independent_oracle(baseline):
    pack = generate_task_pack(seed=42, count=120)
    report = verify_task_pack(baseline, pack)
    assert isinstance(report, PackVerifyReport)
    assert report.scoring_applied is False
    assert report.m6_structure is False
    assert report.hidden is False
    assert report.replay_mode == "none"
    assert report.rewrite_passed is True
    assert report.compilable_answers == report.independent_oracle_matches
    assert report.unscored_oracles >= 2
    assert ERROR_CLASSES_REQUIRED <= set(report.wrong_sql_classes)
    assert report.semantic_passed is True
    assert all(item.split in {"train", "dev"} for item in report.cases)


def test_generated_120_same_sql_variant(baseline, variant):
    pack = generate_task_pack(seed=42, count=120)
    report = verify_task_pack(baseline, pack, variant_dirs=(variant,))
    assert report.replay_mode == "same_sql"
    assert report.variant_count == 1
    assert report.semantic_passed is True
    assert report.scoring_applied is False
    executable = [item for item in report.cases if item.material_status == "compilable_answer"]
    assert all(row.independent_match for item in executable for row in item.variants)


@pytest.mark.parametrize("count", [0, 1, 3, 5])
def test_m6_semantic_verify_requires_all_frozen_variants(baseline, variant, public_300, count):
    with pytest.raises(ValueError, match="four frozen Tiny variants"):
        verify_task_pack(baseline, public_300, variant_dirs=(variant,) * count)


def test_300_cannot_skip_variants_by_clearing_structure_flag(baseline, public_300):
    payload = public_300.model_dump()
    payload["m6_structure"] = False
    pack = type(public_300).model_validate(payload)
    with pytest.raises(ValueError, match="four frozen Tiny variants"):
        verify_task_pack(baseline, pack)


def test_duplicate_variants_are_rejected(baseline, variant, public_300):
    with pytest.raises(ValueError, match="duplicate Tiny variant"):
        verify_task_pack(baseline, public_300, variant_dirs=(variant,) * 4)


def test_300_variants_must_use_frozen_order(
    baseline, variant, duplicate_variant, null_variant, date_variant, public_300
):
    with pytest.raises(ValueError, match="four frozen Tiny variants"):
        verify_task_pack(
            baseline,
            public_300,
            variant_dirs=(date_variant, null_variant, duplicate_variant, variant),
        )


def test_pack_variant_policy_status_requires_explicit_code():
    with pytest.raises(ValueError, match="explicit gateway rejection"):
        PackVariantResult(
            variant_id="tiny_seed_43_distribution",
            policy_incompatible=True,
            independent_match=True,
            results_differ_from_baseline=False,
        )


@pytest.mark.parametrize("rows", [(), ((0,),), ((None,),)])
def test_policy_probe_does_not_infer_rejection_from_result(rows):
    gateway = Mock()
    gateway.execute.return_value = QueryReceipt(
        query_id="empty-but-accepted",
        result=QueryResult(columns=(Column(name="value", kind="integer"),), rows=rows),
        elapsed_ms=1,
    )
    assert pack_verify._policy_block_code(gateway, "SQL") is None
    gateway.execute.assert_called_once_with("SQL")


@pytest.mark.parametrize("code", ["AGGREGATION_TOO_SMALL", "PERMISSION_DENIED"])
def test_policy_probe_records_actual_rejection(code):
    gateway = Mock()
    gateway.execute.side_effect = QueryRejected(code, "synthetic rejection")
    assert pack_verify._policy_block_code(gateway, "SQL") == code


@pytest.mark.parametrize(
    "error",
    [
        QueryRejected("UNSAFE_SQL", "synthetic"),
        QueryRejected("UNSUPPORTED_QUERY", "synthetic"),
        ExecutionFailure("TIMEOUT", "synthetic"),
        ExecutionFailure("WORKER_CRASH", "synthetic"),
        ExecutionFailure("INPUT_LIMIT", "synthetic"),
    ],
)
def test_policy_probe_does_not_swallow_other_failures(error):
    gateway = Mock()
    gateway.execute.side_effect = error
    with pytest.raises(ValueError, match=error.code):
        pack_verify._policy_block_code(gateway, "SQL")


def test_policy_probe_rejects_truncation():
    gateway = Mock()
    gateway.execute.return_value = QueryReceipt(
        query_id="truncated",
        result=QueryResult(
            columns=(Column(name="value", kind="integer"),), rows=(), truncated=True
        ),
        elapsed_ms=1,
    )
    with pytest.raises(ValueError, match="row limit"):
        pack_verify._policy_block_code(gateway, "SQL")


def test_policy_rejection_cannot_hide_variant_oracle_mismatch(baseline, variant, monkeypatch):
    pack = generate_task_pack(seed=42, count=120)
    real_compute = pack_verify.compute_independent
    calls = 0

    def wrong_variant_oracle(*args):
        nonlocal calls
        calls += 1
        result = real_compute(*args)
        if calls == 2:
            return QueryResult(columns=(Column(name="wrong", kind="integer"),), rows=((-1,),))
        return result

    gateway = Mock()
    gateway.execute.side_effect = QueryRejected("AGGREGATION_TOO_SMALL", "synthetic rejection")
    monkeypatch.setattr(pack_verify, "ExecutionGateway", Mock(return_value=gateway))
    monkeypatch.setattr(pack_verify, "compute_independent", wrong_variant_oracle)
    report = verify_task_pack(baseline, pack, variant_dirs=(variant,))
    assert report.semantic_passed is False
    assert report.independent_oracle_matches == report.compilable_answers
    mismatched = [case for case in report.cases if case.failure]
    assert len(mismatched) == 1
    assert mismatched[0].failure == "variant_independent_oracle_mismatch"
    assert mismatched[0].variants[0].policy_incompatible is True
    assert mismatched[0].variants[0].independent_match is False


@pytest.mark.parametrize("tamper", ["count", "duplicate", "pass", "matches", "policy", "classes"])
def test_report_rejects_forged_evidence(report_300, tamper):
    payload = report_300.model_dump()
    executable = next(c for c in payload["cases"] if c["material_status"] == "compilable_answer")
    if tamper == "count":
        executable["variants"] = executable["variants"][:-1]
    elif tamper == "duplicate":
        executable["variants"][1]["variant_id"] = executable["variants"][0]["variant_id"]
    elif tamper == "pass":
        executable["variants"][0]["independent_match"] = False
    elif tamper == "matches":
        payload["independent_oracle_matches"] -= 1
    elif tamper == "policy":
        payload["policy_incompatible_count"] += 1
    else:
        payload["wrong_sql_classes"] = ()
    with pytest.raises(ValueError):
        PackVerifyReport.model_validate(payload)


def test_hidden_pack_verify_uses_hidden_tiny(baseline, tmp_path):
    public = generate_task_pack(seed=42, count=120)
    hidden = generate_hidden_pack(public, seed=42, count=8)
    hidden_data = tmp_path / "hidden-tiny"
    generate_hidden_dataset(hidden_data, seed=1042)
    report = verify_task_pack(hidden_data, hidden, hidden=True)
    assert report.hidden is True
    assert report.semantic_passed is True
    assert report.scoring_applied is False
    assert report.dataset_seed == 1042
    assert ERROR_CLASSES_REQUIRED <= set(report.wrong_sql_classes)
    assert all(item.split == "private" for item in report.cases)
    assert report.variant_count == 0 and report.replay_mode == "none"
    with pytest.raises(ValueError, match="cannot replay public Tiny variants"):
        verify_task_pack(hidden_data, hidden, hidden=True, variant_dirs=(baseline,))
    with pytest.raises(ValueError, match="hidden_profile"):
        verify_task_pack(baseline, hidden, hidden=True)
    with pytest.raises(ValueError, match="hidden Tiny"):
        verify_task_pack(hidden_data, public)


def test_verify_pack_cli_public_summary_hides_gold(baseline, tmp_path):
    pack_dir = tmp_path / "pack"
    write_generated_pack(
        pack_dir,
        generate_task_pack(seed=42, count=120),
        oracles=ROOT / "data/trusted/human_oracles.yaml",
    )
    output = tmp_path / "verify"
    result = runner.invoke(
        app,
        [
            "verify-pack",
            "--dataset",
            str(baseline),
            "--pack",
            str(pack_dir),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["semantic_passed"] is True
    assert summary["scoring_applied"] is False
    assert "dataset_seed" not in summary
    for field in PUBLIC_VERIFY_FORBIDDEN:
        assert field not in summary
    public = json.loads((output / "public" / "summary.json").read_text(encoding="utf-8"))
    assert "compiled_sql" not in public
    assert "dataset_seed" not in public
    assert "question" not in public
    assert "cases" not in public
    private = json.loads((output / "private" / "verify.json").read_text(encoding="utf-8"))
    assert private["dataset_seed"] == 42
    assert any(item.get("compiled_sql") for item in private["cases"])


def test_verify_hidden_cli_rejects_public_tiny(baseline, tmp_path):
    public_dir = tmp_path / "public"
    public = generate_task_pack(seed=42, count=120)
    write_generated_pack(public_dir, public, oracles=ROOT / "data/trusted/human_oracles.yaml")
    hidden_dir = tmp_path / "hidden"
    write_hidden_pack(
        hidden_dir,
        generate_hidden_pack(public, seed=42, count=8),
        public,
        oracles=ROOT / "data/trusted/human_oracles.yaml",
    )
    result = runner.invoke(
        app,
        [
            "verify-hidden",
            "--dataset",
            str(baseline),
            "--pack",
            str(hidden_dir),
            "--output",
            str(tmp_path / "hidden-verify"),
        ],
    )
    assert result.exit_code == 2
    assert "hidden_profile" in result.output or "hidden" in result.output.lower()


def test_write_pack_verify_refuses_overwrite(baseline, tmp_path):
    pack_dir = tmp_path / "pack"
    write_generated_pack(
        pack_dir,
        generate_task_pack(seed=42, count=120),
        oracles=ROOT / "data/trusted/human_oracles.yaml",
    )
    output = tmp_path / "once"
    write_pack_verify(baseline, pack_dir, output)
    with pytest.raises(FileExistsError):
        write_pack_verify(baseline, pack_dir, output)
