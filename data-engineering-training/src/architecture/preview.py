"""Session 1 model of ingestion.

ETL loads a cleaned row and discards the source document.
ELT, at this layer, only lands the raw payload. Nothing here conforms or aggregates.
"""

from __future__ import annotations

import copy
from typing import Any


class OperationalTable:
    """Current-state store. An update replaces the row."""

    def __init__(self, orders: list[dict[str, Any]]) -> None:
        self._rows = {int(order["order_id"]): copy.deepcopy(order) for order in orders}

    def get(self, order_id: int) -> dict[str, Any]:
        return copy.deepcopy(self._rows[int(order_id)])

    def update(self, order_id: int, **changes: Any) -> dict[str, Any]:
        row = self._rows[int(order_id)]
        row.update(changes)
        return self.get(order_id)


class ChangeLog:
    """Append-only observations. A previous version stays addressable."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def observe(self, order: dict[str, Any]) -> None:
        self.events.append(copy.deepcopy(order))

    def versions(self, order_id: int) -> list[dict[str, Any]]:
        return [event for event in self.events if int(event["order_id"]) == int(order_id)]


def revenue_as_app_team(orders: list[dict[str, Any]]) -> float:
    """One consumer's private definition: any status that looks completed."""
    total = 0.0
    for order in orders:
        if "complete" in str(order["status"]).lower():
            total += float(order["total_amount"])
    return round(total, 2)


def revenue_as_finance_export(orders: list[dict[str, Any]]) -> float:
    """Another consumer's private definition: the literal status value `paid`."""
    total = 0.0
    for order in orders:
        if order["status"] == "paid":
            total += float(order["total_amount"])
    return round(total, 2)


def naive_source_total(orders: list[dict[str, Any]]) -> float:
    return round(sum(float(order["total_amount"]) for order in orders), 2)


def etl_load(order: dict[str, Any]) -> dict[str, Any]:
    """Transform first. The loaded row is all that remains."""
    currency = order.get("currency")
    return {
        "order_id": order["order_id"],
        "customer_id": order.get("customer_id"),
        "status": str(order.get("status") or "").strip().lower(),
        "currency": None if currency is None else str(currency).strip().upper(),
        "total_amount": round(float(order["quantity"]) * float(order["unit_price"]), 2),
        "order_date": str(order["created_at"])[:10],
    }


def ingest(
    order: dict[str, Any],
    *,
    run_id: str,
    ingested_at: str,
) -> dict[str, Any]:
    """Land one source document. The payload is not interpreted."""
    return {
        "source_system": "orders_api",
        "ingested_at": ingested_at,
        "run_id": run_id,
        "source_record_id": order["order_id"],
        "payload": copy.deepcopy(order),
    }


def ingest_batch(
    orders: list[dict[str, Any]],
    *,
    run_id: str,
    ingested_at: str,
) -> list[dict[str, Any]]:
    return [ingest(order, run_id=run_id, ingested_at=ingested_at) for order in orders]


def landing_summary(envelopes: list[dict[str, Any]]) -> dict[str, int]:
    identifiers = [envelope["source_record_id"] for envelope in envelopes]
    return {
        "lines": len(envelopes),
        "distinct_orders": len(set(identifiers)),
        "duplicate_lines": len(identifiers) - len(set(identifiers)),
    }
