"""Source rows for the lesson. The cutoff is the whole change rule.

Names and email addresses are the PII. Segment, plan, status, region, and
currency are the customer attributes that Silver and Gold are allowed to keep.
"""

from __future__ import annotations

from datetime import datetime, timezone

CUTOFF = datetime(2026, 7, 4, tzinfo=timezone.utc)
CUTOFF_TEXT = "2026-07-04T00:00:00Z"
PAGE_LIMIT = 10

CUSTOMERS: tuple[dict, ...] = (
    {
        "email_address": "ada@field.test",
        "full_name": "Ada Okonkwo",
        "country": "US",
        "region": "North America",
        "customer_segment": "Retail",
        "account_plan": "Field",
        "account_status": "active",
        "preferred_currency": "USD",
        "updated_at": "2026-07-01T10:00:00Z",
    },
    {
        "email_address": "hana.sato@field.test",
        "full_name": "Hana Sato",
        "country": "JP",
        "region": "Asia Pacific",
        "customer_segment": "Retail",
        "account_plan": "Field",
        "account_status": "active",
        "preferred_currency": "JPY",
        "updated_at": "2026-07-02T08:00:00Z",
    },
    {
        "email_address": "ben@field.test",
        "full_name": "Ben Cho",
        "country": "US",
        "region": "North America",
        "customer_segment": "Education",
        "account_plan": "Workshop",
        "account_status": "active",
        "preferred_currency": "USD",
        "updated_at": "2026-07-02T10:00:00Z",
    },
    {
        "email_address": "farah.hassan@field.test",
        "full_name": "Farah Hassan",
        "country": "GB",
        "region": "Europe",
        "customer_segment": "Education",
        "account_plan": "Atelier",
        "account_status": "active",
        "preferred_currency": "GBP",
        "updated_at": "2026-07-03T15:00:00Z",
    },
    {
        "email_address": "cio@field.test",
        "full_name": "Cio Berger",
        "country": "DE",
        "region": "Europe",
        "customer_segment": "Studio",
        "account_plan": "Atelier",
        "account_status": "active",
        "preferred_currency": "EUR",
        "updated_at": "2026-07-05T10:00:00Z",
    },
    {
        "email_address": "elias.moreau@field.test",
        "full_name": "Elias Moreau",
        "country": "FR",
        "region": "Europe",
        "customer_segment": "Wholesale",
        "account_plan": "Workshop",
        "account_status": "active",
        "preferred_currency": "EUR",
        "updated_at": "2026-07-05T16:00:00Z",
    },
    {
        "email_address": "dia@field.test",
        "full_name": "Dia Nguyen",
        "country": "US",
        "region": "North America",
        "customer_segment": "Retail",
        "account_plan": "Field",
        "account_status": "trial",
        "preferred_currency": "USD",
        "updated_at": "2026-07-06T10:00:00Z",
    },
    {
        "email_address": "gio.rossi@field.test",
        "full_name": "Gio Rossi",
        "country": "IT",
        "region": "Europe",
        "customer_segment": "Studio",
        "account_plan": "Atelier",
        "account_status": "active",
        "preferred_currency": "EUR",
        "updated_at": "2026-07-06T18:00:00Z",
    },
)

PRODUCTS: tuple[dict, ...] = (
    {"product_id": "P7001", "sku": "Field notebook", "category": "Paper", "list_price": "18.00", "updated_at": "2026-07-01T09:00:00Z"},
    {"product_id": "P7002", "sku": "Cedar pencil", "category": "Writing", "list_price": "4.50", "updated_at": "2026-07-02T09:00:00Z"},
    {"product_id": "P7003", "sku": "Ink bottle", "category": "Writing", "list_price": "22.00", "updated_at": "2026-07-05T09:00:00Z"},
    {"product_id": "P7005", "sku": "Cotton apron", "category": "Carry", "list_price": "28.00", "updated_at": "2026-07-05T11:00:00Z"},
    {"product_id": "P7004", "sku": "Linen tote", "category": "Carry", "list_price": "36.00", "updated_at": "2026-07-06T09:00:00Z"},
    {"product_id": "P7006", "sku": "Walnut pen", "category": "Writing", "list_price": "14.00", "updated_at": "2026-07-06T11:00:00Z"},
)

ORDERS: tuple[dict, ...] = (
    {"order_id": "O1001", "email_address": "ada@field.test", "sku": "Field notebook", "status": "paid", "quantity": 1, "updated_at": "2026-07-01T12:00:00Z"},
    {"order_id": "O1008", "email_address": "hana.sato@field.test", "sku": "Cedar pencil", "status": "paid", "quantity": 3, "updated_at": "2026-07-02T12:00:00Z"},
    {"order_id": "O1002", "email_address": "ben@field.test", "sku": "Cedar pencil", "status": "paid", "quantity": 2, "updated_at": "2026-07-02T14:00:00Z"},
    {"order_id": "O1007", "email_address": "farah.hassan@field.test", "sku": "Field notebook", "status": "paid", "quantity": 1, "updated_at": "2026-07-03T16:00:00Z"},
    {"order_id": "O1003", "email_address": "cio@field.test", "sku": "Ink bottle", "status": "shipped", "quantity": 1, "updated_at": "2026-07-05T12:00:00Z"},
    {"order_id": "O1005", "email_address": "elias.moreau@field.test", "sku": "Cotton apron", "status": "shipped", "quantity": 1, "updated_at": "2026-07-05T18:00:00Z"},
    {"order_id": "O1004", "email_address": "dia@field.test", "sku": "Linen tote", "status": "completed", "quantity": 1, "updated_at": "2026-07-06T12:00:00Z"},
    {"order_id": "O1006", "email_address": "gio.rossi@field.test", "sku": "Walnut pen", "status": "paid", "quantity": 2, "updated_at": "2026-07-06T19:00:00Z"},
)

WATCH_KEYS: tuple[str, ...] = ("ada@field.test", "cio@field.test", "P7001", "P7003", "O1001", "O1003")
