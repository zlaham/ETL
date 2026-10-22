"""The lesson loads only rows after 4 July 2026, one step at a time."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.lesson import reset_lesson
from app.main import app

pytestmark = pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient`:DeprecationWarning")

AFTER_EMAILS = (
    "cio@field.test",
    "dia@field.test",
    "elias.moreau@field.test",
    "gio.rossi@field.test",
)
BEFORE_EMAILS = (
    "ada@field.test",
    "ben@field.test",
    "farah.hassan@field.test",
    "hana.sato@field.test",
)
AFTER_PRODUCTS = ("P7003", "P7004", "P7005", "P7006")
AFTER_ORDERS = ("O1003", "O1004", "O1005", "O1006")


@pytest.fixture(scope="session")
def client():
    catalog.catalog_pages = catalog.query_catalog_pages
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _fresh(client):
    reset_lesson()
    yield


def test_catalog_route_uses_the_watermark(client):
    whole = client.get("/api/sources/catalog")
    assert whole.status_code == 200
    assert [row["product_id"] for row in whole.json()["records"]] == [
        "P7001",
        "P7002",
        "P7003",
        "P7005",
        "P7004",
        "P7006",
    ]

    changed = client.get(
        "/api/sources/catalog",
        params={"cursor_updated_at": "2026-07-04T00:00:00Z", "cursor_key": ""},
    )
    assert changed.status_code == 200
    assert [row["product_id"] for row in changed.json()["records"]] == ["P7003", "P7005", "P7004", "P7006"]


def test_sources_mark_the_cutoff_before_any_step(client):
    body = client.get("/api/sources").json()
    by_key = {row["business_key"]: row["outcome"] for row in body["records"]}
    assert by_key["ada@field.test"] == "stays"
    assert by_key["ben@field.test"] == "stays"
    assert by_key["cio@field.test"] == "will_load"
    assert by_key["farah.hassan@field.test"] == "stays"
    assert by_key["elias.moreau@field.test"] == "will_load"
    assert by_key["P7001"] == "stays"
    assert by_key["P7004"] == "will_load"
    assert by_key["O1001"] == "stays"
    assert by_key["O1004"] == "will_load"
    assert client.get("/api/pipeline/runs/latest").status_code == 404


def test_one_step_does_not_run_the_next(client):
    created = client.post("/api/pipeline/steps")
    assert created.status_code == 200
    run = created.json()
    assert [step["id"] for step in run["steps"]] == ["accounts"]
    assert run["next_step_id"] == "catalog"
    assert run["status"] == "running"
    assert {row["business_key"] for row in run["steps"][0]["records"]} == set(AFTER_EMAILS)
    stored = run["steps"][0]["lake_rows"]
    assert run["steps"][0]["lake_table"] == "accounts.raw_customer"
    assert run["steps"][0]["cursor_updated_at"] == "2026-07-04T00:00:00Z"
    assert {row["business_key"] for row in stored} == set(AFTER_EMAILS)
    cio = next(row for row in stored if row["business_key"] == "cio@field.test")
    assert cio["landing_id"].endswith("cio@field.test")
    assert cio["payload"]["email_address"] == "cio@field.test"
    assert cio["payload"]["full_name"] == "Cio Berger"
    assert cio["payload"]["customer_segment"] == "Studio"
    assert "2026-07-04T00:00:00Z" in run["steps"][0]["logs"][0]
    assert "gio.rossi@field.test" in run["steps"][0]["logs"][1]

    counts = _counts(client)
    assert counts[("accounts", "raw_customer")] == 4
    assert counts[("catalog", "raw_catalog")] == 0
    assert counts[("orders", "raw_order")] == 0
    assert counts[("stg", "stg_customer")] == 0

    sources = client.get("/api/sources").json()
    loaded = {row["business_key"] for row in sources["records"] if row["outcome"] == "loaded"}
    assert loaded == set(AFTER_EMAILS)


def test_full_lesson_stages_only_the_new_rows(client):
    run = None
    for _ in range(4):
        response = client.post("/api/pipeline/steps")
        assert response.status_code == 200
        run = response.json()
    assert run["status"] == "succeeded"
    assert [step["id"] for step in run["steps"]] == ["accounts", "catalog", "orders", "stage"]

    catalog_step = run["steps"][1]
    assert "/api/sources/catalog" in catalog_step["logs"][0]
    assert "ops.catalog_product" not in catalog_step["logs"][0]
    assert {row["business_key"] for row in catalog_step["records"]} == set(AFTER_PRODUCTS)
    assert {row["business_key"] for row in run["steps"][2]["records"]} == set(AFTER_ORDERS)

    staged = {row["business_key"] for row in run["steps"][3]["records"]}
    assert staged == set(_customer_keys(AFTER_EMAILS)) | set(AFTER_PRODUCTS) | set(AFTER_ORDERS)
    assert "INSERT INTO stg.stg_customer" in run["steps"][3]["script_sql"]
    assert "md5(lower(btrim(payload->>'email_address')))" in run["steps"][3]["script_sql"]
    assert "customer_email_pk_id" in run["steps"][3]["script_sql"]
    assert "payload->>'customer_segment'" in run["steps"][3]["script_sql"]
    assert "full_name" not in run["steps"][3]["script_sql"]
    assert "customer_id" not in run["steps"][3]["script_sql"]
    assert "payload->>'product_id'" in run["steps"][3]["script_sql"]
    assert "payload->>'order_id'" in run["steps"][3]["script_sql"]
    assert "accounts.raw_customer" in run["steps"][3]["script_sql"]
    assert "catalog.raw_catalog" in run["steps"][3]["script_sql"]
    assert "orders.raw_order" in run["steps"][3]["script_sql"]
    assert "payload_hash" not in run["steps"][3]["script_sql"]

    destination = client.get("/api/destination").json()
    assert [row["business_key"] for row in destination["rows"]] == [
        *_customer_keys(AFTER_EMAILS),
        "P7003",
        "P7004",
        "P7005",
        "P7006",
        "O1003",
        "O1004",
        "O1005",
        "O1006",
    ]
    assert client.post("/api/pipeline/steps").status_code == 409

    reset = client.post("/api/pipeline/reset")
    assert reset.status_code == 200
    assert _counts(client)[("accounts", "raw_customer")] == 0
    assert client.get("/api/pipeline/runs").json() == []


def test_earlier_date_inserts_more_and_leaves_stored_rows(client):
    first = client.post("/api/extract/accounts", json={"updated_at": "2026-07-04T00:00:00Z"})
    assert first.status_code == 200
    body = first.json()
    assert {row["business_key"] for row in body["inserted"]} == set(AFTER_EMAILS)
    kept = {row["business_key"]: row for row in body["rows"]}

    again = client.post("/api/extract/accounts", json={"updated_at": "2026-07-04T00:00:00Z"})
    assert again.status_code == 200
    assert again.json()["inserted"] == []
    assert set(again.json()["already_stored"]) == set(AFTER_EMAILS)

    earlier = client.post("/api/extract/accounts", json={"updated_at": "2026-07-01T00:00:00Z"})
    assert earlier.status_code == 200
    added = earlier.json()
    assert {row["business_key"] for row in added["inserted"]} == set(BEFORE_EMAILS)
    stored = {row["business_key"]: row for row in added["rows"]}
    assert set(stored) == set(BEFORE_EMAILS) | set(AFTER_EMAILS)
    assert stored["cio@field.test"]["landing_id"] == kept["cio@field.test"]["landing_id"]
    assert stored["cio@field.test"]["extracted_at"] == kept["cio@field.test"]["extracted_at"]
    assert client.post("/api/extract/accounts", json={"updated_at": "July 4"}).status_code == 400

    catalog = client.post("/api/extract/catalog", json={"updated_at": "2026-07-04T00:00:00Z"})
    assert {row["business_key"] for row in catalog.json()["inserted"]} == set(AFTER_PRODUCTS)


def test_first_stg_table_is_indexed_in_reportingdw(client):
    loaded = client.post("/api/extract/accounts", json={"updated_at": "2026-07-04T00:00:00Z"})
    assert loaded.status_code == 200
    staged = client.post("/api/stage/customer")
    assert staged.status_code == 200
    body = staged.json()
    assert body["stg_table"] == "stg.stg_customer"
    expected = set(_customer_keys(AFTER_EMAILS))
    assert {row["customer_email_pk_id"] for row in body["inserted_stg"]} == expected
    assert {row["customer_email_pk_id"] for row in body["inserted_reporting"]} == expected
    assert {row["customer_email_pk_id"] for row in body["stg_rows"]} == expected
    assert all("email_address" not in row and "email" not in row and "full_name" not in row for row in body["stg_rows"])
    cio = next(row for row in body["stg_rows"] if row["customer_email_pk_id"] == _md5("cio@field.test"))
    assert cio["customer_segment"] == "Studio"
    assert cio["account_plan"] == "Atelier"
    assert cio["region"] == "Europe"
    assert cio["preferred_currency"] == "EUR"
    country_idx = next(row for row in body["indexes"] if row["index_name"] == "stg_customer_country_idx")
    assert country_idx["schema_name"] == "reportingdw"
    assert "ON reportingdw.stg_customer" in country_idx["definition"]
    assert "(country)" in country_idx["definition"]

    again = client.post("/api/stage/customer")
    assert again.status_code == 200
    assert again.json()["inserted_stg"] == []
    assert again.json()["inserted_reporting"] == []
    kept = {row["customer_email_pk_id"]: row["country"] for row in again.json()["reporting_rows"]}
    assert kept[_md5("cio@field.test")] == "DE"

    client.post("/api/extract/accounts", json={"updated_at": "2026-07-01T00:00:00Z"})
    more = client.post("/api/stage/customer").json()
    assert {row["customer_email_pk_id"] for row in more["inserted_reporting"]} == set(_customer_keys(BEFORE_EMAILS))
    assert kept[_md5("cio@field.test")] == next(
        row["country"]
        for row in more["reporting_rows"]
        if row["customer_email_pk_id"] == _md5("cio@field.test")
    )


def test_each_stg_table_copies_one_lake_table(client):
    client.post("/api/extract/accounts", json={"updated_at": "2026-07-04T00:00:00Z"})
    client.post("/api/extract/catalog", json={"updated_at": "2026-07-04T00:00:00Z"})
    catalog = client.post("/api/stage/catalog")
    assert catalog.status_code == 200
    board = catalog.json()
    by_id = {feed["feed_id"]: feed for feed in board["feeds"]}
    assert by_id["catalog"]["stg_table"] == "stg.stg_catalog"
    assert by_id["catalog"]["lake_table"] == "catalog.raw_catalog"
    assert {row["key"] for row in by_id["catalog"]["rows"]} == set(AFTER_PRODUCTS)
    assert by_id["accounts"]["rows"] == []
    assert by_id["orders"]["rows"] == []
    accounts = client.post("/api/stage/accounts").json()
    staged_accounts = next(feed for feed in accounts["feeds"] if feed["feed_id"] == "accounts")
    assert {row["key"] for row in staged_accounts["rows"]} == set(_customer_keys(AFTER_EMAILS))
    assert {row["key"] for row in next(feed for feed in accounts["feeds"] if feed["feed_id"] == "catalog")["rows"]} == set(AFTER_PRODUCTS)


def _md5(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _customer_keys(emails: tuple[str, ...]) -> list[str]:
    return sorted(_md5(email) for email in emails)


def test_star_uses_keys_extracted_from_each_source(client):
    for feed in ("accounts", "catalog", "orders"):
        loaded = client.post(f"/api/extract/{feed}", json={"updated_at": "2026-07-04T00:00:00Z"})
        assert loaded.status_code == 200
        staged = client.post(f"/api/stage/{feed}")
        assert staged.status_code == 200

    board = client.get("/api/stage").json()
    orders = next(feed for feed in board["feeds"] if feed["feed_id"] == "orders")
    catalog = next(feed for feed in board["feeds"] if feed["feed_id"] == "catalog")
    assert orders["lake_table"] == "orders.raw_order"
    assert catalog["lake_table"] == "catalog.raw_catalog"
    order = next(row for row in orders["rows"] if row["key"] == "O1003")
    order_cols = {field["name"]: field["value"] for field in order["columns"]}
    assert order_cols["order_id"] == "O1003"
    assert order_cols["customer_email_pk_id"] == _md5("cio@field.test")
    assert "email_address" not in order_cols
    product = next(row for row in catalog["rows"] if row["key"] == "P7003")
    product_cols = {field["name"]: field["value"] for field in product["columns"]}
    assert product_cols["product_id"] == "P7003"

    modeled = client.post("/api/model")
    assert modeled.status_code == 200
    body = modeled.json()
    by_table = {table["table_name"]: table for table in body["model"]}
    assert {row["key"] for row in by_table["reportingdw.dim_customer"]["rows"]} == set(_customer_keys(AFTER_EMAILS))
    assert {row["key"] for row in by_table["reportingdw.dim_product"]["rows"]} == set(AFTER_PRODUCTS)
    july5 = hashlib.md5(b"2026-07-05").hexdigest()
    july6 = hashlib.md5(b"2026-07-06").hexdigest()
    assert {row["key"] for row in by_table["reportingdw.dim_date"]["rows"]} == {july5, july6}
    customer_rows = {
        row["key"]: {field["name"]: field["value"] for field in row["columns"]}
        for row in by_table["reportingdw.dim_customer"]["rows"]
    }
    cio_key = _md5("cio@field.test")
    assert customer_rows[cio_key]["customer_key"] == cio_key
    assert customer_rows[cio_key]["customer_email_pk_id"] == cio_key
    assert customer_rows[cio_key]["customer_segment"] == "Studio"
    assert customer_rows[cio_key]["account_plan"] == "Atelier"
    assert customer_rows[cio_key]["region"] == "Europe"
    assert customer_rows[cio_key]["preferred_currency"] == "EUR"
    assert customer_rows[cio_key]["country"] == "DE"
    assert "email_address" not in customer_rows[cio_key]
    assert "full_name" not in customer_rows[cio_key]
    product_rows = {
        row["key"]: {field["name"]: field["value"] for field in row["columns"]}
        for row in by_table["reportingdw.dim_product"]["rows"]
    }
    assert product_rows["P7003"]["product_key"] == _md5("P7003", "Ink bottle", "22.00")
    assert product_rows["P7003"]["category"] == "Writing"
    facts = {row["key"]: {field["name"]: field["value"] for field in row["columns"]} for row in by_table["reportingdw.fct_order"]["rows"]}
    assert set(facts) == set(AFTER_ORDERS)
    assert facts["O1005"]["extended_amount"] == "28.00"
    assert facts["O1006"]["quantity"] == "2"
    assert facts["O1006"]["extended_amount"] == "28.00"
    assert facts["O1005"]["customer_key"] == _md5("elias.moreau@field.test")
    assert facts["O1003"]["extended_amount"] == "22.00"
    assert facts["O1003"]["quantity"] == "1"
    assert facts["O1003"]["order_date_key"] == july5
    assert facts["O1003"]["customer_key"] == customer_rows[cio_key]["customer_key"]
    assert facts["O1003"]["product_key"] == product_rows["P7003"]["product_key"]
    kept_customer = facts["O1003"]["customer_key"]
    country_idx = next(row for row in body["model_indexes"] if row["index_name"] == "dim_customer_country_idx")
    assert country_idx["schema_name"] == "reportingdw"
    assert "ON reportingdw.dim_customer" in country_idx["definition"]
    assert "(country)" in country_idx["definition"]

    again = client.post("/api/model")
    assert again.status_code == 200
    assert again.json()["unresolved_orders"] == []
    again_facts = {
        row["key"]: {field["name"]: field["value"] for field in row["columns"]}
        for row in next(table["rows"] for table in again.json()["model"] if table["table_name"] == "reportingdw.fct_order")
    }
    assert again_facts["O1003"]["customer_key"] == kept_customer
    assert again_facts["O1003"]["extended_amount"] == "22.00"

    for feed in ("accounts", "catalog", "orders"):
        client.post(f"/api/extract/{feed}", json={"updated_at": "2026-07-01T00:00:00Z"})
        client.post(f"/api/stage/{feed}")
    wider = client.post("/api/model").json()
    wider_facts = {
        row["key"]: {field["name"]: field["value"] for field in row["columns"]}
        for row in next(table["rows"] for table in wider["model"] if table["table_name"] == "reportingdw.fct_order")
    }
    assert set(wider_facts) == {"O1001", "O1002", "O1003", "O1004", "O1005", "O1006", "O1007", "O1008"}
    assert wider_facts["O1003"]["customer_key"] == kept_customer
    assert wider_facts["O1003"]["extended_amount"] == "22.00"
    assert wider_facts["O1002"]["extended_amount"] == "9.00"
    assert wider_facts["O1008"]["extended_amount"] == "13.50"
    assert wider_facts["O1007"]["extended_amount"] == "18.00"


def test_added_json_row_lands_and_hashes(client):
    added = client.post(
        "/api/sources/catalog",
        json={
            "product_id": "P7009",
            "sku": "Brass ruler",
            "list_price": "15.00",
            "updated_at": "2026-07-07T12:00:00Z",
        },
    )
    assert added.status_code == 200
    catalog_feed = next(feed for feed in added.json()["feeds"] if feed["id"] == "catalog")
    product = next(row for row in catalog_feed["rows"] if row["product_id"] == "P7009")
    assert product["sku"] == "Brass ruler"
    assert product["list_price"] == "15.00"
    duplicate = client.post(
        "/api/sources/catalog",
        json={
            "product_id": "P7009",
            "sku": "Brass ruler",
            "list_price": "15.00",
            "updated_at": "2026-07-07T12:00:00Z",
        },
    )
    assert duplicate.status_code == 409

    ordered = client.post(
        "/api/sources/orders",
        json={
            "order_id": "O1009",
            "email_address": "cio@field.test",
            "sku": "Brass ruler",
            "status": "paid",
            "quantity": 2,
            "updated_at": "2026-07-07T12:00:00Z",
        },
    )
    assert ordered.status_code == 200
    orders_feed = next(feed for feed in ordered.json()["feeds"] if feed["id"] == "orders")
    assert any(row["order_id"] == "O1009" for row in orders_feed["rows"])

    for feed in ("accounts", "catalog", "orders"):
        loaded = client.post(f"/api/extract/{feed}", json={"updated_at": "2026-07-04T00:00:00Z"})
        assert loaded.status_code == 200
        client.post(f"/api/stage/{feed}")
    catalog_landed = next(row for row in client.post("/api/extract/catalog", json={"updated_at": "2026-07-04T00:00:00Z"}).json()["rows"] if row["business_key"] == "P7009")
    assert catalog_landed["payload"]["product_id"] == "P7009"
    assert catalog_landed["payload"]["sku"] == "Brass ruler"
    assert catalog_landed["payload"]["list_price"] == "15.00"
    assert catalog_landed["payload"]["category"] == "General"

    modeled = client.post("/api/model").json()
    facts = {
        row["key"]: {field["name"]: field["value"] for field in row["columns"]}
        for row in next(table["rows"] for table in modeled["model"] if table["table_name"] == "reportingdw.fct_order")
    }
    assert facts["O1009"]["extended_amount"] == "30.00"
    assert facts["O1009"]["quantity"] == "2"
    assert facts["O1009"]["product_key"] == _md5("P7009", "Brass ruler", "15.00")
    assert facts["O1009"]["customer_key"] == _md5("cio@field.test")
    again = client.post("/api/model").json()
    again_fact = next(
        {field["name"]: field["value"] for field in row["columns"]}
        for row in next(table["rows"] for table in again["model"] if table["table_name"] == "reportingdw.fct_order")
        if row["key"] == "O1009"
    )
    assert again_fact["product_key"] == facts["O1009"]["product_key"]


def test_second_product_with_the_same_sku_is_skipped(client):
    for product_id, price in (("P7011", "8.50"), ("P7012", "9.00")):
        added = client.post(
            "/api/sources/catalog",
            json={
                "product_id": product_id,
                "sku": "Brass clip",
                "list_price": price,
                "updated_at": "2026-07-08T12:00:00Z",
            },
        )
        assert added.status_code == 200
    loaded = client.post("/api/extract/catalog", json={"updated_at": "2026-07-04T00:00:00Z"})
    assert loaded.status_code == 200
    assert client.post("/api/stage/catalog").status_code == 200
    modeled = client.post("/api/model")
    assert modeled.status_code == 200
    body = modeled.json()
    assert body["skipped_products"] == ["P7012"]
    product_ids = {row["key"] for row in next(table["rows"] for table in body["model"] if table["table_name"] == "reportingdw.dim_product")}
    assert "P7011" in product_ids
    assert "P7012" not in product_ids


def test_docs_describe_the_lesson(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    body = spec.json()
    assert body["info"]["title"] == "ETL lesson"
    assert "post" in body["paths"]["/api/pipeline/steps"]
    assert "/api/sources/catalog" in body["paths"]
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()


def _counts(client) -> dict[tuple[str, str], int]:
    tables = client.get("/api/database").json()["tables"]
    return {(row["schema_name"], row["table_name"]): row["rows"] for row in tables}
