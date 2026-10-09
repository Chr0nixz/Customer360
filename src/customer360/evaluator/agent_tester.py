"""Fast protocol conformance test suite for external agents."""

import importlib.util
import inspect
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from customer360.agent.protocol import Agent
from customer360.application import fixture_policy
from customer360.contracts.public import (
    AgentRequest,
    AgentResponse,
    Clarification,
    Refusal,
    Success,
)
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.tools import ToolSession
from customer360.synth.fixture import build_public_fixture


def load_agent_from_path(file_path: Path, class_name: str | None = None) -> Agent:
    """Dynamically load an Agent class from a python file."""
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Agent file not found: {resolved_path}")

    mod_name = f"c360_dyn_agent_{abs(hash(str(resolved_path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, resolved_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module specification from {resolved_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute agent script {resolved_path}: {exc}") from exc

    target_cls = None
    if class_name:
        target_cls = getattr(module, class_name, None)
        if target_cls is None:
            raise AttributeError(f"Class '{class_name}' not found in {resolved_path}")
    else:
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "respond") and callable(obj.respond):
                target_cls = obj
                break

    if target_cls is None:
        raise TypeError(f"No class implementing respond() method found in {resolved_path}")

    return target_cls()


def verify_agent_conformance(
    agent: Agent,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Run a 3-probe conformance test on the provided agent."""
    temp_dir = None
    try:
        if database_path is None:
            import tempfile

            temp_dir = Path(tempfile.mkdtemp(prefix="c360_probe_"))
            database_path = temp_dir / "probe.duckdb"
            build_public_fixture(database_path, seed=42)

        repository = MetadataRepository()
        gateway = ExecutionGateway(database_path, fixture_policy())
        session = ToolSession(gateway, repository)

        probes = [
            {
                "name": "answer_probe",
                "question": "统计现有客户数。",
                "expected_type": Success,
            },
            {
                "name": "clarify_probe",
                "question": "统计最近客户数。",
                "expected_type": Clarification,
            },
            {
                "name": "refusal_probe",
                "question": "统计客户姓名 customer_name 数量。",
                "expected_type": Refusal,
            },
        ]

        diagnostics: list[str] = []
        checked_types: list[str] = []
        passes = 0

        for probe in probes:
            req = AgentRequest(
                case_id=f"probe_{probe['name']}",
                question=probe["question"],
                anchor_date=date(2025, 6, 30),
                metadata_version=repository.metrics.metrics_version,
            )
            try:
                raw_resp = agent.respond(req, session)
                resp = TypeAdapter(AgentResponse).validate_python(raw_resp)
                checked_types.append(resp.status)

                if isinstance(resp, probe["expected_type"]):
                    passes += 1
                    diagnostics.append(
                        f"[{probe['name']}] PASSED: received expected {resp.__class__.__name__}"
                    )
                else:
                    diagnostics.append(
                        f"[{probe['name']}] WARNING: expected {probe['expected_type'].__name__}, "
                        f"received {resp.__class__.__name__} (status={resp.status})"
                    )
            except ValidationError as exc:
                diagnostics.append(f"[{probe['name']}] FAILED: Response validation error: {exc}")
            except Exception as exc:
                diagnostics.append(
                    f"[{probe['name']}] FAILED: Unhandled exception during respond(): {exc}"
                )

        conformance_passed = (passes >= 1) and (len(checked_types) == len(probes))

        return {
            "agent_name": getattr(agent, "name", agent.__class__.__name__),
            "total_probes": len(probes),
            "passed_probes": passes,
            "conformance_passed": conformance_passed,
            "response_statuses": checked_types,
            "diagnostics": diagnostics,
        }
    finally:
        if temp_dir is not None and temp_dir.exists():
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)
