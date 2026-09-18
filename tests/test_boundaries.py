import ast
from pathlib import Path


def test_agent_has_no_private_oracle_or_executor_imports():
    root = Path(__file__).parents[1] / "src/customer360/agent"
    denied = (
        "customer360.contracts.oracle",
        "customer360.contracts.semantic",
        "customer360.tasks",
        "customer360.evaluator",
        "customer360.runtime",
        "duckdb",
        "subprocess",
    )
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(denied), path
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith(denied) for item in node.names), path


def test_synth_never_imports_agent_or_evaluator():
    root = Path(__file__).parents[1] / "src/customer360/synth"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("customer360.agent", "customer360.evaluator")
                ), path
