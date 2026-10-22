"""Embedded Silver contract.

Used only when the checked-in Silver files and the Session 3 Bronze extract are
both missing. The rows are the Session 3 publish: 11 accepted lines, USD 3,779.50.
"""

from __future__ import annotations

SALES = (
    ("OL-1001-1", "ORD-1001", "C100", "P101", 1, "749.00", "749.00", "2026-10-15", "USD"),
    ("OL-1002-1", "ORD-1002", "C101", "P103", 1, "1199.00", "1199.00", "2026-10-15", "USD"),
    ("OL-1003-1", "ORD-1003", "C102", "P104", 2, "19.00", "38.00", "2026-10-15", "USD"),
    ("OL-1003-2", "ORD-1003", "C102", "P106", 1, "49.00", "49.00", "2026-10-15", "USD"),
    ("OL-1004-1", "ORD-1004", "C104", "P107", 1, "89.00", "89.00", "2026-10-16", "USD"),
    ("OL-1005-1", "ORD-1005", "C103", "P105", 3, "12.50", "37.50", "2026-10-16", "USD"),
    ("OL-1006-1", "ORD-1006", "C105", "P102", 1, "729.00", "729.00", "2026-10-16", "USD"),
    ("OL-1007-1", "ORD-1007", "C100", "P108", 2, "24.00", "48.00", "2026-10-17", "USD"),
    ("OL-1008-1", "ORD-1008", "C106", "P109", 1, "16.00", "16.00", "2026-10-17", "USD"),
    ("OL-1009-1", "ORD-1009", "C107", "P104", 4, "19.00", "76.00", "2026-10-17", "USD"),
    ("OL-1010-1", "ORD-1010", "C102", "P101", 1, "749.00", "749.00", "2026-10-18", "USD"),
)

CUSTOMERS = (
    ("C100", "John Smith", "US", "Consumer", "2026-10-01"),
    ("C101", "Priya Nair", "IN", "Consumer", "2026-09-01"),
    ("C102", "Amira Hassan", "AE", "Business", "2026-08-01"),
    ("C103", "Luis Ortega", "ES", "Consumer", "2026-08-15"),
    ("C104", "Mei Chen", "SG", "Wholesale", "2026-07-01"),
    ("C105", "Nora Berg", "SE", "Business", "2026-07-20"),
    ("C106", "Jonah Hale", "GB", "Consumer", "2026-09-12"),
    ("C107", "John Smith", "US", "Consumer", "2026-09-20"),
)

PRODUCTS = (
    ("P101", "IP15-128-BLK", "Apple iPhone 15 128GB Black", "Smartphones", "Mobile Phones", "rules", "2026-10-01"),
    ("P102", "IP15-128-ALT", "iPhone15 - Black - 128 GB", "Smartphones", "Mobile Phones", "rules", "2026-10-01"),
    ("P103", "SM-S928", "Samsung Galaxy S24 Ultra", "Smartphones", "Flagship Phones", "manual", "2026-10-01"),
    ("P104", "USBC-20W", "USB-C Fast Charging Adapter 20W", "Electronics Accessories", "Chargers", "llm", "2026-10-01"),
    ("P105", "ALV-LOT-250", "Premium Moisturizing Aloe Vera Lotion", "Personal Care", "Skin Care", "llm", "2026-10-01"),
    ("P106", "BT-EB-01", "Wireless Bluetooth Earbuds", "Electronics Accessories", "Audio", "llm", "2026-10-01"),
    ("P107", "AF-4L", "Compact 4-Liter Digital Air Fryer", "Home Appliances", "Kitchen", "llm", "2026-10-01"),
    ("P108", "CASE-SIL", "Silicone Protective Case for Mobile Handset", "Electronics Accessories", "Cases", "llm", "2026-10-01"),
    ("P109", "SPF50-MIN", "Daily Mineral Face Sunscreen SPF 50", "Personal Care", "Skin Care", "llm", "2026-10-01"),
    ("P110", "NK-000", None, "Unclassified", None, "fallback", "2026-10-01"),
)

SALES_COLUMNS = (
    "order_line_id",
    "order_id",
    "customer_id",
    "product_id",
    "quantity",
    "unit_price",
    "gross_amount",
    "order_date",
    "currency",
)
CUSTOMER_COLUMNS = (
    "customer_id",
    "customer_name",
    "country_code",
    "customer_segment",
    "source_updated_at",
)
PRODUCT_COLUMNS = (
    "product_id",
    "sku",
    "product_name",
    "category",
    "subcategory",
    "enrichment_method",
    "source_updated_at",
)
