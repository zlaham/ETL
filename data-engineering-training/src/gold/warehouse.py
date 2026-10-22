"""Publish the Session 4 Gold warehouse.

Silver is an input. The SQL in sql/session_04 is the transformation.
Running the build twice replaces the facts and keeps the surrogate keys.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from src.gold.bronze_silver import training_root
from src.gold.contract import (
    ACCESSORIES_AS_IS,
    ACCESSORIES_AS_WAS,
    AVERAGE_ORDER_GROSS,
    BUSINESS_PHONES_AS_IS,
    BUSINESS_PHONES_AS_WAS,
    C050_KEY,
    C100_KEY,
    C101_PHONE,
    C101_VERSION_1_KEY,
    C101_VERSION_2_KEY,
    CONSUMER_PHONES_AS_IS,
    CONSUMER_PHONES_AS_WAS,
    CUSTOMER_REGISTRY_ROWS,
    DATE_ROWS,
    FACT_ROWS,
    GROSS_SALES,
    HOME_APPLIANCES,
    NET_SALES,
    ORDER_COUNT,
    P104_VERSION_1_KEY,
    P104_VERSION_2_KEY,
    PERSONAL_CARE,
    POWER_AS_IS,
    PRODUCT_REGISTRY_ROWS,
    RETURN_AMOUNT,
    SMARTPHONES,
    SUSPENSE_AMOUNT,
    UNITS_RETURNED,
    UNITS_SOLD,
    UNKNOWN_KEY,
    WEEKEND_GROSS,
)
from src.gold.silver import resolve_changes, resolve_silver

SQL_DIR = Path(__file__).resolve().parents[2] / "sql" / "session_04"

DROP_VIEWS = (
    "cmp_original_customer_keys",
    "cmp_fragile_customer_keys",
    "cmp_category_history",
    "cmp_smartphone_segment_history",
    "scenario_c101_phone_return",
)
DROP_TABLES = (
    "gold_contract",
    "gold_bus_matrix",
    "kpi_commercial",
    "mart_sales_by_day_category",
    "gold_suspense",
    "fct_returns",
    "return_resolution",
    "fct_sales_order_lines",
    "dim_date",
    "dim_product",
    "dim_customer",
    "product_version_plan",
    "customer_version_plan",
    "surrogate_registry",
)


class GoldWarehouse:
    """One DuckDB file. The notebook and the tests share this entry point."""

    def __init__(self, root: Path | None = None, database: Path | None = None) -> None:
        self.root = (root or training_root()).resolve()
        self.database = database or (self.root / "artifacts" / "session04.duckdb")
        self.con: duckdb.DuckDBPyConnection | None = None
        self.silver_origin: str | None = None

    def close(self) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    def build(self, *, reset_registry: bool = False) -> dict:
        self._connect()
        if reset_registry:
            self._drop_published()
        frames, origin = resolve_silver(self.root)
        self.silver_origin = origin
        _load_inputs(self.con, frames, resolve_changes(self.root))
        for path in sorted(SQL_DIR.glob("*.sql")):
            execute_sql_file(self.con, path)
        summary = self.summary()
        certify(self.con, summary)
        return summary

    def summary(self) -> dict:
        if self.con is None:
            raise RuntimeError("Build the warehouse before reading it.")
        cursor = self.con.execute("SELECT * FROM kpi_commercial")
        columns = [item[0] for item in cursor.description]
        kpi = cursor.fetchone()
        values = dict(zip(columns, kpi))
        values["silver_origin"] = self.silver_origin
        values["fact_rows"] = self.con.execute("SELECT COUNT(*) FROM fct_sales_order_lines").fetchone()[0]
        values["suspense_rows"] = self.con.execute("SELECT COUNT(*) FROM gold_suspense").fetchone()[0]
        values["registry_rows"] = self.con.execute("SELECT COUNT(*) FROM surrogate_registry").fetchone()[0]
        return values

    def signature(self) -> tuple:
        """Stable identity of a publish. The clock is not part of it."""
        if self.con is None:
            raise RuntimeError("Build the warehouse before signing it.")
        facts = self.con.execute(
            """
            SELECT order_line_id, customer_key, product_key, order_date_key, quantity, gross_amount
            FROM fct_sales_order_lines
            ORDER BY order_line_id
            """
        ).fetchall()
        customers = self.con.execute(
            """
            SELECT customer_key, customer_id, version_number, customer_name, customer_segment,
                   effective_from, effective_to, is_current
            FROM dim_customer
            ORDER BY customer_key, version_number
            """
        ).fetchall()
        products = self.con.execute(
            """
            SELECT product_key, product_id, version_number, category, is_current
            FROM dim_product
            ORDER BY product_key, version_number
            """
        ).fetchall()
        registry = self.con.execute(
            """
            SELECT entity_name, business_key, version_number, surrogate_key
            FROM surrogate_registry
            ORDER BY entity_name, surrogate_key
            """
        ).fetchall()
        return (facts, customers, products, registry)

    def query(self, sql: str) -> pd.DataFrame:
        if self.con is None:
            raise RuntimeError("Build the warehouse before querying it.")
        return self.con.execute(sql).df()

    def sql_text(self, name: str) -> str:
        path = SQL_DIR / name
        if path.suffix != ".sql":
            path = SQL_DIR / f"{name}.sql"
        return path.read_text(encoding="utf-8")

    def execute_sql(self, name: str) -> None:
        if self.con is None:
            raise RuntimeError("Build the warehouse before executing SQL.")
        path = SQL_DIR / name
        if path.suffix != ".sql":
            path = SQL_DIR / f"{name}.sql"
        execute_sql_file(self.con, path)

    def _connect(self) -> None:
        if self.con is not None:
            return
        if str(self.database) != ":memory:":
            self.database.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.database))

    def _drop_published(self) -> None:
        for name in DROP_VIEWS:
            self.con.execute(f"DROP VIEW IF EXISTS {name}")
        for name in DROP_TABLES:
            self.con.execute(f"DROP TABLE IF EXISTS {name}")


def execute_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    for statement in split_sql(path.read_text(encoding="utf-8")):
        try:
            con.execute(statement)
        except Exception as exc:
            preview = " ".join(statement.strip().split())[:180]
            raise RuntimeError(f"{path.name} failed at: {preview}") from exc


def split_sql(script: str) -> list[str]:
    statements = []
    current: list[str] = []
    for line in script.splitlines():
        current.append(line)
        if line.rstrip().endswith(";"):
            statement = "\n".join(current).strip()
            if statement.strip(";\n\t "):
                statements.append(statement)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def certify(con: duckdb.DuckDBPyConnection, summary: dict) -> None:
    """Fail the publish when a certified figure moves."""
    expect(summary["gross_sales"], GROSS_SALES, "gross sales")
    expect(summary["return_amount"], RETURN_AMOUNT, "returns")
    expect(summary["net_sales"], NET_SALES, "net sales")
    expect(summary["average_order_gross"], AVERAGE_ORDER_GROSS, "average order gross")
    expect(summary["order_count"], ORDER_COUNT, "orders")
    expect(summary["line_count"], FACT_ROWS, "sales lines")
    expect(summary["units_sold"], UNITS_SOLD, "units sold")
    expect(summary["units_returned"], UNITS_RETURNED, "units returned")
    expect(summary["fact_rows"], FACT_ROWS, "fact rows")

    _expect_query(
        con,
        "SELECT COUNT(*) FROM surrogate_registry WHERE entity_name = 'customer'",
        CUSTOMER_REGISTRY_ROWS,
        "customer registry",
    )
    _expect_query(
        con,
        "SELECT COUNT(*) FROM surrogate_registry WHERE entity_name = 'product'",
        PRODUCT_REGISTRY_ROWS,
        "product registry",
    )
    _expect_query(con, "SELECT COUNT(*) FROM dim_date", DATE_ROWS, "date rows")
    _expect_query(
        con,
        "SELECT customer_key FROM dim_customer WHERE customer_id = 'C100'",
        C100_KEY,
        "C100 key",
    )
    _expect_query(
        con,
        """
        SELECT customer_key FROM dim_customer
        WHERE customer_id = 'C101' AND version_number = 1
        """,
        C101_VERSION_1_KEY,
        "C101 version 1",
    )
    _expect_query(
        con,
        """
        SELECT customer_key FROM dim_customer
        WHERE customer_id = 'C101' AND version_number = 2
        """,
        C101_VERSION_2_KEY,
        "C101 version 2",
    )
    _expect_query(
        con,
        "SELECT customer_key FROM dim_customer WHERE customer_id = 'C050'",
        C050_KEY,
        "C050 key",
    )
    _expect_query(
        con,
        """
        SELECT product_key FROM dim_product
        WHERE product_id = 'P104' AND version_number = 1
        """,
        P104_VERSION_1_KEY,
        "P104 version 1",
    )
    _expect_query(
        con,
        """
        SELECT product_key FROM dim_product
        WHERE product_id = 'P104' AND version_number = 2
        """,
        P104_VERSION_2_KEY,
        "P104 version 2",
    )
    _expect_query(
        con,
        "SELECT COUNT(*) FROM fct_sales_order_lines WHERE customer_key < 0 OR product_key < 0",
        0,
        "unknown keys on the sales fact",
    )
    _expect_query(
        con,
        "SELECT customer_key FROM dim_customer WHERE customer_id = 'UNKNOWN'",
        UNKNOWN_KEY,
        "unknown customer",
    )
    _expect_query(
        con,
        """
        SELECT gross_amount FROM fct_sales_order_lines WHERE order_line_id = 'OL-1001-1'
        """,
        Decimal("749.00"),
        "OL-1001-1",
    )
    _expect_query(
        con,
        """
        SELECT customers.customer_segment
        FROM fct_sales_order_lines AS facts
        JOIN dim_customer AS customers ON customers.customer_key = facts.customer_key
        WHERE facts.order_line_id = 'OL-1002-1'
        """,
        "Consumer",
        "C101 sale segment",
    )
    _expect_query(
        con,
        """
        SELECT products.category
        FROM fct_sales_order_lines AS facts
        JOIN dim_product AS products ON products.product_key = facts.product_key
        WHERE facts.order_line_id = 'OL-1003-1'
        """,
        "Electronics Accessories",
        "P104 sale category",
    )
    _expect_query(
        con,
        "SELECT COALESCE(SUM(amount), 0) FROM gold_suspense WHERE reason = 'unknown_customer'",
        SUSPENSE_AMOUNT,
        "suspense",
    )
    _expect_query(
        con,
        "SELECT COUNT(*) FROM gold_suspense WHERE reason <> 'unknown_customer'",
        0,
        "unexpected suspense",
    )
    _expect_query(
        con,
        "SELECT COALESCE(SUM(gross_amount), 0) FROM mart_sales_by_day_category",
        GROSS_SALES,
        "daily mart",
    )
    _expect_query(
        con,
        "SELECT COALESCE(SUM(gross_amount), 0) FROM mart_sales_by_day_category WHERE is_weekend",
        WEEKEND_GROSS,
        "weekend gross",
    )
    _expect_query(
        con,
        "SELECT as_was_revenue FROM cmp_category_history WHERE category = 'Smartphones'",
        SMARTPHONES,
        "smartphones",
    )
    _expect_query(
        con,
        "SELECT as_was_revenue FROM cmp_category_history WHERE category = 'Electronics Accessories'",
        ACCESSORIES_AS_WAS,
        "accessories as sold",
    )
    _expect_query(
        con,
        "SELECT as_is_revenue FROM cmp_category_history WHERE category = 'Electronics Accessories'",
        ACCESSORIES_AS_IS,
        "accessories as currently classified",
    )
    _expect_query(
        con,
        "SELECT as_is_revenue FROM cmp_category_history WHERE category = 'Power'",
        POWER_AS_IS,
        "power as currently classified",
    )
    _expect_query(
        con,
        "SELECT as_was_revenue FROM cmp_category_history WHERE category = 'Home Appliances'",
        HOME_APPLIANCES,
        "home appliances",
    )
    _expect_query(
        con,
        "SELECT as_was_revenue FROM cmp_category_history WHERE category = 'Personal Care'",
        PERSONAL_CARE,
        "personal care",
    )
    _expect_query(
        con,
        """
        SELECT revenue FROM cmp_smartphone_segment_history
        WHERE reading = 'as_was' AND customer_segment = 'Consumer'
        """,
        CONSUMER_PHONES_AS_WAS,
        "consumer phones as sold",
    )
    _expect_query(
        con,
        """
        SELECT revenue FROM cmp_smartphone_segment_history
        WHERE reading = 'as_was' AND customer_segment = 'Business'
        """,
        BUSINESS_PHONES_AS_WAS,
        "business phones as sold",
    )
    _expect_query(
        con,
        """
        SELECT revenue FROM cmp_smartphone_segment_history
        WHERE reading = 'as_is' AND customer_segment = 'Consumer'
        """,
        CONSUMER_PHONES_AS_IS,
        "consumer phones as current segment",
    )
    _expect_query(
        con,
        """
        SELECT revenue FROM cmp_smartphone_segment_history
        WHERE reading = 'as_is' AND customer_segment = 'Business'
        """,
        BUSINESS_PHONES_AS_IS,
        "business phones as current segment",
    )
    _expect_query(
        con,
        "SELECT sale_customer_key FROM scenario_c101_phone_return",
        C101_VERSION_1_KEY,
        "scenario sale key",
    )
    _expect_query(
        con,
        "SELECT return_customer_key FROM scenario_c101_phone_return",
        C101_VERSION_2_KEY,
        "scenario return key",
    )
    _expect_query(
        con,
        "SELECT gross_amount FROM scenario_c101_phone_return",
        C101_PHONE,
        "scenario amount",
    )
    _expect_query(
        con,
        """
        SELECT COUNT(*) FROM cmp_original_customer_keys
        WHERE row_number_key <> durable_key
        """,
        0,
        "original keys drifted from their first row numbers",
    )
    _expect_query(
        con,
        """
        SELECT row_number_if_rebuilt FROM cmp_fragile_customer_keys
        WHERE customer_id = 'C100'
        """,
        2,
        "rebuilt row number for C100",
    )
    _expect_query(
        con,
        "SELECT durable_key FROM cmp_fragile_customer_keys WHERE customer_id = 'C100'",
        C100_KEY,
        "durable C100 after C050 arrives",
    )
    _expect_query(
        con,
        "SELECT product_key FROM fct_sales_order_lines WHERE order_line_id = 'OL-1003-1'",
        P104_VERSION_1_KEY,
        "P104 fact key",
    )
    overlaps = con.execute(
        """
        SELECT COUNT(*)
        FROM dim_customer AS older
        JOIN dim_customer AS newer
          ON older.customer_id = newer.customer_id
         AND older.customer_key <> newer.customer_key
         AND older.effective_from <= COALESCE(newer.effective_to, DATE '9999-12-31')
         AND newer.effective_from <= COALESCE(older.effective_to, DATE '9999-12-31')
        """
    ).fetchone()[0]
    expect(overlaps, 0, "overlapping customer versions")


def expect(actual, expected, label: str) -> None:
    if _same(actual, expected):
        return
    raise AssertionError(f"{label}: published {actual}, expected {expected}.")


def _expect_query(con: duckdb.DuckDBPyConnection, sql: str, expected, label: str) -> None:
    row = con.execute(sql).fetchone()
    if row is None:
        raise AssertionError(f"{label}: query returned no row.")
    expect(row[0], expected, label)


def _same(actual, expected) -> bool:
    if isinstance(expected, Decimal):
        return _money(actual) == expected
    if isinstance(expected, int) and not isinstance(expected, bool):
        return int(actual) == expected
    return actual == expected


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _load_inputs(con: duckdb.DuckDBPyConnection, frames: dict[str, pd.DataFrame], changes: dict[str, list[dict]]) -> None:
    _replace_frame(
        con,
        "silver_sales",
        frames["sales"],
        """
        SELECT
            order_line_id,
            order_id,
            customer_id,
            product_id,
            CAST(quantity AS INTEGER) AS quantity,
            CAST(unit_price AS DECIMAL(12, 2)) AS unit_price,
            CAST(gross_amount AS DECIMAL(12, 2)) AS gross_amount,
            CAST(order_date AS DATE) AS order_date,
            currency
        FROM silver_sales_input
        """,
    )
    _replace_frame(
        con,
        "silver_customers",
        frames["customers"],
        """
        SELECT
            customer_id,
            customer_name,
            country_code,
            customer_segment,
            CAST(source_updated_at AS DATE) AS source_updated_at
        FROM silver_customers_input
        """,
    )
    _replace_frame(
        con,
        "silver_products",
        frames["products"],
        """
        SELECT
            product_id,
            sku,
            product_name,
            category,
            subcategory,
            enrichment_method,
            CAST(source_updated_at AS DATE) AS source_updated_at
        FROM silver_products_input
        """,
    )
    _replace_frame(
        con,
        "customer_changes",
        pd.DataFrame(changes["customer_changes"]),
        """
        SELECT customer_id, change_type, attribute, new_value,
               CAST(effective_from AS DATE) AS effective_from, reason
        FROM customer_changes_input
        """,
    )
    _replace_frame(
        con,
        "new_customers",
        pd.DataFrame(changes["new_customers"]),
        """
        SELECT customer_id, customer_name, country_code, customer_segment,
               CAST(effective_from AS DATE) AS effective_from, reason
        FROM new_customers_input
        """,
    )
    _replace_frame(
        con,
        "product_changes",
        pd.DataFrame(changes["product_changes"]),
        """
        SELECT product_id, change_type, attribute, new_value,
               CAST(effective_from AS DATE) AS effective_from, reason
        FROM product_changes_input
        """,
    )
    _replace_frame(
        con,
        "return_events",
        pd.DataFrame(changes["return_events"]),
        """
        SELECT return_id, order_line_id, CAST(quantity AS INTEGER) AS quantity,
               CAST(return_amount AS DECIMAL(12, 2)) AS return_amount,
               CAST(return_date AS DATE) AS return_date, reason
        FROM return_events_input
        """,
    )
    _replace_frame(
        con,
        "late_sales",
        pd.DataFrame(changes["late_sales"]),
        """
        SELECT order_line_id, order_id, customer_id, product_id,
               CAST(quantity AS INTEGER) AS quantity,
               CAST(unit_price AS DECIMAL(12, 2)) AS unit_price,
               CAST(order_date AS DATE) AS order_date
        FROM late_sales_input
        """,
    )


def _replace_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, select_sql: str) -> None:
    prepared = frame.copy()
    for column in prepared.columns:
        prepared[column] = prepared[column].map(_cell_text)
    con.register(f"{table}_input", prepared)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS {select_sql}")
    con.unregister(f"{table}_input")


def _cell_text(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, Decimal)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value
