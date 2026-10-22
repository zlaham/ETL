"""Gold publish: durable keys, attribute history, and marts that reconcile."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

from src.gold.bronze_silver import derive_silver
from src.gold.contract import GROSS_SALES, NET_SALES
from src.gold.silver import (
    choose_silver_origin,
    fallback_frames,
    frame_to_records,
    resolve_silver,
    training_root,
)
from src.gold.warehouse import GoldWarehouse, split_sql

ROOT = training_root()
SQL_DIR = ROOT / "sql" / "session_04"


def test_checked_in_silver_matches_session_3_bronze() -> None:
    derived = derive_silver(ROOT)
    loaded, origin = resolve_silver(ROOT)
    assert origin == "checked_in_silver"
    assert frame_to_records(derived["sales"]) == frame_to_records(loaded["sales"])
    assert frame_to_records(derived["customers"]) == frame_to_records(loaded["customers"])
    assert frame_to_records(derived["products"]) == frame_to_records(loaded["products"])
    assert sum(Decimal(row["gross_amount"]) for row in frame_to_records(loaded["sales"])) == GROSS_SALES
    names = {
        row["customer_id"]: row["customer_name"]
        for row in frame_to_records(loaded["customers"])
        if row["customer_name"] == "John Smith"
    }
    assert names == {"C100": "John Smith", "C107": "John Smith"}


def test_fallback_matches_the_bronze_contract() -> None:
    derived = derive_silver(ROOT)
    fallback = fallback_frames()
    assert frame_to_records(derived["sales"]) == frame_to_records(fallback["sales"])
    assert frame_to_records(derived["customers"]) == frame_to_records(fallback["customers"])
    assert frame_to_records(derived["products"]) == frame_to_records(fallback["products"])


def test_missing_files_rebuild_from_bronze(tmp_path: Path) -> None:
    source = ROOT / "data" / "session_03"
    shutil.copytree(source, tmp_path / "data" / "session_03")
    assert choose_silver_origin(tmp_path) == "session_03_bronze"
    loaded, origin = resolve_silver(tmp_path)
    assert origin == "session_03_bronze"
    assert frame_to_records(loaded["sales"]) == frame_to_records(derive_silver(ROOT)["sales"])


def test_missing_bronze_uses_the_embedded_contract(tmp_path: Path) -> None:
    assert choose_silver_origin(tmp_path) == "embedded_fallback"
    warehouse = GoldWarehouse(tmp_path, tmp_path / "gold.duckdb")
    try:
        summary = warehouse.build(reset_registry=True)
    finally:
        warehouse.close()
    assert summary["silver_origin"] == "embedded_fallback"
    assert summary["gross_sales"] == GROSS_SALES
    assert summary["net_sales"] == NET_SALES


def test_publish_is_idempotent_and_keeps_keys(tmp_path: Path) -> None:
    warehouse = GoldWarehouse(ROOT, tmp_path / "gold.duckdb")
    try:
        first = warehouse.build(reset_registry=True)
        signature = warehouse.signature()
        second = warehouse.build(reset_registry=False)
        assert second["gross_sales"] == first["gross_sales"] == GROSS_SALES
        assert second["net_sales"] == NET_SALES
        assert warehouse.signature() == signature
        assert second["registry_rows"] == first["registry_rows"] == 21
    finally:
        warehouse.close()


def test_rejected_return_is_held_and_does_not_change_the_fact(tmp_path: Path) -> None:
    warehouse = GoldWarehouse(ROOT, tmp_path / "gold.duckdb")
    try:
        warehouse.build(reset_registry=True)
        warehouse.con.execute(
            """
            INSERT INTO return_events
            VALUES ('R-BAD', 'OL-1005-1', 9, 112.50, DATE '2026-10-19', 'overstated')
            """
        )
        warehouse.execute_sql("040_facts.sql")
        warehouse.execute_sql("050_marts.sql")
        held = warehouse.con.execute(
            """
            SELECT COUNT(*)
            FROM gold_suspense
            WHERE reason = 'return_quantity_invalid' AND order_line_id = 'OL-1005-1'
            """
        ).fetchone()[0]
        posted = warehouse.con.execute("SELECT COUNT(*) FROM fct_returns").fetchone()[0]
        gross = warehouse.con.execute("SELECT SUM(gross_amount) FROM fct_sales_order_lines").fetchone()[0]
        assert held == 1
        assert posted == 1
        assert Decimal(str(gross)) == GROSS_SALES
    finally:
        warehouse.close()


def test_calendar_contains_days_with_no_sales(tmp_path: Path) -> None:
    warehouse = GoldWarehouse(ROOT, tmp_path / "gold.duckdb")
    try:
        warehouse.build(reset_registry=True)
        quiet = warehouse.con.execute(
            """
            SELECT COUNT(*)
            FROM dim_date
            WHERE full_date = DATE '2026-10-01'
              AND full_date NOT IN (
                  SELECT order_date FROM mart_sales_by_day_category
              )
            """
        ).fetchone()[0]
        weekend = warehouse.con.execute(
            """
            SELECT day_of_week, is_weekend
            FROM dim_date
            WHERE full_date = DATE '2026-10-18'
            """
        ).fetchone()
        assert quiet == 1
        assert weekend[0] == "Sunday"
        assert weekend[1] is True
    finally:
        warehouse.close()


def test_gold_sql_does_not_read_the_clock_or_the_network() -> None:
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in SQL_DIR.glob("*.sql"))
    assert "current_timestamp" not in text
    assert "current_date" not in text
    assert "now()" not in text
    python = "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "src" / "gold").glob("*.py"))
    assert "httpx" not in python
    assert "urllib" not in python
    assert "socket" not in python
    statements = split_sql((SQL_DIR / "000_macros.sql").read_text(encoding="utf-8"))
    assert len(statements) == 2
