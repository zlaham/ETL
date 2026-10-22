"""Deterministic e-commerce orders for the extraction demonstration.

The same seed always produces the same 500 orders, including the same
dirty values. Bronze is supposed to keep that dirt for a later Silver session.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SEED = 42
ORDER_COUNT = 500
ORDER_ID_START = 1001
ANCHOR = datetime(2026, 7, 1, tzinfo=timezone.utc)
TIED_STAMP = "2026-09-15T12:00:00Z"
CANONICAL_STATUSES = ("pending", "paid", "shipped", "completed", "cancelled")


def to_iso(value: datetime) -> str:
    """Format a timezone-aware instant as a sortable UTC timestamp."""
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def generate_orders(count: int = ORDER_COUNT, seed: int = SEED) -> list[dict[str, Any]]:
    """Build a fixed order population. Imperfections are intentional."""
    if count < 30:
        raise ValueError("count must be at least 30 so the demo rules have room to apply")
    rng = random.Random(seed)
    orders: list[dict[str, Any]] = []
    for offset in range(count):
        created = ANCHOR + timedelta(minutes=rng.randint(0, 60 * 24 * 90))
        updated = created + timedelta(minutes=rng.randint(0, 60 * 24 * 10))
        quantity = rng.choices([1, 2, 3, 4, 5, 6], weights=[40, 25, 15, 10, 7, 3], k=1)[0]
        unit_price = round(rng.uniform(4.5, 240.0), 2)
        orders.append(
            {
                "order_id": ORDER_ID_START + offset,
                "customer_id": 5000 + rng.randint(1, 180),
                "product_id": 7000 + rng.randint(1, 80),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": round(quantity * unit_price, 2),
                "currency": "USD",
                "status": rng.choices(
                    list(CANONICAL_STATUSES),
                    weights=[8, 22, 18, 42, 10],
                    k=1,
                )[0],
                "created_at": to_iso(created),
                "updated_at": to_iso(updated),
            }
        )
    _apply_imperfections(orders)
    return orders


def generate_additional_orders(
    *,
    start_id: int,
    count: int,
    at: datetime,
    seed: int = 99,
) -> list[dict[str, Any]]:
    """Create a small batch of new orders at an explicit demo clock."""
    rng = random.Random(seed)
    orders: list[dict[str, Any]] = []
    for offset in range(count):
        quantity = rng.choice([1, 2, 3])
        unit_price = round(rng.uniform(10, 80), 2)
        stamp = to_iso(at + timedelta(seconds=offset))
        orders.append(
            {
                "order_id": start_id + offset,
                "customer_id": 5000 + rng.randint(1, 180),
                "product_id": 7000 + rng.randint(1, 80),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": round(quantity * unit_price, 2),
                "currency": "usd" if offset == 0 else "USD",
                "status": "paid",
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
    return orders


def imperfection_report(orders: list[dict[str, Any]]) -> dict[str, int]:
    """Count the source defects Silver will have to confront later."""
    mismatched = 0
    for order in orders:
        expected = round(float(order["quantity"]) * float(order["unit_price"]), 2)
        if round(float(order["total_amount"]), 2) != expected:
            mismatched += 1
    return {
        "orders": len(orders),
        "null_customer_id": sum(order["customer_id"] is None for order in orders),
        "null_product_id": sum(order["product_id"] is None for order in orders),
        "null_currency": sum(order["currency"] is None for order in orders),
        "noncanonical_currency": sum(order.get("currency") != "USD" for order in orders),
        "noncanonical_status": sum(order["status"] not in CANONICAL_STATUSES for order in orders),
        "amount_mismatch": mismatched,
        "updated_before_created": sum(order["updated_at"] < order["created_at"] for order in orders),
        "optional_channel_present": sum("channel" in order for order in orders),
        "tied_updated_at_pairs": _tied_pairs(orders),
    }


def example_orders(orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return one dirty record and one clean record for the live walkthrough."""
    clean = next(order for order in orders if _is_clean(order))
    return {"messy": orders[0], "clean": clean}


def save_orders(orders: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(orders, indent=2), encoding="utf-8")


def _apply_imperfections(orders: list[dict[str, Any]]) -> None:
    """Leave realistic source defects in place. Do not repair them."""
    for index, order in enumerate(orders):
        if index % 37 == 0:
            order["customer_id"] = None
        if index % 41 == 0:
            order["product_id"] = None

        if index % 23 == 0:
            order["currency"] = None
        elif index % 23 == 1:
            order["currency"] = "usd"
        elif index % 23 == 2:
            order["currency"] = "Usd"
        elif index % 23 == 3:
            order["currency"] = "US$"
        elif index % 31 == 0:
            order["currency"] = "EUR"

        status = str(order["status"])
        if index % 19 == 0:
            order["status"] = status.upper()
        elif index % 19 == 1:
            order["status"] = status.title()
        elif index % 19 == 2 and status == "cancelled":
            order["status"] = "Canceled"

        if index % 29 == 0:
            order["total_amount"] = round(float(order["total_amount"]) + 1.11, 2)

        if index % 53 == 0:
            created = datetime.strptime(str(order["created_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            order["updated_at"] = to_iso(created - timedelta(hours=5))

        if index % 11 == 0:
            order["channel"] = ("web", "WEB", "mobile", "Mobile", "store")[index % 5]

    # Two different orders share one updated_at so the cursor needs a tie-breaker.
    orders[20]["created_at"] = "2026-09-01T12:00:00Z"
    orders[21]["created_at"] = "2026-09-02T12:00:00Z"
    orders[20]["updated_at"] = TIED_STAMP
    orders[21]["updated_at"] = TIED_STAMP


def _is_clean(order: dict[str, Any]) -> bool:
    expected = round(float(order["quantity"]) * float(order["unit_price"]), 2)
    return (
        order["customer_id"] is not None
        and order["product_id"] is not None
        and order["currency"] == "USD"
        and order["status"] in CANONICAL_STATUSES
        and order["updated_at"] >= order["created_at"]
        and "channel" not in order
        and round(float(order["total_amount"]), 2) == expected
    )


def _tied_pairs(orders: list[dict[str, Any]]) -> int:
    seen: dict[str, int] = {}
    for order in orders:
        seen[order["updated_at"]] = seen.get(order["updated_at"], 0) + 1
    return sum(1 for count in seen.values() if count > 1)


if __name__ == "__main__":
    population = generate_orders()
    print(json.dumps(imperfection_report(population), indent=2))
