"""Session 1 ingestion model: history, ETL loss, and a raw landing."""

from src.architecture.preview import (
    ChangeLog,
    OperationalTable,
    etl_load,
    ingest,
    ingest_batch,
    landing_summary,
    revenue_as_app_team,
    revenue_as_finance_export,
)
from src.source.generate_orders import generate_orders


def test_operational_table_forgets_the_previous_status() -> None:
    table = OperationalTable(generate_orders())
    log = ChangeLog()
    before = table.get(1100)
    log.observe(before)
    table.update(1100, status="refunded", updated_at="2026-10-15T09:00:00Z")
    log.observe(table.get(1100))

    assert table.get(1100)["status"] == "refunded"
    assert [version["status"] for version in log.versions(1100)] == [before["status"], "refunded"]


def test_two_consumers_disagree_on_revenue() -> None:
    orders = generate_orders()
    assert revenue_as_app_team(orders) != revenue_as_finance_export(orders)


def test_etl_discards_the_source_and_ingestion_keeps_it() -> None:
    order = generate_orders()[0]
    loaded = etl_load(order)
    landed = ingest(order, run_id="session1", ingested_at="2026-10-15T09:00:00Z")

    assert "payload" not in loaded
    assert loaded["status"] == "completed"
    assert loaded["total_amount"] != order["total_amount"]
    assert "channel" not in loaded
    assert landed["payload"] == order
    assert landed["payload"]["status"] == "COMPLETED"
    assert landed["payload"]["currency"] is None
    assert landed["run_id"] == "session1"


def test_a_second_ingest_appends_and_does_not_dedupe() -> None:
    orders = generate_orders()
    first = ingest_batch(orders, run_id="run_a", ingested_at="2026-10-15T09:00:00Z")
    second = ingest_batch(orders, run_id="run_b", ingested_at="2026-10-15T09:05:00Z")
    summary = landing_summary(first + second)

    assert summary["lines"] == 1000
    assert summary["distinct_orders"] == 500
    assert summary["duplicate_lines"] == 500
    assert {row["run_id"] for row in first + second} == {"run_a", "run_b"}
