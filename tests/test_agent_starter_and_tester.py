import json

import pytest
from typer.testing import CliRunner

from customer360.agent.starter import generate_agent_starter
from customer360.cli import app
from customer360.evaluator.agent_tester import load_agent_from_path, verify_agent_conformance

runner = CliRunner()


def test_init_and_test_agent_flow(tmp_path):
    agent_file = tmp_path / "my_custom_agent.py"

    # 1. Generate starter
    path = generate_agent_starter(agent_file, agent_name="DemoAgent")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "class DemoAgent:" in content
    assert "tools.execute_sql" in content

    # 2. Refuses overwrite without force
    with pytest.raises(FileExistsError):
        generate_agent_starter(agent_file, force=False)

    # 3. Dynamic load
    agent_instance = load_agent_from_path(agent_file)
    assert hasattr(agent_instance, "respond")

    # 4. Conformance smoke check
    report = verify_agent_conformance(agent_instance)
    assert report["total_probes"] == 3
    assert report["conformance_passed"] is True
    assert set(report["response_statuses"]) == {"success", "clarification_needed", "refused"}


def test_cli_init_and_test_agent(tmp_path):
    agent_file = tmp_path / "cli_agent.py"

    # CLI init-agent
    res_init = runner.invoke(app, ["init-agent", "--output", str(agent_file), "--name", "CliAgent"])
    assert res_init.exit_code == 0
    assert agent_file.exists()

    # CLI test-agent
    res_test = runner.invoke(app, ["test-agent", "--agent", str(agent_file)])
    assert res_test.exit_code == 0
    report = json.loads(res_test.output)
    assert report["conformance_passed"] is True


def test_load_agent_missing_file(tmp_path):
    missing_file = tmp_path / "non_existent.py"
    with pytest.raises(FileNotFoundError):
        load_agent_from_path(missing_file)


def test_load_agent_no_agent_class(tmp_path):
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(TypeError, match="No class implementing respond"):
        load_agent_from_path(empty_file)


def test_generate_agent_starter_invalid_identifier(tmp_path):
    with pytest.raises(ValueError, match="not a valid Python identifier"):
        generate_agent_starter(tmp_path / "bad.py", agent_name="123-bad-name")


def test_generate_agent_starter_invalid_suffix(tmp_path):
    with pytest.raises(ValueError, match="output_path must end with .py"):
        generate_agent_starter(tmp_path / "bad_extension.txt", agent_name="ValidName")


def test_load_agent_syntax_error(tmp_path):
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def broken_func(:\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Failed to execute agent script"):
        load_agent_from_path(broken_file)


def test_load_agent_missing_specified_class(tmp_path):
    agent_file = tmp_path / "valid.py"
    agent_file.write_text(
        "class MyCls:\n    def respond(self, req, tools): pass\n",
        encoding="utf-8",
    )
    with pytest.raises(AttributeError, match="Class 'NoSuchClass' not found"):
        load_agent_from_path(agent_file, class_name="NoSuchClass")


def test_cli_test_agent_missing_file_fails(tmp_path):
    res = runner.invoke(app, ["test-agent", "--agent", str(tmp_path / "none.py")])
    assert res.exit_code == 2
    assert "Agent file not found" in res.output
