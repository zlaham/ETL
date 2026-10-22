"""Extraction behavior the classroom demo depends on."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ingestion.checkpoints import CheckpointStore, Cursor, WatermarkStore
from src.ingestion.incremental_extractor import IncrementalExtractor
from src.ingestion.naive_extractor import NaiveExtractor
from src.ingestion.paginated_extractor import PaginatedExtractor
from src.ingestion.reliable_extractor import CrashPlan, ReliableExtractor
from src.ingestion.retry_policy import RetryPolicy
from src.ingestion import ExtractionError, SimulatedProcessCrash
from src.source.generate_orders import (
    ORDER_COUNT,
    ORDER_ID_START,
    generate_additional_orders,
    generate_orders,
    imperfection_report,
)
from src.source.mock_orders_api import OrdersApi
from src.storage.bronze_writer import BronzeWriter

POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.001, max_delay_seconds=0.01)
CHANGE_AT = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def population() -> list[dict]:
    return generate_orders()


@pytest.fixture
def api(population: list[dict]) -> OrdersApi:
    return OrdersApi.from_orders(population)


def test_orders_are_deterministic_and_dirty(population: list[dict]) -> None:
    assert generate_orders() == population
    assert [order["order_id"] for order in population] == list(
        range(ORDER_ID_START, ORDER_ID_START + ORDER_COUNT)
    )
    report = imperfection_report(population)
    assert report["orders"] == 500
    assert report["null_customer_id"] > 0
    assert report["null_product_id"] > 0
    assert report["null_currency"] > 0
    assert report["noncanonical_currency"] > report["null_currency"]
    assert report["noncanonical_status"] > 0
    assert report["amount_mismatch"] > 0
    assert report["updated_before_created"] > 0
    assert report["optional_channel_present"] > 0
    assert report["tied_updated_at_pairs"] >= 1
    assert max(order["updated_at"] for order in population) < "2026-10-15T09:00:00Z"


def test_naive_fetch_succeeds_and_is_incomplete(api: OrdersApi) -> None:
    with api.client() as client:
        fetched = NaiveExtractor(client, page_size=50).extract()
    assert fetched.status_code == 200
    assert fetched.total == 500
    assert fetched.has_more is True
    assert len(fetched.records) == 50
    assert fetched.missing == 450


def test_paginated_extract_writes_raw_bronze(api: OrdersApi, population: list[dict], tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    with api.client() as client:
        result = PaginatedExtractor(client, writer, page_size=50).extract("full")
    envelopes = writer.read_envelopes("full")
    assert result.status == "success"
    assert result.records_written == 500
    assert result.pages_fetched == 10
    assert len(envelopes) == 500
    assert [item["source_record_id"] for item in envelopes] == [order["order_id"] for order in population]
    messy = envelopes[0]
    assert list(messy) == [
        "source_system",
        "ingested_at",
        "run_id",
        "source_record_id",
        "payload",
    ]
    assert messy["payload"] == population[0]
    assert messy["payload"]["customer_id"] is None
    assert messy["source_system"] == "orders_api"
    assert result.high_watermark is not None


def test_live_offset_pagination_skips_a_row_that_still_exists(api: OrdersApi, tmp_path) -> None:
    api.delete_after_request(1, 1050)
    writer = BronzeWriter(tmp_path / "bronze")
    with api.client() as client:
        result = PaginatedExtractor(
            client,
            writer,
            page_size=100,
            consistent_snapshot=False,
        ).extract("unsafe")
    found = {envelope["source_record_id"] for envelope in writer.read_envelopes("unsafe")}
    assert result.records_written == 499
    assert 1050 in found
    assert 1101 not in found
    assert api.order_count == 499


def test_snapshot_pagination_does_not_skip_under_the_same_delete(population, tmp_path) -> None:
    api = OrdersApi.from_orders(population)
    api.delete_after_request(1, 1050)
    writer = BronzeWriter(tmp_path / "bronze")
    with api.client() as client:
        result = PaginatedExtractor(client, writer, page_size=100).extract("snapshot")
    found = {envelope["source_record_id"] for envelope in writer.read_envelopes("snapshot")}
    assert result.records_written == 500
    assert found == {order["order_id"] for order in population}
    assert api.order_count == 499


def test_retry_recovers_http_500_and_429(api: OrdersApi, tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    store = CheckpointStore(tmp_path / "state")
    api.fail_request(500, page=2, times=1)
    with api.client() as client:
        failed = PaginatedExtractor(client, writer, page_size=50)
        with pytest.raises(ExtractionError) as error:
            failed.extract("partial")
        assert error.value.result is not None
        assert error.value.result.records_written == 50
        assert "500" in str(error.value)

        api.reset_session()
        api.fail_request(500, page=2, times=1)
        recovered = ReliableExtractor(client, writer, store, POLICY, page_size=50)
        result = recovered.extract("retried_500")
        assert result.status == "success"
        assert result.records_written == 500
        assert result.retries == 1
        assert [item["status_code"] for item in result.attempts if item["page"] == 2] == [500, 200]

        api.reset_session()
        api.fail_request(429, page=1, times=1, retry_after="0.01")
        limited = ReliableExtractor(client, writer, store, POLICY, page_size=50)
        limited_result = limited.extract("retried_429")
        assert limited_result.status == "success"
        assert limited_result.records_written == 500
        assert limited_result.attempts[0]["status_code"] == 429
        assert limited_result.attempts[0]["outcome"] == "retry"


def test_checkpoint_does_not_advance_when_bronze_write_fails(api: OrdersApi, tmp_path) -> None:
    class FailingWriter(BronzeWriter):
        def __init__(self, directory) -> None:
            super().__init__(directory)
            self.calls = 0

        def write_records(self, records, *, run_id, ingested_at=None):  # type: ignore[override]
            self.calls += 1
            if self.calls == 2:
                raise OSError("disk full")
            return super().write_records(records, run_id=run_id, ingested_at=ingested_at)

    writer = FailingWriter(tmp_path / "bronze")
    store = CheckpointStore(tmp_path / "state")
    with api.client() as client:
        extractor = ReliableExtractor(client, writer, store, POLICY, page_size=50)
        with pytest.raises(ExtractionError) as error:
            extractor.extract("disk")
    checkpoint = store.load("disk")
    assert checkpoint is not None
    assert checkpoint.last_completed_page == 1
    assert checkpoint.records_committed == 50
    assert checkpoint.status == "failed"
    assert error.value.result is not None
    assert error.value.result.records_committed == 50
    assert len(writer.read_envelopes("disk")) == 50


def test_crash_before_checkpoint_replays_one_page(api: OrdersApi, tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    store = CheckpointStore(tmp_path / "state")
    with api.client() as client:
        extractor = ReliableExtractor(client, writer, store, POLICY, page_size=50)
        with pytest.raises(SimulatedProcessCrash) as crashed:
            extractor.extract("crash", crash=CrashPlan(after_write_before_checkpoint_page=4))
        assert crashed.value.result is not None
        checkpoint = store.load("crash")
        assert checkpoint is not None
        assert checkpoint.status == "interrupted"
        assert checkpoint.last_completed_page == 3
        assert checkpoint.records_committed == 150
        partial = [item["source_record_id"] for item in writer.read_envelopes("crash")]
        assert partial == list(range(1001, 1201))

        resumed = extractor.extract("crash", resume=True)

    final = [item["source_record_id"] for item in writer.read_envelopes("crash")]
    assert resumed.status == "success"
    assert resumed.resumed_from_page == 4
    assert len(final) == 550
    assert set(final) == set(range(1001, 1501))
    assert sorted(order_id for order_id in set(final) if final.count(order_id) == 2) == list(
        range(1151, 1201)
    )
    completed = store.load("crash")
    assert completed is not None
    assert completed.status == "completed"
    assert completed.records_committed == 500


def test_resume_refuses_a_missing_snapshot(api: OrdersApi, tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    store = CheckpointStore(tmp_path / "state")
    with api.client() as client:
        extractor = ReliableExtractor(client, writer, store, POLICY, page_size=50)
        with pytest.raises(SimulatedProcessCrash):
            extractor.extract("crash", crash=CrashPlan(after_write_before_checkpoint_page=2))
        api.drop_snapshots()
        with pytest.raises(ExtractionError) as error:
            extractor.extract("crash", resume=True)
    assert "Unknown snapshot_id" in str(error.value)
    checkpoint = store.load("crash")
    assert checkpoint is not None
    assert checkpoint.last_completed_page == 1
    assert len(writer.read_envelopes("crash")) == 100


def test_incremental_cursor_keeps_timestamp_ties_and_ignores_backdates(tmp_path) -> None:
    stamp = "2026-09-15T12:00:00Z"
    orders = [
        _order(1, stamp),
        _order(2, stamp),
        _order(3, "2026-09-15T12:00:01Z"),
    ]
    api = OrdersApi.from_orders(orders)
    writer = BronzeWriter(tmp_path / "bronze")
    watermarks = WatermarkStore(tmp_path / "state")
    watermarks.save(Cursor(stamp, 1), run_id="seed")
    with api.client() as client:
        first = IncrementalExtractor(client, writer, watermarks, POLICY, page_size=1).extract("sync")
        second = IncrementalExtractor(client, writer, watermarks, POLICY, page_size=1).extract("again")
        api.update_order(1, status="refunded", updated_at="2026-08-01T00:00:00Z")
        missed = IncrementalExtractor(client, writer, watermarks, POLICY, page_size=10).extract("backdated")
        api.update_order(1, status="refunded", updated_at="2026-10-15T09:30:00Z")
        caught = IncrementalExtractor(client, writer, watermarks, POLICY, page_size=10).extract("forward")

    assert [item["source_record_id"] for item in writer.read_envelopes("sync")] == [2, 3]
    assert first.records_written == 2
    assert second.records_written == 0
    assert missed.records_written == 0
    assert [item["source_record_id"] for item in writer.read_envelopes("forward")] == [1]
    assert caught.records_written == 1
    assert api.get_order(1)["status"] == "refunded"


def test_full_then_incremental_separates_new_and_updated_rows(api: OrdersApi, tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    watermarks = WatermarkStore(tmp_path / "state")
    with api.client() as client:
        full = PaginatedExtractor(client, writer, page_size=50).extract("baseline")
        assert full.high_watermark is not None
        watermarks.save(Cursor(**full.high_watermark), run_id=full.run_id)
        for order_id in (1001, 1010, 1100, 1200, 1300):
            api.update_order(order_id, status="refunded", updated_at="2026-10-15T09:00:00Z")
        api.add_orders(generate_additional_orders(start_id=1501, count=8, at=CHANGE_AT))
        synced = IncrementalExtractor(client, writer, watermarks, POLICY, page_size=50).extract("delta")

    delta = writer.read_envelopes("delta")
    assert synced.records_written == 13
    assert api.order_count == 508
    found = {item["source_record_id"] for item in delta}
    assert found == {1001, 1010, 1100, 1200, 1300, *range(1501, 1509)}
    refunded = next(item for item in delta if item["source_record_id"] == 1001)
    assert refunded["payload"]["status"] == "refunded"
    assert refunded["payload"]["currency"] is None
    currencies = {item["payload"]["currency"] for item in delta}
    assert "usd" in currencies
    assert watermarks.load() == Cursor(**synced.high_watermark)  # type: ignore[arg-type]


def test_incremental_requires_a_watermark(api: OrdersApi, tmp_path) -> None:
    writer = BronzeWriter(tmp_path / "bronze")
    watermarks = WatermarkStore(tmp_path / "state")
    with api.client() as client:
        extractor = IncrementalExtractor(client, writer, watermarks, POLICY)
        with pytest.raises(ExtractionError, match="No watermark"):
            extractor.extract("too_soon")


def test_empty_incremental_page_is_http_200(api: OrdersApi) -> None:
    with api.client() as client:
        response = client.get(
            "/api/orders",
            params={"updated_after": "2099-01-01T00:00:00Z", "after_id": 0, "limit": 50},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["data"] == []
    assert body["has_more"] is False
    assert body["total_matching"] == 0


def _order(order_id: int, updated_at: str) -> dict:
    return {
        "order_id": order_id,
        "customer_id": 1,
        "product_id": 2,
        "quantity": 1,
        "unit_price": 10.0,
        "total_amount": 10.0,
        "currency": "USD",
        "status": "paid",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": updated_at,
    }
