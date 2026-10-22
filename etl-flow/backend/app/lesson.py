"""One lesson: load rows newer than 4 July 2026, then type them into stg_."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from app import catalog, mongo_src
from app.catalog import iso, parse_iso
from app.db import SQL_ROOT, DatabaseUnavailable, connect, connection_target, one_statement, sql_statements
from app.lesson_data import CUSTOMERS, CUTOFF, CUTOFF_TEXT, PAGE_LIMIT, PRODUCTS, WATCH_KEYS

PIPELINE = "source_to_stg"
DESCRIPTION = (
    "Four steps. Each one runs, then the screen waits. "
    "The watermark is 4 July 2026. Accounts, the catalog API, and MongoDB "
    "load only newer rows into the data lake. SQL then copies those rows into stg_."
)

STAGE_SQL = SQL_ROOT / "staging" / "010_stg_changes.sql"
STRUCTURED_SQL = SQL_ROOT / "extract" / "structured_customer.sql"
_CUSTOMER_STG_INSERT = """
INSERT INTO stg.stg_customer (
    batch_id, landing_id, customer_email_pk_id,
    country, region, customer_segment, account_plan, account_status, preferred_currency,
    source_updated_at
)
SELECT
    r.batch_id,
    r.landing_id,
    md5(lower(btrim(r.payload->>'email_address'))),
    r.payload->>'country',
    r.payload->>'region',
    r.payload->>'customer_segment',
    r.payload->>'account_plan',
    r.payload->>'account_status',
    r.payload->>'preferred_currency',
    r.source_updated_at
FROM accounts.raw_customer r
WHERE NOT EXISTS (
    SELECT 1
    FROM stg.stg_customer s
    WHERE s.batch_id = r.batch_id
      AND s.customer_email_pk_id = md5(lower(btrim(r.payload->>'email_address')))
)
"""
_CUSTOMER_FIELDS = """
    batch_id, customer_email_pk_id, country, region, customer_segment,
    account_plan, account_status, preferred_currency, source_updated_at
"""
_REPORTING_CUSTOMER_INSERT = """
INSERT INTO reportingdw.stg_customer (
    customer_email_pk_id, country, region, customer_segment,
    account_plan, account_status, preferred_currency, source_updated_at, batch_id
)
SELECT DISTINCT ON (customer_email_pk_id)
    customer_email_pk_id, country, region, customer_segment,
    account_plan, account_status, preferred_currency, source_updated_at, batch_id
FROM stg.stg_customer
WHERE customer_email_pk_id NOT IN (
    SELECT customer_email_pk_id FROM reportingdw.stg_customer
)
ORDER BY customer_email_pk_id, source_updated_at
RETURNING
    batch_id, customer_email_pk_id, country, region, customer_segment,
    account_plan, account_status, preferred_currency, source_updated_at
"""


class LessonFinished(Exception):
    """The four steps have already run."""


class SourceRejected(Exception):
    """A source row the lesson will not add."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
_PRICE = re.compile(r"^\d+\.\d{2}$")


@dataclass(frozen=True)
class StepSpec:
    id: str
    index: int
    title: str
    layer: str
    summary: str
    rules: tuple[str, ...]
    action: str
    source: str | None = None
    script: str | None = None


STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        id="accounts",
        index=2,
        title="Accounts",
        layer="Structured",
        summary="Load accounts newer than the watermark.",
        rules=(
            "Read ops.customer_account.",
            "Keep a row when (updated_at, email_address) is after the watermark.",
            "Store that document in accounts.raw_customer.",
        ),
        action="extract",
        source="structured",
        script="extract/structured_customer.sql",
    ),
    StepSpec(
        id="catalog",
        index=3,
        title="Catalog",
        layer="API",
        summary="Ask the catalog API, then store its JSON.",
        rules=(
            "GET /api/sources/catalog with the watermark.",
            "The extractor does not query the product table.",
            "Store the response in catalog.raw_catalog.",
        ),
        action="extract",
        source="api",
        script="extract/catalog_product.sql",
    ),
    StepSpec(
        id="orders",
        index=4,
        title="Orders",
        layer="MongoDB",
        summary="Load MongoDB orders newer than the watermark.",
        rules=(
            "Read etl_lesson.order_events.",
            "Keep a document when (updated_at, order_id) is after the watermark.",
            "Store it in orders.raw_order.",
        ),
        action="extract",
        source="mongo",
        script="extract/mongo_order.txt",
    ),
    StepSpec(
        id="stage",
        index=5,
        title="Stage",
        layer="stg_",
        summary="Copy the loaded rows into stg_.",
        rules=(
            "The SQL reads only the batches from the three extracts.",
            "It writes stg_customer, stg_catalog, and stg_order.",
            "Older source rows are not in these tables.",
        ),
        action="stage",
        script="staging/010_stg_changes.sql",
    ),
)

SOURCE_STAGE = StepSpec(
    id="sources",
    index=1,
    title="Sources",
    layer="Sources",
    summary="Twelve rows. The ones after 4 July 2026 will load.",
    rules=(
        "Watermark: 2026-07-04T00:00:00Z.",
        "Rows on or before that time stay where they are.",
        "Next, each source loads on its own, and the screen waits.",
    ),
    action="sources",
)

RAW = {
    "structured": ("accounts", "raw_customer", "email_address", "customer"),
    "api": ("catalog", "raw_catalog", "product_id", "catalog"),
    "mongo": ("orders", "raw_order", "order_id", "order"),
}


def lake_name(source: str) -> str:
    schema, table, _key, _entity = RAW[source]
    return f"{schema}.{table}"
FEED_SOURCE = {"accounts": "structured", "catalog": "api", "orders": "mongo"}
WATERMARK_ENTITY = {"structured": "customer", "api": "catalog", "mongo": "order"}


def catalog_view() -> dict:
    target = connection_target()
    return {
        "pipeline": PIPELINE,
        "description": DESCRIPTION,
        "database": str(target["database"]),
        "mongo_database": mongo_src.DATABASE,
        "cutoff": CUTOFF_TEXT,
        "watch_keys": list(WATCH_KEYS),
        "stages": [_spec_dict(spec) for spec in (SOURCE_STAGE, *STEPS)],
    }


async def live_sources() -> dict:
    pages = await catalog.catalog_pages(True, CUTOFF, "")
    products = [record for page in pages for record in page["records"]]
    with connect() as conn:
        customers = [
            _customer(row)
            for row in conn.execute(
                """
                SELECT
                    email_address, full_name, country, region, customer_segment,
                    account_plan, account_status, preferred_currency, updated_at
                FROM ops.customer_account
                ORDER BY updated_at, email_address
                """
            ).fetchall()
        ]
        loaded = {
            "structured": _loaded_keys(conn, "structured"),
            "api": _loaded_keys(conn, "api"),
            "mongo": _loaded_keys(conn, "mongo"),
        }
    orders = mongo_src.all_payloads()
    records = (
        [_source_row(row, "structured", loaded) for row in customers]
        + [_source_row(row, "api", loaded) for row in products]
        + [_source_row(row, "mongo", loaded) for row in orders]
    )
    logs = [f"SELECT ops.customer_account → {len(customers)} rows"]
    logs.extend(_log(page) for page in pages)
    logs.append(f"find etl_lesson.order_events → {len(orders)} rows")
    return {
        "cutoff": CUTOFF_TEXT,
        "records": records,
        "logs": logs,
        "customers": len(customers),
        "products": len(products),
        "orders": len(orders),
        "feeds": [
            {
                "id": "accounts",
                "name": "Accounts",
                "technology": "PostgreSQL",
                "location": "etl_flow.ops.customer_account",
                "columns": [
                    "email_address",
                    "full_name",
                    "customer_segment",
                    "account_plan",
                    "account_status",
                    "region",
                    "country",
                    "preferred_currency",
                    "updated_at",
                ],
                "rows": customers,
            },
            {
                "id": "catalog",
                "name": "Catalog",
                "technology": "HTTP API",
                "location": "GET /api/sources/catalog",
                "columns": ["product_id", "sku", "category", "list_price", "updated_at"],
                "rows": products,
            },
            {
                "id": "orders",
                "name": "Orders",
                "technology": "MongoDB",
                "location": "etl_lesson.order_events",
                "columns": ["order_id", "email_address", "sku", "status", "quantity", "updated_at"],
                "rows": orders,
            },
        ],
    }


def add_source_row(feed_id: str, fields: dict) -> None:
    """Insert one row into a source. The lake is unchanged until the next extract."""
    updated = fields.get("updated_at")
    if not isinstance(updated, str) or not updated.strip():
        raise SourceRejected("updated_at is required")
    try:
        stamp = parse_iso(updated.strip())
    except ValueError as exc:
        raise SourceRejected(str(exc)) from exc
    if feed_id == "accounts":
        email_address = _email(fields.get("email_address"))
        profile = _profile(fields)
        with connect() as conn:
            if conn.execute(
                "SELECT 1 FROM ops.customer_account WHERE email_address = %s",
                (email_address,),
            ).fetchone():
                raise SourceRejected(f"{email_address} is already in ops.customer_account", 409)
            conn.execute(
                """
                INSERT INTO ops.customer_account (
                    email_address, full_name, country, region, customer_segment,
                    account_plan, account_status, preferred_currency, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    email_address,
                    profile["full_name"],
                    profile["country"],
                    profile["region"],
                    profile["customer_segment"],
                    profile["account_plan"],
                    profile["account_status"],
                    profile["preferred_currency"],
                    stamp,
                ),
            )
        return
    if feed_id == "catalog":
        product_id = _token(fields.get("product_id"), "product_id")
        sku = _label(fields.get("sku"), "sku")
        category = _category(fields.get("category"))
        price = fields.get("list_price")
        if not isinstance(price, str) or not _PRICE.fullmatch(price.strip()):
            raise SourceRejected("list_price must be a two-decimal amount, such as 12.50")
        with connect() as conn:
            if conn.execute(
                "SELECT 1 FROM ops.catalog_product WHERE product_id = %s",
                (product_id,),
            ).fetchone():
                raise SourceRejected(f"{product_id} is already in ops.catalog_product", 409)
            conn.execute(
                """
                INSERT INTO ops.catalog_product (product_id, sku, category, list_price, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (product_id, sku, category, price.strip(), stamp),
            )
        return
    if feed_id == "orders":
        order_id = _token(fields.get("order_id"), "order_id")
        email_address = _email(fields.get("email_address"))
        sku = _label(fields.get("sku"), "sku")
        status = _label(fields.get("status"), "status")
        quantity = fields.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise SourceRejected("quantity must be a positive integer")
        if mongo_src.order_exists(order_id):
            raise SourceRejected(f"{order_id} is already in etl_lesson.order_events", 409)
        mongo_src.insert_order(
            {
                "order_id": order_id,
                "email_address": email_address,
                "sku": sku,
                "status": status,
                "quantity": quantity,
                "updated_at": updated.strip(),
            }
        )
        return
    raise SourceRejected(f"Unknown source {feed_id}")


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
        raise SourceRejected(f"{name} must be letters, digits, or ._-")
    return value.strip()


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not _LABEL.fullmatch(value.strip()):
        raise SourceRejected(f"{name} is required")
    return value.strip()


def _email(value: object) -> str:
    if not isinstance(value, str) or not _EMAIL.fullmatch(value.strip()):
        raise SourceRejected("email_address must contain @")
    return value.strip().lower()


def _profile(fields: dict) -> dict:
    names = (
        "full_name",
        "country",
        "region",
        "customer_segment",
        "account_plan",
        "account_status",
        "preferred_currency",
    )
    return {name: _label(fields.get(name), name) for name in names}


def _category(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "General"
    return _label(value, "category")


async def advance() -> dict:
    started = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        run_id = _open_run(conn, started)
        done = {
            row["step_id"]
            for row in conn.execute("SELECT step_id FROM lesson.step WHERE run_id = %s", (run_id,))
        }
        spec = next((step for step in STEPS if step.id not in done), None)
        if spec is None:
            raise LessonFinished(_finished_message())
        if spec.action == "extract":
            await _extract(conn, run_id, spec, started)
        else:
            _stage(conn, run_id, spec, started)
        if spec.id == STEPS[-1].id:
            conn.execute(
                "UPDATE lesson.run SET status = 'succeeded', finished_at = %s WHERE run_id = %s",
                (datetime.now(timezone.utc), run_id),
            )
        return _build(conn, run_id)


def lake_view() -> dict:
    tables = []
    with connect() as conn:
        for feed_id, source in FEED_SOURCE.items():
            tables.append(
                {
                    "feed_id": feed_id,
                    "lake_table": lake_name(source),
                    "rows": _all_physical(conn, source),
                }
            )
    return {"tables": tables}


async def insert_after(feed_id: str, updated_at: str) -> dict:
    """Insert source rows newer than updated_at. Rows already stored are left unchanged."""
    source = FEED_SOURCE[feed_id]
    cursor_at = parse_iso(updated_at)
    key_name = RAW[source][2]
    incoming = None
    if source == "api":
        pages = await catalog.catalog_pages(False, cursor_at, "")
        incoming = [record for page in pages for record in page["records"]]
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        if source == "structured":
            incoming, _request = _structured_page(conn, cursor_at, "")
        elif source == "mongo":
            incoming = mongo_src.fetch_changed(cursor_at, "")
        present = _loaded_keys(conn, source)
        fresh = []
        already = []
        for record in incoming or []:
            key = record[key_name]
            if key in present:
                already.append(key)
            else:
                fresh.append(record)
        batch_id = f"b-{uuid4().hex[:8]}"
        if fresh:
            _insert_raw(conn, source, batch_id, batch_id, datetime.now(timezone.utc), fresh)
        rows = _all_physical(conn, source)
    inserted_keys = {record[key_name] for record in fresh}
    return {
        "feed_id": feed_id,
        "lake_table": lake_name(source),
        "cursor_updated_at": iso(cursor_at),
        "inserted": [row for row in rows if row["batch_id"] == batch_id and row["business_key"] in inserted_keys],
        "already_stored": already,
        "rows": rows,
    }


def customer_stage(*, write: bool) -> dict:
    """Hash account emails into a PII-free Silver row, then copy it to reportingdw."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        inserted_stg: list[dict] = []
        inserted_reporting: list[dict] = []
        if write:
            inserted_stg = [
                _customer_row(row)
                for row in conn.execute(
                    _CUSTOMER_STG_INSERT + f" RETURNING {_CUSTOMER_FIELDS}"
                ).fetchall()
            ]
            inserted_reporting = [
                _customer_row(row) for row in conn.execute(_REPORTING_CUSTOMER_INSERT).fetchall()
            ]
            _index_reporting_customers(conn)
        return {
            "stg_table": "stg.stg_customer",
            "inserted_stg": inserted_stg,
            "stg_rows": [
                _customer_row(row)
                for row in conn.execute(
                    f"""
                    SELECT {_CUSTOMER_FIELDS}
                    FROM stg.stg_customer
                    ORDER BY source_updated_at, customer_email_pk_id
                    """
                ).fetchall()
            ],
            "reporting_table": "reportingdw.stg_customer",
            "inserted_reporting": inserted_reporting,
            "reporting_rows": [
                _customer_row(row)
                for row in conn.execute(
                    f"""
                    SELECT {_CUSTOMER_FIELDS}
                    FROM reportingdw.stg_customer
                    ORDER BY customer_email_pk_id
                    """
                ).fetchall()
            ],
            "indexes": [
                {
                    "schema_name": row["schemaname"],
                    "index_name": row["indexname"],
                    "definition": row["indexdef"],
                }
                for row in conn.execute(
                    """
                    SELECT schemaname, indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'reportingdw' AND tablename = 'stg_customer'
                    ORDER BY indexname
                    """
                ).fetchall()
            ],
        }


def _customer_row(row: dict) -> dict:
    return {
        "batch_id": row["batch_id"],
        "customer_email_pk_id": row["customer_email_pk_id"],
        "country": row["country"],
        "region": row["region"],
        "customer_segment": row["customer_segment"],
        "account_plan": row["account_plan"],
        "account_status": row["account_status"],
        "preferred_currency": row["preferred_currency"],
        "source_updated_at": iso(row["source_updated_at"]),
    }


def _customer_columns(row: dict) -> list[tuple[str, object]]:
    return [
        ("customer_email_pk_id", row["customer_email_pk_id"]),
        ("country", row["country"]),
        ("region", row["region"]),
        ("customer_segment", row["customer_segment"]),
        ("account_plan", row["account_plan"]),
        ("account_status", row["account_status"]),
        ("preferred_currency", row["preferred_currency"]),
    ]


def stage_board() -> dict:
    with connect() as conn:
        return _stage_board(conn, inserted_keys=[])


def stage_feed(feed_id: str) -> dict:
    """Copy one lake table into its stg_ table. Staging does not join."""
    if feed_id not in FEED_SOURCE:
        raise KeyError(feed_id)
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        inserted = _insert_stg(conn, feed_id)
        if feed_id == "accounts":
            _insert_reporting_customers(conn)
            _index_reporting_customers(conn)
        return _stage_board(conn, inserted_keys=inserted)


def _insert_stg(conn, feed_id: str) -> list[str]:
    if feed_id == "accounts":
        rows = conn.execute(_CUSTOMER_STG_INSERT + " RETURNING customer_email_pk_id").fetchall()
        return [row["customer_email_pk_id"] for row in rows]
    if feed_id == "catalog":
        rows = conn.execute(
            """
            INSERT INTO stg.stg_catalog (
                batch_id, product_id, sku, category, list_price, source_updated_at
            )
            SELECT
                r.batch_id,
                r.payload->>'product_id',
                r.payload->>'sku',
                r.payload->>'category',
                (r.payload->>'list_price')::numeric(12, 2),
                r.source_updated_at
            FROM catalog.raw_catalog r
            WHERE NOT EXISTS (
                SELECT 1 FROM stg.stg_catalog s
                WHERE s.batch_id = r.batch_id AND s.product_id = r.payload->>'product_id'
            )
            RETURNING product_id
            """
        ).fetchall()
        return [row["product_id"] for row in rows]
    rows = conn.execute(
        """
        INSERT INTO stg.stg_order (
            batch_id, order_id, customer_email_pk_id,
            sku, status, quantity, source_updated_at
        )
        SELECT
            r.batch_id,
            r.payload->>'order_id',
            md5(lower(btrim(r.payload->>'email_address'))),
            r.payload->>'sku',
            r.payload->>'status',
            (r.payload->>'quantity')::integer,
            r.source_updated_at
        FROM orders.raw_order r
        WHERE NOT EXISTS (
            SELECT 1 FROM stg.stg_order s
            WHERE s.batch_id = r.batch_id AND s.order_id = r.payload->>'order_id'
        )
        RETURNING order_id
        """
    ).fetchall()
    return [row["order_id"] for row in rows]


def _insert_reporting_customers(conn) -> None:
    conn.execute(_REPORTING_CUSTOMER_INSERT).fetchall()


def _index_reporting_customers(conn) -> None:
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS stg_customer_country_idx
        ON reportingdw.stg_customer (country)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS stg_customer_segment_idx
        ON reportingdw.stg_customer (customer_segment)
        """
    )


def publish_model() -> dict:
    """Insert dim_ rows from each stg_ table, then fct_order. Stored keys stay."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        _insert_dimensions(conn)
        _insert_fact(conn)
        _create_model_indexes(conn)
        return _stage_board(conn, inserted_keys=[])


def _insert_dimensions(conn) -> None:
    conn.execute(
        """
        INSERT INTO reportingdw.dim_customer (
            customer_key, customer_email_pk_id, country, region, customer_segment,
            account_plan, account_status, preferred_currency, source_updated_at, batch_id
        )
        SELECT DISTINCT ON (customer_email_pk_id)
            customer_email_pk_id,
            customer_email_pk_id, country, region, customer_segment,
            account_plan, account_status, preferred_currency, source_updated_at, batch_id
        FROM stg.stg_customer
        WHERE customer_email_pk_id NOT IN (
            SELECT customer_email_pk_id FROM reportingdw.dim_customer
        )
        ORDER BY customer_email_pk_id, source_updated_at
        """
    )
    conn.execute(
        """
        INSERT INTO reportingdw.dim_product (
            product_key, product_id, sku, category, list_price, source_updated_at, batch_id
        )
        SELECT DISTINCT ON (product_id)
            md5(product_id || '|' || sku || '|' || to_char(list_price, 'FM999999990.00')),
            product_id, sku, category, list_price, source_updated_at, batch_id
        FROM stg.stg_catalog
        WHERE product_id NOT IN (SELECT product_id FROM reportingdw.dim_product)
          AND sku NOT IN (SELECT sku FROM reportingdw.dim_product)
          AND product_id = (
              SELECT earliest.product_id
              FROM stg.stg_catalog earliest
              WHERE earliest.sku = stg.stg_catalog.sku
              ORDER BY earliest.source_updated_at, earliest.product_id
              LIMIT 1
          )
        ORDER BY product_id, source_updated_at
        """
    )
    conn.execute(
        """
        INSERT INTO reportingdw.dim_date (
            date_key, calendar_date, year_number, month_number, day_number
        )
        SELECT
            md5(to_char(day::date, 'YYYY-MM-DD')),
            day::date,
            EXTRACT(YEAR FROM day)::integer,
            EXTRACT(MONTH FROM day)::integer,
            EXTRACT(DAY FROM day)::integer
        FROM (
            SELECT generate_series(first_day, last_day, interval '1 day') AS day
            FROM (
                SELECT
                    min((source_updated_at AT TIME ZONE 'UTC')::date) AS first_day,
                    max((source_updated_at AT TIME ZONE 'UTC')::date) AS last_day
                FROM stg.stg_order
            ) bounds
            WHERE first_day IS NOT NULL AND last_day IS NOT NULL
        ) days
        WHERE NOT EXISTS (
            SELECT 1
            FROM reportingdw.dim_date existing
            WHERE existing.date_key = md5(to_char(day::date, 'YYYY-MM-DD'))
        )
        """
    )


def _insert_fact(conn) -> None:
    conn.execute(
        """
        INSERT INTO reportingdw.fct_order (
            order_id, customer_key, product_key, order_date_key,
            quantity, unit_price, extended_amount, status, batch_id
        )
        SELECT
            o.order_id,
            c.customer_key,
            p.product_key,
            md5(to_char((o.source_updated_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD')),
            o.quantity,
            p.list_price,
            (o.quantity * p.list_price)::numeric(12, 2),
            o.status,
            o.batch_id
        FROM (
            SELECT DISTINCT ON (order_id)
                order_id, customer_email_pk_id, sku,
                quantity, status, source_updated_at, batch_id
            FROM stg.stg_order
            ORDER BY order_id, source_updated_at
        ) o
        JOIN reportingdw.dim_customer c
          ON c.customer_email_pk_id = o.customer_email_pk_id
        JOIN reportingdw.dim_product p ON p.sku = o.sku
        WHERE NOT EXISTS (
            SELECT 1 FROM reportingdw.fct_order f WHERE f.order_id = o.order_id
        )
        """
    )


def _create_model_indexes(conn) -> None:
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS dim_customer_country_idx
        ON reportingdw.dim_customer (country)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS dim_customer_segment_idx
        ON reportingdw.dim_customer (customer_segment)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS dim_product_sku_idx
        ON reportingdw.dim_product (sku)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS fct_order_customer_key_idx
        ON reportingdw.fct_order (customer_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS fct_order_product_key_idx
        ON reportingdw.fct_order (product_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS fct_order_order_date_key_idx
        ON reportingdw.fct_order (order_date_key)
        """
    )


def _stage_board(conn, inserted_keys: list[str]) -> dict:
    accounts = conn.execute(
        f"""
        SELECT {_CUSTOMER_FIELDS}
        FROM stg.stg_customer
        ORDER BY source_updated_at, customer_email_pk_id
        """
    ).fetchall()
    catalog_rows = conn.execute(
        """
        SELECT batch_id, product_id, sku, category, list_price
        FROM stg.stg_catalog
        ORDER BY source_updated_at, product_id
        """
    ).fetchall()
    orders = conn.execute(
        """
        SELECT batch_id, order_id, customer_email_pk_id, sku, status, quantity
        FROM stg.stg_order
        ORDER BY source_updated_at, order_id
        """
    ).fetchall()
    reporting = conn.execute(
        f"""
        SELECT {_CUSTOMER_FIELDS}
        FROM reportingdw.stg_customer
        ORDER BY customer_email_pk_id
        """
    ).fetchall()
    indexes = conn.execute(
        """
        SELECT schemaname, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'reportingdw' AND tablename = 'stg_customer'
        ORDER BY indexname
        """
    ).fetchall()
    customers = conn.execute(
        """
        SELECT
            customer_key, customer_email_pk_id, country, region, customer_segment,
            account_plan, account_status, preferred_currency, batch_id
        FROM reportingdw.dim_customer
        ORDER BY customer_email_pk_id
        """
    ).fetchall()
    products = conn.execute(
        """
        SELECT product_key, product_id, sku, category, list_price, batch_id
        FROM reportingdw.dim_product
        ORDER BY product_id
        """
    ).fetchall()
    dates = conn.execute(
        """
        SELECT date_key, calendar_date, year_number, month_number, day_number
        FROM reportingdw.dim_date
        ORDER BY calendar_date
        """
    ).fetchall()
    facts = conn.execute(
        """
        SELECT
            order_id, customer_key, product_key, order_date_key,
            quantity, unit_price, extended_amount, status, batch_id
        FROM reportingdw.fct_order
        ORDER BY order_id
        """
    ).fetchall()
    unresolved = conn.execute(
        """
        SELECT o.order_id
        FROM stg.stg_order o
        WHERE NOT EXISTS (
            SELECT 1 FROM reportingdw.fct_order f WHERE f.order_id = o.order_id
        )
        AND (
            NOT EXISTS (
                SELECT 1
                FROM reportingdw.dim_customer c
                WHERE c.customer_email_pk_id = o.customer_email_pk_id
            )
            OR NOT EXISTS (
                SELECT 1 FROM reportingdw.dim_product p WHERE p.sku = o.sku
            )
        )
        ORDER BY o.order_id
        """
    ).fetchall()
    skipped = conn.execute(
        """
        SELECT DISTINCT s.product_id
        FROM stg.stg_catalog s
        WHERE NOT EXISTS (
            SELECT 1 FROM reportingdw.dim_product d WHERE d.product_id = s.product_id
        )
        AND EXISTS (
            SELECT 1 FROM reportingdw.dim_product d WHERE d.sku = s.sku
        )
        ORDER BY s.product_id
        """
    ).fetchall()
    model_indexes = conn.execute(
        """
        SELECT schemaname, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'reportingdw'
          AND tablename IN ('dim_customer', 'dim_product', 'dim_date', 'fct_order')
        ORDER BY tablename, indexname
        """
    ).fetchall()
    return {
        "feeds": [
            {
                "feed_id": "accounts",
                "stg_table": "stg.stg_customer",
                "lake_table": "accounts.raw_customer",
                "rows": [
                    _line(
                        row["customer_email_pk_id"],
                        f"{row['customer_segment']} · {row['region']}",
                        row["batch_id"],
                        _customer_columns(row),
                    )
                    for row in accounts
                ],
            },
            {
                "feed_id": "catalog",
                "stg_table": "stg.stg_catalog",
                "lake_table": "catalog.raw_catalog",
                "rows": [
                    _line(
                        row["product_id"],
                        f"{row['sku']} · {_money(row['list_price'])}",
                        row["batch_id"],
                        [
                            ("product_id", row["product_id"]),
                            ("sku", row["sku"]),
                            ("category", row["category"]),
                            ("list_price", row["list_price"]),
                        ],
                    )
                    for row in catalog_rows
                ],
            },
            {
                "feed_id": "orders",
                "stg_table": "stg.stg_order",
                "lake_table": "orders.raw_order",
                "rows": [
                    _line(
                        row["order_id"],
                        f"{row['customer_email_pk_id']} · {row['sku']} · {row['status']}",
                        row["batch_id"],
                        [
                            ("order_id", row["order_id"]),
                            ("customer_email_pk_id", row["customer_email_pk_id"]),
                            ("sku", row["sku"]),
                            ("status", row["status"]),
                            ("quantity", row["quantity"]),
                        ],
                    )
                    for row in orders
                ],
            },
        ],
        "inserted_keys": inserted_keys,
        "reporting_rows": [
            _line(
                row["customer_email_pk_id"],
                f"{row['customer_segment']} · {row['region']}",
                row["batch_id"],
                _customer_columns(row),
            )
            for row in reporting
        ],
        "indexes": [_index(row) for row in indexes],
        "model": [
            {
                "table_name": "reportingdw.dim_customer",
                "kind": "dimension",
                "rows": [
                    _line(
                        row["customer_email_pk_id"],
                        f"{row['customer_segment']} · {row['region']}",
                        row["batch_id"],
                        [("customer_key", row["customer_key"]), *_customer_columns(row)],
                    )
                    for row in customers
                ],
            },
            {
                "table_name": "reportingdw.dim_product",
                "kind": "dimension",
                "rows": [
                    _line(
                        row["product_id"],
                        f"{row['sku']} · {_money(row['list_price'])}",
                        row["batch_id"],
                        [
                            ("product_key", row["product_key"]),
                            ("product_id", row["product_id"]),
                            ("sku", row["sku"]),
                            ("category", row["category"]),
                            ("list_price", row["list_price"]),
                        ],
                    )
                    for row in products
                ],
            },
            {
                "table_name": "reportingdw.dim_date",
                "kind": "dimension",
                "rows": [
                    _line(
                        str(row["date_key"]),
                        _text(row["calendar_date"]),
                        "",
                        [
                            ("date_key", row["date_key"]),
                            ("calendar_date", row["calendar_date"]),
                            ("year_number", row["year_number"]),
                            ("month_number", row["month_number"]),
                            ("day_number", row["day_number"]),
                        ],
                    )
                    for row in dates
                ],
            },
            {
                "table_name": "reportingdw.fct_order",
                "kind": "fact",
                "rows": [
                    _line(
                        row["order_id"],
                        _money(row["extended_amount"]),
                        row["batch_id"],
                        [
                            ("order_id", row["order_id"]),
                            ("customer_key", row["customer_key"]),
                            ("product_key", row["product_key"]),
                            ("order_date_key", row["order_date_key"]),
                            ("quantity", row["quantity"]),
                            ("unit_price", row["unit_price"]),
                            ("extended_amount", row["extended_amount"]),
                            ("status", row["status"]),
                        ],
                    )
                    for row in facts
                ],
            },
        ],
        "model_indexes": [_index(row) for row in model_indexes],
        "unresolved_orders": [row["order_id"] for row in unresolved],
        "skipped_products": [row["product_id"] for row in skipped],
    }


def _line(key: str, detail: str, batch_id: str, columns: list[tuple[str, object]]) -> dict:
    return {
        "key": key,
        "detail": detail,
        "batch_id": batch_id,
        "columns": [{"name": name, "value": _text(value)} for name, value in columns],
    }


def _index(row: dict) -> dict:
    return {
        "schema_name": row["schemaname"],
        "index_name": row["indexname"],
        "definition": row["indexdef"],
    }


def _text(value) -> str:
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def _money(value) -> str:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def reset_lesson() -> None:
    mongo_src.replace_orders()
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('etl-lesson'))")
        conn.execute(
            """
            TRUNCATE
                reportingdw.fct_order,
                reportingdw.dim_customer,
                reportingdw.dim_product,
                reportingdw.dim_date,
                reportingdw.stg_customer,
                stg.stg_customer,
                stg.stg_catalog,
                stg.stg_order,
                accounts.raw_customer,
                catalog.raw_catalog,
                orders.raw_order,
                ingestion.extract_request,
                ingestion.staged_batch,
                ingestion.watermark,
                lesson.step,
                lesson.run
            RESTART IDENTITY
            """
        )
        conn.execute("DELETE FROM ops.customer_account")
        conn.execute("DELETE FROM ops.catalog_product")
        _insert_ops(conn)
        _insert_watermarks(conn)


def ensure_seed() -> None:
    with connect() as conn:
        _insert_ops(conn)
        _fill_profile_defaults(conn)
        _refresh_landed_profiles(conn)
        _lock_profile_columns(conn)
        marks = conn.execute("SELECT count(*) AS n FROM ingestion.watermark").fetchone()["n"]
        if marks < 3:
            _insert_watermarks(conn)
    mongo_src.seed_if_empty()


def get_run(run_id: str) -> dict | None:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM lesson.run WHERE run_id = %s", (run_id,)).fetchone() is None:
            return None
        return _build(conn, run_id)


def latest_run() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT run_id FROM lesson.run ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return get_run(row["run_id"])


def summaries() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                r.run_id,
                r.status,
                r.started_at,
                r.finished_at,
                (SELECT count(*)::int FROM lesson.step s WHERE s.run_id = r.run_id) AS steps_completed
            FROM lesson.run r
            ORDER BY r.started_at DESC
            """
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "steps_completed": row["steps_completed"],
            "step_count": len(STEPS),
        }
        for row in rows
    ]


def destination() -> dict:
    latest = latest_run()
    rows: list[dict] = []
    run_id = None
    if latest is not None:
        run_id = latest["run_id"]
        stage = next((step for step in latest["steps"] if step["id"] == "stage"), None)
        if stage is not None:
            rows = stage["records"]
    return {
        "schema_name": "stg",
        "tables": ["stg_customer", "stg_catalog", "stg_order"],
        "run_id": run_id,
        "rows": rows,
    }


def database_info() -> dict:
    target = connection_target()
    names = (
        ("ops", "customer_account"),
        ("ops", "catalog_product"),
        ("accounts", "raw_customer"),
        ("catalog", "raw_catalog"),
        ("orders", "raw_order"),
        ("stg", "stg_customer"),
        ("stg", "stg_catalog"),
        ("stg", "stg_order"),
        ("ingestion", "watermark"),
    )
    tables = []
    with connect() as conn:
        for schema_name, table_name in names:
            row = conn.execute(
                sql.SQL("SELECT count(*)::int AS n FROM {}.{}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
            ).fetchone()
            tables.append({"schema_name": schema_name, "table_name": table_name, "rows": row["n"]})
    return {
        "host": str(target["host"]),
        "port": int(target["port"]),
        "database": str(target["database"]),
        "user": str(target["user"]),
        "tables": tables,
    }


async def _extract(conn, run_id: str, spec: StepSpec, started: datetime) -> None:
    source = spec.source or ""
    cursor_at, cursor_key = _cursor(conn, source)
    if source == "structured":
        records, request = _structured_page(conn, cursor_at, cursor_key)
        total = conn.execute("SELECT count(*)::int AS n FROM ops.customer_account").fetchone()["n"]
    elif source == "api":
        pages = await catalog.catalog_pages(False, cursor_at, cursor_key)
        records = [record for page in pages for record in page["records"]]
        request = pages[0]
        total = conn.execute("SELECT count(*)::int AS n FROM ops.catalog_product").fetchone()["n"]
    else:
        records = mongo_src.fetch_changed(cursor_at, cursor_key)
        total = len(mongo_src.all_payloads())
        shown = cursor_key or '""'
        request = {
            "method": "find",
            "url": f"order_events where (updated_at, order_id) > ({iso(cursor_at)}, {shown})",
            "status_code": 200,
            "records": records,
        }
    batch_id = _next_batch(conn, run_id)
    _insert_raw(conn, source, run_id, batch_id, datetime.now(timezone.utc), records)
    conn.execute(
        """
        INSERT INTO ingestion.extract_request (
            batch_id, page_number, source_system, method, url, status_code, row_count
        )
        VALUES (%s, 1, %s, %s, %s, %s, %s)
        """,
        (batch_id, source, request["method"], request["url"], request["status_code"], len(records)),
    )
    saved = _save_watermark(conn, source, batch_id)
    logs = [_log(request)]
    logs.append("watermark unchanged" if saved is None else f"watermark saved at {saved[0]}, {saved[1]}")
    _save_step(
        conn,
        run_id,
        spec,
        started,
        batch_id,
        source,
        total,
        len(records),
        max(total - len(records), 0),
        {
            "logs": logs,
            "cursor_updated_at": iso(cursor_at),
            "cursor_key": cursor_key,
            "lake_table": lake_name(source),
        },
    )


def _stage(conn, run_id: str, spec: StepSpec, started: datetime) -> None:
    batches = conn.execute(
        """
        SELECT batch_id, source_system
        FROM lesson.step
        WHERE run_id = %s AND batch_id IS NOT NULL
        ORDER BY step_index
        """,
        (run_id,),
    ).fetchall()
    if len(batches) != 3:
        raise DatabaseUnavailable("Stage runs after the three extracts.")
    conn.execute(
        """
        CREATE TEMP TABLE eltl_batch (
            batch_id text PRIMARY KEY,
            source_system text NOT NULL
        ) ON COMMIT DROP
        """
    )
    _many(
        conn,
        "INSERT INTO eltl_batch (batch_id, source_system) VALUES (%s, %s)",
        [(row["batch_id"], row["source_system"]) for row in batches],
    )
    for statement in sql_statements(STAGE_SQL.read_text(encoding="utf-8")):
        conn.execute(statement)
    now = datetime.now(timezone.utc)
    _many(
        conn,
        "INSERT INTO ingestion.staged_batch (batch_id, stage_step, staged_at) VALUES (%s, %s, %s)",
        [(row["batch_id"], spec.id, now) for row in batches],
    )
    ids = [row["batch_id"] for row in batches]
    loaded = _count_raw(conn, ids)
    _save_step(
        conn,
        run_id,
        spec,
        started,
        None,
        None,
        loaded,
        loaded,
        0,
        {"logs": [f"{loaded} lake rows copied into stg_"], "batch_ids": ids},
    )


def _structured_page(conn, cursor_at: datetime, cursor_key: str) -> tuple[list[dict], dict]:
    rows = conn.execute(one_statement(STRUCTURED_SQL), (cursor_at, cursor_key, PAGE_LIMIT)).fetchall()
    records = [_customer(row) for row in rows]
    shown = cursor_key or '""'
    return records, {
        "method": "SELECT",
        "url": f"ops.customer_account WHERE (updated_at, email_address) > ({iso(cursor_at)}, {shown})",
        "status_code": 200,
        "records": records,
    }


def _insert_raw(conn, source: str, run_id: str, batch_id: str, extracted_at: datetime, records: list[dict]) -> None:
    schema, table, key_name, _entity = RAW[source]
    statement = sql.SQL(
        """
        INSERT INTO {}.{} (
            landing_id, run_id, batch_id, business_key, source_updated_at, payload, extracted_at
        )
        VALUES (%s, %s, %s, %s, (%s::jsonb ->> 'updated_at')::timestamptz, %s::jsonb, %s)
        """
    ).format(sql.Identifier(schema), sql.Identifier(table))
    seen: set[str] = set()
    for record in records:
        key = record[key_name]
        if key in seen:
            raise DatabaseUnavailable(f"{source} returned {key} twice")
        seen.add(key)
        payload = Jsonb(record)
        conn.execute(statement, (f"{batch_id}-{key}", run_id, batch_id, key, payload, payload, extracted_at))


def _save_watermark(conn, source: str, batch_id: str) -> tuple[str, str] | None:
    schema, table, _key, _entity = RAW[source]
    statement = sql.SQL(
        """
        INSERT INTO ingestion.watermark (
            source_system, entity_name, last_updated_at, last_business_key, batch_id
        )
        SELECT %s, %s, source_updated_at, business_key, batch_id
        FROM {}.{}
        WHERE batch_id = %s
        ORDER BY source_updated_at DESC, business_key DESC
        LIMIT 1
        ON CONFLICT (source_system, entity_name) DO UPDATE
        SET last_updated_at = EXCLUDED.last_updated_at,
            last_business_key = EXCLUDED.last_business_key,
            batch_id = EXCLUDED.batch_id
        WHERE (EXCLUDED.last_updated_at, EXCLUDED.last_business_key)
            > (ingestion.watermark.last_updated_at, ingestion.watermark.last_business_key)
        RETURNING last_updated_at, last_business_key
        """
    ).format(sql.Identifier(schema), sql.Identifier(table))
    row = conn.execute(statement, (source, WATERMARK_ENTITY[source], batch_id)).fetchone()
    if row is None:
        return None
    return iso(row["last_updated_at"]), row["last_business_key"]


def _cursor(conn, source: str) -> tuple[datetime, str]:
    row = conn.execute(
        """
        SELECT last_updated_at, last_business_key
        FROM ingestion.watermark
        WHERE source_system = %s AND entity_name = %s
        """,
        (source, WATERMARK_ENTITY[source]),
    ).fetchone()
    if row is None:
        raise DatabaseUnavailable(f"The {source} watermark is not set.")
    return row["last_updated_at"], row["last_business_key"]


def _build(conn, run_id: str) -> dict:
    header = conn.execute("SELECT * FROM lesson.run WHERE run_id = %s", (run_id,)).fetchone()
    stored = conn.execute(
        "SELECT * FROM lesson.step WHERE run_id = %s ORDER BY step_index",
        (run_id,),
    ).fetchall()
    specs = {spec.id: spec for spec in STEPS}
    steps = [_step_view(conn, specs[row["step_id"]], row) for row in stored]
    done = {step["id"] for step in steps}
    nxt = next((spec.id for spec in STEPS if spec.id not in done), None)
    target = connection_target()
    return {
        "run_id": header["run_id"],
        "pipeline": PIPELINE,
        "status": header["status"],
        "started_at": header["started_at"],
        "finished_at": header["finished_at"],
        "duration_ms": _ms(header["started_at"], header["finished_at"]),
        "database": str(target["database"]),
        "host": str(target["host"]),
        "port": int(target["port"]),
        "mongo_database": mongo_src.DATABASE,
        "completed_steps": len(steps),
        "step_count": len(STEPS),
        "next_step_id": nxt,
        "steps": steps,
    }


def _step_view(conn, spec: StepSpec, row: dict) -> dict:
    detail = row["detail"] or {}
    if spec.action == "extract":
        records = _extract_records(conn, spec.source or "", row["batch_id"])
    else:
        records = _stage_records(conn, detail.get("batch_ids") or [])
    output = row["output_count"]
    held = row["held_count"]
    hint = f"{output} rows in stg_" if spec.action == "stage" else f"{output} loaded · {held} older than the watermark"
    return {
        "id": spec.id,
        "index": spec.index,
        "title": spec.title,
        "layer": spec.layer,
        "summary": spec.summary,
        "rules": list(spec.rules),
        "script": spec.script,
        "script_sql": _script_text(spec.script),
        "status": "succeeded",
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": _ms(row["started_at"], row["finished_at"]),
        "input_count": row["input_count"],
        "output_count": output,
        "held_count": held,
        "hint": hint,
        "tone": "neutral",
        "logs": list(detail.get("logs") or []),
        "records": records,
        "cursor_updated_at": detail.get("cursor_updated_at"),
        "cursor_key": detail.get("cursor_key") or "",
        "lake_table": detail.get("lake_table"),
        "lake_rows": _physical_rows(conn, spec.source or "", row["batch_id"]) if spec.action == "extract" else [],
    }


def _physical_rows(conn, source: str, batch_id: str) -> list[dict]:
    schema, table, _key, _entity = RAW[source]
    rows = conn.execute(
        sql.SQL(
            """
            SELECT landing_id, run_id, batch_id, business_key, source_updated_at, payload, extracted_at
            FROM {}.{}
            WHERE batch_id = %s
            ORDER BY source_updated_at, business_key
            """
        ).format(sql.Identifier(schema), sql.Identifier(table)),
        (batch_id,),
    ).fetchall()
    return [_lake_row(schema, table, row) for row in rows]


def _all_physical(conn, source: str) -> list[dict]:
    schema, table, _key, _entity = RAW[source]
    rows = conn.execute(
        sql.SQL(
            """
            SELECT landing_id, run_id, batch_id, business_key, source_updated_at, payload, extracted_at
            FROM {}.{}
            ORDER BY extracted_at, business_key
            """
        ).format(sql.Identifier(schema), sql.Identifier(table))
    ).fetchall()
    return [_lake_row(schema, table, row) for row in rows]


def _lake_row(schema: str, table: str, row: dict) -> dict:
    return {
        "table_name": f"{schema}.{table}",
        "landing_id": row["landing_id"],
        "run_id": row["run_id"],
        "batch_id": row["batch_id"],
        "business_key": row["business_key"],
        "source_updated_at": iso(row["source_updated_at"]),
        "extracted_at": iso(row["extracted_at"]),
        "payload": row["payload"],
    }


def _extract_records(conn, source: str, batch_id: str) -> list[dict]:
    schema, table, _key, entity = RAW[source]
    rows = conn.execute(
        sql.SQL(
            """
            SELECT business_key, source_updated_at, payload
            FROM {}.{}
            WHERE batch_id = %s
            ORDER BY source_updated_at, business_key
            """
        ).format(sql.Identifier(schema), sql.Identifier(table)),
        (batch_id,),
    ).fetchall()
    return [
        _lesson_row(
            row["business_key"],
            source,
            entity,
            "loaded",
            _blurb(row["payload"]),
            iso(row["source_updated_at"]),
            row["payload"],
        )
        for row in rows
    ]


def _stage_records(conn, batch_ids: list[str]) -> list[dict]:
    if not batch_ids:
        return []
    records = []
    for row in conn.execute(
        """
        SELECT
            s.customer_email_pk_id, s.country, s.region, s.customer_segment,
            s.account_plan, s.account_status, s.preferred_currency, s.source_updated_at
        FROM stg.stg_customer s
        WHERE s.batch_id = ANY(%s)
        ORDER BY s.customer_email_pk_id
        """,
        (batch_ids,),
    ):
        records.append(
            _lesson_row(
                row["customer_email_pk_id"],
                "structured",
                "customer",
                "staged",
                f"PII removed · {row['customer_segment']} · {row['region']}",
                iso(row["source_updated_at"]),
                {
                    "customer_email_pk_id": row["customer_email_pk_id"],
                    "country": row["country"],
                    "region": row["region"],
                    "customer_segment": row["customer_segment"],
                    "account_plan": row["account_plan"],
                    "account_status": row["account_status"],
                    "preferred_currency": row["preferred_currency"],
                },
            )
        )
    for row in conn.execute(
        """
        SELECT s.product_id, s.sku, s.list_price, s.source_updated_at, landed.payload
        FROM stg.stg_catalog s
        JOIN catalog.raw_catalog landed
          ON landed.batch_id = s.batch_id AND landed.business_key = s.product_id
        WHERE s.batch_id = ANY(%s)
        ORDER BY s.product_id
        """,
        (batch_ids,),
    ):
        records.append(
            _lesson_row(
                row["product_id"],
                "api",
                "catalog",
                "staged",
                f"{row['sku']} · {row['list_price']}",
                iso(row["source_updated_at"]),
                row["payload"],
            )
        )
    for row in conn.execute(
        """
        SELECT
            s.order_id, s.customer_email_pk_id, s.sku, s.status,
            s.quantity, s.source_updated_at
        FROM stg.stg_order s
        WHERE s.batch_id = ANY(%s)
        ORDER BY s.order_id
        """,
        (batch_ids,),
    ):
        records.append(
            _lesson_row(
                row["order_id"],
                "mongo",
                "order",
                "staged",
                f"{row['sku']} · {row['status']}",
                iso(row["source_updated_at"]),
                {
                    "order_id": row["order_id"],
                    "customer_email_pk_id": row["customer_email_pk_id"],
                    "sku": row["sku"],
                    "status": row["status"],
                    "quantity": row["quantity"],
                },
            )
        )
    return records


def _source_row(payload: dict, source: str, loaded: dict[str, set[str]]) -> dict:
    _schema, _table, key_name, entity = RAW[source]
    key = payload[key_name]
    if key in loaded[source]:
        outcome, detail = "loaded", "Already in the lake"
    elif parse_iso(payload["updated_at"]) <= CUTOFF:
        outcome, detail = "stays", "On or before 4 July 2026"
    else:
        outcome, detail = "will_load", "After 4 July 2026"
    return _lesson_row(key, source, entity, outcome, detail, payload["updated_at"], payload)


def _lesson_row(key, source, entity, outcome, detail, updated, payload) -> dict:
    body = dict(payload)
    if isinstance(body.get("updated_at"), datetime):
        body["updated_at"] = iso(body["updated_at"])
    return {
        "business_key": key,
        "source": source,
        "entity": entity,
        "outcome": outcome,
        "detail": detail,
        "source_updated_at": updated if isinstance(updated, str) else iso(updated),
        "payload_hash": None,
        "prior_hash": None,
        "page": None,
        "payload": body,
    }


def _blurb(payload: dict) -> str:
    if "email_address" in payload:
        return payload["email_address"]
    if "list_price" in payload:
        return f"{payload['sku']} · {payload['list_price']}"
    return f"{payload.get('sku', '')} · {payload.get('status', '')}".strip(" ·")


def _customer(row: dict) -> dict:
    updated = row["updated_at"]
    return {
        "email_address": row["email_address"].strip().lower(),
        "full_name": row["full_name"],
        "country": row["country"],
        "region": row["region"],
        "customer_segment": row["customer_segment"],
        "account_plan": row["account_plan"],
        "account_status": row["account_status"],
        "preferred_currency": row["preferred_currency"],
        "updated_at": iso(updated) if isinstance(updated, datetime) else updated,
    }


def _loaded_keys(conn, source: str) -> set[str]:
    schema, table, _key, _entity = RAW[source]
    rows = conn.execute(
        sql.SQL("SELECT business_key FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    ).fetchall()
    return {row["business_key"] for row in rows}


def _count_raw(conn, batch_ids: list[str]) -> int:
    total = 0
    for schema, table, _key, _entity in RAW.values():
        row = conn.execute(
            sql.SQL("SELECT count(*)::int AS n FROM {}.{} WHERE batch_id = ANY(%s)").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            ),
            (batch_ids,),
        ).fetchone()
        total += row["n"]
    return total


def _open_run(conn, started: datetime) -> str:
    running = conn.execute(
        "SELECT run_id FROM lesson.run WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if running is not None:
        return running["run_id"]
    latest = conn.execute("SELECT status FROM lesson.run ORDER BY started_at DESC LIMIT 1").fetchone()
    if latest is not None and latest["status"] == "succeeded":
        raise LessonFinished(_finished_message())
    run_id = f"r-{uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO lesson.run (run_id, status, started_at, batch_seq) VALUES (%s, 'running', %s, 0)",
        (run_id, started),
    )
    return run_id


def _next_batch(conn, run_id: str) -> str:
    row = conn.execute(
        "UPDATE lesson.run SET batch_seq = batch_seq + 1 WHERE run_id = %s RETURNING batch_seq",
        (run_id,),
    ).fetchone()
    return f"{run_id}-b{row['batch_seq']:02d}"


def _save_step(conn, run_id, spec, started, batch_id, source, incoming, output, held, detail) -> None:
    conn.execute(
        """
        INSERT INTO lesson.step (
            run_id, step_index, step_id, status, started_at, finished_at,
            batch_id, source_system, input_count, output_count, held_count, detail
        )
        VALUES (%s, %s, %s, 'succeeded', %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_id,
            spec.index,
            spec.id,
            started,
            datetime.now(timezone.utc),
            batch_id,
            source,
            incoming,
            output,
            held,
            Jsonb(detail),
        ),
    )


def _many(conn, statement, rows) -> None:
    with conn.cursor() as cur:
        cur.executemany(statement, rows)


def _insert_ops(conn) -> None:
    _many(
        conn,
        """
        INSERT INTO ops.customer_account (
            email_address, full_name, country, region, customer_segment,
            account_plan, account_status, preferred_currency, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (email_address) DO UPDATE
        SET full_name = EXCLUDED.full_name,
            country = EXCLUDED.country,
            region = EXCLUDED.region,
            customer_segment = EXCLUDED.customer_segment,
            account_plan = EXCLUDED.account_plan,
            account_status = EXCLUDED.account_status,
            preferred_currency = EXCLUDED.preferred_currency,
            updated_at = EXCLUDED.updated_at
        """,
        [
            (
                row["email_address"],
                row["full_name"],
                row["country"],
                row["region"],
                row["customer_segment"],
                row["account_plan"],
                row["account_status"],
                row["preferred_currency"],
                parse_iso(row["updated_at"]),
            )
            for row in CUSTOMERS
        ],
    )
    _many(
        conn,
        """
        INSERT INTO ops.catalog_product (product_id, sku, category, list_price, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (product_id) DO UPDATE
        SET sku = EXCLUDED.sku,
            category = EXCLUDED.category,
            list_price = EXCLUDED.list_price,
            updated_at = EXCLUDED.updated_at
        """,
        [
            (
                row["product_id"],
                row["sku"],
                row["category"],
                Decimal(row["list_price"]),
                parse_iso(row["updated_at"]),
            )
            for row in PRODUCTS
        ],
    )


def _fill_profile_defaults(conn) -> None:
    conn.execute(
        """
        UPDATE ops.customer_account
        SET
            full_name = COALESCE(full_name, email_address),
            region = COALESCE(region, 'Unspecified'),
            customer_segment = COALESCE(customer_segment, 'Retail'),
            account_plan = COALESCE(account_plan, 'Field'),
            account_status = COALESCE(account_status, 'active'),
            preferred_currency = COALESCE(preferred_currency, 'USD')
        WHERE full_name IS NULL
           OR region IS NULL
           OR customer_segment IS NULL
           OR account_plan IS NULL
           OR account_status IS NULL
           OR preferred_currency IS NULL
        """
    )
    conn.execute("UPDATE ops.catalog_product SET category = 'General' WHERE category IS NULL")


def _lock_profile_columns(conn) -> None:
    for schema_name, table_name, columns in (
        (
            "ops",
            "customer_account",
            ("full_name", "region", "customer_segment", "account_plan", "account_status", "preferred_currency"),
        ),
        ("ops", "catalog_product", ("category",)),
        (
            "stg",
            "stg_customer",
            ("region", "customer_segment", "account_plan", "account_status", "preferred_currency"),
        ),
        ("stg", "stg_catalog", ("category",)),
        (
            "reportingdw",
            "stg_customer",
            ("region", "customer_segment", "account_plan", "account_status", "preferred_currency"),
        ),
        (
            "reportingdw",
            "dim_customer",
            ("region", "customer_segment", "account_plan", "account_status", "preferred_currency"),
        ),
        ("reportingdw", "dim_product", ("category",)),
    ):
        for column_name in columns:
            row = conn.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
                """,
                (schema_name, table_name, column_name),
            ).fetchone()
            if row is None or row["is_nullable"] == "NO":
                continue
            conn.execute(
                sql.SQL("ALTER TABLE {}.{} ALTER COLUMN {} SET NOT NULL").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.Identifier(column_name),
                )
            )


def _refresh_landed_profiles(conn) -> None:
    """Fill attributes on rows landed before this lesson shape existed.

    landing_id and extracted_at stay. A payload that already has the attribute
    is left alone, so a later source edit does not rewrite Bronze.
    """
    conn.execute(
        """
        UPDATE accounts.raw_customer r
        SET payload = r.payload || jsonb_build_object(
            'full_name', c.full_name,
            'region', c.region,
            'customer_segment', c.customer_segment,
            'account_plan', c.account_plan,
            'account_status', c.account_status,
            'preferred_currency', c.preferred_currency
        )
        FROM ops.customer_account c
        WHERE r.business_key = c.email_address
          AND NOT (r.payload ? 'customer_segment')
        """
    )
    conn.execute(
        """
        UPDATE stg.stg_customer s
        SET
            region = r.payload->>'region',
            customer_segment = r.payload->>'customer_segment',
            account_plan = r.payload->>'account_plan',
            account_status = r.payload->>'account_status',
            preferred_currency = r.payload->>'preferred_currency'
        FROM accounts.raw_customer r
        WHERE s.landing_id = r.landing_id
          AND s.customer_segment IS NULL
          AND r.payload ? 'customer_segment'
        """
    )
    conn.execute(
        """
        UPDATE stg.stg_customer
        SET
            region = COALESCE(region, 'Unspecified'),
            customer_segment = COALESCE(customer_segment, 'Retail'),
            account_plan = COALESCE(account_plan, 'Field'),
            account_status = COALESCE(account_status, 'active'),
            preferred_currency = COALESCE(preferred_currency, 'USD')
        WHERE region IS NULL
           OR customer_segment IS NULL
           OR account_plan IS NULL
           OR account_status IS NULL
           OR preferred_currency IS NULL
        """
    )
    conn.execute(
        """
        UPDATE reportingdw.stg_customer d
        SET
            region = s.region,
            customer_segment = s.customer_segment,
            account_plan = s.account_plan,
            account_status = s.account_status,
            preferred_currency = s.preferred_currency
        FROM (
            SELECT DISTINCT ON (customer_email_pk_id)
                customer_email_pk_id, region, customer_segment,
                account_plan, account_status, preferred_currency
            FROM stg.stg_customer
            ORDER BY customer_email_pk_id, source_updated_at
        ) s
        WHERE d.customer_email_pk_id = s.customer_email_pk_id
          AND d.customer_segment IS NULL
        """
    )
    conn.execute(
        """
        UPDATE reportingdw.dim_customer d
        SET
            region = s.region,
            customer_segment = s.customer_segment,
            account_plan = s.account_plan,
            account_status = s.account_status,
            preferred_currency = s.preferred_currency
        FROM (
            SELECT DISTINCT ON (customer_email_pk_id)
                customer_email_pk_id, region, customer_segment,
                account_plan, account_status, preferred_currency
            FROM stg.stg_customer
            ORDER BY customer_email_pk_id, source_updated_at
        ) s
        WHERE d.customer_email_pk_id = s.customer_email_pk_id
          AND d.customer_segment IS NULL
        """
    )
    for table in ("reportingdw.stg_customer", "reportingdw.dim_customer"):
        conn.execute(
            sql.SQL(
                """
                UPDATE {}
                SET
                    region = COALESCE(region, 'Unspecified'),
                    customer_segment = COALESCE(customer_segment, 'Retail'),
                    account_plan = COALESCE(account_plan, 'Field'),
                    account_status = COALESCE(account_status, 'active'),
                    preferred_currency = COALESCE(preferred_currency, 'USD')
                WHERE region IS NULL
                   OR customer_segment IS NULL
                   OR account_plan IS NULL
                   OR account_status IS NULL
                   OR preferred_currency IS NULL
                """
            ).format(sql.SQL(table))
        )
    conn.execute(
        """
        UPDATE catalog.raw_catalog r
        SET payload = r.payload || jsonb_build_object('category', c.category)
        FROM ops.catalog_product c
        WHERE r.business_key = c.product_id
          AND NOT (r.payload ? 'category')
        """
    )
    conn.execute(
        """
        UPDATE stg.stg_catalog s
        SET category = r.payload->>'category'
        FROM catalog.raw_catalog r
        WHERE s.batch_id = r.batch_id
          AND s.product_id = r.business_key
          AND s.category IS NULL
          AND r.payload ? 'category'
        """
    )
    conn.execute("UPDATE stg.stg_catalog SET category = 'General' WHERE category IS NULL")
    conn.execute(
        """
        UPDATE reportingdw.dim_product d
        SET category = s.category
        FROM (
            SELECT DISTINCT ON (product_id) product_id, category
            FROM stg.stg_catalog
            ORDER BY product_id, source_updated_at
        ) s
        WHERE d.product_id = s.product_id
          AND d.category IS NULL
          AND s.category IS NOT NULL
        """
    )
    conn.execute("UPDATE reportingdw.dim_product SET category = 'General' WHERE category IS NULL")


def _insert_watermarks(conn) -> None:
    for source, entity in WATERMARK_ENTITY.items():
        conn.execute(
            """
            INSERT INTO ingestion.watermark (
                source_system, entity_name, last_updated_at, last_business_key, batch_id
            )
            VALUES (%s, %s, %s, '', 'cutoff')
            ON CONFLICT (source_system, entity_name) DO NOTHING
            """,
            (source, entity, CUTOFF),
        )


def _spec_dict(spec: StepSpec) -> dict:
    return {
        "id": spec.id,
        "index": spec.index,
        "title": spec.title,
        "layer": spec.layer,
        "summary": spec.summary,
        "rules": list(spec.rules),
        "script": spec.script,
        "script_sql": None,
    }


def _script_text(script: str | None) -> str | None:
    if not script:
        return None
    return (SQL_ROOT / script).read_text(encoding="utf-8")


def _log(page: dict) -> str:
    return f"{page['method']} {page['url']} → {page['status_code']}, {len(page['records'])} rows"


def _ms(started: datetime, finished: datetime | None) -> int:
    end = finished or datetime.now(timezone.utc)
    return max(int((end - started).total_seconds() * 1000), 0)


def _finished_message() -> str:
    return "This lesson is complete. Start over to put the watermark back to 4 July 2026."
