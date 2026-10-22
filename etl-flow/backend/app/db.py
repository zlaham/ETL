"""PostgreSQL connection for the lesson. Silver and gold SQL from the earlier
pipeline are not executed here.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

SQL_ROOT = Path(__file__).resolve().parents[2] / "sql"
BOOTSTRAP_SQL = SQL_ROOT / "bootstrap.sql"
LESSON_SQL = SQL_ROOT / "lesson.sql"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class DatabaseUnavailable(Exception):
    """PostgreSQL or a source the lesson needs cannot be used."""


def database_url() -> str:
    load_dotenv(ENV_PATH)
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseUnavailable(
            "DATABASE_URL is not set. Add it to etl-flow/backend/.env "
            "for the local database etl_flow."
        )
    return url


def connection_target() -> dict[str, str | int]:
    info = conninfo_to_dict(database_url())
    return {
        "host": info.get("host") or "localhost",
        "port": int(info.get("port") or 5432),
        "database": info.get("dbname") or "",
        "user": info.get("user") or "",
    }


def connect() -> psycopg.Connection:
    try:
        conn = psycopg.connect(
            database_url(),
            application_name="etl-flow",
            connect_timeout=5,
            row_factory=dict_row,
        )
    except psycopg.Error as exc:
        raise DatabaseUnavailable(_safe(exc)) from exc
    conn.execute("SET lock_timeout = '5s'")
    conn.execute("SET statement_timeout = '30s'")
    return conn


def prepare_database() -> None:
    with connect() as conn:
        _drop_unused_lesson_tables(conn)
        _move_landing_tables(conn)
        _migrate_customer_email_identity(conn)
        _replace_identity_dimensions(conn)
        for path in (BOOTSTRAP_SQL, LESSON_SQL):
            for statement in sql_statements(path.read_text(encoding="utf-8")):
                conn.execute(statement)
        _widen_lesson_attributes(conn)


def _drop_unused_lesson_tables(conn: psycopg.Connection) -> None:
    """Remove the longer lesson shape if a previous draft created it."""
    for schema, table in (
        ("stg", "stg_skipped"),
        ("source_schema", "raw_structured_customer"),
        ("source_schema", "raw_api_catalog"),
        ("source_schema", "raw_mongo_order"),
    ):
        if _relation(conn, schema, table):
            conn.execute(f"DROP TABLE {schema}.{table} CASCADE")
    if _column(conn, "stg", "stg_customer", "prior_hash"):
        for table in ("stg_customer", "stg_catalog", "stg_order"):
            if _relation(conn, "stg", table):
                conn.execute(f"DROP TABLE stg.{table} CASCADE")


def _migrate_customer_email_identity(conn: psycopg.Connection) -> None:
    """Move customer identity from clear IDs to a normalized email hash.

    Raw source and landing rows keep the email address. Derived lesson tables
    are rebuilt because Silver and Gold must not retain the clear address.
    """
    old_silver = (
        _column(conn, "stg", "stg_customer", "customer_id")
        or _column(conn, "stg", "stg_order", "customer_id")
    )
    old_gold = _column(conn, "reportingdw", "dim_customer", "customer_id")
    old_reporting_stage = _column(conn, "reportingdw", "stg_customer", "customer_id")
    if old_gold and _relation(conn, "reportingdw", "fct_order"):
        conn.execute("DROP TABLE reportingdw.fct_order")
    if old_gold and _relation(conn, "reportingdw", "dim_customer"):
        conn.execute("DROP TABLE reportingdw.dim_customer")
    if old_reporting_stage and _relation(conn, "reportingdw", "stg_customer"):
        conn.execute("DROP TABLE reportingdw.stg_customer")
    if old_silver:
        for table in ("stg_customer", "stg_order"):
            if _relation(conn, "stg", table):
                conn.execute(
                    sql.SQL("DROP TABLE {}.{}").format(
                        sql.Identifier("stg"),
                        sql.Identifier(table),
                    )
                )

    old_source = _column(conn, "ops", "customer_account", "customer_id")
    old_email = _column(conn, "ops", "customer_account", "email")
    if old_source and old_email:
        if _relation(conn, "orders", "raw_order"):
            conn.execute(
                """
                UPDATE orders.raw_order r
                SET payload =
                    (r.payload - 'customer_id')
                    || jsonb_build_object('email_address', lower(btrim(c.email)))
                FROM ops.customer_account c
                WHERE r.payload ? 'customer_id'
                  AND c.customer_id = r.payload->>'customer_id'
                """
            )
        if _relation(conn, "accounts", "raw_customer"):
            conn.execute(
                """
                UPDATE accounts.raw_customer
                SET
                    business_key = lower(btrim(payload->>'email')),
                    payload =
                        (payload - 'customer_id' - 'email')
                        || jsonb_build_object('email_address', lower(btrim(payload->>'email')))
                WHERE payload ? 'email'
                """
            )
        conn.execute(
            """
            ALTER TABLE ops.customer_account
            DROP CONSTRAINT IF EXISTS customer_account_pkey
            """
        )
        conn.execute(
            """
            ALTER TABLE ops.customer_account
            RENAME COLUMN email TO email_address
            """
        )
        conn.execute(
            """
            UPDATE ops.customer_account
            SET email_address = lower(btrim(email_address))
            """
        )
        conn.execute(
            """
            ALTER TABLE ops.customer_account
            DROP COLUMN customer_id
            """
        )
        conn.execute(
            """
            ALTER TABLE ops.customer_account
            ADD PRIMARY KEY (email_address)
            """
        )

def _replace_identity_dimensions(conn: psycopg.Connection) -> None:
    """Rebuild dim_ and fct_ when the surrogate key is still an identity bigint.

    The lesson key is md5() of the natural values. source_schema, silver, and gold stay.
    """
    row = conn.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'reportingdw'
          AND table_name = 'dim_customer'
          AND column_name = 'customer_key'
        """
    ).fetchone()
    if row is None or row["data_type"] != "bigint":
        return
    for table in ("fct_order", "dim_customer", "dim_product", "dim_date"):
        if _relation(conn, "reportingdw", table):
            conn.execute(
                sql.SQL("DROP TABLE {}.{}").format(sql.Identifier("reportingdw"), sql.Identifier(table))
            )


def _move_landing_tables(conn: psycopg.Connection) -> None:
    """Move this lesson's raw tables out of the generic source_schema name.

    source_schema.orders and source_schema.load_run stay where they are.
    An empty duplicate created beside the real table is removed. A table that
    already has rows is never dropped.
    """
    for table, dest in (
        ("raw_customer", "accounts"),
        ("raw_catalog", "catalog"),
        ("raw_order", "orders"),
    ):
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(dest)))
        old = _relation(conn, "source_schema", table)
        new = _relation(conn, dest, table)
        if old and new:
            old_n = _row_count(conn, "source_schema", table)
            new_n = _row_count(conn, dest, table)
            if old_n and new_n:
                raise DatabaseUnavailable(
                    f"{dest}.{table} and source_schema.{table} both have rows. "
                    "Refusing to drop either table."
                )
            if new_n == 0 and _inbound_fks(conn, dest, table) == 0:
                conn.execute(
                    sql.SQL("DROP TABLE {}.{}").format(sql.Identifier(dest), sql.Identifier(table))
                )
                new = False
            elif old_n == 0 and _inbound_fks(conn, "source_schema", table) == 0:
                conn.execute(
                    sql.SQL("DROP TABLE source_schema.{}").format(sql.Identifier(table))
                )
                old = False
            else:
                raise DatabaseUnavailable(
                    f"Could not move source_schema.{table} to {dest}.{table} without dropping rows."
                )
        if old and not new:
            conn.execute(
                sql.SQL("ALTER TABLE source_schema.{} SET SCHEMA {}").format(
                    sql.Identifier(table),
                    sql.Identifier(dest),
                )
            )


def _row_count(conn: psycopg.Connection, schema: str, table: str) -> int:
    row = conn.execute(
        sql.SQL("SELECT count(*)::int AS n FROM {}.{}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )
    ).fetchone()
    return row["n"]


def _inbound_fks(conn: psycopg.Connection, schema: str, table: str) -> int:
    row = conn.execute(
        """
        SELECT count(*)::int AS n
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.confrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE con.contype = 'f' AND n.nspname = %s AND c.relname = %s
        """,
        (schema, table),
    ).fetchone()
    return row["n"]


def _relation(conn: psycopg.Connection, schema: str, table: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
        """,
        (schema, table),
    ).fetchone()
    return row is not None


def _column(conn: psycopg.Connection, schema: str, table: str, column: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    ).fetchone()
    return row is not None


def _widen_lesson_attributes(conn: psycopg.Connection) -> None:
    """Add customer and catalog attributes to tables created by an earlier lesson.

    CREATE TABLE IF NOT EXISTS does not alter an existing table. New columns
    stay nullable until the seed fills them and locks NOT NULL.
    """
    additions = (
        ("ops", "customer_account", "full_name"),
        ("ops", "customer_account", "region"),
        ("ops", "customer_account", "customer_segment"),
        ("ops", "customer_account", "account_plan"),
        ("ops", "customer_account", "account_status"),
        ("ops", "customer_account", "preferred_currency"),
        ("ops", "catalog_product", "category"),
        ("stg", "stg_customer", "region"),
        ("stg", "stg_customer", "customer_segment"),
        ("stg", "stg_customer", "account_plan"),
        ("stg", "stg_customer", "account_status"),
        ("stg", "stg_customer", "preferred_currency"),
        ("stg", "stg_catalog", "category"),
        ("reportingdw", "stg_customer", "region"),
        ("reportingdw", "stg_customer", "customer_segment"),
        ("reportingdw", "stg_customer", "account_plan"),
        ("reportingdw", "stg_customer", "account_status"),
        ("reportingdw", "stg_customer", "preferred_currency"),
        ("reportingdw", "dim_customer", "region"),
        ("reportingdw", "dim_customer", "customer_segment"),
        ("reportingdw", "dim_customer", "account_plan"),
        ("reportingdw", "dim_customer", "account_status"),
        ("reportingdw", "dim_customer", "preferred_currency"),
        ("reportingdw", "dim_product", "category"),
    )
    for schema_name, table_name, column_name in additions:
        if not _relation(conn, schema_name, table_name):
            continue
        if _column(conn, schema_name, table_name, column_name):
            continue
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} ADD COLUMN {} text").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.Identifier(column_name),
            )
        )


def database_status() -> dict:
    prepare_database()
    target = connection_target()
    with connect() as conn:
        schemas = [
            row["schema_name"]
            for row in conn.execute(
                """
                SELECT nspname AS schema_name
                FROM pg_namespace
                WHERE nspname IN (
                    'source_schema', 'ops', 'ingestion', 'stg', 'lesson', 'reportingdw',
                    'accounts', 'catalog', 'orders'
                )
                ORDER BY nspname
                """
            ).fetchall()
        ]
    return {
        "host": str(target["host"]),
        "port": int(target["port"]),
        "database": str(target["database"]),
        "user": str(target["user"]),
        "schemas": schemas,
    }


def sql_statements(script: str) -> list[str]:
    """Split a script on semicolon line endings. Full-line comments are omitted."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buffer.append(line)
        if line.rstrip().endswith(";"):
            text = "\n".join(buffer).strip()
            if text:
                statements.append(text)
            buffer = []
    trailing = "\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def one_statement(path: Path) -> str:
    statements = sql_statements(path.read_text(encoding="utf-8"))
    if len(statements) != 1:
        raise DatabaseUnavailable(f"{path.name} must contain one statement")
    return statements[0]


def _safe(exc: Exception) -> str:
    return str(exc).splitlines()[0][:500]
