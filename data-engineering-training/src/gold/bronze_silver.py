"""Rebuild the Session 3 Silver contract from Session 3 Bronze.

Session 3 keeps this logic in the instructor notebook and does not export Silver
files. Session 4 reads that contract. It does not reopen quarantine, taxonomy,
or the model lesson. When the checked-in Silver files are missing, this module
reproduces the same accepted sales lines and the same published categories.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

TAXONOMY_VERSION = "2026-10"
PROMPT_VERSION = "product-classifier-v1"
MODEL_VERSION = "demo-model-v1"
RULE_VERSION = "keyword-rules-v1"
ALLOWED_CATEGORIES = (
    "Smartphones",
    "Electronics Accessories",
    "Home Appliances",
    "Personal Care",
    "Other",
)
MODEL_SUBCATEGORIES = {
    "Smartphones": ("Mobile Phones",),
    "Electronics Accessories": ("Chargers", "Audio", "Cases"),
    "Home Appliances": ("Kitchen",),
    "Personal Care": ("Skin Care",),
    "Other": ("General",),
}


def training_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bronze_dir(root: Path | None = None) -> Path:
    return (root or training_root()) / "data" / "session_03" / "bronze"


def fixture_path(root: Path | None = None) -> Path:
    return (root or training_root()) / "data" / "session_03" / "fixtures" / "llm_product_classifications.fixture.json"


def bronze_is_available(root: Path | None = None) -> bool:
    folder = bronze_dir(root)
    required = ("orders_raw.jsonl", "customers_raw.jsonl", "products_raw.jsonl")
    return all((folder / name).is_file() for name in required)


def derive_silver(root: Path | None = None) -> dict[str, pd.DataFrame]:
    """Return sales, customers, and products at the Session 3 publish grain."""
    root = root or training_root()
    if not bronze_is_available(root):
        raise FileNotFoundError(f"Session 3 Bronze is not in {bronze_dir(root)}")

    con = duckdb.connect()
    try:
        _load_bronze(con, bronze_dir(root))
        _install_macros(con)
        _build_orders(con)
        _build_customers(con)
        _build_products(con)
        _validate_orders(con)
        _classify(con, fixture_path(root))
        sales = _frame(
            con,
            """
            SELECT
                order_line_id,
                order_id,
                customer_id,
                product_id,
                quantity,
                CAST(unit_price AS DECIMAL(12, 2)) AS unit_price,
                CAST(quantity * unit_price AS DECIMAL(12, 2)) AS gross_amount,
                CAST(order_timestamp_utc AS DATE) AS order_date,
                currency
            FROM accepted_records
            ORDER BY order_line_id
            """,
            decimal_columns={"unit_price", "gross_amount"},
            date_columns={"order_date"},
        )
        customers = _frame(
            con,
            """
            SELECT
                customer_id,
                customer_name,
                country AS country_code,
                customer_segment,
                CAST(source_updated_at_utc AS DATE) AS source_updated_at
            FROM silver_customers
            ORDER BY customer_id
            """,
            date_columns={"source_updated_at"},
        )
        products = _frame(
            con,
            """
            SELECT
                product_id,
                sku,
                product_name,
                category,
                subcategory,
                enrichment_method,
                CAST(source_updated_at_utc AS DATE) AS source_updated_at
            FROM silver_product_categories
            ORDER BY product_id
            """,
            date_columns={"source_updated_at"},
        )
    finally:
        con.close()
    return {"sales": sales, "customers": customers, "products": products}


def _frame(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    decimal_columns: set[str] | None = None,
    date_columns: set[str] | None = None,
) -> pd.DataFrame:
    decimal_columns = decimal_columns or set()
    date_columns = date_columns or set()
    cursor = con.execute(sql)
    columns = [item[0] for item in cursor.description]
    rows = []
    for record in cursor.fetchall():
        row = {}
        for name, value in zip(columns, record):
            if value is None:
                row[name] = None
            elif name in decimal_columns:
                row[name] = Decimal(value).quantize(Decimal("0.01"))
            elif name in date_columns:
                row[name] = value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])
            else:
                row[name] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _load_bronze(con: duckdb.DuckDBPyConnection, folder: Path) -> None:
    files = {
        "bronze_orders": folder / "orders_raw.jsonl",
        "bronze_customers": folder / "customers_raw.jsonl",
        "bronze_products": folder / "products_raw.jsonl",
    }
    for table, path in files.items():
        con.execute(
            f"""
            CREATE OR REPLACE TABLE {table} AS
            SELECT *
            FROM read_json('{_sql_path(path)}', format = 'newline_delimited')
            """
        )


def _install_macros(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        r"""
        CREATE OR REPLACE MACRO parse_source_timestamp(value) AS (
            CASE
                WHEN value IS NULL OR TRIM(CAST(value AS VARCHAR)) = '' THEN NULL
                WHEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%dT%H:%M:%SZ') IS NOT NULL
                    THEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%dT%H:%M:%SZ')
                WHEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%dT%H:%M:%S') IS NOT NULL
                    THEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%dT%H:%M:%S')
                WHEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%d %H:%M:%S') IS NOT NULL
                    THEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%Y-%m-%d %H:%M:%S')
                WHEN regexp_full_match(TRIM(CAST(value AS VARCHAR)), '^[0-9]{2}/[0-9]{2}/[0-9]{4} [0-9]{2}:[0-9]{2}$')
                     AND TRY_CAST(split_part(TRIM(CAST(value AS VARCHAR)), '/', 1) AS INTEGER) > 12
                     AND TRY_CAST(split_part(TRIM(CAST(value AS VARCHAR)), '/', 2) AS INTEGER) BETWEEN 1 AND 12
                    THEN try_strptime(TRIM(CAST(value AS VARCHAR)), '%d/%m/%Y %H:%M')
                ELSE NULL
            END
        );
        CREATE OR REPLACE MACRO timestamp_parse_status(value) AS (
            CASE
                WHEN value IS NULL OR TRIM(CAST(value AS VARCHAR)) = '' THEN 'missing'
                WHEN parse_source_timestamp(value) IS NOT NULL THEN 'parsed'
                WHEN regexp_full_match(TRIM(CAST(value AS VARCHAR)), '^[0-9]{2}/[0-9]{2}/[0-9]{4} [0-9]{2}:[0-9]{2}$')
                     AND TRY_CAST(split_part(TRIM(CAST(value AS VARCHAR)), '/', 1) AS INTEGER) BETWEEN 1 AND 12
                     AND TRY_CAST(split_part(TRIM(CAST(value AS VARCHAR)), '/', 2) AS INTEGER) BETWEEN 1 AND 12
                    THEN 'ambiguous'
                ELSE 'invalid'
            END
        );
        CREATE OR REPLACE MACRO title_case(value) AS (
            CASE
                WHEN value IS NULL OR TRIM(CAST(value AS VARCHAR)) = '' THEN NULL
                ELSE array_to_string(
                    list_transform(
                        string_split(TRIM(CAST(value AS VARCHAR)), ' '),
                        word -> CASE
                            WHEN word = '' THEN ''
                            ELSE UPPER(LEFT(word, 1)) || LOWER(SUBSTR(word, 2))
                        END
                    ),
                    ' '
                )
            END
        );
        """
    )


def _build_orders(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_orders AS
        WITH raw AS (
            SELECT
                delivery_seq,
                source_system,
                run_id,
                source_record_id,
                TRY_CAST(ingested_at AS TIMESTAMP) AS ingested_at,
                NULLIF(TRIM(CAST(payload.order_id AS VARCHAR)), '') AS order_id,
                NULLIF(TRIM(CAST(payload.order_line_id AS VARCHAR)), '') AS order_line_id,
                NULLIF(TRIM(CAST(payload.customer_id AS VARCHAR)), '') AS customer_id,
                NULLIF(TRIM(CAST(payload.product_id AS VARCHAR)), '') AS product_id,
                payload.quantity AS quantity_raw,
                payload.unit_price AS unit_price_raw,
                TRY_CAST(payload.quantity AS INTEGER) AS quantity,
                TRY_CAST(payload.unit_price AS DECIMAL(12, 2)) AS unit_price,
                payload.order_status AS order_status_raw,
                LOWER(TRIM(CAST(payload.order_status AS VARCHAR))) AS order_status_normalized,
                payload.order_timestamp AS order_timestamp_raw,
                payload.source_updated_at AS source_updated_at_raw,
                payload.currency AS currency_raw,
                UPPER(TRIM(CAST(payload.currency AS VARCHAR))) AS currency,
                parse_source_timestamp(payload.order_timestamp) AS order_timestamp_utc,
                timestamp_parse_status(payload.order_timestamp) AS order_timestamp_status,
                parse_source_timestamp(payload.source_updated_at) AS source_updated_at_utc,
                timestamp_parse_status(payload.source_updated_at) AS source_updated_status
            FROM bronze_orders
        )
        SELECT
            *,
            CASE order_status_normalized
                WHEN 'canceled' THEN 'cancelled'
                ELSE order_status_normalized
            END AS order_status
        FROM raw
        """
    )


def _build_customers(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_customers AS
        SELECT
            delivery_seq,
            source_system,
            TRY_CAST(ingested_at AS TIMESTAMP) AS ingested_at,
            NULLIF(TRIM(CAST(payload.customer_id AS VARCHAR)), '') AS customer_id,
            NULLIF(TRIM(CAST(payload.customer_name AS VARCHAR)), '') AS customer_name_raw,
            title_case(payload.customer_name) AS customer_name,
            NULLIF(UPPER(TRIM(CAST(payload.country_code AS VARCHAR))), '') AS country,
            title_case(payload.customer_segment) AS customer_segment,
            parse_source_timestamp(payload.registered_at) AS registered_at_utc,
            parse_source_timestamp(payload.source_updated_at) AS source_updated_at_utc
        FROM bronze_customers
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE silver_customers AS
        SELECT * EXCLUDE (version_rank)
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY customer_id
                    ORDER BY source_updated_at_utc DESC, ingested_at DESC, delivery_seq DESC
                ) AS version_rank
            FROM stg_customers
            WHERE customer_id IS NOT NULL
              AND source_updated_at_utc IS NOT NULL
        )
        WHERE version_rank = 1
        """
    )


def _build_products(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_products AS
        SELECT
            delivery_seq,
            source_system,
            TRY_CAST(ingested_at AS TIMESTAMP) AS ingested_at,
            NULLIF(TRIM(CAST(payload.product_id AS VARCHAR)), '') AS product_id,
            NULLIF(TRIM(CAST(payload.sku AS VARCHAR)), '') AS sku,
            NULLIF(TRIM(CAST(payload.product_description AS VARCHAR)), '') AS product_name,
            NULLIF(TRIM(CAST(payload.vendor_name AS VARCHAR)), '') AS vendor_name,
            NULLIF(TRIM(CAST(payload.category AS VARCHAR)), '') AS source_category,
            parse_source_timestamp(payload.source_updated_at) AS source_updated_at_utc
        FROM bronze_products
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE silver_products AS
        SELECT * EXCLUDE (version_rank)
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY product_id
                    ORDER BY source_updated_at_utc DESC, ingested_at DESC, delivery_seq DESC
                ) AS version_rank
            FROM stg_products
            WHERE product_id IS NOT NULL
        )
        WHERE version_rank = 1
        """
    )


def _validate_orders(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE order_events AS
        SELECT
            *,
            CASE
                WHEN order_id IS NULL THEN 'missing_order_id'
                WHEN order_line_id IS NULL THEN 'missing_order_line_id'
                WHEN order_timestamp_status = 'ambiguous'
                  OR source_updated_status = 'ambiguous' THEN 'ambiguous_timestamp'
                WHEN order_timestamp_status <> 'parsed'
                  OR source_updated_status <> 'parsed' THEN 'invalid_timestamp'
                WHEN order_status IS NULL
                  OR order_status NOT IN (
                      'paid', 'completed', 'cancelled', 'returned', 'pending', 'shipped'
                  ) THEN 'unknown_status'
                WHEN quantity IS NULL OR quantity <= 0 THEN 'invalid_quantity'
                WHEN unit_price IS NULL OR unit_price <= 0 THEN 'invalid_unit_price'
                WHEN customer_id IS NULL THEN 'missing_customer_id'
                WHEN product_id IS NULL THEN 'missing_product_id'
                WHEN currency IS DISTINCT FROM 'USD' THEN 'unsupported_currency'
                ELSE NULL
            END AS structural_reason
        FROM stg_orders
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE order_versions AS
        WITH valid AS (
            SELECT * FROM order_events WHERE structural_reason IS NULL
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER w AS version_rank,
                FIRST_VALUE(quantity) OVER w AS winning_quantity,
                FIRST_VALUE(unit_price) OVER w AS winning_unit_price,
                FIRST_VALUE(order_status) OVER w AS winning_status,
                FIRST_VALUE(source_updated_at_utc) OVER w AS winning_source_updated_at
            FROM valid
            WINDOW w AS (
                PARTITION BY order_id, order_line_id
                ORDER BY source_updated_at_utc DESC, ingested_at DESC, delivery_seq DESC
            )
        )
        SELECT
            *,
            CASE
                WHEN version_rank = 1 THEN 'current'
                WHEN quantity = winning_quantity
                 AND unit_price = winning_unit_price
                 AND order_status = winning_status
                 AND source_updated_at_utc = winning_source_updated_at
                    THEN 'duplicate_delivery'
                ELSE 'superseded'
            END AS version_disposition
        FROM ranked
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE order_disposition AS
        SELECT
            e.delivery_seq,
            e.order_id,
            e.order_line_id,
            e.customer_id,
            e.product_id,
            e.quantity,
            e.unit_price,
            e.order_status,
            e.order_timestamp_utc,
            e.currency,
            CASE
                WHEN e.structural_reason IS NOT NULL THEN 'quarantined'
                WHEN v.version_disposition = 'duplicate_delivery' THEN 'duplicate_delivery'
                WHEN v.version_disposition = 'superseded' THEN 'superseded'
                WHEN v.customer_id NOT IN (SELECT customer_id FROM silver_customers) THEN 'quarantined'
                WHEN v.product_id NOT IN (SELECT product_id FROM silver_products) THEN 'quarantined'
                WHEN v.order_status NOT IN ('paid', 'completed') THEN 'excluded_by_policy'
                ELSE 'accepted'
            END AS disposition
        FROM order_events AS e
        LEFT JOIN order_versions AS v USING (delivery_seq)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE accepted_records AS
        SELECT * FROM order_disposition WHERE disposition = 'accepted'
        """
    )


def _rule_category(description: str | None) -> str:
    text = (description or "").lower()
    if "iphone" in text:
        return "Smartphones"
    if "galaxy" in text:
        return "Smartphones"
    if "adapter" in text:
        return "Accessories"
    return "Unknown"


def _classify(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture["prompt_version"] != PROMPT_VERSION or fixture["taxonomy_version"] != TAXONOMY_VERSION:
        raise RuntimeError("Session 3 fixture versions do not match the Silver contract.")
    if fixture["model_version"] != MODEL_VERSION:
        raise RuntimeError("Session 3 fixture model version does not match the offline contract.")

    rows = con.execute("SELECT product_id, product_name FROM silver_products ORDER BY product_id").fetchall()
    con.execute(
        """
        CREATE OR REPLACE TABLE rule_classifications (
            product_id VARCHAR,
            rule_category VARCHAR,
            rule_subcategory VARCHAR,
            rule_version VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO rule_classifications VALUES (?, ?, ?, ?)",
        [
            (
                product_id,
                category := _rule_category(name),
                "Mobile Phones" if category == "Smartphones" else None,
                RULE_VERSION,
            )
            for product_id, name in rows
        ],
    )
    con.execute("CREATE OR REPLACE TABLE allowed_categories (category VARCHAR)")
    con.executemany("INSERT INTO allowed_categories VALUES (?)", [(category,) for category in ALLOWED_CATEGORIES])
    con.execute("CREATE OR REPLACE TABLE model_subcategories (category VARCHAR, subcategory VARCHAR)")
    con.executemany(
        "INSERT INTO model_subcategories VALUES (?, ?)",
        [
            (category, subcategory)
            for category, subcategories in MODEL_SUBCATEGORIES.items()
            for subcategory in subcategories
        ],
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE manual_category_map AS
        SELECT * FROM (
            VALUES ('P103', 'Smartphones', 'Flagship Phones', 'merchandising-2026-10')
        ) AS approved(product_id, category, subcategory, approval_ref)
        """
    )

    proposals_by_id = {
        row["product_id"]: row
        for row in fixture["classifications"]
        if row["demo_role"] == "model_proposal"
    }
    requested = [
        row[0]
        for row in con.execute(
            """
            SELECT p.product_id
            FROM silver_products AS p
            LEFT JOIN manual_category_map AS m USING (product_id)
            LEFT JOIN rule_classifications AS r USING (product_id)
            WHERE m.product_id IS NULL
              AND r.rule_category NOT IN (SELECT category FROM allowed_categories)
            ORDER BY p.product_id
            """
        ).fetchall()
    ]
    proposals = []
    for product_id in requested:
        source = proposals_by_id[product_id]
        proposals.append(
            (
                product_id,
                source["category"],
                source["subcategory"],
                bool(source["needs_review"]),
                "model_proposal",
            )
        )
    for row in fixture["classifications"]:
        if row["demo_role"] == "model_proposal":
            continue
        proposals.append(
            (
                row.get("product_id"),
                row.get("category"),
                row.get("subcategory"),
                bool(row.get("needs_review")),
                row["demo_role"],
            )
        )
    con.execute(
        """
        CREATE OR REPLACE TABLE ai_proposals (
            product_id VARCHAR,
            category VARCHAR,
            subcategory VARCHAR,
            needs_review BOOLEAN,
            demo_role VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO ai_proposals VALUES (?, ?, ?, ?, ?)", proposals)
    con.execute(
        """
        CREATE OR REPLACE TABLE ai_enrichment_accepted AS
        SELECT product_id, category, subcategory
        FROM (
            SELECT
                proposals.*,
                CASE
                    WHEN proposals.product_id IS NULL OR TRIM(proposals.product_id) = '' THEN 'missing_product_id'
                    WHEN proposals.product_id NOT IN (SELECT product_id FROM silver_products) THEN 'unknown_product'
                    WHEN proposals.needs_review THEN 'model_flagged_uncertain'
                    WHEN proposals.category NOT IN (SELECT category FROM allowed_categories) THEN 'category_outside_taxonomy'
                    WHEN proposals.subcategory IS NULL
                      OR NOT EXISTS (
                          SELECT 1
                          FROM model_subcategories AS allowed
                          WHERE allowed.category = proposals.category
                            AND allowed.subcategory = proposals.subcategory
                      ) THEN 'subcategory_outside_taxonomy'
                    ELSE 'accepted'
                END AS validation_status
            FROM ai_proposals AS proposals
        )
        WHERE validation_status = 'accepted'
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE silver_product_categories AS
        SELECT
            products.product_id,
            products.sku,
            products.product_name,
            products.source_updated_at_utc,
            CASE
                WHEN approved.product_id IS NOT NULL THEN approved.category
                WHEN rules.rule_category IN (SELECT category FROM allowed_categories) THEN rules.rule_category
                WHEN accepted.product_id IS NOT NULL THEN accepted.category
                ELSE 'Unclassified'
            END AS category,
            CASE
                WHEN approved.product_id IS NOT NULL THEN approved.subcategory
                WHEN rules.rule_category IN (SELECT category FROM allowed_categories) THEN rules.rule_subcategory
                WHEN accepted.product_id IS NOT NULL THEN accepted.subcategory
                ELSE NULL
            END AS subcategory,
            CASE
                WHEN approved.product_id IS NOT NULL THEN 'manual'
                WHEN rules.rule_category IN (SELECT category FROM allowed_categories) THEN 'rules'
                WHEN accepted.product_id IS NOT NULL THEN 'llm'
                ELSE 'fallback'
            END AS enrichment_method
        FROM silver_products AS products
        LEFT JOIN manual_category_map AS approved USING (product_id)
        LEFT JOIN rule_classifications AS rules USING (product_id)
        LEFT JOIN ai_enrichment_accepted AS accepted USING (product_id)
        """
    )
