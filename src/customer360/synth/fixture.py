from datetime import date
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from random import Random

import duckdb

from customer360.artifacts import digest, json_text
from customer360.contracts.manifest import FixtureManifest
from customer360.metadata.metrics import load_catalog
from customer360.synth.schema import render_ddl


def _rows():
    return {
        "dim_customer": [
            (
                "C001",
                "客户甲",
                "F",
                date(1988, 1, 12),
                "VIP",
                "low",
                "华东",
                "上海",
                None,
                date(2020, 1, 1),
                "active",
            ),
            (
                "C002",
                "客户乙",
                "M",
                date(1979, 5, 4),
                "standard",
                "medium",
                "华东",
                "杭州",
                "教师",
                date(2021, 4, 20),
                "active",
            ),
            (
                "C003",
                "客户丙",
                "F",
                date(1995, 8, 22),
                "VIP",
                "low",
                "华南",
                "深圳",
                "工程师",
                date(2022, 9, 9),
                "active",
            ),
            (
                "C004",
                "客户丁",
                "M",
                date(1968, 2, 10),
                "standard",
                "high",
                "华北",
                "北京",
                "医生",
                date(2018, 3, 14),
                "dormant",
            ),
            (
                "C005",
                "客户戊",
                "F",
                date(1990, 12, 1),
                "standard",
                "medium",
                "华东",
                "上海",
                "设计师",
                date(2023, 2, 1),
                "active",
            ),
            (
                "C006",
                "客户己",
                "M",
                date(1985, 7, 7),
                "VIP",
                "low",
                "西南",
                "成都",
                None,
                date(2019, 7, 7),
                "closed",
            ),
        ],
        "dim_service_manager": [
            ("M001", "经理一", "B001", "上海一部", "华东", date(2015, 1, 1), "active"),
            ("M002", "经理二", "B002", "深圳一部", "华南", date(2017, 6, 1), "active"),
            ("M003", "经理三", "B003", "北京一部", "华北", date(2012, 9, 1), "dormant"),
        ],
        "dim_product": [
            ("P001", "稳健债券", "bond", "low", "Issuer-A", "CNY", date(2010, 1, 1), "active"),
            ("P002", "成长混合", "fund", "medium", "Issuer-B", "CNY", date(2012, 4, 1), "active"),
            ("P003", "高风险基金", "fund", "high", "Issuer-C", "CNY", date(2014, 7, 1), "active"),
        ],
        "fact_service_relation": [
            ("C001", "M001", date(2020, 1, 1), None, "wealth", True),
            ("C002", "M001", date(2021, 4, 20), None, "wealth", True),
            ("C003", "M002", date(2022, 9, 9), None, "wealth", True),
            ("C004", "M003", date(2018, 3, 14), date(2023, 1, 1), "wealth", True),
        ],
        "dim_date": [
            ("2025-06-28", date(2025, 6, 28), 2025, 2, 6, 26, False, False),
            ("2025-06-29", date(2025, 6, 29), 2025, 2, 6, 26, False, False),
            ("2025-06-30", date(2025, 6, 30), 2025, 2, 6, 27, True, True),
        ],
        "fact_holding": [
            (
                date(2025, 6, 30),
                "C001",
                "P001",
                Decimal("10.00"),
                Decimal("1000.00"),
                Decimal("950.00"),
                Decimal("50.00"),
                "active",
            ),
            (
                date(2025, 6, 30),
                "C003",
                "P002",
                Decimal("5.00"),
                Decimal("800.00"),
                Decimal("760.00"),
                Decimal("40.00"),
                "active",
            ),
        ],
        "fact_asset_snapshot": [
            (
                date(2025, 6, 30),
                "C001",
                Decimal("12000.00"),
                Decimal("2000.00"),
                Decimal("10000.00"),
                Decimal("1000.00"),
                Decimal("11000.00"),
            ),
            (
                date(2025, 6, 30),
                "C002",
                Decimal("3000.00"),
                Decimal("1000.00"),
                Decimal("2000.00"),
                Decimal("500.00"),
                Decimal("2500.00"),
            ),
            (
                date(2025, 6, 30),
                "C003",
                Decimal("8000.00"),
                Decimal("1500.00"),
                Decimal("6500.00"),
                Decimal("0.00"),
                Decimal("8000.00"),
            ),
        ],
        "fact_transaction": [
            (
                "T001",
                date(2025, 6, 29),
                "C001",
                "P001",
                "buy",
                Decimal("100.00"),
                Decimal("1.00"),
                Decimal("1.00"),
                "success",
                "app",
            ),
            (
                "T002",
                date(2025, 6, 30),
                "C001",
                "P002",
                "sell",
                Decimal("200.00"),
                Decimal("2.00"),
                Decimal("2.00"),
                "success",
                "branch",
            ),
            (
                "T003",
                date(2025, 6, 20),
                "C002",
                "P001",
                "buy",
                Decimal("50.00"),
                Decimal("1.00"),
                Decimal("0.50"),
                "success",
                "app",
            ),
            (
                "T004",
                date(2025, 5, 1),
                "C003",
                "P002",
                "subscribe",
                Decimal("300.00"),
                Decimal("3.00"),
                Decimal("1.50"),
                "success",
                "app",
            ),
            (
                "T005",
                date(2025, 3, 1),
                "C003",
                "P002",
                "buy",
                Decimal("400.00"),
                Decimal("4.00"),
                Decimal("2.00"),
                "success",
                "app",
            ),
            (
                "T006",
                date(2025, 6, 1),
                "C004",
                "P003",
                "buy",
                Decimal("999.00"),
                Decimal("9.00"),
                Decimal("9.00"),
                "failed",
                "app",
            ),
            (
                "T007",
                date(2025, 6, 10),
                "C005",
                "P001",
                "buy",
                Decimal("25.00"),
                Decimal("1.00"),
                Decimal("0.25"),
                "cancelled",
                "app",
            ),
        ],
        "fact_cash_flow": [
            ("F001", date(2025, 6, 1), "C001", "in", Decimal("1000.00"), "bank", "success"),
            ("F002", date(2025, 6, 2), "C001", "out", Decimal("-100.00"), "app", "success"),
            ("F003", date(2025, 6, 3), "C003", "in", Decimal("500.00"), "bank", "success"),
        ],
    }


def build_public_fixture(path: Path, seed: int = 42) -> dict:
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite fixture: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(render_ddl())
        rows = _rows()
        # Seed variation stays out of the independently hand-calculated smoke answers.
        shift = Decimal(Random(seed).randrange(1000))
        asset = list(rows["fact_asset_snapshot"][0])
        for i in (2, 3, 6):
            asset[i] += shift
        rows["fact_asset_snapshot"][0] = tuple(asset)
        for table, values in rows.items():
            columns = load_catalog().table(table).columns
            placeholders = ", ".join(["?"] * len(columns))
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', values)
        counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in rows
        }
        content_hashes = {
            table: digest(
                sorted(conn.execute(f'SELECT * FROM "{table}"').fetchall(), key=json_text)
            )
            for table in rows
        }
        manifest = {
            "artifact_kind": "public_fixture_not_tiny",
            "generator_version": "fixture-0.1",
            "snapshot_version": "fixture-v1",
            "schema_version": "0.1",
            "seed": seed,
            "row_counts": counts,
            "config_hash": digest({"seed": seed, "anchor_date": "2025-06-30"}),
            "catalog_hash": digest(load_catalog().model_dump(mode="json")),
            "content_hashes": content_hashes,
            "environment": {name: version(name) for name in ("duckdb", "pydantic")},
        }
        manifest = FixtureManifest.model_validate(manifest).model_dump(mode="json")
        conn.execute("COMMIT")
        conn.execute("CHECKPOINT")
        return manifest
    finally:
        conn.close()
