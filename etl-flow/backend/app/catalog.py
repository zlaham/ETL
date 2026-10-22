"""Catalog HTTP API. Omit the cursor to read every product. Pass it to read changes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from app.db import SQL_ROOT, DatabaseUnavailable, connect, one_statement
from app.lesson_data import CUTOFF, PAGE_LIMIT

CATALOG_SQL = SQL_ROOT / "extract" / "catalog_product.sql"
CATALOG_BASE = "http://127.0.0.1:8020"
_MONEY = re.compile(r"^\d+\.\d{2}$")


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise DatabaseUnavailable("Use a UTC timestamp like 2026-07-04T00:00:00Z") from exc
    return parsed.replace(tzinfo=timezone.utc)


def fetch_catalog_page(entire: bool, cursor_at: datetime, cursor_key: str, limit: int) -> list[dict]:
    statement = one_statement(CATALOG_SQL)
    with connect() as conn:
        rows = conn.execute(statement, (entire, cursor_at, cursor_key, limit)).fetchall()
    return [_record(row) for row in rows]


def _record(row: dict) -> dict:
    price = row["list_price"]
    rendered = f"{price:.2f}" if isinstance(price, Decimal) else str(price)
    if _MONEY.fullmatch(rendered) is None:
        raise DatabaseUnavailable(f"list_price for {row['product_id']} must have two decimals")
    return {
        "product_id": row["product_id"],
        "sku": row["sku"],
        "category": row["category"],
        "list_price": rendered,
        "updated_at": iso(row["updated_at"]),
    }


def _url(entire: bool, cursor_at: datetime, cursor_key: str) -> str:
    params = {"limit": str(PAGE_LIMIT)}
    if not entire:
        params["cursor_updated_at"] = iso(cursor_at)
        params["cursor_key"] = cursor_key
    return f"{CATALOG_BASE}/api/sources/catalog?{urlencode(params)}"


async def query_catalog_pages(entire: bool, cursor_at: datetime, cursor_key: str) -> list[dict]:
    records = fetch_catalog_page(entire, cursor_at, cursor_key, PAGE_LIMIT)
    return [
        {
            "method": "GET",
            "url": _url(entire, cursor_at, cursor_key),
            "status_code": 200,
            "records": records,
        }
    ]


async def http_catalog_pages(entire: bool, cursor_at: datetime, cursor_key: str) -> list[dict]:
    params: dict[str, str | int] = {"limit": PAGE_LIMIT}
    if not entire:
        params["cursor_updated_at"] = iso(cursor_at)
        params["cursor_key"] = cursor_key
    try:
        async with httpx.AsyncClient(base_url=CATALOG_BASE, timeout=10) as client:
            response = await client.get("/api/sources/catalog", params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DatabaseUnavailable(f"catalog API request failed: {exc.__class__.__name__}") from exc
    return [
        {
            "method": "GET",
            "url": str(response.request.url),
            "status_code": response.status_code,
            "records": response.json()["records"],
        }
    ]


catalog_pages = http_catalog_pages


def browse_cursor() -> tuple[datetime, str]:
    return CUTOFF, ""
