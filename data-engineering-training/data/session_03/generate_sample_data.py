"""Write the fixed Session 3 Bronze extract and the offline LLM fixture.

The output is deterministic. Re-running this file rewrites the same bytes.
It does not call a model, an API, or the Session 2 generators.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRONZE = ROOT / "data" / "session_03" / "bronze"
FIXTURES = ROOT / "data" / "session_03" / "fixtures"


def envelope(seq: int, source_system: str, ingested_at: str, source_record_id: str, payload: dict) -> dict:
    return {
        "delivery_seq": seq,
        "source_system": source_system,
        "ingested_at": ingested_at,
        "run_id": f"{source_system}-2026-10-16",
        "source_record_id": source_record_id,
        "payload": payload,
    }


def order(
    seq: int,
    line_id: str,
    order_id: str,
    customer_id: str | None,
    product_id: str | None,
    quantity: str | None,
    unit_price: str | None,
    status: str,
    order_timestamp: str,
    source_updated_at: str,
    ingested_at: str,
    currency: str = "USD",
) -> dict:
    return envelope(
        seq,
        "order_management",
        ingested_at,
        line_id or f"missing-line-{seq}",
        {
            "order_id": order_id,
            "order_line_id": line_id,
            "customer_id": customer_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "order_status": status,
            "order_timestamp": order_timestamp,
            "source_updated_at": source_updated_at,
            "currency": currency,
        },
    )


def customer(
    seq: int,
    customer_id: str | None,
    name: str,
    country: str,
    segment: str,
    registered_at: str,
    source_updated_at: str,
    ingested_at: str,
) -> dict:
    return envelope(
        seq,
        "crm",
        ingested_at,
        customer_id or f"missing-customer-{seq}",
        {
            "customer_id": customer_id,
            "customer_name": name,
            "country_code": country,
            "customer_segment": segment,
            "registered_at": registered_at,
            "source_updated_at": source_updated_at,
        },
    )


def product(
    seq: int,
    product_id: str | None,
    sku: str,
    description: str | None,
    vendor: str,
    category: str | None,
    source_updated_at: str,
    ingested_at: str,
) -> dict:
    return envelope(
        seq,
        "product_catalog",
        ingested_at,
        product_id or f"missing-product-{seq}",
        {
            "product_id": product_id,
            "sku": sku,
            "product_description": description,
            "vendor_name": vendor,
            "category": category,
            "source_updated_at": source_updated_at,
        },
    )


def orders() -> list[dict]:
    """29 deliveries. Comments name the disposition the notebook should reach."""
    return [
        # Superseded. Arrives later than the correction, with the old price.
        order(1, "OL-1001-1", "ORD-1001", "C100", "P101", "1", "799.00", "completed",
              "2026-10-15T10:30:00Z", "2026-10-15T10:30:00Z", "2026-10-16T02:10:00Z"),
        # Authoritative correction. source_updated_at wins over ingested_at.
        order(2, "OL-1001-1", "ORD-1001", "C100", "P101", "1", "749.00", "Completed",
              "2026-10-15T10:30:00Z", "2026-10-15T14:05:00Z", "2026-10-16T01:05:00Z"),
        # Duplicate delivery of the correction.
        order(3, "OL-1001-1", "ORD-1001", "C100", "P101", "1", "749.00", "completed",
              "2026-10-15T10:30:00Z", "2026-10-15T14:05:00Z", "2026-10-16T01:07:00Z"),
        # Unambiguous day-first timestamp: 15 cannot be a month.
        order(4, "OL-1002-1", "ORD-1002", "C101", "P103", "1", "1199.00", "PAID",
              "15/10/2026 11:15", "2026-10-15T11:20:00Z", "2026-10-16T01:10:00Z"),
        order(5, "OL-1002-1", "ORD-1002", "C101", "P103", "1", "1199.00", "paid",
              "15/10/2026 11:15", "2026-10-15T11:20:00Z", "2026-10-16T01:12:00Z"),
        # Space-separated timestamp. Contract: no zone means UTC.
        order(6, "OL-1003-1", "ORD-1003", "C102", "P104", "2", "19.00", "completed",
              "2026-10-15 12:00:00", "2026-10-15 12:05:00", "2026-10-16T01:15:00Z"),
        order(7, "OL-1003-2", "ORD-1003", "C102", "P106", "1", "49.00", "completed",
              "2026-10-15 12:00:00", "2026-10-15T12:05:00Z", "2026-10-16T01:15:00Z"),
        order(8, "OL-1004-1", "ORD-1004", "C104", "P107", "1", "89.00", "paid",
              "2026-10-16T09:00:00", "2026-10-16T09:05:00Z", "2026-10-16T11:00:00Z"),
        order(9, "OL-1005-1", "ORD-1005", "C103", "P105", "3", "12.50", "completed",
              "2026-10-16T09:30:00Z", "2026-10-16T09:40:00Z", "2026-10-16T11:00:00Z", currency="usd"),
        order(10, "OL-1006-1", "ORD-1006", "C105", "P102", "1", "729.00", "paid",
              "2026-10-16 10:00:00", "2026-10-16T10:05:00Z", "2026-10-16T12:00:00Z"),
        order(11, "OL-1007-1", "ORD-1007", "C100", "P108", "2", "24.00", "completed",
              "2026-10-17T08:15:00Z", "2026-10-17T08:20:00Z", "2026-10-17T10:00:00Z"),
        order(12, "OL-1008-1", "ORD-1008", "C106", "P109", "1", "16.00", "paid",
              "17/10/2026 08:45", "2026-10-17T08:50:00Z", "2026-10-17T10:00:00Z"),
        order(13, "OL-1009-1", "ORD-1009", "C107", "P104", "4", "19.00", "Completed",
              "2026-10-17T11:00:00Z", "2026-10-17T11:05:00Z", "2026-10-17T12:00:00Z"),
        order(14, "OL-1010-1", "ORD-1010", "C102", "P101", "1", "749.00", "paid",
              "2026-10-18T13:20:00Z", "2026-10-18T13:25:00Z", "2026-10-18T15:00:00Z"),
        # Valid records excluded by the sales-fact policy.
        order(15, "OL-1011-1", "ORD-1011", "C103", "P103", "1", "1199.00", "cancelled",
              "2026-10-18T14:00:00Z", "2026-10-18T14:10:00Z", "2026-10-18T16:00:00Z"),
        order(16, "OL-1012-1", "ORD-1012", "C101", "P105", "1", "12.50", "returned",
              "2026-10-18T15:00:00Z", "2026-10-18T15:30:00Z", "2026-10-18T16:30:00Z"),
        order(17, "OL-1013-1", "ORD-1013", "C106", "P106", "1", "49.00", "Canceled",
              "2026-10-18T16:00:00Z", "2026-10-18T16:05:00Z", "2026-10-18T17:00:00Z"),
        order(18, "OL-1014-1", "ORD-1014", "C104", "P107", "1", "89.00", "pending",
              "2026-10-18T16:30:00Z", "2026-10-18T16:35:00Z", "2026-10-18T17:10:00Z"),
        order(19, "OL-1025-1", "ORD-1025", "C105", "P102", "1", "729.00", "shipped",
              "2026-10-18T17:00:00Z", "2026-10-18T17:05:00Z", "2026-10-18T18:00:00Z"),
        # Structural and referential failures. One reason each.
        order(20, "OL-1015-1", "ORD-1015", None, "P101", "1", "749.00", "completed",
              "2026-10-18T10:00:00Z", "2026-10-18T10:00:00Z", "2026-10-18T12:00:00Z"),
        order(21, "OL-1016-1", "ORD-1016", "C100", "P104", "-1", "19.00", "completed",
              "2026-10-18T10:05:00Z", "2026-10-18T10:05:00Z", "2026-10-18T12:00:00Z"),
        order(22, "OL-1017-1", "ORD-1017", "C102", "P108", "1", "24.00", "completed",
              "2026-13-40T10:00:00", "2026-10-18T10:00:00Z", "2026-10-18T12:00:00Z"),
        order(23, "OL-1018-1", "ORD-1018", "C105", "P109", "1", "16.00", "voided",
              "2026-10-18T10:15:00Z", "2026-10-18T10:15:00Z", "2026-10-18T12:00:00Z"),
        order(24, "OL-1019-1", "ORD-1019", "C103", "P102", "1", None, "completed",
              "2026-10-18T10:20:00Z", "2026-10-18T10:20:00Z", "2026-10-18T12:00:00Z"),
        order(25, "OL-1020-1", "ORD-1020", "C100", "P106", "1", "49.00", "completed",
              "05/10/2026 09:00", "2026-10-18T09:00:00Z", "2026-10-18T12:00:00Z"),
        order(26, "OL-1021-1", "ORD-1021", "C101", "P999", "1", "10.00", "completed",
              "2026-10-18T11:00:00Z", "2026-10-18T11:00:00Z", "2026-10-18T13:00:00Z"),
        order(27, "OL-1022-1", "ORD-1022", "C999", "P104", "1", "19.00", "paid",
              "2026-10-18T11:05:00Z", "2026-10-18T11:05:00Z", "2026-10-18T13:00:00Z"),
        order(28, "OL-1023-1", "ORD-1023", "C106", "P105", "two", "12.50", "completed",
              "2026-10-18T11:10:00Z", "2026-10-18T11:10:00Z", "2026-10-18T13:00:00Z"),
        order(29, "OL-1024-1", "ORD-1024", "C101", "P109", "1", "16.00", "completed",
              "2026-10-18T11:20:00Z", "2026-10-18T11:20:00Z", "2026-10-18T13:00:00Z", currency="EUR"),
    ]


def customers() -> list[dict]:
    return [
        customer(1, "C100", "JOHN SMITH", "US", "consumer", "2024-03-12T00:00:00Z",
                 "2026-10-01T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(2, "C100", "John Smith", "US", "consumer", "2024-03-12T00:00:00Z",
                 "2026-10-01T00:00:00Z", "2026-10-16T01:04:00Z"),
        customer(3, "C101", "Priya Nair", "IN", "Consumer", "2023-11-02T00:00:00Z",
                 "2026-09-01T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(4, "C102", "amira hassan", "AE", "business", "2022-01-19 08:00:00",
                 "2026-08-01T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(5, "C103", "Luis Ortega", "ES", "Consumer", "15/01/2025 09:30",
                 "2026-08-15T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(6, "C104", "MEI CHEN", "SG", "WHOLESALE", "2021-06-01T00:00:00Z",
                 "2026-07-01T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(7, "C105", "  Nora Berg", "SE", "Business", "2020-04-04T00:00:00Z",
                 "2026-07-20T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(8, "C106", "Jonah Hale", "GB", "consumer", "2024-12-12T00:00:00Z",
                 "2026-09-12T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(9, "C106", "Jonah Hale", "GB", "consumer", "2024-12-12T00:00:00Z",
                 "2026-09-12T00:00:00Z", "2026-10-16T01:09:00Z"),
        # Same presentation name as C100 after normalization. Different identifier.
        customer(10, "C107", "john smith", "US", "Consumer", "2025-02-02T00:00:00Z",
                 "2026-09-20T00:00:00Z", "2026-10-16T01:00:00Z"),
        customer(11, None, "Ghost Record", "US", "Consumer", "2025-01-01T00:00:00Z",
                 "2026-09-01T00:00:00Z", "2026-10-16T01:00:00Z"),
    ]


def products() -> list[dict]:
    updated = "2026-10-01T00:00:00Z"
    ingested = "2026-10-16T01:00:00Z"
    rows = [
        product(1, "P101", "IP15-128-BLK", "Apple iPhone 15 128GB Black", "Apple", None, updated, ingested),
        product(2, "P101", "IP15-128-BLK", "Apple iPhone 15 128GB Black", "Apple", None, updated, "2026-10-16T01:06:00Z"),
        product(3, "P102", "IP15-128-ALT", "iPhone15 - Black - 128 GB", "BrightMobile", "Miscellaneous", updated, ingested),
        product(4, "P103", "SM-S928", "Samsung Galaxy S24 Ultra", "Samsung", "phones", updated, ingested),
        product(5, "P104", "USBC-20W", "USB-C Fast Charging Adapter 20W", "Voltline", None, updated, ingested),
        product(6, "P105", "ALV-LOT-250", "Premium Moisturizing Aloe Vera Lotion", "Botanica", "General", updated, ingested),
        product(7, "P106", "BT-EB-01", "Wireless Bluetooth Earbuds", "SoundArc", "Unknown", updated, ingested),
        product(8, "P107", "AF-4L", "Compact 4-Liter Digital Air Fryer", "Hearth & Kiln", None, updated, ingested),
        product(9, "P108", "CASE-SIL", "Silicone Protective Case for Mobile Handset", "CaseCo", "Miscellaneous", updated, ingested),
        product(10, "P109", "SPF50-MIN", "Daily Mineral Face Sunscreen SPF 50", "Botanica", "", updated, ingested),
        product(11, "P110", "NK-000", None, "Northline", None, updated, ingested),
        product(12, None, "BAD-SKU", "Orphan Catalog Row", "Northline", "General", updated, ingested),
    ]
    return rows


def fixture() -> dict:
    return {
        "label": "Precomputed LLM output fixture — no live model inference.",
        "model_version": "demo-model-v1",
        "prompt_version": "product-classifier-v1",
        "taxonomy_version": "2026-10",
        "classifications": [
            {
                "product_id": "P103",
                "category": "Smartphones",
                "subcategory": "Mobile Phones",
                "needs_review": False,
                "demo_role": "precedence_example",
            },
            {
                "product_id": "P104",
                "category": "Electronics Accessories",
                "subcategory": "Chargers",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P105",
                "category": "Personal Care",
                "subcategory": "Skin Care",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P106",
                "category": "Electronics Accessories",
                "subcategory": "Audio",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P107",
                "category": "Home Appliances",
                "subcategory": "Kitchen",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P108",
                "category": "Electronics Accessories",
                "subcategory": "Cases",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P109",
                "category": "Personal Care",
                "subcategory": "Skin Care",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P110",
                "category": "Wearables",
                "subcategory": "Watches",
                "needs_review": False,
                "demo_role": "model_proposal",
            },
            {
                "product_id": "P110",
                "category": "Home Appliances",
                "subcategory": "Kitchen",
                "needs_review": True,
                "demo_role": "injected_defect",
            },
            {
                "product_id": "P999",
                "category": "Other",
                "subcategory": "General",
                "needs_review": False,
                "demo_role": "injected_defect",
            },
            {
                "product_id": None,
                "category": "Smartphones",
                "subcategory": "Mobile Phones",
                "needs_review": False,
                "demo_role": "injected_defect",
            },
        ],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    write_jsonl(BRONZE / "orders_raw.jsonl", orders())
    write_jsonl(BRONZE / "customers_raw.jsonl", customers())
    write_jsonl(BRONZE / "products_raw.jsonl", products())
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "llm_product_classifications.fixture.json").write_text(
        json.dumps(fixture(), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"orders {len(orders())}")
    print(f"customers {len(customers())}")
    print(f"products {len(products())}")


if __name__ == "__main__":
    main()
