"""D076: formal Gold applicability is probed through the real gateway wherever
it can affect scoring.

C360_1284-class failures: the Gold reference contributes zero customers on a
distribution variant while the baseline still contributes rows. The variant
replay used to record the agent rejection as a plain mismatch; for
baseline-eligible cases the Gold-side gateway probe now marks such a snapshot
inapplicable, aligned with the D036 rule that zero-contribution Gold carries no
discriminative signal. Cases already excluded by their baseline keep plain
replay rows, preserving the frozen robustness-coverage gate.
"""

import shutil

import duckdb
import pytest

from customer360.contracts.evaluation import FORMAL_EVALUATOR_VERSION
from customer360.evaluator.formal import _reference
from customer360.runtime.gateway import ExecutionGateway
from customer360.runtime.policy import tiny_eval_policy
from customer360.tasks.generator import generate_task_pack
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset

pytestmark = pytest.mark.slow

FACT_TABLES = (
    "fact_transaction",
    "fact_cash_flow",
    "fact_holding",
    "fact_asset_snapshot",
    "fact_service_relation",
)


def _region_answer_case(pack):
    """Pick a dev answer case whose Gold filters one region on a single table."""
    for item in pack.cases:
        if item.split != "dev" or item.expected_action != "answer":
            continue
        spec = item.semantic_spec()
        if spec.join is not None:
            continue
        for filt in spec.filters:
            if filt.field == "region" and filt.operator == "eq":
                return item, filt.values[0]
    raise AssertionError("dev pack has no single-table region answer case")


@pytest.fixture()
def doctored_variant(tmp_path, baseline):
    """Baseline Tiny copy with one region removed, so any region-filtered Gold
    contributes zero customers and the real gateway must reject it."""
    item, region = _region_answer_case(generate_task_pack(seed=42, count=120))
    database, _manifest = load_verified_dataset(baseline)
    path = tmp_path / "doctored.duckdb"
    shutil.copyfile(database, path)
    con = duckdb.connect(str(path))
    for table in FACT_TABLES:
        con.execute(
            f"DELETE FROM {table} WHERE customer_id IN "
            "(SELECT customer_id FROM dim_customer WHERE region = ?)",
            [region],
        )
    con.execute("DELETE FROM dim_customer WHERE region = ?", [region])
    con.close()
    return item, path


def test_formal_evaluator_version_bumped_for_variant_probe():
    assert FORMAL_EVALUATOR_VERSION == "0.7"


def test_reference_marks_zero_contribution_variant_inapplicable(repository, doctored_variant):
    item, path = doctored_variant
    gateway = ExecutionGateway(path, tiny_eval_policy())
    slices = load_table_slices(path, repository.catalog)
    independent, blocked = _reference("doctored_variant", item, path, gateway, repository, slices)
    assert independent is not None
    assert blocked is not None
    assert blocked.applicable is False
    assert blocked.policy_code == "AGGREGATION_TOO_SMALL"
    assert blocked.independent_match is False


def test_reference_still_runs_contributing_gold_on_baseline(repository, baseline):
    item, _region = _region_answer_case(generate_task_pack(seed=42, count=120))
    database, _manifest = load_verified_dataset(baseline)
    gateway = ExecutionGateway(database, tiny_eval_policy())
    slices = load_table_slices(database, repository.catalog)
    independent, blocked = _reference("baseline", item, database, gateway, repository, slices)
    assert blocked is None
    assert independent is not None
