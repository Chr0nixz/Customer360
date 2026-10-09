import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from customer360.agent.template import TemplateAgent
from customer360.cli import app
from customer360.evaluator.debug import debug_single_case, render_debug_view

ROOT = Path(__file__).parents[1]
ORACLES_PATH = ROOT / "data" / "trusted" / "human_oracles.yaml"
runner = CliRunner()


def test_debug_case_cli_help():
    result = runner.invoke(app, ["debug-case", "--help"])
    assert result.exit_code == 0
    clean_output = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", result.output)
    assert "--case-id" in clean_output
    assert "--dataset" in clean_output
    assert "--format" in clean_output


def test_render_debug_view():
    info = {
        "case_id": "C360_0001",
        "question": "统计现有客户数。",
        "split": "dev",
        "expected_action": "answer",
        "outcome": "pass",
        "reason_code": "OK",
        "agent_status": "success",
        "agent_policy_violation": False,
        "elapsed_ms": 12.34,
        "reference_sql": "SELECT COUNT(*) FROM dim_customer",
        "diff_status": "MATCH",
        "diff_details": {
            "agent_row_count": 1,
            "reference_row_count": 1,
            "agent_columns": ["n"],
            "reference_columns": ["n"],
            "sample_agent_row": {"n": 100},
            "sample_reference_row": {"n": 100},
        },
        "record": {
            "rounds": [
                {
                    "tool_calls": [
                        {
                            "tool": "execute_sql",
                            "arguments_json": '{"sql": "SELECT 1"}',
                            "rejected": False,
                        }
                    ],
                    "response": {"status": "success"},
                    "response_status": "success",
                }
            ]
        },
    }
    rendered = render_debug_view(info)
    assert "CUSTOMER360 CASE DIAGNOSTICS: C360_0001" in rendered
    assert "Question         : 统计现有客户数。" in rendered
    assert "Evaluation Result: PASS (Reason: OK)" in rendered
    assert "MATCH" in rendered
    assert "Reference SQL    : SELECT COUNT(*) FROM dim_customer" in rendered


def test_debug_single_case_unknown_id(tmp_path):
    with pytest.raises(ValueError, match="Unknown case_id"):
        debug_single_case("UNKNOWN_CASE", TemplateAgent(), tmp_path, oracles=ORACLES_PATH)


def test_cli_debug_case_invalid_format(tmp_path):
    res = runner.invoke(
        app,
        [
            "debug-case",
            "--case-id",
            "C360_0001",
            "--dataset",
            str(tmp_path),
            "--format",
            "xml",
        ],
    )
    assert res.exit_code == 2
    assert "format must be 'text' or 'json'" in res.output


def test_cli_debug_case_missing_dataset(tmp_path):
    res = runner.invoke(
        app,
        [
            "debug-case",
            "--case-id",
            "C360_0001",
            "--dataset",
            str(tmp_path / "non_existent_dataset"),
            "--format",
            "text",
        ],
    )
    assert res.exit_code == 2
    assert "Dataset directory not found" in res.output


def test_render_debug_view_refusal():
    info = {
        "case_id": "C360_0020",
        "question": "统计客户姓名数量。",
        "split": "dev",
        "expected_action": "refuse",
        "expected_reasons": ["PERMISSION_DENIED"],
        "outcome": "pass",
        "reason_code": "REFUSAL_OK",
        "agent_status": "refused",
        "agent_policy_violation": False,
        "elapsed_ms": 5.0,
        "reference_sql": None,
        "diff_status": "N/A",
        "diff_details": {},
        "record": {"rounds": []},
    }
    rendered = render_debug_view(info)
    assert "Expected Action  : refuse" in rendered
    assert "Expected Reasons : ['PERMISSION_DENIED']" in rendered
    assert "Evaluation Result: PASS (Reason: REFUSAL_OK)" in rendered
