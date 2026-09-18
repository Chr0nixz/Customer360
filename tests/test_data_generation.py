"""T1 acceptance tests: reproducible Tiny generation, named quality checks,
independent metric slices and an explicit Tiny-scoped authorization policy."""

import json
import shutil
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

import customer360.synth.generator as generator_module
from customer360.agent.submission import SqlSubmissionAgent
from customer360.artifacts import digest, json_text
from customer360.contracts.execution import AccessPolicy, TableGrant
from customer360.contracts.generation import GenerationConfig, QualityCheck
from customer360.contracts.oracle import AnswerOracle, PrivateCase
from customer360.contracts.public import AgentRequest
from customer360.contracts.semantic import Filter, PointInTime, RollingWindow, SemanticSpec
from customer360.errors import QueryRejected
from customer360.evaluator.runner import evaluate_case
from customer360.metadata.metrics import MetadataRepository
from customer360.runtime.gateway import ExecutionGateway
from customer360.synth.generator import generate_dataset, load_generation_config
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.trusted_data import load_verified_dataset

ROOT = Path(__file__).parents[1]
ANCHOR = date(2025, 6, 30)
WINDOW_START = ANCHOR - timedelta(days=89)


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-seed42") / "first"
    manifest, quality = generate_dataset(GenerationConfig(seed=42), output)
    return output, manifest, quality


@pytest.fixture(scope="module")
def run_a_rerun(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-again") / "run"
    manifest, quality = generate_dataset(GenerationConfig(seed=42), output)
    return output, manifest, quality


@pytest.fixture(scope="module")
def run_b(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-seed43") / "run"
    manifest, quality = generate_dataset(GenerationConfig(seed=43), output)
    return output, manifest, quality


def _table_digests(database: Path, table_names: tuple[str, ...]) -> dict[str, str]:
    with duckdb.connect(str(database), read_only=True) as db:
        return {
            table: digest(sorted(db.execute(f'SELECT * FROM "{table}"').fetchall(), key=json_text))
            for table in table_names
        }


def _raw_rows(database: Path) -> tuple[list, list]:
    with duckdb.connect(str(database), read_only=True) as db:
        levels = db.execute("SELECT customer_id, customer_level FROM dim_customer").fetchall()
        transactions = db.execute(
            "SELECT transaction_date, customer_id, amount, status FROM fact_transaction"
        ).fetchall()
    return levels, transactions


def _metric_slices(database: Path) -> dict[str, object]:
    with duckdb.connect(str(database), read_only=True) as db:
        customers = db.execute(
            "SELECT customer_id, customer_level, status FROM dim_customer"
        ).fetchall()
        transactions = db.execute(
            "SELECT transaction_date, amount, status FROM fact_transaction"
        ).fetchall()
        flows = db.execute(
            "SELECT flow_date, flow_type, signed_amount, status FROM fact_cash_flow"
        ).fetchall()
        relations = db.execute("SELECT is_primary, end_date FROM fact_service_relation").fetchall()
        assets = db.execute(
            "SELECT snapshot_date, total_asset, net_asset FROM fact_asset_snapshot"
        ).fetchall()
    success = [
        Decimal(amount)
        for txn_date, amount, status in transactions
        if status == "success" and WINDOW_START <= txn_date <= ANCHOR
    ]
    return {
        "distinct_customer_count": sum(1 for _, level, _ in customers if level == "VIP"),
        "active_customer_count": sum(1 for _, _, status in customers if status == "active"),
        "successful_transaction_count": len(success),
        "successful_transaction_amount": str(sum(success, Decimal("0"))),
        "failed_transaction_count": sum(
            1
            for txn_date, _, status in transactions
            if status == "failed" and WINDOW_START <= txn_date <= ANCHOR
        ),
        "successful_net_cash_flow": str(
            sum(
                (
                    amount
                    for flow_date, _, amount, status in flows
                    if status == "success" and WINDOW_START <= flow_date <= ANCHOR
                ),
                Decimal("0"),
            )
        ),
        "successful_cash_inflow": str(
            sum(
                (
                    amount
                    for flow_date, flow_type, amount, status in flows
                    if status == "success"
                    and flow_type == "in"
                    and WINDOW_START <= flow_date <= ANCHOR
                ),
                Decimal("0"),
            )
        ),
        "current_primary_service_relation_count": sum(
            1 for primary, end in relations if primary and end is None
        ),
        "snapshot_total_asset": str(
            sum((total for snapshot, total, _ in assets if snapshot == ANCHOR), Decimal("0"))
        ),
        "snapshot_net_asset": str(
            sum((net for snapshot, _, net in assets if snapshot == ANCHOR), Decimal("0"))
        ),
    }


def _window_active_customers(database: Path) -> tuple[str, ...]:
    with duckdb.connect(str(database), read_only=True) as db:
        rows = db.execute(
            "SELECT DISTINCT customer_id FROM fact_transaction "
            "WHERE status = 'success' AND transaction_date BETWEEN ? AND ? "
            "ORDER BY customer_id",
            (WINDOW_START, ANCHOR),
        ).fetchall()
    return tuple(row[0] for row in rows)[:10]


def tiny_policy(customer_ids: tuple[str, ...], role: str) -> AccessPolicy:
    """Explicit Tiny customer scope; no wildcard, no reuse of the fixture policy."""
    return AccessPolicy(
        role=role,
        customer_ids=customer_ids,
        grants=(
            TableGrant(
                table="dim_customer",
                columns=(
                    "customer_id",
                    "customer_level",
                    "gender",
                    "risk_level",
                    "region",
                    "city",
                    "occupation",
                    "registration_date",
                    "status",
                ),
            ),
            TableGrant(
                table="fact_transaction",
                columns=(
                    "transaction_id",
                    "transaction_date",
                    "customer_id",
                    "product_id",
                    "transaction_type",
                    "amount",
                    "quantity",
                    "fee",
                    "status",
                    "channel",
                ),
            ),
            TableGrant(
                table="fact_cash_flow",
                columns=(
                    "flow_id",
                    "flow_date",
                    "customer_id",
                    "flow_type",
                    "signed_amount",
                    "channel",
                    "status",
                ),
            ),
            TableGrant(
                table="fact_service_relation",
                columns=(
                    "customer_id",
                    "manager_id",
                    "start_date",
                    "end_date",
                    "relation_type",
                    "is_primary",
                ),
            ),
            TableGrant(
                table="fact_asset_snapshot",
                columns=(
                    "snapshot_date",
                    "customer_id",
                    "total_asset",
                    "cash_asset",
                    "investment_asset",
                    "liability",
                    "net_asset",
                ),
            ),
        ),
    )


def test_same_seed_reproduces_identical_content(repository, run_a, run_a_rerun):
    output, manifest, _ = run_a
    rerun_output, rerun_manifest, _ = run_a_rerun
    assert rerun_manifest == manifest
    names = tuple(table.table_name for table in repository.catalog.tables)
    digests = _table_digests(output / "dataset.duckdb", names)
    rerun_digests = _table_digests(rerun_output / "dataset.duckdb", names)
    assert digests == rerun_digests
    assert digests == manifest["content_hashes"]


def test_different_seed_changes_business_content(repository, run_a, run_b):
    output, manifest_a, _ = run_a
    output_b, manifest_b, _ = run_b
    assert manifest_a["seed"] == 42 and manifest_b["seed"] == 43
    names = tuple(table.table_name for table in repository.catalog.tables)
    digests_a = _table_digests(output / "dataset.duckdb", names)
    digests_b = _table_digests(output_b / "dataset.duckdb", names)
    assert {"dim_customer", "fact_asset_snapshot", "fact_transaction"} <= {
        table for table, value in digests_a.items() if digests_b.get(table) != value
    }
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        total_a = sum(
            (
                Decimal(row[0])
                for row in db.execute(
                    "SELECT amount FROM fact_transaction WHERE status = 'success'"
                ).fetchall()
            ),
            Decimal("0"),
        )
    with duckdb.connect(str(output_b / "dataset.duckdb"), read_only=True) as db:
        total_b = sum(
            (
                Decimal(row[0])
                for row in db.execute(
                    "SELECT amount FROM fact_transaction WHERE status = 'success'"
                ).fetchall()
            ),
            Decimal("0"),
        )
    assert total_a != total_b


def test_nine_tables_load_at_exact_tiny_scale(repository, run_a):
    output, manifest, _ = run_a
    database = output / "dataset.duckdb"
    with duckdb.connect(str(database), read_only=True) as db:
        tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        assert tables == {table.table_name for table in repository.catalog.tables}
        assert db.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0] == 100
        assert db.execute("SELECT COUNT(*) FROM fact_transaction").fetchone()[0] == 2000
        for table, count in manifest["row_counts"].items():
            assert db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == count


def test_quality_report_all_named_checks_pass(run_a):
    _, _, quality = run_a
    assert quality["all_passed"] is True
    assert quality["failed_count"] == 0
    ids = [check["check_id"] for check in quality["checks"]]
    assert len(ids) >= 30
    assert len(set(ids)) == len(ids)
    assert all(check["description"] and check["observed"] for check in quality["checks"])


def test_designated_customer_groups_and_null_ratio(run_a):
    output, _, _ = run_a
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS "
                "(SELECT 1 FROM fact_transaction t WHERE t.customer_id = c.customer_id)"
            ).fetchone()[0]
            == 5
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS "
                "(SELECT 1 FROM fact_holding h WHERE h.customer_id = c.customer_id)"
            ).fetchone()[0]
            == 5
        )
        assert (
            db.execute("SELECT COUNT(*) FROM dim_customer WHERE occupation IS NULL").fetchone()[0]
            == 3
        )


def test_status_enums_and_amount_signs(run_a):
    output, _, _ = run_a
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_transaction WHERE status NOT IN "
                "('success', 'failed', 'cancelled')"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_cash_flow WHERE flow_type = 'in' AND signed_amount <= 0"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_cash_flow WHERE flow_type = 'out' AND signed_amount >= 0"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute("SELECT COUNT(*) FROM fact_transaction WHERE amount < 0").fetchone()[0] == 0
        )


def test_boundary_dates_of_the_ninety_day_window(run_a):
    output, _, _ = run_a
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        counts = dict(
            db.execute(
                "SELECT transaction_date, COUNT(*) FROM fact_transaction "
                "WHERE status = 'success' AND transaction_date IN (?, ?, ?) "
                "GROUP BY transaction_date",
                (WINDOW_START - timedelta(days=1), WINDOW_START, ANCHOR),
            ).fetchall()
        )
    assert counts[WINDOW_START - timedelta(days=1)] >= 1
    assert counts[WINDOW_START] >= 1
    assert counts[ANCHOR] >= 1


def test_asset_identities_and_multiple_valuation_dates(run_a):
    output, _, _ = run_a
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_asset_snapshot WHERE "
                "total_asset <> cash_asset + investment_asset "
                "OR net_asset <> total_asset - liability"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute("SELECT COUNT(DISTINCT snapshot_date) FROM fact_asset_snapshot").fetchone()[
                0
            ]
            == 7
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM (SELECT snapshot_date FROM fact_asset_snapshot "
                "GROUP BY snapshot_date HAVING COUNT(*) <> 100)"
            ).fetchone()[0]
            == 0
        )


def test_service_intervals_and_primary_uniqueness(run_a):
    output, _, _ = run_a
    with duckdb.connect(str(output / "dataset.duckdb"), read_only=True) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_service_relation "
                "WHERE (end_date IS NOT NULL AND end_date <= start_date) OR end_date > ?",
                (ANCHOR,),
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_service_relation a JOIN fact_service_relation b "
                "ON a.customer_id = b.customer_id AND a.rowid < b.rowid "
                "WHERE a.is_primary AND b.is_primary "
                "AND a.start_date < COALESCE(b.end_date, DATE '9999-12-31') "
                "AND b.start_date < COALESCE(a.end_date, DATE '9999-12-31')"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_service_relation r JOIN dim_customer c "
                "USING (customer_id) WHERE r.end_date IS NULL AND c.status = 'closed'"
            ).fetchone()[0]
            == 0
        )


def test_foreign_keys_and_unique_grain_enforced(run_a, tmp_path):
    source = run_a[0] / "dataset.duckdb"
    work = tmp_path / "copy.duckdb"
    shutil.copy(source, work)
    with duckdb.connect(str(work)) as db:
        with pytest.raises(duckdb.ConstraintException):
            db.execute(
                "INSERT INTO fact_transaction VALUES ("
                "'TX999', '2025-06-30', 'C999', 'P001', 'buy', 1, 1, 0, 'success', 'app')"
            )
        with pytest.raises(duckdb.ConstraintException):
            db.execute("INSERT INTO fact_asset_snapshot SELECT * FROM fact_asset_snapshot LIMIT 1")


def test_ten_metrics_on_tiny_match_independent_python(run_a):
    output, _, _ = run_a
    database = output / "dataset.duckdb"
    levels, _ = _raw_rows(database)
    expected = _metric_slices(database)
    repository = MetadataRepository()
    gateway = ExecutionGateway(
        database, tiny_policy(tuple(sorted(customer for customer, _ in levels)), "tiny_full_scope")
    )
    rolling = RollingWindow(days=90, anchor_date=ANCHOR)
    point = PointInTime(snapshot_date=ANCHOR)
    cases = [
        (
            SemanticSpec(
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
            ),
            expected["distinct_customer_count"],
        ),
        (SemanticSpec(metric="active_customer_count"), expected["active_customer_count"]),
        (
            SemanticSpec(metric="successful_transaction_count", time_window=rolling),
            expected["successful_transaction_count"],
        ),
        (
            SemanticSpec(metric="successful_transaction_amount", time_window=rolling),
            expected["successful_transaction_amount"],
        ),
        (
            SemanticSpec(metric="failed_transaction_count", time_window=rolling),
            expected["failed_transaction_count"],
        ),
        (
            SemanticSpec(metric="successful_net_cash_flow", time_window=rolling),
            expected["successful_net_cash_flow"],
        ),
        (
            SemanticSpec(metric="successful_cash_inflow", time_window=rolling),
            expected["successful_cash_inflow"],
        ),
        (
            SemanticSpec(metric="current_primary_service_relation_count"),
            expected["current_primary_service_relation_count"],
        ),
        (
            SemanticSpec(metric="snapshot_total_asset", time_window=point),
            expected["snapshot_total_asset"],
        ),
        (
            SemanticSpec(metric="snapshot_net_asset", time_window=point),
            expected["snapshot_net_asset"],
        ),
    ]
    assert len(cases) == 10
    for spec, value in cases:
        receipt = gateway.execute(compile_semantic(spec, repository).sql)
        assert receipt.result.rows[0][0] == value, spec.metric


def test_tiny_scoped_policy_hides_out_of_scope_customers(run_a):
    output, _, _ = run_a
    database = output / "dataset.duckdb"
    scope = _window_active_customers(database)
    gateway = ExecutionGateway(database, tiny_policy(scope, "tiny_analyst"))
    levels, _ = _raw_rows(database)
    scoped = set(scope)
    vip_in_scope = sum(1 for customer, level in levels if customer in scoped and level == "VIP")
    receipt = gateway.execute(
        "SELECT COUNT(DISTINCT customer_id) AS customer_count FROM dim_customer "
        "WHERE customer_level = 'VIP'"
    )
    assert receipt.result.rows[0][0] == vip_in_scope
    outside = next(customer for customer, _ in levels if customer not in scoped)
    with pytest.raises(QueryRejected) as exc_info:
        gateway.execute(
            "SELECT COUNT(transaction_id) AS transaction_count FROM fact_transaction "
            f"WHERE customer_id = '{outside}' AND transaction_date >= '2025-04-02' "
            "AND transaction_date <= '2025-06-30'"
        )
    assert exc_info.value.code == "AGGREGATION_TOO_SMALL"


def test_tiny_policy_rejects_restricted_columns(run_a):
    output, _, _ = run_a
    database = output / "dataset.duckdb"
    scope = _window_active_customers(database)
    policy = tiny_policy(scope, "tiny_analyst")
    restricted = policy.model_dump()
    restricted["grants"][0]["columns"] = tuple(restricted["grants"][0]["columns"]) + (
        "customer_name",
    )
    with pytest.raises(QueryRejected) as exc_info:
        ExecutionGateway(database, AccessPolicy.model_validate(restricted))
    assert exc_info.value.code == "PERMISSION_DENIED"


def _case(case_id: str, spec: SemanticSpec) -> PrivateCase:
    return PrivateCase(
        request=AgentRequest(
            case_id=case_id,
            question="Tiny slice case.",
            anchor_date=ANCHOR,
            metadata_version="0.3",
        ),
        oracle=AnswerOracle(semantic_spec=spec),
    )


def test_evaluate_case_on_tiny_answers_and_negatives(run_a):
    output, _, _ = run_a
    database = output / "dataset.duckdb"
    scope = _window_active_customers(database)
    gateway = ExecutionGateway(database, tiny_policy(scope, "tiny_analyst"))
    repository = MetadataRepository()
    spec = SemanticSpec(
        metric="successful_transaction_count",
        time_window=RollingWindow(days=90, anchor_date=ANCHOR),
    )
    compiled = compile_semantic(spec, repository)
    record = evaluate_case(
        _case("tiny_good", spec), SqlSubmissionAgent(compiled.sql), gateway, repository
    )
    assert (record.outcome, record.reason_code) == ("pass", "OK")
    record = evaluate_case(
        _case("tiny_wrong", spec),
        SqlSubmissionAgent(
            "SELECT COUNT(DISTINCT customer_id) AS transaction_count FROM fact_transaction"
        ),
        gateway,
        repository,
    )
    assert (record.outcome, record.reason_code) == ("fail", "RESULT_MISMATCH")
    record = evaluate_case(
        _case("tiny_unsafe", spec),
        SqlSubmissionAgent("DROP TABLE fact_transaction"),
        gateway,
        repository,
    )
    assert (record.outcome, record.reason_code) == ("fail", "UNSAFE_SQL")


def test_non_tiny_scale_and_overwrite_fail_closed(run_a, tmp_path):
    output, _, _ = run_a
    with pytest.raises(FileExistsError):
        generate_dataset(GenerationConfig(seed=42), output)
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="standard", customers=100, transactions=2000)
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="tiny", customers=10_000, transactions=300_000)
    bogus = GenerationConfig.model_construct(scale="xlarge")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        generate_dataset(bogus, tmp_path / "xlarge")


def test_yaml_generation_config_matches_contract_defaults():
    config = load_generation_config(ROOT / "configs" / "data_generation.yaml")
    assert config == GenerationConfig()


def test_generation_config_rejects_bad_inputs():
    with pytest.raises(ValidationError, match="designated"):
        GenerationConfig(
            customers_without_transactions=90,
            customers_without_positions=90,
            customers_with_null_occupation=90,
        )
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(customers=200)
    with pytest.raises(ValidationError):
        GenerationConfig(snapshot_dates=(date(2025, 3, 31), date(2024, 12, 31), ANCHOR))
    with pytest.raises(ValidationError):
        GenerationConfig(snapshot_dates=(date(2024, 12, 31), date(2025, 5, 31)))
    with pytest.raises(ValidationError):
        GenerationConfig(horizon_start=ANCHOR)


def test_generator_handles_minimal_valid_dimensions():
    config = GenerationConfig(
        managers=1,
        products=1,
        horizon_start=date(2025, 6, 29),
        snapshot_dates=(date(2025, 6, 29), ANCHOR),
    )
    rows = generator_module._build_rows(config)
    assert len(rows["dim_service_manager"]) == 1
    assert len(rows["dim_product"]) == 1
    assert len(rows["fact_transaction"]) == config.transactions


def test_yaml_config_with_unknown_scale_fails_clean(tmp_path):
    config = tmp_path / "bad-scale.yaml"
    config.write_text("scale: xlarge\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not supported"):
        load_generation_config(config)
    assert not (tmp_path / "xlarge").exists()


def test_standard_and_large_config_sizes_are_frozen():
    tiny = GenerationConfig()
    standard = GenerationConfig(scale="standard")
    large = GenerationConfig(scale="large")
    assert (tiny.customers, tiny.transactions) == (100, 2000)
    assert (standard.customers, standard.transactions) == (10_000, 300_000)
    assert (large.customers, large.transactions) == (100_000, 3_000_000)
    assert standard.customers_without_transactions == 500
    assert standard.customers_without_positions == 500
    assert standard.customers_with_null_occupation == 300
    assert large.customers_without_transactions == 5_000
    assert large.customers_with_null_occupation == 3_000
    for config in (tiny, standard, large):
        designated = (
            config.customers_without_transactions
            + config.customers_without_positions
            + config.customers_with_null_occupation
        )
        assert designated <= config.customers
    with pytest.raises(ValidationError, match="strictly"):
        GenerationConfig(scale="large", customers=10_000, transactions=300_000)


TINY_SEED42_CONTENT_HASHES = {
    "dim_customer": "442efa7d021f75f7f7ce3975075cdc8413b7c89398ff9a2e6feaed5415770c11",
    "dim_date": "ad94d20620349a6bc6a36313f576d545cec5fc6d07c4edb15a1488da2227ca07",
    "dim_product": "6a882f182255fc2e4d4f43635fc146723d3d887741269b2d321b3ca31756e20a",
    "dim_service_manager": "24f6f9e5d83956e1a3083e496971c145e503ecdb617203c63e85c424b4e0ad64",
    "fact_asset_snapshot": "a4400ad500aa586360ababab14b3cd4ecccac58914c250ebbb609b0581f4c28d",
    "fact_cash_flow": "bccc0736efdfdc67f634103108231addee9d4c2acd6adb2297d56f0bfa84fe12",
    "fact_holding": "f97c8b2c58c376f0b6916d68948d7b13860c9c0585c2789d88f8400bc2c7defb",
    "fact_service_relation": "f8f5427d7040099ec7067526a34bfba4e4bb955174fbd60444b224b463546c0c",
    "fact_transaction": "4f5fec3f3dfa37f4e57de6ddd83a6065f0075aa3a581eda99d33fd9bf5b7bae4",
}
TINY_SEED42_QUALITY_HASH = "4684c2cdc41cf97b5b5a6b9a2ebe602db2491be4d28c072cc6101b62f4dde683"


def test_tiny_seed42_content_hashes_remain_frozen(run_a):
    _, manifest, quality = run_a
    assert manifest["scale"] == "tiny"
    assert manifest["row_counts"]["dim_customer"] == 100
    assert manifest["row_counts"]["fact_transaction"] == 2000
    assert manifest["content_hashes"] == TINY_SEED42_CONTENT_HASHES
    assert manifest["quality_report_hash"] == TINY_SEED42_QUALITY_HASH
    assert quality["all_passed"] is True
    assert quality["scale"] == "tiny"


def test_quality_failure_blocks_manifest_publish(monkeypatch, tmp_path):
    def failing_checks(conn, config):
        return tuple(
            QualityCheck(
                check_id=f"forced_failure_{index:02d}",
                description="hardening: simulated failed assertion",
                passed=False,
                observed="0",
            )
            for index in range(30)
        )

    monkeypatch.setattr(generator_module, "run_quality_checks", failing_checks)
    output = tmp_path / "tiny-broken"
    with pytest.raises(ValueError, match="quality checks failed"):
        generate_dataset(GenerationConfig(seed=42), output)
    assert (output / "dataset.duckdb").exists()
    assert (output / "quality_report.json").exists()
    assert not (output / "manifest.json").exists()
    assert not (output / "generation_config.json").exists()
    report = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert report["all_passed"] is False
    assert report["failed_count"] == 30


def test_verified_dataset_rejects_tampered_quality_sidecar(run_a, tmp_path):
    source, _, _ = run_a
    copied = tmp_path / "copied"
    shutil.copytree(source, copied)
    quality_path = copied / "quality_report.json"
    payload = json.loads(quality_path.read_text(encoding="utf-8"))
    payload["seed"] = 43
    quality_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="quality report hash"):
        load_verified_dataset(copied)


def test_verified_dataset_rejects_malformed_manifest(run_a, tmp_path):
    source, _, _ = run_a
    copied = tmp_path / "copied-manifest"
    shutil.copytree(source, copied)
    (copied / "manifest.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest is not valid JSON"):
        load_verified_dataset(copied)


def test_output_directory_inventory(run_a):
    output, _, _ = run_a
    assert {path.name for path in output.iterdir()} == {
        "dataset.duckdb",
        "manifest.json",
        "quality_report.json",
        "generation_config.json",
    }
