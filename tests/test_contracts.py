from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from customer360.artifacts import digest
from customer360.contracts.generation import DatasetManifest
from customer360.contracts.manifest import FixtureManifest
from customer360.contracts.oracle import (
    CaseOracle,
    ClarificationOracle,
    ClarificationTurn,
    RefusalOracle,
    SlotReply,
)
from customer360.contracts.public import AgentRequest, AgentResponse, Column, QueryResult
from customer360.contracts.semantic import Filter, PointInTime, RollingWindow, SemanticSpec


def test_public_request_rejects_private_fields():
    with pytest.raises(ValidationError):
        AgentRequest(
            case_id="public",
            question="统计客户数",
            anchor_date=date(2025, 6, 30),
            metadata_version="0.3",
            semantic_spec={"metric": "distinct_customer_count"},
        )


def test_clarification_oracle_rejects_conflicting_slot_replies():
    spec = SemanticSpec(metric="distinct_customer_count")
    with pytest.raises(ValidationError, match="conflicting slot replies"):
        ClarificationOracle(
            replies=(SlotReply(slot="customer_level", reply="VIP"),),
            turns=(
                ClarificationTurn(
                    expected_slots=("customer_level",),
                    replies=(SlotReply(slot="customer_level", reply="standard"),),
                ),
            ),
            completed_spec=spec,
        )
    oracle = ClarificationOracle(
        replies=(SlotReply(slot="customer_level", reply="VIP"),),
        completed_spec=spec,
    )
    assert oracle.replay_script()[0].replies[0].reply == "VIP"
    roundtrip = ClarificationOracle.model_validate_json(oracle.model_dump_json())
    assert roundtrip.replies[0].reply == "VIP"


def test_refusal_oracle_has_no_gold_sql():
    oracle = RefusalOracle(accepted_reason_codes=("PERMISSION_DENIED",))
    assert TypeAdapter(CaseOracle).validate_json(oracle.model_dump_json()) == oracle
    assert "sql" not in oracle.model_dump_json()


@pytest.mark.parametrize(
    "response",
    [
        {"status": "success", "answer": "6", "sql": "SELECT 6", "confidence": 1},
        {"status": "clarification_needed", "questions": [], "requested_slots": []},
        {"status": "refused", "reason_code": "INTERNAL_ERROR", "reason": "x"},
        {"status": "error", "reason_code": "TOOL_ERROR", "message": "x", "sql": "leak"},
    ],
)
def test_invalid_agent_response(response):
    with pytest.raises(ValidationError):
        TypeAdapter(AgentResponse).validate_python(response)


@pytest.mark.parametrize(
    "kind,value",
    [
        ("integer", True),
        ("integer", "1"),
        ("date", "2025-99-01"),
        ("decimal", "NaN"),
        ("decimal", "Infinity"),
        ("decimal", 1),
        ("boolean", 1),
    ],
)
def test_typed_cells_reject_ambiguous_values(kind, value):
    with pytest.raises(ValidationError):
        QueryResult(columns=(Column(name="value", kind=kind),), rows=((value,),))


def test_result_wire_roundtrip():
    result = QueryResult(
        columns=(Column(name="amount", kind="decimal"), Column(name="d", kind="date")),
        rows=(("100.00", "2025-06-30"), (None, None)),
    )
    assert QueryResult.model_validate_json(result.model_dump_json()) == result


def test_rolling_days_are_inclusive():
    window = RollingWindow(days=90, anchor_date=date(2025, 6, 30))
    assert window.start_date == date(2025, 4, 2)
    assert (window.anchor_date - window.start_date).days + 1 == 90


@pytest.mark.parametrize(
    "kwargs",
    [
        {"field": "region", "operator": "eq", "values": ()},
        {"field": "region", "operator": "in", "values": ()},
        {"field": "region", "operator": "eq", "values": (None,)},
        {"field": "region; DROP TABLE x", "operator": "eq", "values": ("x",)},
    ],
)
def test_invalid_filter(kwargs):
    with pytest.raises(ValidationError):
        Filter(**kwargs)


def test_dsl_does_not_silently_drop_unimplemented_features():
    with pytest.raises(ValidationError):
        SemanticSpec(metric="distinct_customer_count", window_function="row_number")


def test_point_in_time_window_is_explicit():
    window = PointInTime(snapshot_date=date(2025, 6, 30))
    spec = SemanticSpec(metric="snapshot_total_asset", time_window=window)
    assert spec.time_window == window
    with pytest.raises(ValidationError):
        SemanticSpec(
            metric="snapshot_total_asset",
            time_window={"type": "latest_snapshot", "snapshot_date": "2025-06-30"},
        )
    latest = SemanticSpec(
        metric="latest_total_asset",
        time_window={"type": "latest_snapshot", "anchor_date": "2025-06-30"},
    )
    assert latest.time_window.type == "latest_snapshot"


def test_dataset_and_fixture_manifest_kinds_are_isolated(repository):
    tables = tuple(table.table_name for table in repository.catalog.tables)
    hashes = {name: digest(name) for name in tables}
    counts = dict.fromkeys(tables, 1)
    tiny = DatasetManifest(
        seed=42,
        anchor_date=date(2025, 6, 30),
        config_hash=digest("config"),
        catalog_hash=digest("catalog"),
        row_counts=counts,
        content_hashes=hashes,
        quality_report_hash=digest("quality"),
        environment={},
    )
    assert tiny.artifact_kind == "tiny_dataset"
    assert tiny.generator_version == "0.1.0"
    with pytest.raises(ValidationError):
        FixtureManifest.model_validate(tiny.model_dump(mode="json"))
    fixture_like = tiny.model_copy(
        update={
            "artifact_kind": "public_fixture_not_tiny",
            "generator_version": "fixture-0.1",
            "snapshot_version": "fixture-v1",
        }
    )
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(fixture_like.model_dump(mode="json"))
