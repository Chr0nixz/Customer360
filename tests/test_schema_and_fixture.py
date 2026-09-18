from datetime import date
from decimal import Decimal

import duckdb
import pytest

from customer360.synth.fixture import build_public_fixture
from customer360.synth.schema import render_ddl, render_literal


def test_exactly_nine_core_tables(repository, database):
    with duckdb.connect(str(database), read_only=True) as db:
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
    assert tables == {t.table_name for t in repository.catalog.tables}
    assert len(tables) == 9
    assert render_ddl().count("CREATE TABLE") == 9


def test_fixture_hash_reproducibility_and_seed_variation(tmp_path):
    a = build_public_fixture(tmp_path / "a.duckdb", 42)
    b = build_public_fixture(tmp_path / "b.duckdb", 42)
    c = build_public_fixture(tmp_path / "c.duckdb", 43)
    assert a == b
    assert a["content_hashes"] != c["content_hashes"]
    assert a["row_counts"]["dim_customer"] == 6


def test_fixture_does_not_overwrite(database):
    with pytest.raises(FileExistsError):
        build_public_fixture(database)


def test_hand_calculated_reference_values(database):
    # Independent of the semantic compiler, metric registry and evaluator.
    with duckdb.connect(str(database), read_only=True) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM dim_customer WHERE customer_level = 'VIP'").fetchone()[
                0
            ]
            == 3
        )
        count, amount = db.execute(
            "SELECT COUNT(*), SUM(amount) FROM fact_transaction "
            "WHERE transaction_id IN ('T001', 'T002', 'T003', 'T004')"
        ).fetchone()
        assert (count, amount) == (4, Decimal("650.00"))


def test_fixture_asset_identities(database):
    with duckdb.connect(str(database), read_only=True) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fact_asset_snapshot WHERE "
                "total_asset != cash_asset + investment_asset "
                "OR net_asset != total_asset - liability"
            ).fetchone()[0]
            == 0
        )


def test_foreign_key_and_grain_constraints(tmp_path):
    path = tmp_path / "constraints.duckdb"
    build_public_fixture(path)
    with duckdb.connect(str(path)) as db:
        with pytest.raises(duckdb.ConstraintException):
            db.execute(
                "INSERT INTO fact_asset_snapshot VALUES ('2025-06-30', 'unknown', 0, 0, 0, 0, 0)"
            )
        with pytest.raises(duckdb.ConstraintException):
            db.execute("INSERT INTO fact_holding SELECT * FROM fact_holding LIMIT 1")


def test_render_literal_covers_schema_kinds():
    assert render_literal(None) == "NULL"
    assert render_literal(True) == "TRUE"
    assert render_literal(False) == "FALSE"
    assert render_literal(7) == "7"
    assert render_literal(Decimal("12.30")) == "12.30"
    assert render_literal(date(2025, 6, 30)) == "DATE '2025-06-30'"
    assert render_literal("O'Brien") == "'O''Brien'"


def test_render_literal_rejects_unsupported_types():
    with pytest.raises(TypeError):
        render_literal(3.14)
    with pytest.raises(TypeError):
        render_literal(b"bytes")


def test_render_literal_roundtrip_through_duckdb():
    literal = render_literal("O'Brien")
    assert literal == "'O''Brien'"
    with duckdb.connect(":memory:") as db:
        assert db.execute(f"SELECT {literal}").fetchone()[0] == "O'Brien"
