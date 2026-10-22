"""Resolve the Silver inputs Gold is allowed to read."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.gold.bronze_silver import bronze_is_available, derive_silver, training_root
from src.gold.changes import CUSTOMER_CHANGES, LATE_SALES, NEW_CUSTOMERS, PRODUCT_CHANGES, RETURN_EVENTS
from src.gold.fallback_data import (
    CUSTOMER_COLUMNS,
    CUSTOMERS,
    PRODUCT_COLUMNS,
    PRODUCTS,
    SALES,
    SALES_COLUMNS,
)

SILVER_FILES = {
    "sales": "sales_lines.jsonl",
    "customers": "customers.jsonl",
    "products": "products.jsonl",
}
CHANGE_FILES = {
    "customer_changes": "customer_changes.jsonl",
    "new_customers": "new_customers.jsonl",
    "product_changes": "product_changes.jsonl",
    "return_events": "return_events.jsonl",
    "late_sales": "late_sales.jsonl",
}
CHANGE_DEFAULTS = {
    "customer_changes": CUSTOMER_CHANGES,
    "new_customers": NEW_CUSTOMERS,
    "product_changes": PRODUCT_CHANGES,
    "return_events": RETURN_EVENTS,
    "late_sales": LATE_SALES,
}


def silver_dir(root: Path | None = None) -> Path:
    return (root or training_root()) / "data" / "session_04" / "silver"


def changes_dir(root: Path | None = None) -> Path:
    return (root or training_root()) / "data" / "session_04" / "changes"


def choose_silver_origin(root: Path | None = None) -> str:
    root = root or training_root()
    if _silver_files_ready(root):
        return "checked_in_silver"
    if bronze_is_available(root):
        return "session_03_bronze"
    return "embedded_fallback"


def resolve_silver(root: Path | None = None) -> tuple[dict[str, pd.DataFrame], str]:
    """Prefer checked-in Silver, then Session 3 Bronze, then the embedded rows."""
    root = root or training_root()
    origin = choose_silver_origin(root)
    if origin == "checked_in_silver":
        frames = _read_jsonl_dir(silver_dir(root), SILVER_FILES)
    elif origin == "session_03_bronze":
        frames = derive_silver(root)
    else:
        frames = fallback_frames()
    return frames, origin


def resolve_changes(root: Path | None = None) -> dict[str, list[dict]]:
    root = root or training_root()
    folder = changes_dir(root)
    if all((folder / name).is_file() for name in CHANGE_FILES.values()):
        loaded = {}
        for key, name in CHANGE_FILES.items():
            loaded[key] = [
                json.loads(line)
                for line in (folder / name).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return loaded
    return {key: [dict(row) for row in rows] for key, rows in CHANGE_DEFAULTS.items()}


def fallback_frames() -> dict[str, pd.DataFrame]:
    return {
        "sales": _typed_frame(SALES_COLUMNS, SALES, money={"unit_price", "gross_amount"}, dates={"order_date"}),
        "customers": _typed_frame(CUSTOMER_COLUMNS, CUSTOMERS, dates={"source_updated_at"}),
        "products": _typed_frame(PRODUCT_COLUMNS, PRODUCTS, dates={"source_updated_at"}),
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_json_ready(row), ensure_ascii=False, separators=(",", ":")) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def frame_to_records(frame: pd.DataFrame) -> list[dict]:
    records = []
    for row in frame.to_dict(orient="records"):
        records.append(_json_ready(row))
    return records


def _silver_files_ready(root: Path) -> bool:
    folder = silver_dir(root)
    return all((folder / name).is_file() for name in SILVER_FILES.values())


def _read_jsonl_dir(folder: Path, files: dict[str, str]) -> dict[str, pd.DataFrame]:
    frames = {}
    for key, name in files.items():
        rows = [json.loads(line) for line in (folder / name).read_text(encoding="utf-8").splitlines() if line.strip()]
        frames[key] = pd.DataFrame(rows)
    frames["sales"] = _coerce_sales(frames["sales"])
    frames["customers"] = _coerce_customers(frames["customers"])
    frames["products"] = _coerce_products(frames["products"])
    return frames


def _coerce_sales(frame: pd.DataFrame) -> pd.DataFrame:
    return _typed_frame(
        SALES_COLUMNS,
        [tuple(row[column] for column in SALES_COLUMNS) for row in frame.to_dict(orient="records")],
        money={"unit_price", "gross_amount"},
        dates={"order_date"},
    )


def _coerce_customers(frame: pd.DataFrame) -> pd.DataFrame:
    return _typed_frame(
        CUSTOMER_COLUMNS,
        [tuple(row[column] for column in CUSTOMER_COLUMNS) for row in frame.to_dict(orient="records")],
        dates={"source_updated_at"},
    )


def _coerce_products(frame: pd.DataFrame) -> pd.DataFrame:
    return _typed_frame(
        PRODUCT_COLUMNS,
        [tuple(row[column] for column in PRODUCT_COLUMNS) for row in frame.to_dict(orient="records")],
        dates={"source_updated_at"},
    )


def _typed_frame(
    columns: tuple[str, ...],
    rows: tuple[tuple, ...] | list[tuple],
    *,
    money: set[str] | None = None,
    dates: set[str] | None = None,
) -> pd.DataFrame:
    money = money or set()
    dates = dates or set()
    records = []
    for row in rows:
        record = {}
        for column, value in zip(columns, row):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                record[column] = None
            elif column in money:
                record[column] = Decimal(str(value)).quantize(Decimal("0.01"))
            elif column in dates:
                record[column] = date.fromisoformat(str(value)[:10])
            elif column == "quantity":
                record[column] = int(value)
            else:
                record[column] = value
        records.append(record)
    return pd.DataFrame(records, columns=list(columns))


def _json_ready(row: dict) -> dict:
    ready = {}
    for key, value in row.items():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            ready[key] = None
        elif isinstance(value, Decimal):
            ready[key] = f"{value:.2f}"
        elif isinstance(value, date):
            ready[key] = value.isoformat()
        elif hasattr(value, "item"):
            ready[key] = value.item()
        else:
            ready[key] = value
    return ready
