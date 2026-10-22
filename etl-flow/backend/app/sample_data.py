"""Operational orders for the pipeline demo.

The planted rows are the cases the UI and the tests walk through:

- 1001 is clean
- 1002 has a padded status and a lowercase currency
- 1003 states a total that is not quantity × price
- 1004 is missing a customer
- 1005 is missing a product and a sku
- 1006 has quantity 0
- 1007 has a negative price
- 1008 is missing a currency
- 1009 has a status outside the contract
- 1010 is pending and stays out of the fact
- 1011 is cancelled and stays out of the fact
- 1012 needs status and currency normalized
- 1013 was updated before it was created
- 1014 is priced in EUR
- 1015 uses the spelling Canceled

The generated tail is deterministic for seed 42 and is already clean enough
to pass the contract. Some of those rows are pending or cancelled on purpose.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

SEED = 42

CATALOG: tuple[tuple[int, str, float], ...] = (
    (7001, "Field notebook", 18.0),
    (7002, "Cedar pencil", 4.5),
    (7003, "Ink bottle", 22.0),
    (7004, "Linen tote", 36.0),
    (7005, "Desk lamp", 84.0),
    (7006, "Wool blanket", 64.0),
    (7007, "Ceramic cup", 16.0),
    (7008, "Brass clip", 9.0),
)


def raw_orders() -> list[dict[str, Any]]:
    """Return a fresh copy of the operational list."""
    return [_order(**row) for row in _planted()] + _generated()


def _planted() -> list[dict[str, Any]]:
    return [
        dict(
            order_id=1001,
            customer_id=5101,
            product_id=7001,
            sku="Field notebook",
            quantity=2,
            unit_price=18.0,
            status="paid",
            created_at="2026-07-02T15:04:00Z",
            updated_at="2026-07-02T18:11:00Z",
        ),
        dict(
            order_id=1002,
            customer_id=5102,
            product_id=7005,
            sku="Desk lamp",
            quantity=1,
            unit_price=84.0,
            currency="usd",
            status=" Paid ",
            channel="ios",
            created_at="2026-07-03T11:00:00Z",
            updated_at="2026-07-03T12:30:00Z",
        ),
        dict(
            order_id=1003,
            customer_id=5103,
            product_id=7004,
            sku="Linen tote",
            quantity=2,
            unit_price=36.0,
            total_amount=73.11,
            status="completed",
            channel="store",
            created_at="2026-07-05T09:15:00Z",
            updated_at="2026-07-06T09:15:00Z",
        ),
        dict(
            order_id=1004,
            customer_id=None,
            product_id=7002,
            sku="Cedar pencil",
            quantity=1,
            unit_price=4.5,
            status="paid",
            created_at="2026-07-06T08:00:00Z",
            updated_at="2026-07-06T09:00:00Z",
        ),
        dict(
            order_id=1005,
            customer_id=5105,
            product_id=None,
            sku=None,
            quantity=1,
            unit_price=22.0,
            status="paid",
            created_at="2026-07-06T10:00:00Z",
            updated_at="2026-07-06T11:00:00Z",
        ),
        dict(
            order_id=1006,
            customer_id=5106,
            product_id=7003,
            sku="Ink bottle",
            quantity=0,
            unit_price=22.0,
            total_amount=0.0,
            status="paid",
            created_at="2026-07-07T10:00:00Z",
            updated_at="2026-07-07T12:00:00Z",
        ),
        dict(
            order_id=1007,
            customer_id=5107,
            product_id=7008,
            sku="Brass clip",
            quantity=1,
            unit_price=-3.5,
            total_amount=-3.5,
            status="paid",
            created_at="2026-07-08T10:00:00Z",
            updated_at="2026-07-08T12:00:00Z",
        ),
        dict(
            order_id=1008,
            customer_id=5108,
            product_id=7007,
            sku="Ceramic cup",
            quantity=1,
            unit_price=16.0,
            currency=None,
            status="shipped",
            created_at="2026-07-09T10:00:00Z",
            updated_at="2026-07-09T12:00:00Z",
        ),
        dict(
            order_id=1009,
            customer_id=5109,
            product_id=7006,
            sku="Wool blanket",
            quantity=1,
            unit_price=64.0,
            status="refunded",
            created_at="2026-07-10T10:00:00Z",
            updated_at="2026-07-10T12:00:00Z",
        ),
        dict(
            order_id=1010,
            customer_id=5110,
            product_id=7001,
            sku="Field notebook",
            quantity=1,
            unit_price=18.0,
            status="pending",
            created_at="2026-07-11T10:00:00Z",
            updated_at="2026-07-11T12:00:00Z",
        ),
        dict(
            order_id=1011,
            customer_id=5111,
            product_id=7002,
            sku="Cedar pencil",
            quantity=3,
            unit_price=4.5,
            status="cancelled",
            created_at="2026-07-12T10:00:00Z",
            updated_at="2026-07-12T12:00:00Z",
        ),
        dict(
            order_id=1012,
            customer_id=5112,
            product_id=7006,
            sku="Wool blanket",
            quantity=1,
            unit_price=64.0,
            currency="Usd",
            status="Shipped",
            created_at="2026-07-13T10:00:00Z",
            updated_at="2026-07-14T10:00:00Z",
        ),
        dict(
            order_id=1013,
            customer_id=5113,
            product_id=7007,
            sku="Ceramic cup",
            quantity=2,
            unit_price=16.0,
            status="completed",
            channel="WEB",
            created_at="2026-08-01T12:00:00Z",
            updated_at="2026-08-01T07:00:00Z",
        ),
        dict(
            order_id=1014,
            customer_id=5114,
            product_id=7008,
            sku="Brass clip",
            quantity=2,
            unit_price=9.0,
            currency="EUR",
            status="paid",
            created_at="2026-08-02T10:00:00Z",
            updated_at="2026-08-02T12:00:00Z",
        ),
        dict(
            order_id=1015,
            customer_id=5115,
            product_id=7003,
            sku="Ink bottle",
            quantity=1,
            unit_price=22.0,
            status="Canceled",
            created_at="2026-08-03T10:00:00Z",
            updated_at="2026-08-03T12:00:00Z",
        ),
    ]


def _generated(start_id: int = 1016, count: int = 20) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    statuses = (
        "completed",
        "paid",
        "shipped",
        "completed",
        "pending",
        "paid",
        "cancelled",
        "shipped",
    )
    channels = (None, "web", "ios", None, "store")
    anchor = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    for offset in range(count):
        product_id, sku, price = CATALOG[offset % len(CATALOG)]
        quantity = 1 + (offset % 3)
        created = anchor + timedelta(days=offset, hours=offset % 5, minutes=rng.randint(0, 40))
        updated = created + timedelta(hours=4 + (offset % 6))
        rows.append(
            _order(
                order_id=start_id + offset,
                customer_id=5301 + (offset % 12),
                product_id=product_id,
                sku=sku,
                quantity=quantity,
                unit_price=price,
                currency="USD",
                status=statuses[offset % len(statuses)],
                channel=channels[offset % len(channels)],
                created_at=_iso(created),
                updated_at=_iso(updated),
            )
        )
    return rows


def _order(
    order_id: int,
    *,
    customer_id: int | None = 5200,
    product_id: int | None = 7001,
    sku: str | None = "Field notebook",
    quantity: int = 1,
    unit_price: float = 18.0,
    total_amount: float | None = None,
    currency: str | None = "USD",
    status: str | None = "paid",
    channel: str | None = None,
    created_at: str = "2026-07-04T10:00:00Z",
    updated_at: str = "2026-07-04T12:00:00Z",
) -> dict[str, Any]:
    if total_amount is None:
        total_amount = round(quantity * unit_price, 2)
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "product_id": product_id,
        "sku": sku,
        "quantity": quantity,
        "unit_price": unit_price,
        "total_amount": total_amount,
        "currency": currency,
        "status": status,
        "channel": channel,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
