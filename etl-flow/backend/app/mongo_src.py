"""MongoDB orders. Database etl_lesson, collection order_events."""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo import MongoClient

from app.catalog import iso, parse_iso
from app.db import DatabaseUnavailable
from app.lesson_data import ORDERS, PAGE_LIMIT

MONGO_URL = "mongodb://127.0.0.1:27017"
DATABASE = "etl_lesson"
COLLECTION = "order_events"
FIELDS = ("order_id", "email_address", "sku", "status", "quantity", "updated_at")


def ping() -> str | None:
    client = _client()
    try:
        client.admin.command("ping")
        return None
    except Exception as exc:
        return str(exc).splitlines()[0][:300]
    finally:
        client.close()


def replace_orders() -> None:
    _with_collection(_write_base)


def seed_if_empty() -> None:
    def _seed(collection) -> None:
        if collection.count_documents({}) == 0 or collection.find_one(
            {"email_address": {"$exists": False}},
            {"_id": 1},
        ):
            _write_base(collection)
            return
        present = {document["order_id"] for document in collection.find({}, {"order_id": 1})}
        missing = [order for order in ORDERS if order["order_id"] not in present]
        if missing:
            collection.insert_many([_document(order) for order in missing])

    _with_collection(_seed)


def order_exists(order_id: str) -> bool:
    found = {"yes": False}

    def _read(collection) -> None:
        found["yes"] = collection.find_one({"order_id": order_id}, {"_id": 1}) is not None

    _with_collection(_read)
    return found["yes"]


def insert_order(order: dict) -> None:
    def _insert(collection) -> None:
        collection.insert_one(_document(order))

    _with_collection(_insert)


def all_payloads() -> list[dict]:
    found: list[dict] = []

    def _read(collection) -> None:
        documents = collection.find({}).sort([("updated_at", 1), ("order_id", 1)])
        found.extend(order_payload(document) for document in documents)

    _with_collection(_read)
    return found


def fetch_changed(cursor_at: datetime, cursor_key: str) -> list[dict]:
    found: list[dict] = []

    def _read(collection) -> None:
        query = {
            "$or": [
                {"updated_at": {"$gt": cursor_at}},
                {"updated_at": cursor_at, "order_id": {"$gt": cursor_key}},
            ]
        }
        documents = (
            collection.find(query).sort([("updated_at", 1), ("order_id", 1)]).limit(PAGE_LIMIT)
        )
        found.extend(order_payload(document) for document in documents)

    _with_collection(_read)
    return found


def order_payload(document: dict) -> dict:
    missing = [field for field in FIELDS if field not in document]
    if missing:
        raise DatabaseUnavailable(f"order {document.get('order_id', '?')} is missing {', '.join(missing)}")
    if not isinstance(document["quantity"], int) or isinstance(document["quantity"], bool):
        raise DatabaseUnavailable(f"order {document['order_id']} quantity must be an integer")
    updated = document["updated_at"]
    if isinstance(updated, datetime):
        updated = iso(updated)
    else:
        updated = iso(parse_iso(str(updated)))
    return {
        "order_id": document["order_id"],
        "email_address": document["email_address"].strip().lower(),
        "sku": document["sku"],
        "status": document["status"],
        "quantity": document["quantity"],
        "updated_at": updated,
    }


def _write_base(collection) -> None:
    collection.delete_many({})
    collection.insert_many([_document(order) for order in ORDERS])
    collection.create_index([("updated_at", 1), ("order_id", 1)])
    collection.create_index("order_id", unique=True)


def _document(order: dict) -> dict:
    payload = order_payload(order)
    payload["updated_at"] = parse_iso(payload["updated_at"])
    return payload


def _with_collection(fn) -> None:
    client = _client()
    try:
        try:
            client.admin.command("ping")
        except Exception as exc:
            raise DatabaseUnavailable(
                f"MongoDB is not reachable at 127.0.0.1:27017 ({str(exc).splitlines()[0][:200]})"
            ) from exc
        fn(client[DATABASE][COLLECTION])
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable(f"MongoDB failed: {str(exc).splitlines()[0][:300]}") from exc
    finally:
        client.close()


def _client() -> MongoClient:
    return MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc)
